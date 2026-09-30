"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { SessionBar } from "@/components/SessionBar";
import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { createSet, deleteSet, listSets } from "@/lib/sets-client";

/** Vocabulary sets list (section 26): create, open, delete. */
export default function SetsPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const sets = useQuery({ queryKey: ["sets", "list"], queryFn: listSets });

  const create = useMutation({
    mutationFn: () =>
      createSet({ name, description: description || null }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["sets"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not create the set."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteSet(id),
    onSuccess: () => {
      setConfirmId(null);
      queryClient.invalidateQueries({ queryKey: ["sets"] });
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <SessionBar />
      <h1 className="text-xl font-semibold">Vocabulary sets</h1>

      <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={onSubmit}>
        <label className="block">
          <span className="text-xs text-neutral-500">Name</span>
          <input
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. A2 Cooking"
            className="block w-64 rounded border border-neutral-300 px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="text-xs text-neutral-500">Description (optional)</span>
          <input
            maxLength={10_000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="block w-80 rounded border border-neutral-300 px-2 py-1"
          />
        </label>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Create set"}
        </button>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </form>

      <table className="mt-4 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-neutral-300 text-left">
            <th className="py-1">Name</th>
            <th className="py-1">Description</th>
            <th className="py-1">Items</th>
            <th className="py-1"></th>
          </tr>
        </thead>
        <tbody>
          {(sets.data?.sets ?? []).map((s) => (
            <tr key={s.id} className="border-b border-neutral-100">
              <td className="py-1">
                <Link
                  href={ROUTES.set(s.id)}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {s.name}
                </Link>
              </td>
              <td className="py-1 text-neutral-600">{s.description ?? "—"}</td>
              <td className="py-1">{s.item_count}</td>
              <td className="py-1 text-right">
                {confirmId === s.id ? (
                  <span className="flex items-center justify-end gap-2">
                    <span className="text-xs text-neutral-600">Delete this set?</span>
                    <button
                      type="button"
                      onClick={() => remove.mutate(s.id)}
                      className="rounded bg-red-600 px-2 py-0.5 text-xs text-white hover:bg-red-500"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmId(null)}
                      className="rounded border border-neutral-300 px-2 py-0.5 text-xs"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmId(s.id)}
                    className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-50"
                  >
                    Delete…
                  </button>
                )}
              </td>
            </tr>
          ))}
          {(sets.data?.sets ?? []).length === 0 && (
            <tr>
              <td colSpan={4} className="py-8 text-center text-neutral-500">
                {sets.isLoading ? "Loading…" : "No sets yet — create one above, or from the vocabulary table."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}
