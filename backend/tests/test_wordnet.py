"""Phase 8 tests: WordNet catalog, sense linking, construction storage (D010)."""

import json

import pytest
from pipeline.enrich.wordnet import (
    WORDNET_LINK_VERSION,
    WordnetEvidence,
    build_synset_catalog,
    build_wordnet_evidence,
    canonical_pos_of_wn,
    link_senses,
    relation_group,
    stem_token,
)
from pipeline.identity.identity import MasterSense
from pipeline.sources.wordnet_adapter import (
    SourceSynset,
    SourceSynsetRelation,
    SourceWordnetLink,
)
from pipeline.storage.sqlite_store import ConstructionStore


def _synset(synset_id, pos="n", definition="", members=None, examples=None):
    return SourceSynset(
        synset_id=synset_id,
        part_of_speech=pos,
        definition=definition,
        examples=examples or [],
        ili=None,
        members=members or [],
        source_record_id=f"wordnet2025:{synset_id}",
    )


def _rel(a, b, relation="hypernym"):
    return SourceSynsetRelation(from_synset_id=a, to_synset_id=b, relation=relation)


def _master(
    word="bank",
    pos="noun",
    gloss="financial institution",
    sense_key=None,
):
    return MasterSense(
        headword_display=word,
        headword_search=word,
        pos_canonical=pos,
        sense_key=sense_key or f"{word}|{pos}|test",
        gloss_display=gloss,
        gloss_search=gloss,
    )


def _evidence():
    """bank: 3 noun synsets, 1 verb synset; quickly: 1 adverb synset."""
    return {
        "bank": WordnetEvidence(
            lemma="bank",
            synsets_by_pos={
                "n": ["wn::08470062-n", "wn::09200000-n", "wn::09210000-n"],
                "v": ["wn::02200000-v"],
            },
            sense_ids={
                "wn::08470062-n": "bank%2:06:00::",
                "wn::02200000-v": "bank%2:33:00::",
            },
        ),
        "quickly": WordnetEvidence(
            lemma="quickly",
            synsets_by_pos={"r": ["wn::00050000-r"]},
            sense_ids={"wn::00050000-r": "quickly%4:02:00::"},
        ),
    }


def _catalog():
    return build_synset_catalog(
        [
            _synset("wn::08470062-n", "n", "sloping land beside a body of water"),
            _synset("wn::09200000-n", "n", "a financial institution that accepts deposits"),
            _synset("wn::09210000-n", "n", "a long ridge or pile, as of clouds"),
            _synset("wn::02200000-v", "v", "act as the bank in a game of chance"),
            _synset("wn::00050000-r", "r", "with rapid movements"),
        ],
        [
            _rel("wn::09200000-n", "wn::08470062-n", "hypernym"),
            _rel("wn::08470062-n", "wn::09200000-n", "hyponym"),
            _rel("wn::09200000-n", "wn::09200000-n", "similar"),
        ],
    )


class TestRelationGrouping:
    def test_canonical_groups(self) -> None:
        assert relation_group("similar") == "synonym"
        assert relation_group("hypernym") == "hypernym"
        assert relation_group("instance_hypernym") == "hypernym"
        assert relation_group("hyponym") == "hyponym"
        assert relation_group("instance_hyponym") == "hyponym"
        assert relation_group("mero_part") == "related"
        assert relation_group("derivation") == "related"
        assert relation_group("domain_topic") == "related"

    def test_unknown_relation_preserved(self) -> None:
        assert relation_group("also") == "also"

    def test_pos_letter_with_suffix(self) -> None:
        assert canonical_pos_of_wn("n") == "noun"
        assert canonical_pos_of_wn("n-1") == "noun"
        assert canonical_pos_of_wn("r") == "adverb"


class TestCatalog:
    def test_build_and_stats(self) -> None:
        cat = _catalog()
        st = cat.stats()
        assert st["synsets"] == 5
        assert st["relations"] == 3
        assert st["hypernym"] == 1
        assert st["hyponym"] == 1
        assert st["synonym"] == 1

    def test_neighbors_by_group(self) -> None:
        cat = _catalog()
        assert cat.neighbors("wn::09200000-n", "hypernym") == ["wn::08470062-n"]
        assert cat.neighbors("wn::09200000-n", "hyponym") == []
        assert cat.neighbors("wn::09200000-n", "synonym") == ["wn::09200000-n"]

    def test_duplicate_edges_dropped(self) -> None:
        cat = build_synset_catalog(
            [_synset("a"), _synset("b")],
            [_rel("a", "b"), _rel("a", "b")],
        )
        assert len(cat.relations) == 1
        assert cat.duplicates_dropped == 1

    def test_definition_tokens_ignore_stopwords(self) -> None:
        entry = build_synset_catalog(
            [_synset("x", "n", "a financial institution that accepts deposits")], []
        ).synsets["x"]
        assert "financial" in entry.definition_tokens
        assert "a" not in entry.definition_tokens


class TestEvidence:
    def test_grouping_by_lemma_and_pos(self) -> None:
        ev = build_wordnet_evidence([
            SourceWordnetLink(lemma="Bank", pos_raw="n", sense_id="s1", synset_id="x1"),
            SourceWordnetLink(lemma="bank", pos_raw="n", sense_id="s2", synset_id="x2"),
            SourceWordnetLink(lemma="bank", pos_raw="n-1", sense_id="s3", synset_id="x2"),
            SourceWordnetLink(lemma="bank", pos_raw="v", sense_id="s4", synset_id="x3"),
        ])
        assert set(ev) == {"bank"}
        e = ev["bank"]
        assert e.synsets_by_pos["n"] == ["x1", "x2"]  # deduped, order kept
        assert e.synsets_by_pos["v"] == ["x3"]
        assert e.sense_ids["x2"] == "s2"  # first wins

    def test_suffix_pos_letter_normalized(self) -> None:
        ev = build_wordnet_evidence([
            SourceWordnetLink(lemma="one", pos_raw="n-1", sense_id="s", synset_id="x"),
        ])
        assert ev["one"].synsets_by_pos == {"n": ["x"]}


class TestSenseLinking:
    def test_multi_candidate_disambiguated_by_definition(self) -> None:
        senses = [_master(gloss="financial institution")]
        links, report = link_senses(senses, _catalog(), _evidence())
        assert len(links["bank|noun|test"]) == 1
        link = links["bank|noun|test"][0]
        assert link.synset_id == "wn::09200000-n"
        assert link.method == "definition-match"
        # sense gloss is a 2-token subset of the synset definition (D008 subset rule)
        assert link.confidence == pytest.approx(0.9)
        assert report.senses_linked == 1
        assert report.ambiguous == 0

    def test_single_candidate_with_matching_definition(self) -> None:
        senses = [_master(word="quickly", pos="adverb", gloss="with rapid movements")]
        links, report = link_senses(senses, _catalog(), _evidence())
        assert links["quickly|adverb|test"][0].synset_id == "wn::00050000-r"
        assert links["quickly|adverb|test"][0].method == "definition-match"

    def test_single_candidate_monosemous_fallback(self) -> None:
        # Gloss overlap is weak, but WordNet has exactly one noun synset
        # for 'bank' here — its own assertion carries the link.
        cat = build_synset_catalog([_synset("solo", "n", "a financial institution")], [])
        ev = {"bank": WordnetEvidence(lemma="bank", synsets_by_pos={"n": ["solo"]})}
        senses = [_master(gloss="completely unrelated meaning here")]
        links, report = link_senses(senses, cat, ev)
        link = links["bank|noun|test"][0]
        assert link.method == "monosemous"
        assert link.confidence == pytest.approx(0.80)
        assert link.synset_id == "solo"
        assert report.senses_linked == 1

    def test_multi_candidate_no_signal_stays_unlinked(self) -> None:
        # Several noun synsets, none sharing tokens with the gloss.
        cat = build_synset_catalog(
            [
                _synset("m1", "n", "sloping land beside water"),
                _synset("m2", "n", "a supply held in reserve"),
            ],
            [],
        )
        ev = {"xyz": WordnetEvidence(lemma="xyz", synsets_by_pos={"n": ["m1", "m2"]})}
        senses = [_master(word="xyz", gloss="a quilted mattress covering")]
        links, report = link_senses(senses, cat, ev)
        assert "xyz|noun|test" not in links
        assert report.weak_definition == 1

    def test_shared_tokens_tier_links_unique_argmax(self) -> None:
        # Def similarity below threshold, but exactly one candidate shares
        # two significant tokens with the sense gloss.
        cat = build_synset_catalog(
            [
                _synset("h1", "n", "a financial establishment with money vaults"),
                _synset("h2", "n", "sloping land beside a river"),
            ],
            [],
        )
        ev = {"bank": WordnetEvidence(lemma="bank", synsets_by_pos={"n": ["h1", "h2"]})}
        senses = [_master(gloss="an establishment where money is kept")]
        links, report = link_senses(senses, cat, ev)
        link = links["bank|noun|test"][0]
        assert link.synset_id == "h1"
        assert link.method == "shared-tokens"
        assert link.confidence == pytest.approx(0.70)

    def test_stemmer_inflection_chain(self) -> None:
        assert stem_token("deposits") == "deposit"
        assert stem_token("deposited") == stem_token("depositing")
        assert stem_token("reserves") == stem_token("reserving")
        assert stem_token("countries") == "countri"
        assert stem_token("bank") == "bank"
        # v1.1 guard: stems keep >= 3 chars (never collapse to 'do')
        # and use/uses agree.
        assert stem_token("dose") == "dos"
        assert stem_token("dose") != "do"
        assert stem_token("uses") == stem_token("use")

    def test_stemming_improves_definition_match(self) -> None:
        cat = build_synset_catalog(
            [_synset("d1", "v", "to deposit money in a financial institution")], []
        )
        ev = {"bank": WordnetEvidence(lemma="bank", synsets_by_pos={"v": ["d1"]})}
        # Raw tokens jaccard ~0.33 (depositing/institutions inflected);
        # stemmed tokens match the definition exactly (full-match = 0.95).
        senses = [_master(pos="verb", gloss="depositing money in financial institutions")]
        links, _ = link_senses(senses, cat, ev)
        link = links["bank|verb|test"][0]
        assert link.method == "definition-match"
        assert link.confidence == pytest.approx(0.95)

    def test_pos_mismatch_not_linked(self) -> None:
        # 'quickly' has only adverb evidence; a noun sense of it cannot link.
        senses = [_master(word="quickly", pos="noun", gloss="financial institution")]
        links, report = link_senses(senses, _catalog(), _evidence())
        assert "quickly|noun|test" not in links
        assert report.pos_mismatch == 1

    def test_no_evidence_counted(self) -> None:
        senses = [_master(word="xylophone", gloss="a musical instrument")]
        links, report = link_senses(senses, _catalog(), _evidence())
        assert not links
        assert report.no_evidence == 1

    def test_ambiguous_tie_left_unlinked(self) -> None:
        # Two noun synsets with identical definitions -> tie.
        cat = build_synset_catalog(
            [
                _synset("a1", "n", "financial institution"),
                _synset("a2", "n", "financial institution"),
            ],
            [],
        )
        ev = {"bank": WordnetEvidence(lemma="bank", synsets_by_pos={"n": ["a1", "a2"]})}
        senses = [_master(gloss="financial institution")]
        links, report = link_senses(senses, cat, ev)
        assert "bank|noun|test" not in links
        assert report.ambiguous == 1

    def test_never_fabricates_when_synset_unknown(self) -> None:
        # Evidence references a synset absent from the catalog.
        ev = {"ghost": WordnetEvidence(lemma="ghost", synsets_by_pos={"n": ["missing"]})}
        senses = [_master(word="ghost", gloss="financial institution")]
        links, report = link_senses(senses, _catalog(), ev)
        # Single candidate with unknown synset: WordNet's own assertion
        # is accepted (sense-id method), nothing is invented.
        assert links["ghost|noun|test"][0].method == "sense-id"

    def test_adjective_accepts_satellite_letters(self) -> None:
        cat = build_synset_catalog([_synset("s1", "s", "very small")], [])
        ev = {"tiny": WordnetEvidence(lemma="tiny", synsets_by_pos={"s": ["s1"]})}
        senses = [_master(word="tiny", pos="adjective", gloss="very small")]
        links, _ = link_senses(senses, cat, ev)
        assert links["tiny|adjective|test"][0].synset_id == "s1"

    def test_determinism_same_input_same_output(self) -> None:
        senses = [_master(gloss="financial institution")]
        l1, r1 = link_senses(senses, _catalog(), _evidence())
        l2, r2 = link_senses(senses, _catalog(), _evidence())
        assert l1 == l2 and r1.as_dict() == r2.as_dict()

    def test_version_bumped_for_stem_guard(self) -> None:
        assert WORDNET_LINK_VERSION == "wnlink-v1.1"


class TestWordnetStore:
    def test_roundtrip_and_counts(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        senses = [_master(gloss="financial institution")]
        store.upsert_senses([_Enriched(s) for s in senses])
        catalog = _catalog()
        links, _ = link_senses(senses, catalog, _evidence())
        written = store.upsert_wordnet(catalog, links)
        assert written == 5 + 3 + 1

        counts = store.count_wordnet()
        assert counts["synsets"] == 5
        assert counts["relations"] == 3
        assert counts["sense_links"] == 1
        assert counts["linked_senses"] == 1

        qc = store.qc_summary()
        assert qc["with_wordnet"] == 1

        row = store.conn.execute(
            "SELECT relation FROM wordnet_relations WHERE from_synset_id = 'wn::09200000-n' "
            "AND to_synset_id = 'wn::08470062-n'"
        ).fetchone()
        assert row == ("hypernym",)
        store.close()

    def test_idempotent_reupsert(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        senses = [_master(gloss="financial institution")]
        store.upsert_senses([_Enriched(s) for s in senses])
        catalog = _catalog()
        links, _ = link_senses(senses, catalog, _evidence())
        store.upsert_wordnet(catalog, links)
        store.upsert_wordnet(catalog, links)
        counts = store.count_wordnet()
        assert counts["synsets"] == 5
        assert counts["relations"] == 3
        assert counts["sense_links"] == 1
        store.close()

    def test_examples_json_roundtrip(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        catalog = build_synset_catalog(
            [_synset("x", "n", "a bank", members=["bank"], examples=["he robs a bank"])], []
        )
        store.upsert_wordnet(catalog, {})
        raw = store.conn.execute(
            "SELECT examples_json FROM wordnet_synsets WHERE synset_id = 'x'"
        ).fetchone()[0]
        assert json.loads(raw) == ["he robs a bank"]
        store.close()


class _Enriched:
    """Minimal stand-in for EnrichedSense (store reads .sense + decisions)."""

    def __init__(self, sense) -> None:
        self.sense = sense
        self.cefr_level = None
        self.cefr_confidence = 0.0
        self.cefr_conflict = False
        self.frequency_rank = None
        self.frequency_band = None
