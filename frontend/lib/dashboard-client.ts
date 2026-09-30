/**
 * Dashboard API functions (Phase 21, section 36): typed wrappers around
 * the per-student dashboard endpoints, via the shared error-envelope
 * client.
 */

import { apiFetch } from "@/lib/api";

export interface DashboardSense {
  id: string;
  headword: string;
  part_of_speech: string | null;
  cefr_level: string | null;
  definition_preview: string | null;
  translation_pl: string | null;
  example: string | null;
}

export interface DashboardNextUp {
  assignment_id: string;
  learning_state: string;
  is_overdue: boolean | null;
  due_at: string | null;
  sense: DashboardSense;
}

export interface DashboardCounts {
  assigned: number;
  learning: number;
  reviewing: number;
  mastered: number;
  due: number;
  overdue: number;
}

export interface DashboardDifficultItem {
  assignment_id: string;
  sense_id: string;
  headword: string;
  part_of_speech: string | null;
  cefr_level: string | null;
  hard_count: number;
  total_reviews: number;
}

export interface DashboardRecentReview {
  rating: "HARD" | "MEDIUM" | "EASY";
  reviewed_at: string;
  new_due_at: string | null;
  headword: string;
  part_of_speech: string | null;
}

export interface StudentDashboard {
  student: {
    id: string;
    display_name: string;
    status: string;
  };
  counts: DashboardCounts;
  next_up: DashboardNextUp | null;
  difficult: DashboardDifficultItem[];
  recent_reviews: DashboardRecentReview[];
}

export interface DashboardOverview {
  students: Array<
    DashboardCounts & {
      student: {
        id: string;
        display_name: string;
        status: string;
      };
    }
  >;
  total: number;
  totals: DashboardCounts;
}

export function fetchStudentDashboard(studentId: string): Promise<StudentDashboard> {
  return apiFetch<StudentDashboard>(`/api/v1/students/${studentId}/dashboard`);
}

export function fetchDashboardOverview(): Promise<DashboardOverview> {
  return apiFetch<DashboardOverview>("/api/v1/dashboard");
}
