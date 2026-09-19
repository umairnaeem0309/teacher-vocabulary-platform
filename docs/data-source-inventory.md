# Data Source Inventory (Phase 3)

Generated: 2026-09-26 · Python 3.12.9 · all files under `data/raw/` (immutable inputs, Git-ignored, see data/raw/README.md)

| Dataset | Size | Records | Role |
|---|---|---|---|
| raw-wiktextract-data.jsonl.gz | 2.7 GB | 10,913,996 lines (all languages) | lexical core: senses, glosses, **Polish translations** |
| cefrj-vocabulary-profile-1.5.csv | 227.7 KB | 7,799 | CEFR A1–B2 evidence |
| octanove-vocabulary-profile-c1c2-1.0.csv | 45.4 KB | 2,136 | CEFR C1/C2 evidence |
| NGSL_1.2_stats.csv | 61.1 KB | 2,809 | frequency evidence |
| english-wordnet-2025-json/ | 69.1 MB | 107,519 synsets | semantic relationships |

## 1. Wiktextract / Kaikki (primary source)

- Format: gzipped JSONL, UTF-8; **streamed** (never fully in RAM, sections 47–48).
- Total lines: **10,913,996** (908.6s streaming pass).
- Malformed (unparsable JSON): **0** (0.0000%) — will be reported, never silently dropped (section 45).
- Language distribution (top): English 1,492,836, Latin 892,320, Spanish 811,049, Italian 623,702, Portuguese 446,044, Russian 442,594, French 403,269, German 371,261, Chinese 327,297, Swedish 313,364, Finnish 266,150, Galician 212,972
- English entries: **1,492,836**

### English-entry profile (50,000-entry sample)

- POS distribution: `noun` 831,966, `verb` 222,221, `name` 200,625, `adj` 186,151, `adv` 27,625, `phrase` 5,258, `intj` 4,967, `prep_phrase` 3,045, `prefix` 2,508, `suffix` 1,675, `proverb` 1,583, `pron` 1,045, `contraction` 952, `prep` 882, `num` 639, `symbol` 467, `conj` 380, `det` 357, `character` 190, `particle` 111, `infix` 59, `punct` 57, `interfix` 38, `article` 27, `circumfix` 4, `postp` 3, `adv_phrase` 1
- Senses per word (avg): **2.8** → the sense-level requirement (section 9) matters at scale.
- Gloss coverage: **100.0%** of senses carry a gloss (140,175/140,188).
- **Polish coverage: 39.5%** of sampled English words have ≥1 Polish translation (avg 2.4 per covered word). Remaining entries keep English-only definitions (section 110: never deleted for missing Polish).
- Field coverage (share of sampled entries with the field present): `senses` 50000, `pos` 50000, `word` 50000, `lang` 50000, `lang_code` 50000, `head_templates` 49245, `sounds` 41394, `categories` 41063, `etymology_text` 40936, `forms` 39700, `etymology_templates` 38346, `translations` 28478, `derived` 23377, `related` 15175, `etymology_number` 14530, `hyphenations` 9674, `synonyms` 7952, `wikipedia` 3112
- Top translation target languages: fi 75,293, de 69,312, ru 68,113, es 64,696, fr 49,207, pl 47,977, pt 47,057, it 44,519
- Most common sense tags: `uncountable` 27,160, `countable` 23,335, `transitive` 14,336, `alt-of` 9,033, `obsolete` 7,309, `intransitive` 6,767, `not-comparable` 6,224, `slang` 5,934, `abbreviation` 5,913, `figuratively` 3,468, `initialism` 3,412, `informal` 3,254

### ETL implications

1. Filter `lang == "English"` early; ~half the dump is other languages.
2. Translations live at **word level** (`translations[]`, `code: "pl"`), not per sense — sense/translation alignment needs gloss heuristics (documented in Phase 5, D-decision to follow).
3. Sense tags (`archaic`, `obsolete`, `rare`…) feed `vocabulary_flags` and priority signals directly.

## 2. CEFR-J Vocabulary Profile 1.5

- Columns: `headword, pos, CEFR, CoreInventory 1, CoreInventory 2, Threshold`; 7,799 rows.
- CEFR distribution: A1: 1,164, A2: 1,411, B1: 2,446, B2: 2,778
- POS values: `noun` 4,091, `adjective` 1,494, `verb` 1,349, `adverb` 552, `pronoun` 83, `preposition` 76, `determiner` 46, `conjunction` 37, `number` 30, `modal auxiliary` 13, `be-verb` 10, `interjection` 9, `do-verb` 5, `have-verb` 3, `infinitive-to` 1
- Multiword headwords: 144; slash-variant headwords (e.g. `a.m./A.M./am/AM`): 167 — normalization must split variants (Phase 5).
- Duplicate (headword, POS) pairs: **0** — CEFR conflict policy needed (section 14; Phase 7).
- Auxiliary columns mostly empty: {'CoreInventory 1': 1698, 'CoreInventory 2': 107, 'Threshold': 1740}.

## 3. Octanove C1/C2 Vocabulary Profile 1.0

- Columns: `headword, pos, CEFR, notes`; 2,136 rows.
- CEFR distribution: C1: 1,111, C2: 1,025
- POS values: `noun` 834, `adjective` 561, `verb` 460, `adverb` 273, `preposition` 5, `` 1, `conjunction` 1, `vern` 1
- Notes filled: 45; multiword: 11; duplicate (headword, POS): 58.

## 4. NGSL 1.2 frequency stats

- Columns: `Lemma, SFI Rank, SFI, Adjusted Frequency per Million (U)`; 2,809 rows.
- Rank range: 1–2,809; frequency/million range: 3–60,910.
- Unparsable numeric rows: 0; multiword lemmas: 0; capitalized: 3; duplicate lemmas: 0 — keep highest-frequency row per lemma (Phase 7 rule).

## 5. Open English WordNet 2025

- 45 synset files + 27 entry index files + frames.json (39 verb frames).
- Synsets: **107,519**; definitions on 107,519; examples on 34,095; ILI on 104,335.
- Synsets by POS group: adj 18,219, adv 3,615, noun 71,864, verb 13,821
- Relations available: `hypernym` 88,075, `similar` 23,176, `domain_topic` 6,433, `mero_part` 5,387, `entails` 407, `causes` 221
- Entry index: 128,009 lemmas → 185,129 sense links; 7,349 lemmas span multiple POS.

## 6. Cross-source integration notes

- Join keys differ: CEFR/Octanove use headword+POS strings; NGSL uses lemmas; Wiktextract uses entry words; WordNet uses synset IDs. Sense identity (Phase 6) is the only safe join point — never raw spellings (section 9).
- CEFR evidence = CEFR-J (A1–B2) + Octanove (C1/C2) + limited Wiktextract category hints; conflicts preserved per source (section 14).
- Frequency evidence = NGSL ranks/SFI; word-level, so senses of one word share word frequency until sense-frequency estimation exists (Phase 10 priority handles this, section 16).
- The 2.7 GB dump streams at roughly 12,012 records/s on this machine — full ETL passes are feasible (checkpointed, section 125).

Machine-readable twin: `data/source-inventory.json` (Git-ignored like all generated data artifacts).
