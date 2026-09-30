/**
 * Application route manifest (master_prompt.md section 53).
 *
 * Single source of truth for navigation and route coverage tests. Dynamic
 * segments are expressed as functions; `ROUTE_DEFINITIONS` mirrors the
 * complete required route list so tests can verify nothing is missing.
 */

export const ROUTES = {
  login: "/login",
  dashboard: "/dashboard",
  vocabulary: "/vocabulary",
  vocabularySense: (senseId: string) => `/vocabulary/${senseId}`,
  students: "/students",
  student: (studentId: string) => `/students/${studentId}`,
  studentVocabulary: (studentId: string) => `/students/${studentId}/vocabulary`,
  studentReview: (studentId: string) => `/students/${studentId}/review`,
  sets: "/sets",
  set: (setId: string) => `/sets/${setId}`,
  settings: "/settings",
  settingsShortcuts: "/settings/shortcuts",
} as const;

export interface RouteDefinition {
  /** Concrete Next.js route path (square-bracket dynamic segments). */
  path: string;
  /** Which phase implements the real UI. */
  phase: number;
  description: string;
}

export const ROUTE_DEFINITIONS: RouteDefinition[] = [
  { path: "/login", phase: 15, description: "Teacher authentication" },
  { path: "/dashboard", phase: 21, description: "Per-student due/overdue overview" },
  { path: "/vocabulary", phase: 16, description: "Dense vocabulary browser" },
  { path: "/vocabulary/[senseId]", phase: 16, description: "Single sense details" },
  { path: "/students", phase: 17, description: "Student list and management" },
  { path: "/students/[studentId]", phase: 17, description: "Student profile" },
  { path: "/students/[studentId]/vocabulary", phase: 17, description: "Student vocabulary" },
  { path: "/students/[studentId]/review", phase: 21, description: "Live review mode" },
  { path: "/sets", phase: 19, description: "Vocabulary sets" },
  { path: "/sets/[setId]", phase: 19, description: "Set details" },
  { path: "/settings", phase: 21, description: "Application settings" },
  { path: "/settings/shortcuts", phase: 21, description: "Keyboard shortcut configuration" },
];
