"""Search engine (Phase 14, sections 20-22).

Four layers per the specification:

- Layer 1 (lexical): PostgreSQL full-text search over weighted tsvectors
  (headword A, definition preview B, translations A, full definitions B)
  plus a fast exact-prefix path on headword/forms. `websearch_to_tsquery`
  gives teachers safe, forgiving query syntax.
- Layer 2 (filters): SQL-level constraints — CEFR, category (with all
  descendant subcategories), POS, priority level, frequency bands, flags,
  translation availability (§42: reliable/multiple/uncertain/missing),
  and student-scoped views (learning state, due status, difficulty,
  assigned/not-assigned, teacher priority overrides). §22 forbids
  client-side filtering of a small result set, so filters compose in SQL.
- Layer 3 (semantic): the teacher's query is embedded once (BGE-M3) and
  compared against precomputed sense embeddings via pgvector HNSW
  (`<=>` cosine), bounded by a cosine cutoff so a neighbour is a neighbour
  and not merely the nearest row. Never embeds rows at search time (§20).
- Layer 3b (topic): the query is matched against the taxonomy (category
  keys and names, with a bounded prefix rule) and the matched subtrees'
  senses become a candidate channel. This is what makes a topic query
  ("travel", "airport problems") return a topic's vocabulary instead of
  only senses whose text contains the query word.
- Layer 4 (hybrid): deterministic weighted rank
  `score = 0.50 * lexical + 0.25 * semantic + 0.20 * topic
   + 0.05 * metadata`, blended by RRF so channels of unlike scale are
  comparable before weighting; metadata bonus (high-frequency +
  high-priority) breaks ties. Documented in docs/search.md; unit-tested
  for determinism (§20 "must be documented").

Both signals are computed against the SAME base filter set (§22: filtering
is not applied after the fact to a truncated candidate list).

Deterministic sorts (§21) are filtered browses over the lexical corpus
(headword, Polish translation, CEFR, topic, POS, priority, frequency and —
with a student viewpoint — learning status); SQL orders and paginates the
full filtered set, so pagination stays consistent with the ordering.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.normalize.clean import search_key

# ---- Ranking constants (docs/search.md is the prose spec of these) --------
RRF_K = 60  # standard RRF constant
W_LEXICAL = 0.50
W_SEMANTIC = 0.25
W_TOPIC = 0.20
W_METADATA = 0.05
# Metadata relevance: frequency rank <= 3000 is "common vocabulary";
# priority levels from prio-v1.1 (section 16).
COMMON_RANK_MAX = 3000
# Adaptive HNSW walk (D014 measured): the count above is exact, but the
# page fetch goes through the HNSW graph with a distance post-filter, and
# a graph grown by tens of thousands of incremental inserts loses recall —
# a deep page can return fewer rows than the count promises (measured:
# offset-618 fetch returned 0 rows against an exact count of 632;
# hnsw.ef_search=800 restored 615). If the walk underfills the window,
# retry with a wider graph walk instead of shipping a short page.
HNSW_EF_BASE = 40
HNSW_EF_STEPS = (200, 800)
PRIORITY_LEVELS = ("VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW")
# Lexical prefix matches (headword/forms) must not be drowned by RRF:
# prefix hits get a guaranteed floor added to their RRF contribution.
PREFIX_BONUS = 0.25
# Semantic neighbours beyond this cosine distance are noise rather than
# neighbours (BGE-M3 vectors are L2-normalized, so distance = 1 - cos).
# Without a cutoff every query "matches" the whole corpus, which made the
# reported total meaningless (searching "hotel" claimed 41,690 results) and
# let stopword-ish senses (on/at/so) rank as neighbours.
MAX_SEMANTIC_DISTANCE = 0.55
# Semantic channel scope: which senses may BE a semantic neighbour. This is a
# recipe/corpus-quality rule, not a distance rule (D032).
#
# The corpus's `other` POS bucket is Wiktionary's catch-all: closed-class
# grammatical senses (`on` "paid for by", `at` "in response or reaction
# to", `an` "form of a (all article senses)", `so` "so long as") and
# proper-name / abbreviation entries (`AIR` "station code of Airport",
# `Castle` "a place name", `MAP` "initialism of modified American plan").
# Neither is a vocabulary *concept*, and BGE-M3 gives them vectors near the
# corpus centroid, so for a lone content-word query they land inside the
# cosine cutoff of almost anything. Measured on `hotel`: `on` sat at 0.448
# and `an` at 0.420 while the genuine neighbour `hotelier` sat at 0.443 and
# `vacancy` at 0.422 -- the noise overlaps the valid neighbours, so no
# distance threshold can separate them (tightening the cutoff drops
# `hotelier` before it drops `on`). The same values held after re-embedding
# every recipe variant tried offline (gloss-only, no-POS, 4 examples,
# no-headword: best case moved the closest offender only to 0.461, still
# inside the cutoff) and after every embedding-space normalisation tried
# (corpus-mean centring, all-but-the-top k=1..8, CSLS local scaling -- each
# either failed to separate `on` from `hotelier` or traded it for
# place-name/abbreviation noise). Scoping the channel instead removes the
# noise outright while relevance is preserved or improves: over the §21
# probes `hotel` 1/14 -> 0/14 noise, `airport` 4/14 -> 6/14 relevant (the
# `AIR`/`Airport`/`Landing` place-name senses go too), `travel`/`cooking`
# unchanged, and `hotel`'s neighbour total drops from the inflated 646 to
# 414 honest neighbours.
#
# The lexical channel is untouched: a teacher who types `on` or `AIR` still
# finds those senses (layers 1-2 are the lookup; layer 3 is the concept
# search). The live corpus has no NULL part_of_speech (71,149 senses: noun
# 35,064, verb 18,667, adjective 9,620, adverb 2,159, other 5,596, phrase
# 43), so this omits exactly the `other` bucket -- 7.9% of the corpus.
SEMANTIC_POS = ("noun", "verb", "adjective", "adverb", "phrase")
# Topic channel: a query token at least this long may match a category key
# or name token by prefix (airport -> Airports) so plurals still match.
TOPIC_PREFIX_MIN = 4
# Thematic adjacency between taxonomy roots, applied to the topic channel.
# Travel vocabulary and transportation vocabulary are one syllabus unit (the
# teacher asking for "travel" expects car/plane/bus/taxi alongside hotel and
# trip), but the taxonomy keeps them as sibling roots, so the subtree match
# alone never reaches them. Curated and versioned like the taxonomy itself:
# only pairs that are unambiguously one lesson are listed.
TAXONOMY_ROOT_AFFINITY: dict[str, frozenset[str]] = {
    "travel": frozenset({"transportation"}),
    "transportation": frozenset({"travel"}),
}

MAX_LIMIT = 200


@dataclass(frozen=True)
class SearchFilters:
    """Layer 2 filter set (all optional; absent = no constraint)."""

    cefr: list[str] = field(default_factory=list)
    pos: list[str] = field(default_factory=list)
    priority_levels: list[str] = field(default_factory=list)
    priority_min: str | None = None  # "HIGH+" -> levels >= HIGH
    category_key: str | None = None  # includes all descendant subcategories
    frequency_bands: list[str] = field(default_factory=list)
    max_frequency_rank: int | None = None
    flags: list[str] = field(default_factory=list)  # SenseFlag values
    student_id: uuid.UUID | None = None
    assigned: bool | None = None  # True=assigned only, False=not assigned
    learning_states: list[str] = field(default_factory=list)
    due_only: bool | None = None  # due_at <= now
    difficult_only: bool | None = None  # lapses > 0
    teacher_priority_only: bool | None = None  # has override row
    # §42 translation availability: reliable | multiple | uncertain | missing.
    translation_availability: str | None = None


@dataclass(frozen=True)
class SearchRequest:
    """A full search request (sections 20-22)."""

    query: str = ""
    mode: str = "hybrid"  # hybrid | lexical | semantic
    filters: SearchFilters = field(default_factory=SearchFilters)
    # §21 sorts: relevance | headword | polish | cefr | topic | pos |
    # priority | frequency | student_status.
    sort: str = "relevance"
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class SearchHit:
    """One result row."""

    sense_id: uuid.UUID
    sense_key: str
    headword: str
    part_of_speech: str | None
    cefr_level: str | None
    definition_preview: str | None
    priority_score: float | None
    priority_level: str | None
    frequency_rank: int | None
    translations: list[str]
    lexical_rank: int | None  # 1-based RRF input rank; None if not lexical hit
    semantic_rank: int | None
    semantic_distance: float | None
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "sense_id": str(self.sense_id),
            "sense_key": self.sense_key,
            "headword": self.headword,
            "part_of_speech": self.part_of_speech,
            "cefr_level": self.cefr_level,
            "definition_preview": self.definition_preview,
            "priority_score": self.priority_score,
            "priority_level": self.priority_level,
            "frequency_rank": self.frequency_rank,
            "translations": self.translations,
            "lexical_rank": self.lexical_rank,
            "semantic_rank": self.semantic_rank,
            "semantic_distance": self.semantic_distance,
            "score": round(self.score, 6),
        }


@dataclass(frozen=True)
class SearchResult:
    hits: list[SearchHit]
    total: int
    mode: str
    query: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "mode": self.mode,
            "query": self.query,
            "hits": [h.as_dict() for h in self.hits],
        }


# --------------------------------------------------------------------------
# Filter SQL (Layer 2)
# --------------------------------------------------------------------------

_PRIORITY_MIN_SQL = """
(EXISTS (
    SELECT 1 FROM (VALUES (:pmin)) AS v(minlevel)
    WHERE array_position(
        ARRAY['VERY HIGH','HIGH','MEDIUM','LOW','VERY LOW'],
        vs.priority_level) <= array_position(
        ARRAY['VERY HIGH','HIGH','MEDIUM','LOW','VERY LOW'],
        v.minlevel)
))
"""

_STUDENT_JOINS = """
LEFT JOIN student_vocabulary sv
    ON sv.sense_id = vs.id AND sv.student_id = :student_id
LEFT JOIN student_fsrs_states sfs ON sfs.student_vocabulary_id = sv.id
"""


def _category_id(conn: Connection, key: str) -> uuid.UUID | None:
    row = conn.execute(
        text("SELECT id FROM categories WHERE key = :k"), {"k": key}
    ).first()
    return row[0] if row else None


def _apply_filters(
    conn: Connection,
    f: SearchFilters,
    where: list[str],
    params: dict[str, Any],
) -> None:
    """Append Layer-2 predicates to `where` (composed IN SQL, section 22)."""

    if f.cefr:
        where.append("vs.cefr_level = ANY(:cefr)")
        params["cefr"] = f.cefr

    if f.pos:
        where.append("vs.part_of_speech = ANY(:pos)")
        params["pos"] = f.pos

    if f.priority_levels:
        where.append("vs.priority_level = ANY(:plevels)")
        params["plevels"] = f.priority_levels

    if f.priority_min is not None:
        # Teacher-facing labels carry a "+" suffix ("HIGH+", sections 22/25)
        # while the stored levels do not — accept both spellings so the
        # documented API example does not 500 (Phase 27 acceptance run).
        level = (
            f.priority_min[:-1]
            if f.priority_min.endswith("+")
            else f.priority_min
        )
        if level not in PRIORITY_LEVELS:
            raise ValueError(f"unknown priority level: {f.priority_min}")
        where.append(_PRIORITY_MIN_SQL)
        params["pmin"] = level

    if f.category_key is not None:
        # The category itself plus every descendant (recursive).
        cat_id = _category_id(conn, f.category_key)
        if cat_id is None:
            where.append("FALSE")
        else:
            where.append(
                """
                vs.id IN (
                    WITH RECURSIVE subtree AS (
                        SELECT id FROM categories WHERE id = :cat_id
                        UNION ALL
                        SELECT c.id FROM categories c
                        JOIN subtree s ON c.parent_id = s.id
                    )
                    SELECT sc.sense_id FROM sense_categories sc
                    WHERE sc.category_id IN (SELECT id FROM subtree)
                )
                """
            )
            params["cat_id"] = cat_id

    if f.frequency_bands:
        # Bands live on frequency evidence rows (rank-derived at import).
        where.append(
            "vs.id IN (SELECT fe.sense_id FROM frequency_evidence fe "
            "WHERE fe.rank IS NOT NULL AND "
            "fe.rank <= :band_max)"
        )
        params["band_max"] = max(_BAND_MAX.get(b, 0) for b in f.frequency_bands)

    if f.max_frequency_rank is not None:
        where.append(
            "vs.id IN (SELECT fe.sense_id FROM frequency_evidence fe "
            "WHERE fe.rank <= :maxrank)"
        )
        params["maxrank"] = f.max_frequency_rank

    if f.flags:
        where.append(
            "vs.id IN (SELECT vf.sense_id FROM vocabulary_flags vf "
            "WHERE vf.flag = ANY(:flags))"
        )
        params["flags"] = f.flags

    if f.student_id is not None:
        params["student_id"] = f.student_id
        if f.assigned is False:
            # §22 example: NOT ASSIGNED for student X.
            where.append("sv.id IS NULL")
        elif f.assigned is True:
            where.append("sv.id IS NOT NULL AND sv.is_active")
        if f.learning_states:
            where.append("sv.learning_state = ANY(:lstates)")
            params["lstates"] = f.learning_states
        if f.due_only:
            where.append("sfs.due_at IS NOT NULL AND sfs.due_at <= now()")
        if f.difficult_only:
            where.append("sfs.lapses > 0")
        if f.teacher_priority_only:
            where.append(
                "vs.id IN (SELECT tpo.sense_id FROM teacher_priority_overrides tpo "
                "WHERE tpo.student_id = :student_id)"
            )

    if f.translation_availability is not None:
        # §42: teachers must be able to isolate missing/uncertain Polish
        # translations. D007 alignment confidences are 0.50 (cognate/common
        # form) and 0.35 (low-confidence position fallback); the corpus
        # carries no higher-value rows. So "reliable" = at least one
        # cognate-or-better alignment (>= 0.50); "uncertain" = has
        # translations but only low-confidence / unknown ones.
        avail = f.translation_availability
        if avail == "missing":
            where.append(
                "NOT EXISTS (SELECT 1 FROM sense_translations st "
                "WHERE st.sense_id = vs.id)"
            )
        elif avail == "multiple":
            where.append(
                "(SELECT count(*) FROM sense_translations st "
                "WHERE st.sense_id = vs.id) > 1"
            )
        elif avail == "reliable":
            where.append(
                "EXISTS (SELECT 1 FROM sense_translations st "
                "WHERE st.sense_id = vs.id AND st.confidence >= 0.5)"
            )
        elif avail == "uncertain":
            where.append(
                "EXISTS (SELECT 1 FROM sense_translations st "
                "WHERE st.sense_id = vs.id) AND NOT EXISTS ("
                "SELECT 1 FROM sense_translations st "
                "WHERE st.sense_id = vs.id AND st.confidence >= 0.5)"
            )
        else:
            raise ValueError(
                f"unknown translation availability: {avail}"
            )


# Frequency bands from the construction pipeline (top1000/top2000/top3000).
_BAND_MAX = {"top1000": 1000, "top2000": 2000, "top3000": 3000}


# --------------------------------------------------------------------------
# Layer 1: lexical search
# --------------------------------------------------------------------------


def _lexical_query(
    conn: Connection, req: SearchRequest, ranked: bool = True
) -> list[dict[str, Any]]:
    """Lexical candidates: ts_rank over the weighted corpus.

    ranked=True: rows ordered best-first by lex_score, ranks 1..N (RRF input).
    ranked=False (browse): SQL orders by the requested deterministic sort over
    the full filtered set; an empty query matches everything (the filters
    alone define the set).
    """
    where: list[str] = ["vs.is_active"]
    params: dict[str, Any] = {"q": req.query}
    _apply_filters(conn, req.filters, where, params)

    prefix_sql, prefix_or, prefix_params = _prefix_predicates(req.query)
    params.update(prefix_params)
    # Prefix matches earn a guaranteed lexical floor; none possible without
    # a prefix predicate, so the bonus binds as 0.0.
    params["prefix_bonus"] = PREFIX_BONUS if prefix_sql else 0.0

    # A query-less browse must not require any tsquery hit (an empty
    # websearch_to_tsquery matches nothing).
    match_sql = ""
    if req.query.strip():
        twin = _punctuation_twin(req.query)
        if twin:
            params["qnorm"] = twin
        match_sql = "\n      AND " + _fts_disjunction(req.query, prefix_or)

    if ranked:
        order_sql = "lex_score DESC, vs.headword_normalized, vs.sense_key"
    elif req.sort == "headword":
        order_sql = "vs.headword_normalized, vs.sense_key"
    elif req.sort == "polish":
        # §21: sort by first Polish translation (none last).
        order_sql = (
            "(SELECT st.translation FROM sense_translations st "
            " WHERE st.sense_id = vs.id ORDER BY st.position LIMIT 1) "
            "NULLS LAST, vs.headword_normalized, vs.sense_key"
        )
    elif req.sort == "cefr":
        # §21: CEFR order A1 < A2 < B1 < B2 < C1 < C2 (unknown last).
        order_sql = (
            "array_position(ARRAY['A1','A2','B1','B2','C1','C2'], "
            "vs.cefr_level) NULLS LAST, vs.headword_normalized, vs.sense_key"
        )
    elif req.sort == "topic":
        # §21: first category key (uncategorised last).
        order_sql = (
            "(SELECT min(c.key) FROM sense_categories sc "
            " JOIN categories c ON c.id = sc.category_id "
            " WHERE sc.sense_id = vs.id) NULLS LAST, "
            "vs.headword_normalized, vs.sense_key"
        )
    elif req.sort == "pos":
        order_sql = (
            "vs.part_of_speech NULLS LAST, vs.headword_normalized, vs.sense_key"
        )
    elif req.sort == "student_status":
        # §21: sort by the student's learning state (assignment viewpoint).
        order_sql = (
            "array_position("
            "ARRAY['NEW','ASSIGNED','ENCOUNTERED','LEARNING','REVIEWING','MASTERED'],"
            " sv.learning_state) NULLS LAST, vs.headword_normalized, vs.sense_key"
        )
    elif req.sort == "priority":
        order_sql = (
            "vs.priority_score DESC NULLS LAST, vs.headword_normalized, vs.sense_key"
        )
    else:  # frequency
        order_sql = "frequency_rank NULLS LAST, vs.headword_normalized, vs.sense_key"

    sql = f"""
    SELECT vs.id, vs.sense_key, vs.headword, vs.part_of_speech::text,
           vs.cefr_level::text, vs.definition_preview,
           vs.priority_score, vs.priority_level,
           (SELECT min(fe.rank) FROM frequency_evidence fe
             WHERE fe.sense_id = vs.id) AS frequency_rank,
           COALESCE(
             (SELECT array_agg(st.translation ORDER BY st.position)
                FROM sense_translations st WHERE st.sense_id = vs.id),
             '{{}}') AS translations,
           ts_rank(vs.fts, websearch_to_tsquery('simple', :q))
             + COALESCE((
               SELECT max(ts_rank(st.fts, websearch_to_tsquery('simple', :q)))
                 FROM sense_translations st WHERE st.sense_id = vs.id), 0)
             + COALESCE((
               SELECT max(ts_rank(sd.fts, websearch_to_tsquery('simple', :q)))
                 FROM sense_definitions sd WHERE sd.sense_id = vs.id), 0)
             + :prefix_bonus AS lex_score,
           {prefix_sql or "FALSE"} AS is_prefix
    FROM vocabulary_senses vs
    {"" if req.filters.student_id is None else _STUDENT_JOINS}
    WHERE {" AND ".join(where)}{match_sql}
    ORDER BY {order_sql}
    {"LIMIT :lim" if ranked else "LIMIT :lim OFFSET :off"}
    """
    if ranked:
        # Ranked rows feed RRF, so fetch the whole page window and let the
        # hybrid step paginate; an SQL OFFSET here would restart the ranks on
        # every page and reshuffle already-seen results.
        params.update({"lim": req.offset + req.limit})
    else:
        params.update({"lim": req.limit, "off": req.offset})
    rows = conn.execute(text(sql), params).mappings().fetchall()
    out = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["_lexical_rank"] = i
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Layer 3b: topic / taxonomy search
# --------------------------------------------------------------------------

def _topic_tokens(value: str) -> list[str]:
    """Query tokens eligible to name a taxonomy category."""
    return [t for t in search_key(value).split() if len(t) >= 3]


def _token_matches_category(token: str, key: str, name: str) -> bool:
    """Does a query token name this category (key or display name)?

    Exact token match, plus a bounded prefix rule so a plural or inflected
    query still finds its category (`airport` -> Airports, `hotel` ->
    Hotels). The prefix rule needs TOPIC_PREFIX_MIN characters so short
    words cannot collide with unrelated category names.
    """
    candidates = set(key.split("-")) | set(search_key(name).split())
    for cand in candidates:
        if token == cand:
            return True
        if (
            len(token) >= TOPIC_PREFIX_MIN
            and len(cand) >= TOPIC_PREFIX_MIN
            and (token.startswith(cand) or cand.startswith(token))
        ):
            return True
    return False


def _topic_category_keys(conn: Connection, query: str) -> list[str]:
    """Taxonomy keys matched by the query, plus curated thematic roots.

    Deterministic: keys are returned sorted.
    """
    tokens = _topic_tokens(query)
    if not tokens:
        return []
    rows = conn.execute(text("SELECT key, name FROM categories")).fetchall()
    matched: set[str] = set()
    for key, name in rows:
        if any(_token_matches_category(t, key, name or "") for t in tokens):
            matched.add(key)
    for key in list(matched):
        matched.update(TAXONOMY_ROOT_AFFINITY.get(key, ()))
    return sorted(matched)


def _topic_query(
    conn: Connection, req: SearchRequest
) -> tuple[list[dict[str, Any]], int]:
    """Senses in the query's taxonomy subtree, best (most common) first.

    Returns (rows with _topic_rank, total senses in the matched subtrees).
    Filters apply to the same base set as every other channel (section 22:
    no post-hoc filtering of a truncated list).
    """
    keys = _topic_category_keys(conn, req.query)
    if not keys:
        return [], 0

    where: list[str] = ["vs.is_active"]
    params: dict[str, Any] = {"topic_keys": keys}
    _apply_filters(conn, req.filters, where, params)

    subtree = """
        WITH RECURSIVE subtree AS (
            SELECT id FROM categories WHERE key = ANY(:topic_keys)
            UNION ALL
            SELECT c.id FROM categories c JOIN subtree s ON c.parent_id = s.id
        )
    """
    join_sql = "" if req.filters.student_id is None else _STUDENT_JOINS
    base_where = (
        " AND ".join(where)
        + " AND vs.id IN (SELECT sc.sense_id FROM sense_categories sc "
        "WHERE sc.category_id IN (SELECT id FROM subtree))"
    )

    total = conn.execute(
        text(f"{subtree} SELECT count(*) FROM vocabulary_senses vs {join_sql} "
             f"WHERE {base_where}"),
        params,
    ).scalar()

    sql = f"""
    {subtree}
    SELECT vs.id
    FROM vocabulary_senses vs
    {join_sql}
    WHERE {base_where}
    ORDER BY vs.priority_score DESC NULLS LAST,
             vs.headword_normalized, vs.sense_key
    LIMIT :fetch
    """
    # Fetch the whole page window, never just the current page: topic ranks
    # feed RRF and must not restart on every page (stable pagination).
    params["fetch"] = req.offset + req.limit
    rows = conn.execute(text(sql), params).mappings().fetchall()
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows, start=1):
        out.append({"id": r["id"], "_topic_rank": i})
    return out, int(total or 0)


def _punctuation_twin(q: str) -> str:
    """Search-key twin of the query, or '' when it must not be used.

    `vocabulary_senses.fts` is a GENERATED column over
    `headword_normalized` — the *search key* — so punctuation is stripped in
    the index but not in the text the teacher typed:

        to_tsvector('simple', 'A.M.')  -> 'a.m'
        the A.M. row indexes           -> 'a':1 'm':2      (from `a m`)
        to_tsvector('simple', "don't") -> 'don't'
        the don't row indexes          -> 'dont'

    A sense could therefore not match its own headword. The twin restores
    that without touching the primary query, so `websearch_to_tsquery`'s
    quoted phrases, `OR` and `-exclusion` syntax keep working (section 20).

    Deliberately narrow: only a *single token containing punctuation* needs
    the twin. Multi-word queries, quoted phrases and leading `-`/`!`
    exclusions are left alone — normalizing those would rewrite the
    teacher's query rather than repair it.
    """
    stripped = q.strip()
    if not stripped or " " in stripped:
        return ""
    if stripped[0] in "-!\"":
        return ""
    if any(ch in stripped for ch in "\"'`*()"):
        twin = search_key(stripped)
    else:
        return ""
    if not twin or twin == stripped or " " in twin:
        return ""
    return twin


def _fts_disjunction(q: str, prefix_or: str) -> str:
    """The `( ... )` text-search predicate for a non-empty query."""
    twin = _punctuation_twin(q)
    head = "vs.fts @@ websearch_to_tsquery('simple', :q)"
    trans = "st.fts @@ websearch_to_tsquery('simple', :q)"
    defs = "sd.fts @@ websearch_to_tsquery('simple', :q)"
    if twin:
        # Bound, not interpolated: the twin is a search key (letters,
        # digits, spaces), never query syntax.
        head += "\n        OR vs.fts @@ websearch_to_tsquery('simple', :qnorm)"
        trans += (
            "\n                          OR st.fts @@ "
            "websearch_to_tsquery('simple', :qnorm)"
        )
        defs += (
            "\n                          OR sd.fts @@ "
            "websearch_to_tsquery('simple', :qnorm)"
        )
    return f"""(
        {head}
        OR EXISTS (SELECT 1 FROM sense_translations st
                   WHERE st.sense_id = vs.id AND {trans})
        OR EXISTS (SELECT 1 FROM sense_definitions sd
                   WHERE sd.sense_id = vs.id AND {defs})
        {('OR ' + prefix_or) if prefix_or else ''}
      )"""


def _prefix_predicates(q: str) -> tuple[str, str, dict[str, Any]]:
    """Exact/prefix predicate over headword + forms (Layer 1 'exact/text').

    Returns (and_form, or_form, params): the same predicate as a WHERE
    conjunct and as a match-clause disjunct. Empty/short queries
    contribute nothing ("", {}, no binds).

    The pattern is built with ``search_key`` because ``headword_normalized``
    *is* a search key: typing `A.M.` must prefix-match `a m`, not `a.m.`.
    """
    if not q.strip():
        return "", "", {}
    prefix = search_key(q)
    if not prefix:
        # Punctuation-only query: LIKE '%' would match every row.
        return "", "", {}
    and_form = (
        "(vs.headword_normalized LIKE :pfx OR EXISTS ("
        "SELECT 1 FROM vocabulary_forms vf WHERE vf.sense_id = vs.id "
        "AND vf.form_normalized LIKE :pfx))"
    )
    return and_form, and_form, {"pfx": prefix + "%"}


# --------------------------------------------------------------------------
# Layer 3: semantic search
# --------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _embed_query_cached(text_query: str) -> tuple[float, ...]:
    """CPU query embedding, memoized (Phase 25 performance).

    The model is locked to a single version (D014) and encoding is
    deterministic, so the vector for a given query text never changes
    within a process. On CPU the encode dominates semantic latency
    (~260 ms vs ~5 ms for the actual vector search), and teachers
    routinely repeat the same topic query across students, so caching
    safely removes the dominant cost for repeats. Bounded to 256 entries.
    """
    from pipeline.enrich.embeddings import EmbeddingModel

    model = EmbeddingModel.shared()
    return tuple(model.encode([text_query])[0])


def embed_query(text_query: str) -> list[float]:
    """Embed the teacher's query once (BGE-M3, same model as the corpus)."""
    return list(_embed_query_cached(text_query))


def _semantic_query(
    conn: Connection, req: SearchRequest
) -> tuple[list[dict[str, Any]], int]:
    """Nearest senses by cosine over the HNSW index, same filter set.

    Returns (rows with _semantic_rank, total senses within the cosine
    cutoff — no longer "every sense matching the filters").
    """
    vec = embed_query(req.query)
    where: list[str] = [
        "vs.is_active",
        "se.embedding_version = 'emb-v1'",
        # Semantic scope (SEMANTIC_POS): only vocabulary-concept senses are
        # eligible neighbours. Part of the same base filter set as every
        # other predicate, so it applies to the count and the page window
        # alike (section 22: no post-hoc filtering of a truncated list).
        "vs.part_of_speech::text = ANY(:sem_pos)",
    ]
    params: dict[str, Any] = {
        "qv": "[" + ",".join(repr(x) for x in vec) + "]",
        "maxdist": MAX_SEMANTIC_DISTANCE,
        "sem_pos": list(SEMANTIC_POS),
    }
    _apply_filters(conn, req.filters, where, params)
    # Cosine cutoff (see MAX_SEMANTIC_DISTANCE): a neighbour, not merely the
    # nearest row. Applied to the count too, so the reported total and the
    # page window describe the same set.
    where.append("se.embedding <=> CAST(:qv AS vector) <= :maxdist")

    base_where = " AND ".join(where)
    count_sql = f"""
        SELECT count(*) FROM sense_embeddings se
        JOIN vocabulary_senses vs ON vs.id = se.sense_id
        {"" if req.filters.student_id is None else _STUDENT_JOINS}
        WHERE {base_where}
    """
    total = conn.execute(text(count_sql), params).scalar()

    sql = f"""
    SELECT vs.id, vs.sense_key, vs.headword, vs.part_of_speech::text,
           vs.cefr_level::text, vs.definition_preview,
           vs.priority_score, vs.priority_level,
           (SELECT min(fe.rank) FROM frequency_evidence fe
             WHERE fe.sense_id = vs.id) AS frequency_rank,
           COALESCE(
             (SELECT array_agg(st.translation ORDER BY st.position)
                FROM sense_translations st WHERE st.sense_id = vs.id),
             '{{}}') AS translations,
           se.embedding <=> CAST(:qv AS vector) AS distance
    FROM sense_embeddings se
    JOIN vocabulary_senses vs ON vs.id = se.sense_id
    {"" if req.filters.student_id is None else _STUDENT_JOINS}
    WHERE {base_where}
    ORDER BY distance
    LIMIT :fetch
    """
    # Page window (offset + limit), not the page itself: these ranks feed RRF
    # and must be identical on every page, otherwise paging reshuffles results.
    params["fetch"] = req.offset + req.limit
    rows = conn.execute(text(sql), params).mappings().fetchall()
    if len(rows) < params["fetch"] and total and total > len(rows):
        # D014 recall rule: the exact count promises more than the index
        # walk found. Retry with a wider graph walk so a deep page inside
        # `total` is not starved to a short (or empty) page. Cheap when the
        # graph is healthy (the first fetch already fills the window);
        # ef=800 costs ~0.5-1.5s only on the underfilled pages.
        # set_config (session) + explicit restore: SET LOCAL would depend on
        # an explicit transaction this engine call does not own, and an
        # unrestored session value would leak through the connection pool.
        prior_ef = conn.execute(text("SHOW hnsw.ef_search")).scalar()
        try:
            want = int(params["fetch"])
            for ef in HNSW_EF_STEPS:
                conn.execute(
                    text("SELECT set_config('hnsw.ef_search', :v, false)"),
                    {"v": str(ef)},
                )
                rows = conn.execute(text(sql), params).mappings().fetchall()
                if len(rows) >= want or len(rows) >= int(total):
                    break
        finally:
            if prior_ef:
                conn.execute(
                    text("SELECT set_config('hnsw.ef_search', :v, false)"),
                    {"v": str(prior_ef)},
                )
    out = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["_semantic_rank"] = i
        d["_semantic_distance"] = float(r["distance"])
        out.append(d)
    return out, int(total or 0)


# --------------------------------------------------------------------------
# Layer 4: hybrid ranking (documented deterministic strategy)
# --------------------------------------------------------------------------

def rrf(rank: int | None) -> float:
    """Reciprocal-rank contribution: 1 / (RRF_K + rank)."""
    return 0.0 if rank is None else 1.0 / (RRF_K + rank)


def metadata_bonus(
    frequency_rank: int | None, priority_level: str | None
) -> float:
    """Deterministic tie-breaker: common vocabulary + high priority."""
    bonus = 0.0
    if frequency_rank is not None and frequency_rank <= COMMON_RANK_MAX:
        bonus += 0.5
    if priority_level in ("VERY HIGH", "HIGH"):
        bonus += 0.5
    return bonus  # in [0, 1]


def hybrid_score(
    lex_rank: int | None,
    sem_rank: int | None,
    frequency_rank: int | None,
    priority_level: str | None,
    is_prefix: bool = False,
    topic_rank: int | None = None,
) -> float:
    """score = 0.50·lexical + 0.25·semantic + 0.20·topic + 0.05·metadata.

    All four terms are reciprocal-rank units, so the weights compare
    channels that are not directly comparable (measured rank quality).

    - Prefix (exact) lexical matches get PREFIX_BONUS added to their
      lexical contribution so an exact headword hit cannot lose to a
      thesaurus-style semantic hit in normal queries.
    - The topic term is the taxonomy channel: it is what turns a headword
      query into a topical browse, so it carries real weight rather than
      acting as a tie-break. It is 0 for queries that match no category.

    `topic_rank` is keyword-only for callers written before the channel
    existed; omitting it reproduces the three-channel blend exactly.
    """
    lex = rrf(lex_rank) + (PREFIX_BONUS if (is_prefix and lex_rank) else 0.0)
    sem = rrf(sem_rank)
    top = rrf(topic_rank)
    meta = metadata_bonus(frequency_rank, priority_level)
    return (
        W_LEXICAL * lex
        + W_SEMANTIC * sem
        + W_TOPIC * top
        + W_METADATA * meta
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def _fetch_senses(conn: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT vs.id, vs.sense_key, vs.headword, vs.part_of_speech::text,
                   vs.cefr_level::text, vs.definition_preview,
                   vs.priority_score, vs.priority_level,
                   (SELECT min(fe.rank) FROM frequency_evidence fe
                     WHERE fe.sense_id = vs.id) AS frequency_rank,
                   COALESCE(
                     (SELECT array_agg(st.translation ORDER BY st.position)
                        FROM sense_translations st WHERE st.sense_id = vs.id),
                     '{}') AS translations
            FROM vocabulary_senses vs WHERE vs.id = ANY(:ids)
            """
        ),
        {"ids": list(ids)},
    ).mappings().fetchall()
    return {r["id"]: dict(r) for r in rows}


def _normalize_request(req: SearchRequest) -> SearchRequest:
    """Clamp and validate a request (deterministic, no hidden defaults)."""
    mode = req.mode if req.mode in ("hybrid", "lexical", "semantic") else "hybrid"
    valid_sorts = (
        "relevance",
        "headword",
        "polish",
        "cefr",
        "topic",
        "pos",
        "priority",
        "frequency",
        "student_status",
    )
    sort = req.sort if req.sort in valid_sorts else "relevance"
    if sort == "student_status" and req.filters.student_id is None:
        # Learning-state ordering is meaningless without a student viewpoint.
        sort = "priority"
    limit = max(1, min(req.limit, MAX_LIMIT))
    offset = max(0, req.offset)
    if not req.query.strip() and req.sort == "relevance":
        # Query-less search degrades to a filtered browse (any mode);
        # deterministic order = priority then headword.
        sort = "priority"
    return SearchRequest(
        query=req.query,
        mode=mode,
        filters=req.filters,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def search(conn: Connection, req: SearchRequest) -> SearchResult:
    """Run the requested search mode (sections 20-22)."""
    req = _normalize_request(req)

    if req.sort != "relevance" or req.mode == "lexical":
        # Deterministic sorts are filtered browses over the lexical corpus:
        # SQL orders and paginates the full filtered set (no top-k truncation).
        return _search_lexical_only(conn, req)
    if req.mode == "semantic":
        return _search_semantic_only(conn, req)
    return _search_hybrid(conn, req)


def _finalize(
    conn: Connection,
    merged: dict[uuid.UUID, dict[str, Any]],
    req: SearchRequest,
    total_lexical: int,
    total_semantic: int,
    mode: str,
    rank_sorted: bool = True,
    total_topic: int = 0,
) -> SearchResult:
    senses = _fetch_senses(conn, list(merged))
    hits: list[SearchHit] = []
    for sid, ranks in merged.items():
        s = senses[sid]
        is_prefix = bool(ranks.get("_is_prefix"))
        score = hybrid_score(
            ranks.get("_lexical_rank"),
            ranks.get("_semantic_rank"),
            s.get("frequency_rank"),
            s.get("priority_level"),
            is_prefix=is_prefix,
            topic_rank=ranks.get("_topic_rank"),
        )
        hits.append(
            SearchHit(
                sense_id=sid,
                sense_key=s["sense_key"],
                headword=s["headword"],
                part_of_speech=s["part_of_speech"],
                cefr_level=s["cefr_level"],
                definition_preview=s["definition_preview"],
                priority_score=s["priority_score"],
                priority_level=s["priority_level"],
                frequency_rank=s["frequency_rank"],
                translations=list(s["translations"] or []),
                lexical_rank=ranks.get("_lexical_rank"),
                semantic_rank=ranks.get("_semantic_rank"),
                semantic_distance=ranks.get("_semantic_distance"),
                score=score,
            )
        )
    # Every channel's total is now query-bounded (lexical hits, semantic
    # neighbours inside the cosine cutoff, topic senses in the matched
    # subtrees), so the largest of them is an honest "how many are there"
    # for pagination rather than the size of the whole corpus.
    total = max(total_lexical, total_semantic, total_topic)
    if not rank_sorted:
        # Browse path: rows came back SQL-ordered and already paginated.
        return SearchResult(hits=hits, total=total, mode=mode, query=req.query)

    if req.sort == "headword":
        hits.sort(key=lambda h: (h.headword.lower(), h.sense_key))
    elif req.sort == "priority":
        hits.sort(
            key=lambda h: (
                -(h.priority_score or 0.0),
                h.headword.lower(),
            )
        )
    elif req.sort == "frequency":
        hits.sort(key=lambda h: (h.frequency_rank is None, h.frequency_rank or 0))
    else:
        hits.sort(key=lambda h: (-h.score, h.headword.lower(), h.sense_key))
        # Relevance is the default view, and the one where a polysemous
        # headword would otherwise monopolise the page (see `_diversify`).
        # Explicit sorts (cefr, headword, ...) keep their strict ordering.
        hits = _diversify(hits)

    page = hits[req.offset : req.offset + req.limit]
    return SearchResult(hits=page, total=total, mode=mode, query=req.query)


def _diversify(hits: list[SearchHit]) -> list[SearchHit]:
    """One result per headword first; repeats follow in the same order.

    A Wiktionary headword carries many senses (`travel` 13, `set` 96) and
    every rank-derived channel lists all of them adjacent, so a relevance
    page for "travel" filled up with the word *travel* and pushed the
    vocabulary the teacher was actually asking for (bus, journey, hotel)
    off the page. Worse for topical queries, which is where it was noticed.

    Repeats are NOT dropped — the sense list stays complete and every sense
    keeps its relative position — they are only tiered: all first
    occurrences, then all second occurrences, and so on. Deterministic
    (tier = how many earlier hits share the headword), so it is stable for a
    given candidate window and testable without a database.
    """
    seen: dict[str, int] = {}
    tiers: list[list[SearchHit]] = []
    for hit in hits:
        key = hit.headword.casefold()
        tier = seen.get(key, 0)
        seen[key] = tier + 1
        while len(tiers) <= tier:
            tiers.append([])
        tiers[tier].append(hit)
    out: list[SearchHit] = []
    for tier in tiers:
        out.extend(tier)
    return out


def _merge(
    lex_rows: list[dict[str, Any]],
    sem_rows: list[dict[str, Any]],
    topic_rows: list[dict[str, Any]] | None = None,
) -> dict[uuid.UUID, dict[str, Any]]:
    merged: dict[uuid.UUID, dict[str, Any]] = {}
    for r in lex_rows:
        merged[r["id"]] = {
            "_lexical_rank": r["_lexical_rank"],
            "_is_prefix": bool(r.get("is_prefix")),
        }
    for r in sem_rows:
        entry = merged.setdefault(r["id"], {"_is_prefix": False})
        entry["_semantic_rank"] = r["_semantic_rank"]
        entry["_semantic_distance"] = r["_semantic_distance"]
    for r in topic_rows or []:
        entry = merged.setdefault(r["id"], {"_is_prefix": False})
        entry["_topic_rank"] = r["_topic_rank"]
    return merged


def _count_lexical(conn: Connection, req: SearchRequest) -> int:
    where: list[str] = ["vs.is_active"]
    params: dict[str, Any] = {"q": req.query}
    _apply_filters(conn, req.filters, where, params)
    prefix_sql, prefix_or, prefix_params = _prefix_predicates(req.query)
    params.update(prefix_params)
    match_sql = ""
    if req.query.strip():
        twin = _punctuation_twin(req.query)
        if twin:
            params["qnorm"] = twin
        match_sql = "\n          AND " + _fts_disjunction(req.query, prefix_or)
    sql = f"""
        SELECT count(*) FROM vocabulary_senses vs
        {"" if req.filters.student_id is None else _STUDENT_JOINS}
        WHERE {" AND ".join(where)}{match_sql}
    """
    return int(conn.execute(text(sql), params).scalar() or 0)


def _or_query(q: str) -> str:
    """Loose form of a multi-word query: OR-join the terms (websearch syntax).

    Section 21: topic phrases like "airport problems" must answer even when
    the phrase never co-occurs in one item. The strict websearch query is
    AND-like; the loose form matches any term. Only used as a fallback when
    the strict query returns nothing (documented in docs/search.md).
    """
    return " OR ".join(q.split())


def _lexical_stage(
    conn: Connection, req: SearchRequest, ranked: bool
) -> tuple[list[dict[str, Any]], SearchRequest]:
    """Run the strict lexical query, falling back to loose OR matching.

    Returns (rows, the request whose query produced them) so the matching
    count uses the identical query text.
    """
    rows = _lexical_query(conn, req, ranked=ranked)
    if ranked and not rows and len(req.query.split()) > 1:
        loose_req = dataclasses.replace(req, query=_or_query(req.query))
        rows = _lexical_query(conn, loose_req, ranked=ranked)
        return rows, loose_req
    return rows, req


def _search_lexical_only(conn: Connection, req: SearchRequest) -> SearchResult:
    ranked = req.sort == "relevance"
    rows, req_eff = _lexical_stage(conn, req, ranked=ranked)
    total = _count_lexical(conn, req_eff)
    merged = _merge(rows, [])
    return _finalize(
        conn, merged, req_eff, total, 0, mode="lexical", rank_sorted=ranked
    )


def _search_semantic_only(conn: Connection, req: SearchRequest) -> SearchResult:
    rows, total = _semantic_query(conn, req)
    merged = _merge([], rows)
    return _finalize(conn, merged, req, 0, total, mode="semantic")


def _search_hybrid(conn: Connection, req: SearchRequest) -> SearchResult:
    lex_rows, lex_req = _lexical_stage(conn, req, ranked=True)
    sem_rows, sem_total = _semantic_query(conn, req)
    topic_rows, topic_total = _topic_query(conn, req)
    merged = _merge(lex_rows, sem_rows, topic_rows)
    lex_total = _count_lexical(conn, lex_req)
    return _finalize(
        conn,
        merged,
        lex_req,
        lex_total,
        sem_total,
        mode="hybrid",
        total_topic=topic_total,
    )
