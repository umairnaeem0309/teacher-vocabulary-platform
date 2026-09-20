"""Tests for Phase 4 source adapters (synthetic fixtures, no raw data)."""

import gzip
import json
from pathlib import Path

import pytest
from pipeline.sources.cefrj_adapter import adapt_cefrj
from pipeline.sources.ngsl_adapter import adapt_ngsl
from pipeline.sources.octanove_adapter import adapt_octanove
from pipeline.sources.wiktextract_adapter import adapt_wiktextract
from pipeline.sources.wordnet_adapter import adapt_wordnet_dir


@pytest.fixture(name="csv_dir")
def csv_dir_fixture(tmp_path: Path) -> Path:
    (tmp_path / "cefrj.csv").write_text(
        "headword,pos,CEFR,CoreInventory 1,CoreInventory 2,Threshold\n"
        "a,determiner,A1,,,\n"
        "abandon,verb,B1,,,\n"
        "bank,noun,B1,,,\n"
        "a.m./A.M./am/AM,adverb,A1,,,\n"
        "bad,adjective,ZZ,,\n"           # invalid CEFR -> failed
        ",noun,A1,,\n"                   # missing headword -> failed
        "a.m./B.M./bm/BM,noun,A2,,\n",   # second slash-variant -> duplicate warning too
        encoding="utf-8",
    )
    (tmp_path / "octanove.csv").write_text(
        "headword,pos,CEFR,notes\n"
        "exterior,noun,C1,\n"
        "cloak,,C1,missing pos\n"        # missing pos -> warning
        "bag,noun,B9,\n"                 # invalid level -> failed
        "cloak,,C1,duplicate\n",         # duplicate -> warning
        encoding="utf-8",
    )
    (tmp_path / "ngsl.csv").write_text(
        "Lemma,SFI Rank,SFI,Adjusted Frequency per Million (U)\n"
        "the,1,87.85,60910\n"
        "bank,1234,55.00,1234.5\n"
        "bad,notanumber,55.00,1234.5\n"  # unparsable -> failed
        "bank,1300,54.00,1100.0\n",      # duplicate lemma -> warning
        encoding="utf-8",
    )
    return tmp_path


class TestCefrjAdapter:
    def test_records_and_stats(self, csv_dir: Path) -> None:
        run = adapt_cefrj(csv_dir / "cefrj.csv")
        assert run.source == "cefrj"
        assert run.stats.read == 7
        assert run.stats.processed == 5
        assert run.stats.failed == 2
        assert len(run.errors) == 2
        assert {r.headword for r in run.records} == {
            "a", "abandon", "bank", "a.m./A.M./am/AM", "a.m./B.M./bm/BM",
        }
        assert all(r.source_record_id.startswith("cefrj:row:") for r in run.records)

    def test_warnings_marked_on_records(self, csv_dir: Path) -> None:
        run = adapt_cefrj(csv_dir / "cefrj.csv")
        slash = [r for r in run.records if "/" in r.headword]
        assert len(slash) == 2
        assert all("slash_variant_headword" in r.warnings for r in slash)

    def test_determinism(self, csv_dir: Path) -> None:
        r1 = adapt_cefrj(csv_dir / "cefrj.csv")
        r2 = adapt_cefrj(csv_dir / "cefrj.csv")
        assert r1.stats.as_dict() == r2.stats.as_dict()
        assert [r.headword for r in r1.records] == [r.headword for r in r2.records]


class TestOctanoveAdapter:
    def test_records_warnings_and_failures(self, csv_dir: Path) -> None:
        run = adapt_octanove(csv_dir / "octanove.csv")
        assert run.stats.read == 4
        assert run.stats.processed == 3
        assert run.stats.failed == 1          # B9 out of profile scope
        missing_pos = [r for r in run.records if not r.pos_raw]
        assert len(missing_pos) == 2          # both cloak rows lack pos
        assert all("missing_pos" in r.warnings for r in missing_pos)

    def test_only_c1_c2_accepted(self, csv_dir: Path) -> None:
        run = adapt_octanove(csv_dir / "octanove.csv")
        assert {r.cefr for r in run.records} == {"C1"}


class TestNgslAdapter:
    def test_numeric_parsing_and_failures(self, csv_dir: Path) -> None:
        run = adapt_ngsl(csv_dir / "ngsl.csv")
        assert run.stats.read == 4
        assert run.stats.processed == 3
        assert run.stats.failed == 1
        the = next(r for r in run.records if r.lemma == "the")
        assert the.rank == 1 and the.frequency_per_million == 60910.0


class TestWiktextractAdapter:
    @pytest.fixture(name="dump")
    def dump_fixture(self, tmp_path: Path) -> Path:
        records = [
            {"word": "dictionary", "lang": "English", "pos": "noun",
             "senses": [
                 {"glosses": ["a reference book"],
                  "examples": [{"text": "Look it up in the dictionary"}],
                  "tags": ["countable"], "id": "dictionary%2:09:00::"},
                 {"tags": ["no-gloss"]},
             ],
             "translations": [{"code": "pl", "word": "słownik"},
                              {"code": "de", "word": "Wörterbuch"}],
             "categories": ["English nouns"]},
            {"word": "le chat", "lang": "French", "pos": "noun", "senses": []},
            {"word": "no-senses", "lang": "English", "pos": "noun", "senses": []},
            "broken json line",
        ]
        p = tmp_path / "dump.jsonl.gz"
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for rec in records:
                f.write((rec if isinstance(rec, str) else json.dumps(rec)) + "\n")
        return p

    def test_streaming_extraction(self, dump: Path) -> None:
        run = adapt_wiktextract(dump)
        assert run.stats.read == 4
        assert run.stats.processed == 1
        assert run.stats.skipped == 2          # French + English without senses
        assert run.stats.failed == 1           # malformed JSON

    def test_record_shape(self, dump: Path) -> None:
        run = adapt_wiktextract(dump)
        rec = run.records[0]
        assert rec.word == "dictionary"
        assert rec.pos_raw == "noun"
        assert len(rec.senses) == 1            # glossless sense dropped
        assert rec.senses[0].gloss == "a reference book"
        assert rec.senses[0].examples == ["Look it up in the dictionary"]
        assert rec.senses[0].tags == ["countable"]
        assert rec.polish_translations == ["słownik"]  # only pl
        assert rec.categories == ["English nouns"]
        assert rec.source_record_id.startswith("wiktextract:line:")

    def test_max_records_caps_read(self, dump: Path) -> None:
        run = adapt_wiktextract(dump, max_records=2)
        assert run.stats.read == 2

    def test_gzip_diacritics_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "d.jsonl.gz"
        with gzip.open(p, "wt", encoding="utf-8") as f:
            f.write(json.dumps(
                {"word": "sword", "lang": "English", "pos": "noun",
                 "senses": [{"glosses": ["a blade weapon"]}],
                 "translations": [{"code": "pl", "word": "miecz"}]},
                ensure_ascii=False) + "\n")
        run = adapt_wiktextract(p)
        assert run.records[0].polish_translations == ["miecz"]


class TestWordnetAdapter:
    @pytest.fixture(name="wn_dir")
    def wn_dir_fixture(self, tmp_path: Path) -> Path:
        wn = tmp_path / "wn"
        wn.mkdir()
        (wn / "verb.change.json").write_text(json.dumps({
            "00109468-v": {
                "definition": "undergo a change",
                "example": ["She changed completely"],
                "hypernym": ["02372362-v"],
                "ili": "i22325",
                "members": ["change"],
                "partOfSpeech": "v",
            },
            "09999999-v": {"definition": "edge case", "partOfSpeech": "v"},
        }), encoding="utf-8")
        (wn / "entries-a.json").write_text(json.dumps({
            "A": {"n": {"sense": [{"id": "a%1:23:01::", "synset": "13679721-n"}]}},
            "Bad": {"n": {"sense": [{"id": "x%1:00::"}]}},  # missing synset -> failed
        }), encoding="utf-8")
        return wn

    def test_synsets_relations_members(self, wn_dir: Path) -> None:
        run = adapt_wordnet_dir(wn_dir)
        synsets = [r for r in run.records if type(r).__name__ == "SourceSynset"]
        relations = [r for r in run.records if type(r).__name__ == "SourceSynsetRelation"]
        assert len(synsets) == 2
        assert len(relations) == 1
        assert relations[0].from_synset_id == "00109468-v"
        assert relations[0].relation == "hypernym"
        first = synsets[0]
        assert first.part_of_speech == "v"
        assert first.ili == "i22325"
        assert first.members == ["change"]

    def test_entry_links_and_failures(self, wn_dir: Path) -> None:
        run = adapt_wordnet_dir(wn_dir)
        links = [r for r in run.records if type(r).__name__ == "SourceWordnetLink"]
        assert len(links) == 1
        assert links[0].lemma == "A"
        assert links[0].synset_id == "13679721-n"
        assert run.stats.failed == 1

    def test_memberless_synset_warns(self, wn_dir: Path) -> None:
        run = adapt_wordnet_dir(wn_dir)
        assert run.stats.warning == 1  # 09999999-v has no members
