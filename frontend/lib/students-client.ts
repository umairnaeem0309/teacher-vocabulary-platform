/**
 * Students API functions (Phase 17): typed wrappers around the
 * /students endpoints, via the shared error-envelope client.
 */

import { apiFetch } from "@/lib/api";

export interface Student {
  id: string;
  display_name: string;
  email: string | null;
  notes: string | null;
  status: "ACTIVE" | "INACTIVE" | "DELETED";
  created_at: string;
  updated_at: string;
  assigned_count: number;
}

export interface StudentsListBody {
  students: Student[];
  total: number;
}

export interface StudentVocabularyItem {
  id: string;
  learning_state: string;
  is_active: boolean;
  assigned_at: string;
  teacher_priority_override: string | null;
  sense: {
    id: string;
    headword: string;
    part_of_speech: string | null;
    cefr_level: string | null;
    definition_preview: string | null;
    priority_level: string | null;
    translation_pl: string | null;
  };
  due_at: string | null;
  repetitions: number;
  lapses: number;
}

export function listStudents(includeInactive = false): Promise<StudentsListBody> {
  return apiFetch<StudentsListBody>(
    `/api/v1/students${includeInactive ? "?include_inactive=true" : ""}`,
  );
}

export function createStudent(body: {
  display_name: string;
  email?: string | null;
  notes?: string | null;
}): Promise<Student> {
  return apiFetch<Student>("/api/v1/students", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateStudent(
  studentId: string,
  body: { display_name?: string; email?: string | null; notes?: string | null },
): Promise<Student> {
  return apiFetch<Student>(`/api/v1/students/${encodeURIComponent(studentId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function setStudentStatus(
  studentId: string,
  status: "ACTIVE" | "INACTIVE" | "DELETED",
): Promise<Student> {
  return apiFetch<Student>(
    `/api/v1/students/${encodeURIComponent(studentId)}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
}

export function fetchStudent(studentId: string): Promise<Student> {
  return apiFetch<Student>(`/api/v1/students/${encodeURIComponent(studentId)}`);
}

export function fetchStudentVocabulary(
  studentId: string,
): Promise<{ items: StudentVocabularyItem[]; total: number }> {
  return apiFetch<{ items: StudentVocabularyItem[]; total: number }>(
    `/api/v1/students/${encodeURIComponent(studentId)}/vocabulary`,
  );
}
