/**
 * Search API functions (Phases 14/16): typed wrappers around the backend
 * endpoints, all going through the shared `apiFetch` error-envelope client.
 */

import { apiFetch } from "@/lib/api";
import type {
  FilterFacets,
  SearchRequestBody,
  SearchResultBody,
  SenseDetail,
} from "@/lib/search-types";

export function postSearch(body: SearchRequestBody): Promise<SearchResultBody> {
  return apiFetch<SearchResultBody>("/api/v1/vocabulary/search", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** GET /vocabulary — browse endpoint used for query-less table views. */
export function browseVocabulary(params: SearchRequestBody): Promise<SearchResultBody> {
  const qs = new URLSearchParams();
  qs.set("sort", params.sort);
  qs.set("limit", String(params.limit));
  qs.set("offset", String(params.offset));
  if (params.query.trim()) {
    qs.set("query", params.query.trim());
  }
  if (params.mode !== "lexical") {
    qs.set("mode", params.mode);
  }
  const f = params.filters;
  if (f.cefr.length) qs.set("cefr", f.cefr.join(","));
  if (f.pos.length) qs.set("pos", f.pos.join(","));
  if (f.priority_levels.length) qs.set("priority_levels", f.priority_levels.join(","));
  if (f.priority_min) qs.set("priority_min", f.priority_min);
  if (f.category_key) qs.set("category_key", f.category_key);
  if (f.frequency_bands.length) qs.set("frequency_bands", f.frequency_bands.join(","));
  if (f.max_frequency_rank !== null) {
    qs.set("max_frequency_rank", String(f.max_frequency_rank));
  }
  if (f.flags.length) qs.set("flags", f.flags.join(","));
  if (f.student_id) qs.set("student_id", f.student_id);
  if (f.assigned !== null) qs.set("assigned", f.assigned ? "true" : "false");
  if (f.learning_states.length) qs.set("learning_states", f.learning_states.join(","));
  if (f.due_only === true) qs.set("due_only", "true");
  if (f.difficult_only === true) qs.set("difficult_only", "true");
  if (f.teacher_priority_only === true) qs.set("teacher_priority_only", "true");
  if (f.translation_availability) qs.set("translation_availability", f.translation_availability);
  return apiFetch<SearchResultBody>(`/api/v1/vocabulary?${qs.toString()}`);
}

export function fetchFilterFacets(): Promise<FilterFacets> {
  return apiFetch<FilterFacets>("/api/v1/vocabulary/search/filters");
}

export function fetchSenseDetail(senseId: string): Promise<SenseDetail> {
  return apiFetch<SenseDetail>(
    `/api/v1/vocabulary/${encodeURIComponent(senseId)}`,
  );
}

/** Teacher session (Phase 15) — used by the session bar and login page. */
export interface TeacherSession {
  teacher: { id: string; email: string; display_name: string };
  expires_at: string;
}

export function fetchSession(): Promise<TeacherSession> {
  return apiFetch<TeacherSession>("/api/v1/auth/session");
}

export function login(email: string, password: string): Promise<TeacherSession> {
  return apiFetch<TeacherSession>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<{ revoked: boolean }> {
  return apiFetch<{ revoked: boolean }>("/api/v1/auth/logout", { method: "POST" });
}
