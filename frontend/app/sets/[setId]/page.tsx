"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";

import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { listStudents } from "@/lib/students-client";
import {
  assignSet,
  fetchSet,
  removeSetItems,
  updateSet,
} from "@/lib/sets-client";

/** Set detail (section 26): view/rename, remove items, assign to student. */
export default function SetDetailPage({
  params,
}: {
  params: Promise<{ setId: string }>;
}) {
  const { setId } = use(params);
  const queryClient = useQueryClient();
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [studentId, setStudentId] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<Set<string>>(new Set());

  const set = useQuery({
    queryKey: ["sets", "detail", setId],
    queryFn: () => fetchSet(setId),
    retry: false,
  });
  const students = useQuery({
    queryKey: ["students", "list", false],
    queryFn: () => listStudents(false),
    staleTime: 5 * 60_000,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["sets"] });
  }

  const save = useMutation({
    mutationFn: () =>
      updateSet(setId, {
        ...(name !== null ? { name } : {}),
        ...(description !== null ? { description: description || null } : {}),
      }),
    onSuccess: () => {
      setError(null);
      setName(null);
      setDescription(null);
      invalidate();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not save."),
  });

  const remove = useMutation({
    mutationFn: (sense_ids: string[]) => removeSetItems(setId, sense_ids),
    onSuccess: (r) => {
      setPendingRemoval(new Set());
      setNote(`${r.removed} removed from the set.`);
      invalidate();
    },
  });

  const assign = useMutation({
    mutationFn: () => assignSet(setId, studentId),
    onSuccess: (r) => {
      setNote(
        `${r.new} assigned to the student, ${r.already_assigned} already had them.`,
      );
    },
    onError: (err) =>
      setNote(err instanceof ApiError ? err.message : "Assignment failed."),
  });

  if (set.isError) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-red-600">This set could not be loaded.</p>
        <Link href={ROUTES.sets} className="mt-4 inline-block underline">
          ← Back to sets
        </Link>
      </main>
    );
  }

  const s = set.data;
  const dirty = name !== null || description !== null;

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <Link href={ROUTES.sets} className="text-sm underline">
        ← Back to sets
      </Link>

      {set.isLoading || !s ? (
        <p className="mt-8 text-neutral-500">Loading…</p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">{s.name}</h1>
            <span className="text-sm text-neutral-500">{s.item_count} items</span>
          </div>

          <section className="mt-4 space-y-2">
            <label className="block">
              <span className="text-xs text-neutral-500">Name</span>
              <input
                maxLength={200}
                className="block w-72 rounded border border-neutral-300 px-2 py-1"
                value={name ?? s.name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs text-neutral-500">Description</span>
              <input
                maxLength={10_000}
                className="block w-96 rounded border border-neutral-300 px-2 py-1"
                value={description ?? s.description ?? ""}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="button"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate()}
              className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-40"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </section>

          <section className="mt-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Assign this set
            </h2>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <select
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                className="rounded border border-neutral-300 px-2 py-1"
              >
                <option value="">choose student…</option>
                {(students.data?.students ?? []).map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.display_name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!studentId || assign.isPending}
                onClick={() => assign.mutate()}
                className="rounded bg-neutral-900 px-3 py-1.5 text-white hover:bg-neutral-800 disabled:opacity-40"
              >
                {assign.isPending ? "Assigning…" : "Assign set"}
              </button>
              {/* §36: review this set for the chosen student. */}
              <Link
                href={
                  studentId
                    ? `${ROUTES.studentReview(studentId)}?set=${encodeURIComponent(setId)}`
                    : ROUTES.set(setId)
                }
                aria-disabled={!studentId}
                className={`rounded border border-neutral-300 px-3 py-1.5 hover:bg-neutral-100 ${
                  studentId ? "" : "pointer-events-none opacity-40"
                }`}
              >
                Review set
              </Link>
              {note && <span className="text-xs text-neutral-600">{note}</span>}
            </div>
          </section>

          <section className="mt-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Items ({s.items.length})
            </h2>
            {pendingRemoval.size > 0 && (
              <button
                type="button"
                onClick={() => remove.mutate([...pendingRemoval])}
                className="mt-2 rounded bg-red-600 px-2 py-1 text-xs text-white hover:bg-red-500"
              >
                Remove {pendingRemoval.size} selected
              </button>
            )}
            <table className="mt-2 w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-300 text-left">
                  <th className="w-8 py-1"></th>
                  <th className="py-1">Headword</th>
                  <th className="py-1">Polish</th>
                  <th className="py-1">CEFR</th>
                  <th className="py-1">Definition</th>
                </tr>
              </thead>
              <tbody>
                {s.items.map((item) => (
                  <tr key={item.sense_id} className="border-b border-neutral-100">
                    <td className="py-1">
                      <input
                        type="checkbox"
                        checked={pendingRemoval.has(item.sense_id)}
                        onChange={(e) => {
                          const next = new Set(pendingRemoval);
                          if (e.target.checked) next.add(item.sense_id);
                          else next.delete(item.sense_id);
                          setPendingRemoval(next);
                        }}
                        aria-label={`Select ${item.headword}`}
                      />
                    </td>
                    <td className="py-1">
                      <Link
                        href={ROUTES.vocabularySense(item.sense_id)}
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        {item.headword}
                      </Link>
                    </td>
                    <td className="py-1 text-neutral-600">
                      {item.translation_pl ?? "—"}
                    </td>
                    <td className="py-1">{item.cefr_level ?? "—"}</td>
                    <td className="py-1 text-neutral-600">
                      {item.definition_preview?.slice(0, 90) ?? "—"}
                    </td>
                  </tr>
                ))}
                {s.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-neutral-500">
                      Empty set — add senses from the vocabulary table.
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
