/**
 * Reviews API functions (Phase 20).
 */

import { apiFetch } from "@/lib/api";

export interface DueItem {
  assignment_id: string;
  learning_state: string;
  is_overdue: boolean | null;
  due_at: string | null;
  repetitions: number;
  lapses: number;
  last_review_at: string | null;
  sense: {
    id: string;
    headword: string;
    part_of_speech: string | null;
    cefr_level: string | null;
    definition_preview: string | null;
    translation_pl: string | null;
    example: string | null;
  };
}

/** §36: narrow the review queue to a chosen selection. */
export interface DueQueueOptions {
  includeNew?: boolean;
  assignmentIds?: string[];
  setId?: string;
  learningStates?: string[];
  difficultOnly?: boolean;
  search?: string;
}

export function fetchDueQueue(
  studentId: string,
  limit = 50,
  options: DueQueueOptions = {},
): Promise<{ items: DueItem[]; total: number }> {
  const qs = new URLSearchParams();
  qs.set("student_id", studentId);
  qs.set("limit", String(limit));
  if (options.includeNew === false) qs.set("include_new", "false");
  if (options.assignmentIds?.length) {
    qs.set("assignment_ids", options.assignmentIds.join(","));
  }
  if (options.setId) qs.set("set_id", options.setId);
  if (options.learningStates?.length) {
    qs.set("learning_states", options.learningStates.join(","));
  }
  if (options.difficultOnly) qs.set("difficult_only", "true");
  if (options.search) qs.set("search", options.search);
  return apiFetch<{ items: DueItem[]; total: number }>(
    `/api/v1/reviews/due?${qs.toString()}`,
  );
}

export interface ReviewResult {
  assignment_id: string;
  rating: string;
  fsrs_grade: number;
  learning_state: string;
  stability: number;
  difficulty: number;
  repetitions: number;
  lapses: number;
  due_at: string;
  reviewed_at: string;
}

export function recordReview(body: {
  student_id: string;
  assignment_id: string;
  rating: "HARD" | "MEDIUM" | "EASY";
}): Promise<ReviewResult> {
  return apiFetch<ReviewResult>("/api/v1/reviews", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
