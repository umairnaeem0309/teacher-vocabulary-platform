import Link from "next/link";

import { ROUTE_DEFINITIONS, ROUTES } from "@/lib/routes";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold">
        English&ndash;Polish Vocabulary Platform
      </h1>
      <p className="mt-2 text-sm text-neutral-600">
        Teacher workstation for vocabulary discovery, assignment and FSRS-based
        review. Phase 1: route structure in place; feature UIs land phase by
        phase (see plan.md).
      </p>
      <ul className="mt-8 space-y-1 text-sm">
        {ROUTE_DEFINITIONS.map((route) => (
          <li key={route.path} className="flex items-baseline gap-3">
            <Link
              href={route.path.replace("[senseId]", "demo").replace("[studentId]", "demo").replace("[setId]", "demo")}
              className="font-mono text-blue-700 underline decoration-dotted"
            >
              {route.path}
            </Link>
            <span className="text-neutral-500">{route.description}</span>
            <span className="ml-auto shrink-0 text-xs text-neutral-400">
              phase {route.phase}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-8 text-xs text-neutral-500">
        API health:{" "}
        <a className="underline" href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/health`}>
          /api/v1/health
        </a>{" "}
        · default login route: {ROUTES.login}
      </p>
    </main>
  );
}
