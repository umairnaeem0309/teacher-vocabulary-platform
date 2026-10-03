/**
 * Assignments API functions (Phase 18).
 */

import { apiFetch } from "@/lib/api";

export interface AssignReport {
  selected: number;
  new: number;
  already_assigned: number;
  failed: { sense_id: string; reason: string }[];
  student_id: string;
  sense_ids: string[];
}

export function assignSenses(body: {
  student_id: string;
  sense_ids: string[];
  learning_state?: string;
  reactivate?: boolean;
}): Promise<AssignReport> {
  return apiFetch<AssignReport>("/api/v1/assignments", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** PATCH /assignments/{id} — state move, priority override, hide, §38 reset. */
export interface AssignmentUpdate {
  learning_state?: string;
  teacher_priority_override?: string | null;
  is_active?: boolean;
  reset_review?: boolean;
  due_at?: string;
}

export function updateAssignment(
  studentId: string,
  assignmentId: string,
  body: AssignmentUpdate,
): Promise<unknown> {
  const qs = new URLSearchParams({ student_id: studentId });
  return apiFetch<unknown>(
    `/api/v1/assignments/${encodeURIComponent(assignmentId)}?${qs.toString()}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

/** §38: clear the FSRS state so a card re-enters the queue as new. */
export function resetReviewState(
  studentId: string,
  assignmentId: string,
): Promise<unknown> {
  return updateAssignment(studentId, assignmentId, { reset_review: true });
}
