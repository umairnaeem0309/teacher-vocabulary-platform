"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { apiFetch } from "@/lib/api";
import {
  fetchDashboardOverview,
  type DashboardCounts,
} from "@/lib/dashboard-client";
import { ROUTES } from "@/lib/routes";
import { fetchSession } from "@/lib/search-client";

/**
 * Teacher dashboard (sections 36/98) — the post-sign-in home base.
 *
 * HCI layout, top to bottom:
 *   1. Greeting + date with primary actions (browse / manage).
 *   2. Six KPI tiles — the §36 working counts (overdue → due → name is
 *      decided server-side for the table below).
 *   3. Attention-ordered student queue (drill-down + review actions).
 *   4. Quick links into every workbench area + a live API/database status
 *      card so backend connection problems are visible at a glance.
 */

const COUNT_COLUMNS: Array<{ key: keyof DashboardCounts; label: string }> = [
  { key: "overdue", label: "Overdue" },
  { key: "due", label: "Due today" },
  { key: "learning", label: "Learning" },
  { key: "reviewing", label: "Reviewing" },
  { key: "mastered", label: "Mastered" },
  { key: "assigned", label: "Assigned" },
];

const KPI_TONE: Record<keyof DashboardCounts, { value: string; bar: string }> = {
  overdue: { value: "text-red-600", bar: "bg-red-500" },
  due: { value: "text-amber-600", bar: "bg-amber-500" },
  learning: { value: "text-blue-600", bar: "bg-blue-500" },
  reviewing: { value: "text-violet-600", bar: "bg-violet-500" },
  mastered: { value: "text-emerald-600", bar: "bg-emerald-500" },
  assigned: { value: "text-neutral-800", bar: "bg-neutral-400" },
};

const QUICK_LINKS: Array<{ label: string; description: string; href: string }> = [
  {
    label: "Vocabulary browser",
    description: "Search, filter and copy the corpus",
    href: ROUTES.vocabulary,
  },
  {
    label: "Students & reviews",
    description: "Roster, assignments, FSRS review",
    href: ROUTES.students,
  },
  {
    label: "Vocabulary sets",
    description: "Build sets and assign them in bulk",
    href: ROUTES.sets,
  },
  {
    label: "Keyboard shortcuts",
    description: "Customise the review key bindings",
    href: ROUTES.settingsShortcuts,
  },
  {
    label: "App settings",
    description: "Account, shortcuts and system status",
    href: ROUTES.settings,
  },
];

interface Health {
  status: string;
  app?: string;
  environment?: string;
  database?: string | null;
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
        ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          ok ? "bg-emerald-500" : "bg-red-500"
        }`}
      />
      {label}
    </span>
  );
}

export default function DashboardPage() {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    retry: false,
  });
  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: fetchDashboardOverview,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/api/v1/health"),
    staleTime: 30_000,
    retry: false,
  });

  const firstName = session.data?.teacher.display_name.trim().split(/\s+/)[0];
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  const data = overview.data;
  const totals = data?.totals;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8">
      {/* 1. Header: greeting + primary actions */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-neutral-500">{today}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {greeting()}
            {firstName ? `, ${firstName}` : ""}
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Who needs review next — overdue and due work sort to the top.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href={ROUTES.vocabulary}
            className="rounded-lg bg-neutral-900 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-neutral-800"
          >
            Browse vocabulary
          </Link>
          <Link
            href={ROUTES.students}
            className="rounded-lg border border-neutral-300 bg-white px-3.5 py-2 text-sm font-medium shadow-sm hover:bg-neutral-50"
          >
            Manage students
          </Link>
        </div>
      </div>

      {/* Loading skeleton for the KPI row */}
      {overview.isLoading && (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {COUNT_COLUMNS.map(({ key }) => (
            <div
              key={key}
              className="animate-pulse rounded-xl border border-neutral-200 bg-white p-4"
            >
              <div className="h-1 w-8 rounded-full bg-neutral-200" />
              <div className="mt-3 h-3 w-16 rounded bg-neutral-200" />
              <div className="mt-2 h-6 w-10 rounded bg-neutral-200" />
            </div>
          ))}
        </div>
      )}

      {/* Error state with retry */}
      {overview.isError && (
        <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-700">
            Could not load the dashboard.
          </p>
          <p className="mt-0.5 text-sm text-red-600">
            Check that the backend is running on port 8000, then try again.
          </p>
          <button
            type="button"
            onClick={() => overview.refetch()}
            className="mt-3 rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}

      {/* 2. KPI tiles */}
      {totals && (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {COUNT_COLUMNS.map(({ key, label }) => (
            <div
              key={key}
              className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm"
            >
              <span
                className={`block h-1 w-8 rounded-full ${KPI_TONE[key].bar}`}
              />
              <p className="mt-3 text-xs font-medium uppercase tracking-wide text-neutral-500">
                {label}
              </p>
              <p
                className={`mt-1 text-2xl font-semibold tabular-nums ${KPI_TONE[key].value}`}
              >
                {totals[key]}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* 3 + 4. Student queue beside quick links & system status */}
      {data && (
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          <section className="rounded-xl border border-neutral-200 bg-white shadow-sm lg:col-span-2">
            <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
              <h2 className="text-sm font-semibold">
                Students needing attention
              </h2>
              <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
                {data.students.length} of {data.total}
              </span>
            </div>

            {data.students.length === 0 ? (
              <div className="px-6 py-10 text-center">
                <h3 className="text-base font-semibold">No students yet</h3>
                <p className="mx-auto mt-1 max-w-sm text-sm text-neutral-500">
                  Add your first student to start assigning vocabulary and
                  tracking FSRS reviews.
                </p>
                <div className="mt-4 flex justify-center gap-2">
                  <Link
                    href={ROUTES.students}
                    className="rounded-lg bg-neutral-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-neutral-800"
                  >
                    Add a student
                  </Link>
                  <Link
                    href={ROUTES.vocabulary}
                    className="rounded-lg border border-neutral-300 bg-white px-3.5 py-2 text-sm font-medium hover:bg-neutral-50"
                  >
                    Browse vocabulary
                  </Link>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs uppercase tracking-wide text-neutral-500">
                      <th className="px-4 py-3 font-medium">Student</th>
                      {COUNT_COLUMNS.map(({ key, label }) => (
                        <th
                          key={key}
                          className="px-2 py-3 text-right font-medium"
                        >
                          {label}
                        </th>
                      ))}
                      <th className="px-4 py-3" aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {data.students.map((row) => (
                      <tr
                        key={row.student.id}
                        className="transition-colors hover:bg-neutral-50"
                      >
                        <td className="px-4 py-3">
                          <Link
                            href={ROUTES.student(row.student.id)}
                            className="font-medium underline-offset-2 hover:underline"
                          >
                            {row.student.display_name}
                          </Link>
                        </td>
                        {COUNT_COLUMNS.map(({ key }) => (
                          <td
                            key={key}
                            className="px-2 py-3 text-right tabular-nums"
                          >
                            {key === "overdue" && row.overdue > 0 ? (
                              <span className="font-semibold text-red-600">
                                {row.overdue}
                              </span>
                            ) : (
                              row[key]
                            )}
                          </td>
                        ))}
                        <td className="px-4 py-3 text-right">
                          {row.assigned > 0 && (
                            <Link
                              href={ROUTES.studentReview(row.student.id)}
                              className="rounded-md bg-neutral-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-neutral-800"
                            >
                              Review
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="space-y-6">
            {/* Quick links */}
            <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold">Quick links</h2>
              <ul className="mt-2 divide-y divide-neutral-100">
                {QUICK_LINKS.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="group flex items-center justify-between gap-2 py-2.5"
                    >
                      <span>
                        <span className="block text-sm font-medium group-hover:text-blue-700">
                          {link.label}
                        </span>
                        <span className="block text-xs text-neutral-500">
                          {link.description}
                        </span>
                      </span>
                      <span
                        aria-hidden="true"
                        className="text-neutral-400 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-700"
                      >
                        →
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>

            {/* Live backend status */}
            <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">System status</h2>
                <button
                  type="button"
                  onClick={() => health.refetch()}
                  className="text-xs text-neutral-500 underline hover:text-neutral-800"
                >
                  Refresh
                </button>
              </div>
              {health.isLoading && (
                <p className="mt-2 text-sm text-neutral-500">Checking…</p>
              )}
              {health.isError && (
                <div className="mt-2">
                  <p className="text-sm font-medium text-red-600">
                    Backend unreachable
                  </p>
                  <p className="mt-0.5 text-xs text-neutral-500">
                    Start uvicorn on port 8000 and refresh.
                  </p>
                </div>
              )}
              {health.data && (
                <dl className="mt-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <dt className="text-neutral-500">API</dt>
                    <dd>
                      <StatusBadge
                        ok={health.data.status === "ok"}
                        label={health.data.status}
                      />
                    </dd>
                  </div>
                  <div className="flex items-center justify-between">
                    <dt className="text-neutral-500">Database</dt>
                    <dd>
                      <StatusBadge
                        ok={health.data.database === "up"}
                        label={health.data.database ?? "unknown"}
                      />
                    </dd>
                  </div>
                  {health.data.environment && (
                    <div className="flex items-center justify-between">
                      <dt className="text-neutral-500">Environment</dt>
                      <dd className="font-medium capitalize text-neutral-700">
                        {health.data.environment}
                      </dd>
                    </div>
                  )}
                </dl>
              )}
            </section>
          </div>
        </div>
      )}
    </main>
  );
}
