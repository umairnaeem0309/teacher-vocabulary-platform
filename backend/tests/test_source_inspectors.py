"""Tests for Phase 3 dataset inspectors (synthetic fixtures, no raw data)."""

import gzip
import json
from pathlib import Path

import pytest
from pipeline.sources.csv_sources import inspect_cefrj, inspect_ngsl, inspect_octanove
from pipeline.sources.wiktextract_inspect import profile_wiktextract
from pipeline.sources.wordnet_inspect import inspect_wordnet_dir


@pytest.fixture(name="csv_dir")
def csv_dir_fixture(tmp_path: Path) -> Path:
    (tmp_path / "cefrj.csv").write_text(
        "headword,pos,CEFR,CoreInventory 1,CoreInventory 2,Threshold\n"
        "a,determiner,A1,,,\n"
        "abandon,verb,B1,,,\n"
        "abandoned,adjective,B2,,,\n"
        "bank,noun,B1,,,\n"
        "bank,verb,C1,,,\n",
        encoding="utf-8",
    )
    (tmp_path / "octanove.csv").write_text(
        "headword,pos,CEFR,notes\n"
        "exterior,noun,C1,\n"
        "cloak,noun,C1,also verb\n",
        encoding="utf-8",
    )
    (tmp_path / "ngsl.csv").write_text(
        "Lemma,SFI Rank,SFI,Adjusted Frequency per Million (U)\n"
        "the,1,87.85,60910\n"
        "bank,1234,55.00,1234.5\n"
        "give up,999,50.00,900.10\n",
        encoding="utf-8",
    )
    return tmp_path


def test_cefrj_inspector_stats(csv_dir: Path) -> None:
    r = inspect_cefrj(csv_dir / "cefrj.csv")
    assert r["record_count"] == 5
    assert r["cefr_distribution"] == {"A1": 1, "B1": 2, "B2": 1, "C1": 1}
    assert r["duplicate_headword_pos_pairs"] == 0
    assert r["slash_variant_headwords"] == 0
    assert r["auxiliary_column_fill"]["Threshold"] == 0


def test_octanove_inspector_stats(csv_dir: Path) -> None:
    r = inspect_octanove(csv_dir / "octanove.csv")
    assert r["record_count"] == 2
    assert r["cefr_distribution"] == {"C1": 2}
    assert r["notes_filled"] == 1


def test_ngsl_inspector_stats(csv_dir: Path) -> None:
    r = inspect_ngsl(csv_dir / "ngsl.csv")
    assert r["record_count"] == 3
    assert r["rank_range"] == [1, 1234]
    assert r["multiword_lemmas"] == 1
    assert r["unparsable_numeric_rows"] == 0
    assert r["duplicate_lemmas"] == 0


def test_wiktextract_profile_streams_and_counts(tmp_path: Path) -> None:
    records = [
        {"word": "dictionary", "lang": "English", "pos": "noun",
         "senses": [{"glosses": ["a reference book"]}],
         "translations": [{"code": "pl", "word": "słownik"}]},
        {"word": "bank", "lang": "English", "pos": "noun",
         "senses": [{"glosses": ["financial institution"]},
                    {"glosses": ["side of a river"]}],
         "translations": [{"code": "pl", "word": "bank"}, {"code": "pl", "word": "brzeg"}]},
        {"word": "le/chat", "lang": "French", "pos": "noun", "senses": []},
        "not json at all",  # malformed line
    ]
    p = tmp_path / "dump.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for rec in records:
            if isinstance(rec, str):
                f.write(rec + "\n")
            else:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    r = profile_wiktextract(p)
    assert r["total_records"] == 4
    assert r["malformed_records"] == 1
    assert r["english_records"] == 2
    assert r["non_english_records"] == 1
    assert r["english_pos_distribution"] == {"noun": 2}
    assert r["sample_sense_stats"]["senses_total"] == 3
    assert r["sample_sense_stats"]["gloss_coverage_pct"] == 100.0
    assert r["sample_polish_coverage"]["words_with_pl_translation"] == 2
    # bank contributes 2 Polish translations
    assert r["sample_polish_coverage"]["avg_pl_translations_per_covered_word"] == 1.5


def test_wiktextract_handles_gzip_and_polish_diacritics(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(json.dumps(
            {"word": "łódź-related", "lang": "English", "pos": "noun",
             "senses": [], "translations": [{"code": "pl", "word": "łódź"}]},
            ensure_ascii=False) + "\n")
    r = profile_wiktextract(p)
    assert r["english_records"] == 1
    assert r["sample_polish_coverage"]["words_with_pl_translation"] == 1


def test_wordnet_inspector_counts(tmp_path: Path) -> None:
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
        "00113228-v": {"definition": "vary slightly", "members": ["shade"],
                       "partOfSpeech": "v"},
    }), encoding="utf-8")
    (wn / "noun.food.json").write_text(json.dumps({
        "07700600-n": {"definition": "a midday meal", "members": ["lunch"],
                       "partOfSpeech": "n"},
    }), encoding="utf-8")
    (wn / "entries-a.json").write_text(json.dumps({
        "A": {"n": {"sense": [{"id": "a%1:23:01::", "synset": "13679721-n"},
                              {"id": "a%1:27:00::", "synset": "15114370-n"}]}}}),
        encoding="utf-8")
    (wn / "frames.json").write_text(
        json.dumps({"ditransitive": "Somebody ----s somebody something"}),
        encoding="utf-8")

    r = inspect_wordnet_dir(wn)
    assert r["synset_count_total"] == 3
    assert r["synsets_by_pos_group"] == {"noun": 1, "verb": 2}
    assert r["synsets_with_definition"] == 3
    assert r["synsets_with_example"] == 1
    assert r["synsets_with_ili"] == 1
    assert r["relation_counts"] == {"hypernym": 1}
    assert r["entry_lemma_count"] == 1
    assert r["entry_sense_links_total"] == 2
    assert r["verb_frames_count"] == 1
