"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";

import { ApiError } from "@/lib/api";
import { fetchStudentDashboard } from "@/lib/dashboard-client";
import { ROUTES } from "@/lib/routes";
import {
  fetchStudent,
  fetchStudentVocabulary,
  setStudentStatus,
  updateStudent,
} from "@/lib/students-client";

/**
 * Student profile (section 27): identity, edit, assigned vocabulary with
 * learning state, lifecycle actions. Deactivate/reactivate are immediate
 * (reversible); delete asks for confirmation because it soft-deletes the
 * record (history is preserved, but the profile leaves the lists).
 */
export default function StudentProfilePage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = use(params);
  const queryClient = useQueryClient();
  const [name, setName] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

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

  const dashboard = useQuery({
    queryKey: ["students", "dashboard", studentId],
    queryFn: () => fetchStudentDashboard(studentId),
    retry: false,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["students"] });
  }

  const save = useMutation({
    mutationFn: () =>
      updateStudent(studentId, {
        ...(name !== null ? { display_name: name } : {}),
        ...(email !== null ? { email: email || null } : {}),
        ...(notes !== null ? { notes: notes || null } : {}),
      }),
    onSuccess: () => {
      setError(null);
      setName(null);
      setEmail(null);
      setNotes(null);
      invalidate();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not save."),
  });

  const setStatus = useMutation({
    mutationFn: (status: "ACTIVE" | "INACTIVE" | "DELETED") =>
      setStudentStatus(studentId, status),
    onSuccess: () => {
      setConfirmDelete(false);
      invalidate();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not update status."),
  });

  if (student.isError) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-red-600">This student could not be loaded.</p>
        <Link href={ROUTES.students} className="mt-4 inline-block underline">
          ← Back to students
        </Link>
      </main>
    );
  }

  const s = student.data;
  const dirty = name !== null || email !== null || notes !== null;

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <Link href={ROUTES.students} className="text-sm underline">
        ← Back to students
      </Link>

      {student.isLoading || !s ? (
        <p className="mt-8 text-neutral-500">Loading…</p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">{s.display_name}</h1>
            <span
              className={`rounded px-2 py-0.5 text-xs ${
                s.status === "ACTIVE"
                  ? "bg-green-100 text-green-800"
                  : "bg-neutral-200 text-neutral-600"
              }`}
            >
              {s.status}
            </span>
            <span className="text-sm text-neutral-500">
              {s.assigned_count} assigned
            </span>
          </div>

          <section className="mt-4 space-y-2">
            <label className="block">
              <span className="text-xs text-neutral-500">Name</span>
              <input
                maxLength={200}
                className="block w-72 rounded border border-neutral-300 px-2 py-1"
                value={name ?? s.display_name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs text-neutral-500">Email</span>
              <input
                type="email"
                maxLength={320}
                className="block w-72 rounded border border-neutral-300 px-2 py-1"
                value={email ?? s.email ?? ""}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs text-neutral-500">Notes</span>
              <textarea
                rows={3}
                className="block w-96 rounded border border-neutral-300 px-2 py-1"
                value={notes ?? s.notes ?? ""}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!dirty || save.isPending}
                onClick={() => save.mutate()}
                className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-40"
              >
                {save.isPending ? "Saving…" : "Save changes"}
              </button>

              {s.status === "ACTIVE" && (
                <button
                  type="button"
                  onClick={() => setStatus.mutate("INACTIVE")}
                  className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100"
                >
                  Deactivate
                </button>
              )}
              {s.status === "INACTIVE" && (
                <button
                  type="button"
                  onClick={() => setStatus.mutate("ACTIVE")}
                  className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100"
                >
                  Reactivate
                </button>
              )}
              {s.status !== "DELETED" && !confirmDelete && (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
                >
                  Delete…
                </button>
              )}
              {confirmDelete && (
                <span className="flex items-center gap-2 text-sm">
                  <span className="text-neutral-600">
                    Delete this student? History is kept, but this cannot be
                    undone from the UI.
                  </span>
                  <button
                    type="button"
                    onClick={() => setStatus.mutate("DELETED")}
                    className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-500"
                  >
                    Confirm delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="rounded border border-neutral-300 px-3 py-1.5"
                  >
                    Cancel
                  </button>
                </span>
              )}
            </div>
          </section>

          <section className="mt-8">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Review dashboard
            </h2>
            {dashboard.isLoading && (
              <p className="mt-2 text-sm text-neutral-500">Loading…</p>
            )}
            {dashboard.data && <DashboardPanel data={dashboard.data} />}
          </section>

          <section className="mt-8">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                Assigned vocabulary ({vocabulary.data?.total ?? 0})
              </h2>
              <Link
                href={ROUTES.studentVocabulary(studentId)}
                className="text-xs underline"
              >
                Filter vocabulary →
              </Link>
            </div>
            <table className="mt-2 w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-300 text-left">
                  <th className="py-1">Headword</th>
                  <th className="py-1">Polish</th>
                  <th className="py-1">CEFR</th>
                  <th className="py-1">State</th>
                  <th className="py-1">Due</th>
                </tr>
              </thead>
              <tbody>
                {(vocabulary.data?.items ?? []).map((item) => (
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
                      {item.due_at
                        ? new Date(item.due_at).toLocaleDateString()
                        : "—"}
                    </td>
                  </tr>
                ))}
                {(vocabulary.data?.items ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-neutral-500">
                      Nothing assigned yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </>
      )}
    </main>
  );
}

function DashboardPanel({
  data,
}: {
  data: Awaited<ReturnType<typeof fetchStudentDashboard>>;
}) {
  const c = data.counts;
  const next = data.next_up;

  return (
    <div className="mt-2 space-y-3">
      <div className="flex flex-wrap gap-2 text-sm">
        {(
          [
            ["Assigned", c.assigned],
            ["Learning", c.learning],
            ["Reviewing", c.reviewing],
            ["Mastered", c.mastered],
            ["Due today", c.due],
            ["Overdue", c.overdue],
          ] as const
        ).map(([label, value]) => (
          <span key={label} className="rounded border border-neutral-200 px-2 py-1">
            <span className="text-neutral-500">{label}</span>{" "}
            <span
              className={`font-semibold ${
                label === "Overdue" && value > 0 ? "text-red-600" : ""
              }`}
            >
              {value}
            </span>
          </span>
        ))}
      </div>

      {next ? (
        <div className="rounded border border-neutral-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            What should I review next?
          </p>
          <p className="mt-1 text-sm">
            <span className="font-medium">{next.sense.headword}</span>
            {next.sense.part_of_speech && (
              <span className="text-neutral-500"> · {next.sense.part_of_speech}</span>
            )}
            {next.sense.translation_pl && (
              <span className="text-neutral-600"> — {next.sense.translation_pl}</span>
            )}
          </p>
          <p className="mt-0.5 text-xs text-neutral-500">
            {next.is_overdue === true
              ? "Overdue — schedule this first."
              : next.is_overdue === false
                ? "Due today."
                : "New — never reviewed."}
          </p>
          <Link
            href={ROUTES.studentReview(data.student.id)}
            className="mt-2 inline-block rounded bg-neutral-900 px-3 py-1.5 text-xs text-white hover:bg-neutral-800"
          >
            Start review
          </Link>
        </div>
      ) : (
        c.assigned > 0 && (
          <p className="text-sm text-neutral-500">
            Nothing due right now — the next card comes back later (see the
            vocabulary table below).
          </p>
        )
      )}

      {data.difficult.length > 0 && (
        <div>
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Difficult (most HARD ratings, last 30 days)
            <Link
              href={`${ROUTES.studentReview(data.student.id)}?difficult=yes`}
              className="rounded border border-neutral-300 px-2 py-0.5 text-[10px] font-normal normal-case tracking-normal hover:bg-neutral-100"
            >
              Review difficult
            </Link>
          </p>
          <ul className="mt-1 list-inside list-disc text-sm">
            {data.difficult.map((d) => (
              <li key={d.assignment_id}>
                <Link
                  href={ROUTES.vocabularySense(d.sense_id)}
                  className="underline-offset-2 hover:underline"
                >
                  {d.headword}
                </Link>{" "}
                <span className="text-neutral-500">
                  — {d.hard_count} HARD of {d.total_reviews} reviews
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.recent_reviews.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Recent reviews
          </p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {data.recent_reviews.slice(0, 5).map((r, i) => (
              <li key={`${r.headword}-${r.reviewed_at}-${i}`}>
                <span
                  className={`inline-block w-14 rounded px-1 text-center text-xs ${
                    r.rating === "HARD"
                      ? "bg-red-100 text-red-700"
                      : r.rating === "MEDIUM"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-green-100 text-green-700"
                  }`}
                >
                  {r.rating}
                </span>{" "}
                {r.headword}{" "}
                <span className="text-xs text-neutral-500">
                  {new Date(r.reviewed_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
