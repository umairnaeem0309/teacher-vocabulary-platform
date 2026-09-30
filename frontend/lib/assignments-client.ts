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
