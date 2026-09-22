"""Phase 6 sense-identity tests (sections 9, 25-26, 59-60; D008)."""


from pipeline.identity.identity import (
    KEY_VERSION,
    _significant_tokens,
    make_sense_key,
    resolve_identities,
)
from pipeline.normalize.align import AlignedTranslation
from pipeline.normalize.clean import search_key


def _candidate(word, gloss, pos="noun", source="wiktextract", rid=None, pl=None):
    """Build a minimal NormalizedSenseCandidate-shaped object."""
    from pipeline.normalize.normalizer import PROCESSING_VERSION, NormalizedSenseCandidate

    gloss_display = gloss
    gloss_search = search_key(gloss)
    return NormalizedSenseCandidate(
        headword_display=word,
        headword_search=search_key(word),
        pos_canonical=pos,
        pos_raw=pos,
        gloss_display=gloss_display,
        gloss_search=gloss_search,
        examples_display=[],
        tags=[],
        translations=[
            AlignedTranslation(t, 0.9, "inline") for t in (pl or [])
        ],
        sources=[source],
        source_record_ids=[rid or f"{source}:test:{abs(hash(gloss)) % 99999}"],
        processing_version=PROCESSING_VERSION,
    )


def _sorted(cands):
    return sorted(
        cands,
        key=lambda c: (c.headword_search, c.pos_canonical, c.gloss_search,
                       c.source_record_ids[0]),
    )


class TestSignificantTokens:
    def test_stopwords_and_short_tokens_dropped(self) -> None:
        tokens = _significant_tokens(search_key("a fund from deposits of money"))
        assert "fund" in tokens and "deposits" in tokens
        assert "the" not in tokens and "of" not in tokens

    def test_synonyms_collapse(self) -> None:
        a = _significant_tokens(search_key("a child"))
        b = _significant_tokens(search_key("a kid"))
        assert a == b


class TestSenseKey:
    def test_format_and_stability(self) -> None:
        k1 = make_sense_key("bank", "noun", "financial institution")
        k2 = make_sense_key("bank", "noun", "financial institution")
        assert k1 == k2
        assert k1.startswith("bank|noun|")
        assert k1.count("|") == 2
        digest = k1.rsplit("|", 1)[1]
        assert len(digest) == 12 and all(c in "0123456789abcdef" for c in digest)

    def test_different_glosses_different_keys(self) -> None:
        k1 = make_sense_key("bank", "noun", "financial institution")
        k2 = make_sense_key("bank", "noun", "land beside a river")
        assert k1 != k2

    def test_key_version_constant(self) -> None:
        assert KEY_VERSION == "sensekey-v1"


class TestBankAcceptance:
    """The BRD acceptance case: two BANK senses stay two master senses."""

    def test_two_bank_senses_remain_distinct(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution that accepts deposits"),
            _candidate("bank", "land beside a river"),
        ])
        masters, stats = resolve_identities(cands)
        assert len(masters) == 2
        assert stats.read == 2
        keys = {m.sense_key for m in masters}
        assert len(keys) == 2

    def test_bank_same_meaning_from_two_sources_merges(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution",
                       source="wiktextract", rid="wx:1"),
            _candidate("bank", "financial institution that accepts deposits",
                       source="wordnet2025", rid="wn:2"),
        ])
        masters, _ = resolve_identities(cands)
        assert len(masters) == 1
        m = masters[0]
        assert set(m.sources) == {"wiktextract", "wordnet2025"}
        assert len(m.source_record_ids) == 2

    def test_bank_polish_translations_land_on_right_sense(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution", pl=["bank"]),
            _candidate("bank", "land beside a river", pl=["brzeg rzeki"]),
        ])
        masters, _ = resolve_identities(cands)
        by_gloss = {m.gloss_display: m for m in masters}
        financial = by_gloss["financial institution"]
        river = by_gloss["land beside a river"]
        assert {t.text for t in financial.translations} == {"bank"}
        assert {t.text for t in river.translations} == {"brzeg rzeki"}


class TestMergeRules:
    def test_subset_glosses_merge(self) -> None:
        cands = _sorted([
            _candidate("run", "move fast on foot", pos="verb"),
            _candidate("run", "move fast", pos="verb"),
        ])
        masters, _ = resolve_identities(cands)
        assert len(masters) == 1

    def test_genuinely_different_stay_separate(self) -> None:
        cands = _sorted([
            _candidate("run", "move fast on foot", pos="verb"),
            _candidate("run", "manage a business", pos="verb"),
        ])
        masters, _ = resolve_identities(cands)
        assert len(masters) == 2

    def test_same_gloss_different_pos_separate(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution", pos="noun"),
            _candidate("bank", "financial institution", pos="verb"),
        ])
        masters, _ = resolve_identities(cands)
        assert len(masters) == 2  # POS is part of identity group
        assert {m.pos_canonical for m in masters} == {"noun", "verb"}

    def test_examples_and_tags_union(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution", rid="a:1"),
            _candidate("bank", "financial institution that accepts deposits",
                       rid="a:2"),
        ])
        cands[0].examples_display = ["The bank closed early"]
        cands[1].examples_display = ["The bank closed early", "He robbed a bank"]
        cands[0].tags = ["countable"]
        masters, _ = resolve_identities(cands)
        m = masters[0]
        assert set(m.examples_display) == {"The bank closed early", "He robbed a bank"}
        assert m.tags == ["countable"]

    def test_evidence_union_without_duplicates(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution", rid="a:1"),
            _candidate("bank", "financial institution that accepts deposits",
                       rid="a:2"),
        ])
        ev = {"source": "cefrj", "cefr": "B1", "pos_raw": "noun"}
        cands[0].cefr_evidence = [ev]
        cands[1].cefr_evidence = [ev]  # identical evidence from merged senses
        masters, _ = resolve_identities(cands)
        assert masters[0].cefr_evidence == [ev]


class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution"),
            _candidate("bank", "land beside a river"),
            _candidate("bank", "financial institution that accepts deposits"),
        ])
        m1, s1 = resolve_identities(cands)
        m2, s2 = resolve_identities(cands)
        assert [m.sense_key for m in m1] == [m.sense_key for m in m2]
        assert s1.as_dict() == s2.as_dict()

    def test_counts_are_consistent(self) -> None:
        cands = _sorted([
            _candidate("bank", "financial institution"),
            _candidate("bank", "land beside a river"),
        ])
        masters, stats = resolve_identities(cands)
        assert stats.read == 2
        assert stats.processed == len(masters) == 2
