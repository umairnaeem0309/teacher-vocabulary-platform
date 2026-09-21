"""Phase 5 normalization tests (sections 81, 108; D007)."""


import pytest
from pipeline.normalize.align import (
    CONF_COGNATE,
    CONF_INLINE,
    AlignmentInput,
    align_translations,
    extract_inline_polish,
)
from pipeline.normalize.clean import (
    clean_display,
    clean_gloss,
    pick_american_spelling,
    search_key,
    strip_diacritics,
)
from pipeline.normalize.normalizer import normalize_wiktextract
from pipeline.normalize.pos import canonical_pos
from pipeline.sources.wiktextract_adapter import SourceLexicalRecord, SourceSense


class TestClean:
    def test_display_preserves_case_and_diacritics(self) -> None:
        assert clean_display("  Łódź   voivodeship ") == "Łódź voivodeship"
        assert clean_display("Bank") == "Bank"  # never lowercased destructively

    def test_search_key_is_casefolded_and_stripped(self) -> None:
        assert search_key("Łódź") == "lodz"
        assert search_key("  ŻÓŁĆ  ") == "zolc"
        assert search_key("a.m.") == "a m"
        assert search_key("Bank") == "bank"

    def test_search_key_deterministic_and_colliding(self) -> None:
        # different display forms, same search key (for identity grouping)
        assert search_key("café") == search_key("cafe")

    def test_strip_diacritics(self) -> None:
        assert strip_diacritics("ąćęłńóśźż") == "acelnoszz"

    def test_clean_gloss_removes_qualifier(self) -> None:
        assert clean_gloss("(esp. of dogs) a loud noise") == "a loud noise"
        assert clean_gloss("financial institution") == "financial institution"

    def test_american_spelling(self) -> None:
        assert pick_american_spelling("a computing centre") == "a computing center"
        assert pick_american_spelling("Colour marker") == "Color marker"


class TestPosMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("noun", "noun"),
            ("verb", "verb"),
            ("adj", "adjective"),
            ("adjective", "adjective"),
            ("adv", "adverb"),
            ("modal auxiliary", "verb"),
            ("be-verb", "verb"),
            ("name", "other"),
            ("n", "noun"),
            ("v", "verb"),
            ("a", "adjective"),
            ("s", "adjective"),
            ("r", "adverb"),
            ("proverb", "phrase"),
            ("prep_phrase", "phrase"),
            ("", "other"),
            ("totally-unknown", "other"),
        ],
    )
    def test_mapping(self, raw: str, expected: str) -> None:
        assert canonical_pos(raw) == expected


class TestInlineExtraction:
    def test_extract_inline_polish(self) -> None:
        assert extract_inline_polish("river bank (pl: brzeg rzeki)") == ["brzeg rzeki"]
        assert extract_inline_polish("(płsk. kasa) money box") == ["kasa"]
        assert extract_inline_polish("no hint here") == []


class TestAlignmentHeuristic:
    """The BANK case and friends (sections 9, 25-26; D007)."""

    def test_bank_case_splits_translations(self) -> None:
        """Word-level [bank, brzeg, bank strony rzeki] must not go to both senses."""
        inp = AlignmentInput(
            word="bank",
            glosses=[
                "financial institution that accepts deposits",
                "land beside a river",
            ],
            word_level_translations=["bank", "brzeg", "brzeg rzeki"],
            senses_with_inline=[[], ["brzeg rzeki"]],  # river sense has inline hint
        )
        result = align_translations(inp)
        financial, river = result[0], result[1]
        # river sense got the inline match with high confidence
        assert any(a.text == "brzeg rzeki" and a.method == "inline" for a in river)
        # cognate 'bank' attached to both with cognate confidence
        assert any(a.method == "cognate" for a in financial)
        assert any(a.method == "cognate" for a in river)
        # 'brzeg' (bare) did not get inlined into the financial sense
        assert not any(a.text == "brzeg" and a.method == "inline" for a in financial)

    def test_cognate_goes_to_all_senses(self) -> None:
        inp = AlignmentInput(
            word="hotel",
            glosses=["establishment providing lodging"],
            word_level_translations=["hotel"],
        )
        result = align_translations(inp)
        assert result[0][0].text == "hotel"
        assert result[0][0].confidence == CONF_COGNATE

    def test_position_fallback_capped(self) -> None:
        inp = AlignmentInput(
            word="run",
            glosses=["move fast", "operate", "flow"],
            word_level_translations=[
                "bieg", "biegać", "operować", "płynąć", "zarządzać", "przebieg",
            ],
        )
        result = align_translations(inp)
        for bucket in result:
            assert len(bucket) <= 3  # cap respected
        # every translation appears somewhere (nothing dropped silently)
        assigned = {a.text for bucket in result for a in bucket}
        assert assigned == set(inp.word_level_translations)

    def test_inline_highest_confidence(self) -> None:
        inp = AlignmentInput(
            word="kasa",
            glosses=["money box (pl: kasa)"],
            word_level_translations=["kasa", "skrytka"],
            senses_with_inline=[["kasa"]],
        )
        result = align_translations(inp)
        inline = [a for a in result[0] if a.method == "inline"]
        assert inline and inline[0].confidence == CONF_INLINE

    def test_determinism(self) -> None:
        inp = AlignmentInput(
            word="bank",
            glosses=["a", "b"],
            word_level_translations=["x", "y", "z"],
        )
        r1 = align_translations(inp)
        r2 = align_translations(inp)
        assert [[(a.text, a.method) for a in b] for b in r1] == [
            [(a.text, a.method) for a in b] for b in r2
        ]


def _make_run(*entries: dict) -> object:
    """Build a fake AdapterRun-shaped object with SourceLexicalRecords."""
    from pipeline.records import AdapterRun

    run = AdapterRun(source="wiktextract")
    for entry in entries:
        run.records.append(
            SourceLexicalRecord(
                word=entry["word"],
                pos_raw=entry.get("pos", "noun"),
                senses=[
                    SourceSense(
                        gloss=s["gloss"],
                        tags=s.get("tags", []),
                        examples=s.get("examples", []),
                    )
                    for s in entry["senses"]
                ],
                polish_translations=entry.get("pl", []),
            )
        )
    return run


class TestNormalizer:
    def test_merges_evidence_and_alignment(self) -> None:
        from pipeline.sources.cefrj_adapter import SourceCefrRecord
        from pipeline.sources.ngsl_adapter import SourceFrequencyRecord

        run = _make_run(
            {
                "word": "bank",
                "pos": "noun",
                "senses": [
                    {"gloss": "financial institution", "tags": ["countable"]},
                    {"gloss": "land beside a river (pl: brzeg rzeki)"},
                ],
                "pl": ["bank", "brzeg", "brzeg rzeki"],
            }
        )
        cefrj = [SourceCefrRecord(headword="bank", pos_raw="noun", cefr="B1")]
        ngsl = [SourceFrequencyRecord(
            lemma="bank", rank=1234, sfi=55.0, frequency_per_million=1234.5)]

        candidates, stats = normalize_wiktextract(run, cefrj=cefrj, ngsl=ngsl)
        assert stats.processed == 2
        assert all(c.headword_search == "bank" for c in candidates)
        # word-level evidence attached to both senses
        assert all(c.cefr_evidence[0]["cefr"] == "B1" for c in candidates)
        assert all(c.frequency_evidence[0]["rank"] == 1234 for c in candidates)
        # search keys are cleaned
        assert all(c.gloss_search == search_key(c.gloss_display) for c in candidates)

    def test_empty_gloss_sense_skipped(self) -> None:
        run = _make_run(
            {"word": "x", "senses": [{"gloss": ""}]}
        )
        _, stats = normalize_wiktextract(run)
        assert stats.processed == 0
        assert stats.skipped == 1
