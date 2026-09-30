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

export function fetchDueQueue(
  studentId: string,
  limit = 50,
): Promise<{ items: DueItem[]; total: number }> {
  return apiFetch<{ items: DueItem[]; total: number }>(
    `/api/v1/reviews/due?student_id=${encodeURIComponent(studentId)}&limit=${limit}`,
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
