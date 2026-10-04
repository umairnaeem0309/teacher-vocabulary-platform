"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { apiBase, apiFetch } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { fetchSession } from "@/lib/search-client";

/**
 * Settings hub (section 39): account identity, the keyboard-shortcut
 * configuration entry point, and a live backend/database status card so
 * connection problems are diagnosable without opening dev tools.
 */

interface Health {
  status: string;
  app?: string;
  environment?: string;
  database?: string | null;
}

function Card({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    retry: false,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/api/v1/health"),
    staleTime: 30_000,
    retry: false,
  });

  const teacher = session.data?.teacher;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 md:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Account, preferences and system status for this workstation.
      </p>

      <div className="mt-6 space-y-4">
        <Card title="Account">
          {teacher ? (
            <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
              <dt className="text-neutral-500">Display name</dt>
              <dd className="font-medium sm:col-span-2">{teacher.display_name}</dd>
              <dt className="text-neutral-500">Email</dt>
              <dd className="sm:col-span-2">{teacher.email}</dd>
            </dl>
          ) : session.isError ? (
            <p className="text-sm text-red-600">
              Could not load the account — are you signed in?
            </p>
          ) : (
            <p className="text-sm text-neutral-500">Loading…</p>
          )}
        </Card>

        <Card
          title="Keyboard shortcuts"
          action={
            <Link
              href={ROUTES.settingsShortcuts}
              className="text-sm font-medium text-blue-700 underline-offset-2 hover:underline"
            >
              Configure shortcuts →
            </Link>
          }
        >
          <p className="text-sm text-neutral-600">
            Reveal, HARD, MEDIUM and EASY keys are configurable per browser
            (stored locally, survives reloads).
          </p>
        </Card>

        <Card
          title="System status"
          action={
            <button
              type="button"
              onClick={() => health.refetch()}
              className="text-xs text-neutral-500 underline hover:text-neutral-800"
            >
              Refresh
            </button>
          }
        >
          {health.isLoading && (
            <p className="text-sm text-neutral-500">Checking…</p>
          )}
          {health.isError && (
            <div>
              <p className="text-sm font-medium text-red-600">
                Backend unreachable
              </p>
              <p className="mt-0.5 text-xs text-neutral-500">
                Start uvicorn on port 8000 (see documentation.md §8).
              </p>
            </div>
          )}
          {health.data && (
            <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
              <dt className="text-neutral-500">API</dt>
              <dd className="font-medium sm:col-span-2">{health.data.status}</dd>
              <dt className="text-neutral-500">Database</dt>
              <dd className="sm:col-span-2">{health.data.database ?? "unknown"}</dd>
              <dt className="text-neutral-500">Environment</dt>
              <dd className="capitalize sm:col-span-2">
                {health.data.environment ?? "—"}
              </dd>
              <dt className="text-neutral-500">Backend URL</dt>
              <dd className="sm:col-span-2 font-mono text-xs">{apiBase()}</dd>
            </dl>
          )}
        </Card>

        <Card title="About">
          <p className="text-sm text-neutral-600">
            <span className="font-medium">Vocabulary Workbench</span> —
            English–Polish vocabulary teaching &amp; FSRS review platform for a
            single teacher per deployment.
          </p>
        </Card>
      </div>
    </main>
  );
}
