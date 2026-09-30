"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { SessionBar } from "@/components/SessionBar";
import {
  fetchDashboardOverview,
  type DashboardCounts,
} from "@/lib/dashboard-client";
import { ROUTES } from "@/lib/routes";

/**
 * Teacher dashboard (section 98): one row per student with the §36
 * working counts, sorted so the students who need attention first are at
 * the top (overdue → due → name, decided server-side). Practical, not
 * analytics — the per-student drill-down ("what should I review next?")
 * lives on the student profile.
 */

const COUNT_COLUMNS: Array<{ key: keyof DashboardCounts; label: string }> = [
  { key: "overdue", label: "Overdue" },
  { key: "due", label: "Due today" },
  { key: "learning", label: "Learning" },
  { key: "reviewing", label: "Reviewing" },
  { key: "mastered", label: "Mastered" },
  { key: "assigned", label: "Assigned" },
];

export default function DashboardPage() {
  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: fetchDashboardOverview,
  });

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <SessionBar />
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Who needs review next — overdue and due work sort to the top.
      </p>

      {overview.isLoading && (
        <p className="mt-8 text-neutral-500">Loading…</p>
      )}
      {overview.isError && (
        <p className="mt-8 text-red-600">Could not load the dashboard.</p>
      )}

      {overview.data && (
        <>
          <div className="mt-4 flex flex-wrap gap-2 text-sm">
            {COUNT_COLUMNS.map(({ key, label }) => (
              <span
                key={key}
                className="rounded border border-neutral-200 px-2 py-1"
              >
                <span className="text-neutral-500">{label}</span>{" "}
                <span className="font-semibold">{overview.data.totals[key]}</span>
              </span>
            ))}
          </div>

          <table className="mt-4 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-neutral-300 text-left">
                <th className="py-1">Student</th>
                {COUNT_COLUMNS.map(({ key, label }) => (
                  <th key={key} className="py-1 text-right">
                    {label}
                  </th>
                ))}
                <th className="py-1" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {overview.data.students.map((row) => (
                <tr key={row.student.id} className="border-b border-neutral-100">
                  <td className="py-1.5">
                    <Link
                      href={ROUTES.student(row.student.id)}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {row.student.display_name}
                    </Link>
                  </td>
                  {COUNT_COLUMNS.map(({ key }) => (
                    <td key={key} className="py-1.5 text-right tabular-nums">
                      {key === "overdue" && row.overdue > 0 ? (
                        <span className="font-semibold text-red-600">
                          {row.overdue}
                        </span>
                      ) : (
                        row[key]
                      )}
                    </td>
                  ))}
                  <td className="py-1.5 text-right">
                    {row.assigned > 0 && (
                      <Link
                        href={ROUTES.studentReview(row.student.id)}
                        className="rounded bg-neutral-900 px-2 py-1 text-xs text-white hover:bg-neutral-800"
                      >
                        Review
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
              {overview.data.students.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-neutral-500">
                    No students yet — add one on the{" "}
                    <Link href={ROUTES.students} className="underline">
                      students
                    </Link>{" "}
                    page.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
