/**
 * Vocabulary sets API functions (Phase 19).
 */

import { apiFetch } from "@/lib/api";

export interface VocabularySet {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface SetDetail extends VocabularySet {
  items: {
    sense_id: string;
    added_at: string;
    headword: string;
    part_of_speech: string | null;
    cefr_level: string | null;
    definition_preview: string | null;
    translation_pl: string | null;
  }[];
}

export interface ItemsReport {
  selected: number;
  new: number;
  already_in_set: number;
  failed: { sense_id: string; reason: string }[];
  set_id: string;
  sense_ids: string[];
}

export interface AssignReport {
  selected: number;
  new: number;
  already_assigned: number;
  failed: { sense_id: string; reason: string }[];
  set_id: string;
  set_name: string;
}

export function listSets(): Promise<{ sets: VocabularySet[]; total: number }> {
  return apiFetch<{ sets: VocabularySet[]; total: number }>("/api/v1/sets");
}

export function createSet(body: {
  name: string;
  description?: string | null;
}): Promise<VocabularySet> {
  return apiFetch<VocabularySet>("/api/v1/sets", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchSet(setId: string): Promise<SetDetail> {
  return apiFetch<SetDetail>(`/api/v1/sets/${encodeURIComponent(setId)}`);
}

export function updateSet(
  setId: string,
  body: { name?: string; description?: string | null },
): Promise<VocabularySet> {
  return apiFetch<VocabularySet>(`/api/v1/sets/${encodeURIComponent(setId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteSet(setId: string): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(
    `/api/v1/sets/${encodeURIComponent(setId)}`,
    { method: "DELETE" },
  );
}

export function addSetItems(
  setId: string,
  sense_ids: string[],
): Promise<ItemsReport> {
  return apiFetch<ItemsReport>(`/api/v1/sets/${encodeURIComponent(setId)}/items`, {
    method: "POST",
    body: JSON.stringify({ sense_ids }),
  });
}

export function removeSetItems(
  setId: string,
  sense_ids: string[],
): Promise<{ removed: number; not_in_set: number }> {
  return apiFetch<{ removed: number; not_in_set: number }>(
    `/api/v1/sets/${encodeURIComponent(setId)}/items`,
    { method: "DELETE", body: JSON.stringify({ sense_ids }) },
  );
}

export function assignSet(
  setId: string,
  student_id: string,
  learning_state = "ASSIGNED",
): Promise<AssignReport> {
  return apiFetch<AssignReport>(
    `/api/v1/sets/${encodeURIComponent(setId)}/assign`,
    { method: "POST", body: JSON.stringify({ student_id, learning_state }) },
  );
}
