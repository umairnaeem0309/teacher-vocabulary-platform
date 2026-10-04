"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ROUTES } from "@/lib/routes";
import { fetchSession } from "@/lib/search-client";

/**
 * Entry route: land on the workbench, not on the phase manifest.
 *
 * Resolves GET /api/v1/auth/session once, then forwards — authenticated
 * teachers to the dashboard, everyone else to the sign-in page. A backend
 * that is down counts as signed out so the teacher still reaches /login
 * (the form surfaces the connection error on submit).
 */
export default function Home() {
  const router = useRouter();
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    retry: false,
  });

  useEffect(() => {
    if (!session.isFetched) return;
    router.replace(session.data?.teacher ? ROUTES.dashboard : ROUTES.login);
  }, [session.isFetched, session.data, router]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2">
      <h1 className="text-xl font-semibold">
        English&ndash;Polish Vocabulary Platform
      </h1>
      <p className="text-sm text-neutral-500">Opening the workbench…</p>
    </main>
  );
}
