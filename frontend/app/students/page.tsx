"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { SessionBar } from "@/components/SessionBar";
import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { createStudent, listStudents, setStudentStatus } from "@/lib/students-client";

/**
 * Student management (section 27): list, create, deactivate/reactivate.
 * Delete is deliberately not offered as a one-click action — §27 requires
 * confirmation for destructive operations, and soft deletion here is a
 * status change; the UI exposes it only inside a profile with a
 * confirm step (Phase 17 scope: lifecycle via this list + profiles).
 */
export default function StudentsPage() {
  const queryClient = useQueryClient();
  const [showInactive, setShowInactive] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  const students = useQuery({
    queryKey: ["students", "list", { showInactive }],
    queryFn: () => listStudents(showInactive),
  });

  const create = useMutation({
    mutationFn: () =>
      createStudent({ display_name: name, email: email || null }),
    onSuccess: () => {
      setName("");
      setEmail("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["students"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not create the student."),
  });

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "ACTIVE" | "INACTIVE" }) =>
      setStudentStatus(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["students"] }),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <SessionBar />
      <h1 className="text-xl font-semibold">Students</h1>

      <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={onSubmit}>
        <label className="block">
          <span className="text-xs text-neutral-500">Name</span>
          <input
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="block w-56 rounded border border-neutral-300 px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="text-xs text-neutral-500">Email (optional)</span>
          <input
            type="email"
            maxLength={320}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="block w-64 rounded border border-neutral-300 px-2 py-1"
          />
        </label>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Add student"}
        </button>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </form>

      <label className="mt-3 flex items-center gap-2 text-sm text-neutral-600">
        <input
          type="checkbox"
          checked={showInactive}
          onChange={(e) => setShowInactive(e.target.checked)}
        />
        Show deactivated
      </label>

      <table className="mt-2 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-neutral-300 text-left">
            <th className="py-1">Name</th>
            <th className="py-1">Email</th>
            <th className="py-1">Assigned</th>
            <th className="py-1">Status</th>
            <th className="py-1"></th>
          </tr>
        </thead>
        <tbody>
          {(students.data?.students ?? []).map((s) => (
            <tr key={s.id} className="border-b border-neutral-100">
              <td className="py-1">
                <Link href={ROUTES.student(s.id)} className="font-medium underline-offset-2 hover:underline">
                  {s.display_name}
                </Link>
              </td>
              <td className="py-1 text-neutral-600">{s.email ?? "—"}</td>
              <td className="py-1">{s.assigned_count}</td>
              <td className="py-1">
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    s.status === "ACTIVE"
                      ? "bg-green-100 text-green-800"
                      : "bg-neutral-200 text-neutral-600"
                  }`}
                >
                  {s.status}
                </span>
              </td>
              <td className="py-1 text-right">
                {s.status === "ACTIVE" ? (
                  <button
                    type="button"
                    className="rounded border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100"
                    onClick={() => setStatus.mutate({ id: s.id, status: "INACTIVE" })}
                  >
                    Deactivate
                  </button>
                ) : (
                  <button
                    type="button"
                    className="rounded border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100"
                    onClick={() => setStatus.mutate({ id: s.id, status: "ACTIVE" })}
                  >
                    Reactivate
                  </button>
                )}
              </td>
            </tr>
          ))}
          {(students.data?.students ?? []).length === 0 && (
            <tr>
              <td colSpan={5} className="py-8 text-center text-neutral-500">
                {students.isLoading ? "Loading…" : "No students yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}
