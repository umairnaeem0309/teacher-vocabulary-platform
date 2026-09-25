"""Phase 9 tests: deterministic thematic taxonomy (D011, tax-v1)."""


from pipeline.enrich.taxonomy import (
    TAXONOMY,
    TAXONOMY_VERSION,
    classify_senses,
    taxonomy_nodes,
)
from pipeline.enrich.wordnet import (
    WordnetEvidence,
    build_synset_catalog,
    link_senses,
)
from pipeline.identity.identity import MasterSense
from pipeline.sources.wordnet_adapter import (
    SourceSynset,
    SourceSynsetRelation,
)
from pipeline.storage.sqlite_store import ConstructionStore


def _master(word, gloss, pos="noun", sense_key=None):
    return MasterSense(
        headword_display=word,
        headword_search=word,
        pos_canonical=pos,
        sense_key=sense_key or f"{word}|{pos}|test",
        gloss_display=gloss,
        gloss_search=gloss,
    )


class _E:
    def __init__(self, sense) -> None:
        self.sense = sense
        self.cefr_level = None
        self.cefr_confidence = 0.0
        self.cefr_conflict = False
        self.frequency_rank = None
        self.frequency_band = None


class TestTaxonomyStructure:
    def test_minimum_spec_categories_present(self) -> None:
        keys = {t.key for t in TAXONOMY}
        for required in (
            "travel", "home-housing", "family-relationships", "food-cooking",
            "work-business", "money-finance", "education", "technology",
            "internet-social", "news-media", "entertainment", "health",
            "shopping", "transportation", "nature", "weather", "society",
            "government", "communication", "emotions", "personality",
            "sports", "hobbies", "daily-life",
        ):
            assert required in keys

    def test_nodes_unique_and_hierarchical(self) -> None:
        nodes = taxonomy_nodes()
        keys = [n["key"] for n in nodes]
        assert len(keys) == len(set(keys))
        by_key = {n["key"]: n for n in nodes}
        assert by_key["travel"]["parent_key"] is None
        assert by_key["travel-airports"]["parent_key"] == "travel"
        assert by_key["food-methods"]["parent_key"] == "food-cooking"
        tops = [n for n in nodes if n["parent_key"] is None]
        assert len(tops) == 24

    def test_version_is_stable_string(self) -> None:
        assert TAXONOMY_VERSION == "tax-v1.2"


class TestHeadwordTier:
    def test_airport_headword_tier(self) -> None:
        assigns, _ = classify_senses([_master("airport", "a place where air travel operates")])
        rows = assigns["airport|noun|test"]
        travel = [a for a in rows if a.category_key == "travel"]
        assert {(a.category_key, a.subcategory_key) for a in travel} == {
            ("travel", "travel-airports"),
            ("travel", None),
        }
        assert all(a.confidence == 0.90 and a.method == "headword" for a in travel)

    def test_hotel(self) -> None:
        assigns, _ = classify_senses([_master("hotel", "an establishment providing lodging")])
        keys = {(a.category_key, a.subcategory_key) for a in assigns["hotel|noun|test"]}
        assert ("travel", "travel-hotels") in keys

    def test_garden(self) -> None:
        assigns, _ = classify_senses([_master("garden", "an outdoor space where plants are grown")])
        keys = {(a.category_key, a.subcategory_key) for a in assigns["garden|noun|test"]}
        assert ("home-housing", "home-gardening") in keys

    def test_headword_beats_gloss_for_same_category(self) -> None:
        # 'reception' is itself a hotel keyword -> headword tier (0.90),
        # even though the gloss mentions 'hotel' too.
        assigns, _ = classify_senses([_master("reception", "the hotel welcome desk")])
        sub = next(
            a for a in assigns["reception|noun|test"]
            if a.subcategory_key == "travel-hotels"
        )
        assert sub.method == "headword" and sub.confidence == 0.90

    def test_polysemous_keyword_without_meaning_evidence_stays_uncategorized(self) -> None:
        # v1.2 audit fix: 'fast' is a diet keyword, but this sense is
        # about photography — no same-category gloss evidence, no assign.
        s = _master("fast", "more sensitive to light than average")
        assigns, _ = classify_senses([s])
        cats = {a.category_key for a in assigns.get("fast|noun|test", [])}
        assert "food-cooking" not in cats

    def test_polysemous_keyword_with_meaning_evidence_assigns(self) -> None:
        # 'train' + fitness meaning in the gloss -> corroborated.
        s = _master("train", "to practise and exercise to prepare for a match")
        assigns, _ = classify_senses([s])
        keys = {(a.category_key, a.subcategory_key) for a in assigns["train|noun|test"]}
        assert ("sports", "sport-fitness") in keys


class TestGlossTier:
    def test_multi_keyword_gloss_assigns_sub(self) -> None:
        # passport + visa + customs -> travel-documents (3 hits >= 2)
        s = _master("papers", "your passport, visa and customs documents")
        assigns, _ = classify_senses([s])
        keys = {(a.category_key, a.subcategory_key) for a in assigns["papers|noun|test"]}
        assert ("travel", "travel-documents") in keys
        assert ("travel", None) in keys

    def test_single_keyword_gloss_does_not_assign(self) -> None:
        # v1.1: single-keyword gloss hits are noise (D011 audit) and no
        # longer produce assignments.
        s = _master("foyer", "a lobby with a reception desk")
        assigns, _ = classify_senses([s])
        assert not assigns

    def test_multi_category_sense(self) -> None:
        # gloss has 2 hotel keywords (travel) and 2 road-traffic keywords
        # (transportation); 'connection' is not a keyword anywhere.
        s = _master("connection", "a hotel booking beside a busy traffic junction")
        assigns, report = classify_senses([s])
        cats = {a.category_key for a in assigns["connection|noun|test"]}
        assert {"travel", "transportation"} <= cats
        assert report.multi_category_senses >= 1

    def test_uncategorized_counted_not_forced(self) -> None:
        # Nonsense stem-free gloss avoids every keyword table.
        s = _master("florb", "a zxqvu gronk quadules blorptively")
        assigns, report = classify_senses([s])
        assert not assigns
        assert report.uncategorized == 1
        assert report.senses_categorized == 0


class TestWordnetChainTier:
    def _catalog(self):
        # dog -> canine -> animal(nature): definition stems carry the
        # 'animal' domain token two hypernym hops away.
        return build_synset_catalog(
            [
                SourceSynset(
                    synset_id="d1", part_of_speech="n",
                    definition="a domesticated canine kept as a companion",
                    examples=[], ili=None, members=["dog", "pup"],
                ),
                SourceSynset(
                    synset_id="c1", part_of_speech="n",
                    definition="canine mammal of the family Canidae",
                    examples=[], ili=None, members=["canine"],
                ),
                SourceSynset(
                    synset_id="a1", part_of_speech="n",
                    definition="a living animal organism with sensation",
                    examples=[], ili=None, members=["animal"],
                ),
            ],
            [
                SourceSynsetRelation(from_synset_id="d1", to_synset_id="c1", relation="hypernym"),
                SourceSynsetRelation(from_synset_id="c1", to_synset_id="a1", relation="hypernym"),
            ],
        )

    def _evidence(self):
        return {"dog": WordnetEvidence(lemma="dog", synsets_by_pos={"n": ["d1"]})}

    def test_dog_via_hypernym_chain(self) -> None:
        senses = [_master("dog", "a common name for the species Canis familiaris")]
        catalog = self._catalog()
        links, _ = link_senses(senses, catalog, self._evidence())
        assigns, _ = classify_senses(senses, links, catalog)
        rows = assigns["dog|noun|test"]
        cats = {a.category_key for a in rows}
        assert "nature" in cats
        wn = [a for a in rows if a.method == "wordnet-chain"]
        assert wn and all(a.confidence == 0.85 for a in wn)

    def test_no_catalog_no_chain(self) -> None:
        senses = [_master("dog", "a common name for the species Canis familiaris")]
        assigns, _ = classify_senses(senses, {}, None)
        assert not any(
            a.method == "wordnet-chain" for a in assigns.get("dog|noun|test", [])
        )


class TestDeterminismAndReport:
    def test_same_input_same_output(self) -> None:
        senses = [
            _master("airport", "a place where planes land"),
            _master("stew", "a dish of meat and vegetables cooked slowly"),
            _master("florb", "a zxqvu gronk quadules blorptively"),
        ]
        a1, r1 = classify_senses(senses)
        a2, r2 = classify_senses(senses)
        assert a1 == a2
        assert r1.as_dict() == r2.as_dict()

    def test_report_counts(self) -> None:
        senses = [
            _master("airport", "an air travel terminal where planes land"),
            _master("whatsit", "a gadget whose name one has forgotten"),
        ]
        _, report = classify_senses(senses)
        d = report.as_dict()
        assert d["senses_total"] == 2
        assert d["senses_categorized"] == 1
        assert d["uncategorized"] == 1
        assert d["assignments_created"] >= 2
        assert d["version"] == "tax-v1.2"

    def test_spec_words_classified(self) -> None:
        """Spec §85 test list: travel/cooking/airport/hotel/personality/
        business/health."""
        cases = [
            ("travel", "going abroad on a journey for tourism"),
            ("cook", "to prepare food by heating it in a pan"),
            ("airport", "an air travel terminal where planes take off"),
            ("hotel", "travel lodging with rooms for booking"),
            ("generous", "a kind personality trait, happy to give"),
            ("business", "a company that sells goods for commercial profit"),
            ("health", "being free from illness and disease"),
        ]
        senses = [_master(w, g) for w, g in cases]
        assigns, report = classify_senses(senses)
        assert report.senses_categorized == len(cases)
        tops = {
            w: {a.category_key for a in assigns.get(f"{w}|noun|test", [])}
            for w, _ in cases
        }
        assert "travel" in tops["travel"]
        assert "food-cooking" in tops["cook"]
        assert "travel" in tops["airport"]
        assert "travel" in tops["hotel"]
        assert "personality" in tops["generous"]
        assert "work-business" in tops["business"]
        assert "health" in tops["health"]


class TestTaxonomyStore:
    def test_nodes_and_assignments_roundtrip(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        senses = [_master("airport", "an air travel terminal where planes land")]
        store.upsert_senses([_E(s) for s in senses])
        assigns, _ = classify_senses(senses)
        nodes = taxonomy_nodes()
        assert store.upsert_taxonomy_nodes(nodes) == len(nodes)
        written = store.upsert_categories(assigns)
        assert written == len(assigns["airport|noun|test"])
        counts = store.count_taxonomy()
        assert counts["nodes"] == len(nodes)
        assert counts["categorized_senses"] == 1
        qc = store.qc_summary()
        assert qc["with_categories"] == 1
        row = store.conn.execute(
            "SELECT subcategory_key, confidence FROM sense_categories "
            "WHERE category_key='travel' AND subcategory_key IS NOT NULL"
        ).fetchone()
        assert row == ("travel-airports", 0.9)
        store.close()

    def test_idempotent_reupsert(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        senses = [_master("airport", "an air travel terminal where planes land")]
        store.upsert_senses([_E(s) for s in senses])
        store.upsert_taxonomy_nodes(taxonomy_nodes())
        assigns, _ = classify_senses(senses)
        store.upsert_categories(assigns)
        store.upsert_categories(assigns)
        counts = store.count_taxonomy()
        assert counts["assignments"] == len(assigns["airport|noun|test"])
        store.close()
