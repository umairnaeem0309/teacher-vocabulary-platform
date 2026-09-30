/**
 * Types mirroring the backend search API (Phase 14) and the Phase 16
 * browse/detail endpoints. Kept in sync with
 * backend/app/api/v1/search.py, backend/app/api/v1/vocabulary.py and
 * pipeline/search/engine.py.
 */

export type SearchMode = "hybrid" | "lexical" | "semantic";
export type SortKey = "relevance" | "headword" | "priority" | "frequency";

export interface SearchFilters {
  cefr: string[];
  pos: string[];
  priority_levels: string[];
  priority_min: string | null;
  category_key: string | null;
  frequency_bands: string[];
  max_frequency_rank: number | null;
  flags: string[];
}

export const EMPTY_FILTERS: SearchFilters = {
  cefr: [],
  pos: [],
  priority_levels: [],
  priority_min: null,
  category_key: null,
  frequency_bands: [],
  max_frequency_rank: null,
  flags: [],
};

export interface SearchHit {
  sense_id: string;
  sense_key: string;
  headword: string;
  part_of_speech: string | null;
  cefr_level: string | null;
  definition_preview: string | null;
  priority_score: number | null;
  priority_level: string | null;
  frequency_rank: number | null;
  translations: string[];
  lexical_rank: number | null;
  semantic_rank: number | null;
  semantic_distance: number | null;
  score: number;
}

export interface SearchResultBody {
  total: number;
  mode: SearchMode;
  query: string;
  hits: SearchHit[];
}

export interface SearchRequestBody {
  query: string;
  mode: SearchMode;
  filters: SearchFilters;
  sort: SortKey;
  limit: number;
  offset: number;
}

/** GET /vocabulary/search/filters — enumerable filter values. */
export interface FilterFacets {
  categories: { key: string; name: string }[];
  part_of_speech: string[];
  cefr: string[];
  priority_levels: string[];
  frequency_bands: string[];
  flags: string[];
}

/** GET /vocabulary/{sense_id} — full detail payload. */
export interface SenseDetail {
  sense: {
    id: string;
    sense_key: string;
    headword: string;
    headword_normalized: string;
    part_of_speech: string | null;
    cefr_level: string | null;
    definition_preview: string | null;
    priority_score: number | null;
    priority_level: string | null;
    priority_version: string | null;
    processing_version: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
  };
  forms: { form: string; is_lemma: boolean }[];
  definitions: { definition: string; source: string }[];
  translations: { translation: string; language: string; confidence: number | null }[];
  examples: { example: string; source: string }[];
  categories: { key: string; name: string }[];
  frequency: {
    source_key: string;
    source_name: string;
    rank: number | null;
    frequency_per_million: number | null;
    raw_value: string | null;
  }[];
  priorities: { version: string; score: number; level: string }[];
}
