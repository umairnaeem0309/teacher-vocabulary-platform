"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { fetchDueQueue, recordReview, type DueItem } from "@/lib/reviews-client";
import {
  bindingLabel,
  matchesBinding,
  useShortcuts,
} from "@/lib/shortcuts";

/**
 * Live review screen (sections 32/34/36): one card at a time for a teacher
 * conducting a lesson. Shows word, Polish, definition, example and
 * learning state; controls are HARD / MEDIUM / EASY (mapped to FSRS
 * Again/Hard/Good server-side). Keyboard shortcuts are configurable in
 * settings (§35). §36: the queue can be narrowed via URL params — a set
 * (`set=`), difficult cards (`difficult=yes`), learning states (`states=`) or
 * a headword search (`search=`). Duplicate submission is guarded by an
 * in-flight lock.
 */
export default function ReviewPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  return (
    <Suspense fallback={<main className="mx-auto max-w-2xl px-6 py-16">Loading…</main>}>
      <ReviewScreen params={params} />
    </Suspense>
  );
}

function ReviewScreen({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = use(params);
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  // §36 review-selection options decoded from the URL.
  const setId = searchParams.get("set") ?? undefined;
  const difficultOnly = searchParams.get("difficult") === "yes";
  const search = searchParams.get("search") ?? undefined;
  const learningStates = (searchParams.get("states") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const shortcuts = useShortcuts();
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const queue = useQuery({
    queryKey: [
      "reviews",
      "due",
      studentId,
      setId,
      difficultOnly,
      search,
      learningStates,
    ],
    queryFn: () =>
      fetchDueQueue(studentId, 200, {
        setId,
        difficultOnly,
        search,
        learningStates,
      }),
    retry: false,
  });

  const items: DueItem[] = queue.data?.items ?? [];
  const current: DueItem | undefined = items[index];

  const review = useMutation({
    mutationFn: (rating: "HARD" | "MEDIUM" | "EASY") =>
      recordReview({
        student_id: studentId,
        assignment_id: current.assignment_id,
        rating,
      }),
    onSuccess: (r) => {
      setError(null);
      setRevealed(false);
      setResult(
        `Recorded ${r.rating} — next due ${new Date(r.due_at).toLocaleString()}`,
      );
      // Refetch in the background; keep showing the current card until we
      // advance, so a slow network never reveals the answer early.
      queryClient.invalidateQueries({ queryKey: ["reviews", "due", studentId] });
      // The student dashboard (counts, due/overdue, recent reviews) is
      // derived from review history — invalidate it too so returning to
      // the profile immediately reflects the new FSRS state (§59 steps
      // 21-22); back-navigation restores the cached page without
      // refetching, so the invalidation has to be recorded here.
      queryClient.invalidateQueries({ queryKey: ["students"] });
      if (index + 1 >= items.length) {
        setDone(true);
      } else {
        setIndex((i) => i + 1);
      }
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Review failed.");
    },
  });

  const rate = useCallback(
    (rating: "HARD" | "MEDIUM" | "EASY") => {
      // Duplicate-submission guard: ignore keys while a review is in flight.
      if (!current || review.isPending) return;
      review.mutate(rating);
    },
    [current, review],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.repeat) return;
      // Ignore keystrokes while the teacher is typing in a field.
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        return;
      }
      if (matchesBinding(e, shortcuts.reveal)) {
        e.preventDefault();
        setRevealed(true);
        return;
      }
      if (revealed) {
        if (matchesBinding(e, shortcuts.hard)) rate("HARD");
        if (matchesBinding(e, shortcuts.medium)) rate("MEDIUM");
        if (matchesBinding(e, shortcuts.easy)) rate("EASY");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rate, shortcuts, revealed]);

  if (queue.isError) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-red-600">The review queue could not be loaded.</p>
        <Link href={ROUTES.student(studentId)} className="mt-4 inline-block underline">
          ← Back to student
        </Link>
      </main>
    );
  }

  if (done || (!queue.isLoading && items.length === 0)) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-center">
        <h1 className="text-2xl font-semibold">Queue clear</h1>
        <p className="mt-2 text-neutral-600">
          Nothing is due for this student right now.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link
            href={ROUTES.student(studentId)}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100"
          >
            ← Back to student
          </Link>
          <button
            type="button"
            onClick={() => {
              setDone(false);
              setIndex(0);
              queue.refetch();
            }}
            className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800"
          >
            Refresh queue
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-8">
      <Link href={ROUTES.student(studentId)} className="text-sm underline">
        ← Back to student
      </Link>

      <div className="mt-4 flex items-center justify-between text-sm text-neutral-500">
        <span>
          Card {Math.min(index + 1, items.length)} of {items.length}
        </span>
        {current && (
          <span className="flex gap-2">
            {current.is_overdue && (
              <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
                overdue
              </span>
            )}
            <span className="rounded bg-neutral-200 px-2 py-0.5 text-xs">
              {current.learning_state}
            </span>
            <span className="rounded bg-neutral-200 px-2 py-0.5 text-xs">
              reviews {current.repetitions}
              {current.lapses > 0 && ` · lapses ${current.lapses}`}
            </span>
          </span>
        )}
      </div>

      {queue.isLoading || !current ? (
        <p className="mt-16 text-center text-neutral-500">Loading…</p>
      ) : (
        <>
          <section className="mt-6 rounded-lg border border-neutral-200 p-8 text-center">
            <h1 className="text-4xl font-semibold">{current.sense.headword}</h1>
            {current.sense.part_of_speech && (
              <p className="mt-1 text-sm text-neutral-500">
                {current.sense.part_of_speech}
                {current.sense.cefr_level && ` · ${current.sense.cefr_level}`}
              </p>
            )}

            {revealed ? (
              <div className="mt-6 space-y-3">
                <p className="text-2xl">{current.sense.translation_pl ?? "—"}</p>
                {current.sense.definition_preview && (
                  <p className="text-neutral-600">
                    {current.sense.definition_preview}
                  </p>
                )}
                {current.sense.example && (
                  <p className="text-sm italic text-neutral-500">
                    “{current.sense.example}”
                  </p>
                )}
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setRevealed(true)}
                className="mt-8 rounded border border-neutral-300 px-6 py-2 text-sm hover:bg-neutral-100"
              >
                Reveal ({bindingLabel(shortcuts.reveal)})
              </button>
            )}
          </section>

          <div className="mt-4 grid grid-cols-3 gap-3">
            <button
              type="button"
              disabled={!revealed || review.isPending}
              onClick={() => rate("HARD")}
              className="rounded bg-red-600 px-4 py-3 text-white hover:bg-red-500 disabled:opacity-30"
            >
              HARD{" "}
              <span className="text-xs opacity-75">({bindingLabel(shortcuts.hard)})</span>
            </button>
            <button
              type="button"
              disabled={!revealed || review.isPending}
              onClick={() => rate("MEDIUM")}
              className="rounded bg-amber-500 px-4 py-3 text-white hover:bg-amber-400 disabled:opacity-30"
            >
              MEDIUM{" "}
              <span className="text-xs opacity-75">({bindingLabel(shortcuts.medium)})</span>
            </button>
            <button
              type="button"
              disabled={!revealed || review.isPending}
              onClick={() => rate("EASY")}
              className="rounded bg-green-600 px-4 py-3 text-white hover:bg-green-500 disabled:opacity-30"
            >
              EASY{" "}
              <span className="text-xs opacity-75">({bindingLabel(shortcuts.easy)})</span>
            </button>
          </div>

          {result && <p className="mt-3 text-sm text-green-700">{result}</p>}
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          {review.isPending && (
            <p className="mt-3 text-sm text-neutral-500">Recording…</p>
          )}

          <p className="mt-6 text-center text-xs text-neutral-400">
            Shortcuts: {bindingLabel(shortcuts.hard)} hard ·{" "}
            {bindingLabel(shortcuts.medium)} medium ·{" "}
            {bindingLabel(shortcuts.easy)} easy · {bindingLabel(shortcuts.reveal)}{" "}
            reveal ·{" "}
            <Link href={ROUTES.settingsShortcuts} className="underline">
              configure
            </Link>
          </p>
        </>
      )}
    </main>
  );
}
