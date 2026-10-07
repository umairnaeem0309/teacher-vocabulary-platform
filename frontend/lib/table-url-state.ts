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

/**
 * Defaults are the *searching* teacher's view, not the browsing one:
 * relevance order over the hybrid (lexical + semantic + topic) engine.
 *
 * This used to be `lexical` + `headword`, which silently disabled the whole
 * semantic and taxonomy layers — a query came back in alphabetical order
 * (`travel` -> airsick, astral, basket, ...) and a topic query could never
 * reach the vocabulary of that topic. Query-less browsing is unaffected: the
 * page maps relevance-on-an-empty-query to `priority` (see `effectiveSort`
 * in app/vocabulary/page.tsx), so the browse path stays a deterministic
 * SQL-ordered scan with no embedding call.
 */
export const DEFAULT_TABLE_STATE: TableState = {
  query: "",
  mode: "hybrid",
  sort: "relevance",
  filters: EMPTY_FILTERS,
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
};

const LIST_PARAMS = ["cefr", "pos", "priority_levels", "frequency_bands", "flags", "learning_states"] as const;

/** boolean|null filters stored as "yes" when on (absent = unset). */
const FLAG_PARAMS = {
  due_only: "due",
  difficult_only: "difficult",
  teacher_priority_only: "tprio",
} as const;

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
  if (f.student_id) p.set("student", f.student_id);
  if (f.assigned !== null) p.set("assigned", f.assigned ? "yes" : "no");
  if (f.due_only === true) p.set(FLAG_PARAMS.due_only, "yes");
  if (f.difficult_only === true) p.set(FLAG_PARAMS.difficult_only, "yes");
  if (f.teacher_priority_only === true) {
    p.set(FLAG_PARAMS.teacher_priority_only, "yes");
  }
  if (f.translation_availability) p.set("tavail", f.translation_availability);
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
    learning_states: parseList(params.get("learning_states")),
    priority_min: params.get("pmin"),
    category_key: params.get("cat"),
    max_frequency_rank: parseNullableInt(params.get("maxrank")),
    student_id: params.get("student"),
    assigned: parseAssigned(params.get("assigned")),
    due_only: parseFlag(params.get("due")),
    difficult_only: parseFlag(params.get("difficult")),
    teacher_priority_only: parseFlag(params.get("tprio")),
    translation_availability: params.get("tavail"),
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

function parseAssigned(value: string | null): boolean | null {
  if (value === "yes") return true;
  if (value === "no") return false;
  return null;
}

function parseFlag(value: string | null): boolean | null {
  return value === "yes" ? true : null;
}

function parseMode(value: string | null): SearchMode {
  return value === "hybrid" || value === "semantic" || value === "lexical"
    ? value
    : DEFAULT_TABLE_STATE.mode;
}

const SORT_KEYS: SortKey[] = [
  "relevance",
  "headword",
  "polish",
  "cefr",
  "topic",
  "pos",
  "priority",
  "frequency",
  "student_status",
];

function parseSort(value: string | null): SortKey {
  return value !== null && (SORT_KEYS as string[]).includes(value)
    ? (value as SortKey)
    : DEFAULT_TABLE_STATE.sort;
}

function clampPageSize(value: string | null): number {
  const n = parseNonNegativeInt(value);
  if (n === null || n < 10) return DEFAULT_PAGE_SIZE;
  // Hard cap must match the backend's MAX_LIMIT (200) or the API returns
  // 422 for a page size the URL/UI otherwise accepts (Phase 25 fix).
  return Math.min(n, 200);
}

/** True when nothing deviates from the defaults (hides a clean URL). */
export function isDefaultState(state: TableState): boolean {
  return stateToParams(state).size === 0;
}
