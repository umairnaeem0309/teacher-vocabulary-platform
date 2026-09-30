/**
 * Pure bidirectional mapping between the vocabulary table's state and
 * URL search params. Every table interaction is shareable/bookmarkable,
 * and back/forward navigation restores the exact view (section 23:
 * dense table; teacher-workstation ergonomics).
 */

import { EMPTY_FILTERS } from "@/lib/search-types";
import type { SearchFilters, SearchMode, SortKey } from "@/lib/search-types";

export interface TableState {
  query: string;
  mode: SearchMode;
  sort: SortKey;
  filters: SearchFilters;
  page: number; // 0-based
  pageSize: number;
}

export const DEFAULT_PAGE_SIZE = 50;

export const DEFAULT_TABLE_STATE: TableState = {
  query: "",
  mode: "lexical",
  sort: "headword",
  filters: EMPTY_FILTERS,
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
};

const LIST_PARAMS = ["cefr", "pos", "priority_levels", "frequency_bands", "flags"] as const;

export function stateToParams(state: TableState): URLSearchParams {
  const p = new URLSearchParams();
  if (state.query.trim()) p.set("q", state.query.trim());
  if (state.mode !== DEFAULT_TABLE_STATE.mode) p.set("mode", state.mode);
  if (state.sort !== DEFAULT_TABLE_STATE.sort) p.set("sort", state.sort);
  const f = state.filters;
  for (const key of LIST_PARAMS) {
    if (f[key].length) p.set(key, f[key].join(","));
  }
  if (f.priority_min) p.set("pmin", f.priority_min);
  if (f.category_key) p.set("cat", f.category_key);
  if (f.max_frequency_rank !== null) p.set("maxrank", String(f.max_frequency_rank));
  if (state.page !== 0) p.set("page", String(state.page));
  if (state.pageSize !== DEFAULT_PAGE_SIZE) p.set("size", String(state.pageSize));
  return p;
}

export function paramsToState(params: URLSearchParams): TableState {
  const filters: SearchFilters = {
    ...EMPTY_FILTERS,
    cefr: parseList(params.get("cefr")),
    pos: parseList(params.get("pos")),
    priority_levels: parseList(params.get("priority_levels")),
    frequency_bands: parseList(params.get("frequency_bands")),
    flags: parseList(params.get("flags")),
    priority_min: params.get("pmin"),
    category_key: params.get("cat"),
    max_frequency_rank: parseNullableInt(params.get("maxrank")),
  };
  const rawPage = parseNonNegativeInt(params.get("page"));
  return {
    query: params.get("q") ?? "",
    mode: parseMode(params.get("mode")),
    sort: parseSort(params.get("sort")),
    filters,
    page: rawPage === null ? 0 : rawPage,
    pageSize: clampPageSize(params.get("size")),
  };
}

function parseList(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

function parseNonNegativeInt(value: string | null): number | null {
  if (value === null) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function parseNullableInt(value: string | null): number | null {
  return parseNonNegativeInt(value);
}

function parseMode(value: string | null): SearchMode {
  return value === "hybrid" || value === "semantic" || value === "lexical"
    ? value
    : DEFAULT_TABLE_STATE.mode;
}

function parseSort(value: string | null): SortKey {
  return value === "relevance" || value === "priority" || value === "frequency"
    ? value
    : value === "headword"
      ? "headword"
      : DEFAULT_TABLE_STATE.sort;
}

function clampPageSize(value: string | null): number {
  const n = parseNonNegativeInt(value);
  if (n === null || n < 10) return DEFAULT_PAGE_SIZE;
  return Math.min(n, 500);
}

/** True when nothing deviates from the defaults (hides a clean URL). */
export function isDefaultState(state: TableState): boolean {
  return stateToParams(state).size === 0;
}
