"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useMemo, useState } from "react";

import { resetReviewState } from "@/lib/assignments-client";
import { ROUTES } from "@/lib/routes";
import {
  fetchStudent,
  fetchStudentVocabulary,
} from "@/lib/students-client";
import { LEARNING_STATES } from "@/lib/search-types";

/**
 * Student vocabulary (§39, §59 step 14): the teacher's own list of what this
 * student has been assigned, filterable by due status, difficulty and
 * learning state. Required by §53 as its own route; the profile page links
 * here for focused filtering.
 *
 * The payload is already the student's complete assigned set (bounded per
 * student, see GET /students/{id}/vocabulary), so filtering is applied to
 * the fetched list — this is not a corpus search, where §22 requires SQL.
 */

type RowFilter = "all" | "due" | "overdue" | "difficult";

export default function StudentVocabularyPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = use(params);
  const queryClient = useQueryClient();
  const [rowFilter, setRowFilter] = useState<RowFilter>("all");
  const [stateFilter, setStateFilter] = useState<string>("");
  const [note, setNote] = useState<string | null>(null);

  // §38: a teacher can reset a card's review state where appropriate.
  const reset = useMutation({
    mutationFn: (assignmentId: string) =>
      resetReviewState(studentId, assignmentId),
    onSuccess: () => {
      setNote("Review state reset — the card is new again.");
      queryClient.invalidateQueries({ queryKey: ["students"] });
    },
    onError: () => setNote("Could not reset the review state."),
  });

  const student = useQuery({
    queryKey: ["students", "detail", studentId],
    queryFn: () => fetchStudent(studentId),
    retry: false,
  });

  const vocabulary = useQuery({
    queryKey: ["students", "vocabulary", studentId],
    queryFn: () => fetchStudentVocabulary(studentId),
    retry: false,
  });

  const items = useMemo(() => vocabulary.data?.items ?? [], [vocabulary.data]);

  // "Due now" is a wall-clock predicate, so the clock must be read at
  // render time. The alternative (setState-in-effect) is forbidden by the
  // same rule set and would only add a cascading render, so the impure read
  // is deliberate and narrowly disabled here.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();

  const visible = useMemo(() => {
    return items.filter((item) => {
      if (stateFilter && item.learning_state !== stateFilter) return false;
      const dueMs = item.due_at ? Date.parse(item.due_at) : null;
      if (rowFilter === "due") return dueMs !== null && dueMs <= now;
      if (rowFilter === "overdue") return dueMs !== null && dueMs < now;
      if (rowFilter === "difficult") return (item.lapses ?? 0) > 0;
      return true;
    });
  }, [items, rowFilter, stateFilter, now]);

  if (vocabulary.isError || student.isError) {
    return (
      <main className="mx-auto max-w-4xl px-4 py-6">
        <p className="text-red-600">
          This student&apos;s vocabulary could not be loaded.
        </p>
        <Link href={ROUTES.students} className="mt-4 inline-block underline">
          ← Back to students
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <Link href={ROUTES.student(studentId)} className="text-sm underline">
        ← Back to student
      </Link>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">
          {student.data?.display_name ?? "Student"} — vocabulary
        </h1>
        <span className="text-sm text-neutral-500">
          {items.length} assigned
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="block">
          <span className="text-xs text-neutral-500">Show</span>
          <select
            value={rowFilter}
            onChange={(e) => setRowFilter(e.target.value as RowFilter)}
            className="ml-2 rounded border border-neutral-300 px-2 py-1"
          >
            <option value="all">All</option>
            <option value="due">Due</option>
            <option value="overdue">Overdue</option>
            <option value="difficult">Difficult</option>
          </select>
        </label>

        <label className="block">
          <span className="text-xs text-neutral-500">Learning state</span>
          <select
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            className="ml-2 rounded border border-neutral-300 px-2 py-1"
          >
            <option value="">Any</option>
            {LEARNING_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <span className="text-neutral-500">
          {visible.length} of {items.length} shown
        </span>
        {note && <span className="text-xs text-neutral-600">{note}</span>}
      </div>

      <table className="mt-3 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-neutral-300 text-left">
            <th className="py-1">Headword</th>
            <th className="py-1">Polish</th>
            <th className="py-1">CEFR</th>
            <th className="py-1">State</th>
            <th className="py-1">Due</th>
            <th className="py-1">Reps</th>
            <th className="py-1">Review</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((item) => (
            <tr key={item.id} className="border-b border-neutral-100">
              <td className="py-1">
                <Link
                  href={ROUTES.vocabularySense(item.sense.id)}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {item.sense.headword}
                </Link>
              </td>
              <td className="py-1 text-neutral-600">
                {item.sense.translation_pl ?? "—"}
              </td>
              <td className="py-1">{item.sense.cefr_level ?? "—"}</td>
              <td className="py-1">{item.learning_state}</td>
              <td className="py-1">
                {item.due_at ? new Date(item.due_at).toLocaleDateString() : "—"}
              </td>
              <td className="py-1">{item.repetitions ?? 0}</td>
              <td className="py-1">
                <button
                  type="button"
                  title="Reset the FSRS review state (card becomes new)"
                  disabled={reset.isPending || item.repetitions == null}
                  onClick={() => reset.mutate(item.id)}
                  className="rounded border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100 disabled:opacity-40"
                >
                  Reset
                </button>
              </td>
            </tr>
          ))}
          {visible.length === 0 && (
            <tr>
              <td colSpan={7} className="py-6 text-center text-neutral-500">
                {vocabulary.isLoading ? "Loading…" : "Nothing matches this filter."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}
