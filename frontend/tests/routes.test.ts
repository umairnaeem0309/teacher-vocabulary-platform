/**
 * Route coverage tests (section 53).
 *
 * Verifies (a) the manifest contains every required route and (b) a real
 * page.tsx exists for each of them, so a route can never silently vanish.
 */
import { existsSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { ROUTE_DEFINITIONS, ROUTES } from "@/lib/routes";

const APP_DIR = path.resolve(__dirname, "../app");

function pageFileFor(routePath: string): string {
  const parts = routePath.split("/").filter(Boolean);
  const segments = parts.map((p) => (p.startsWith("[") ? p : p));
  return path.join(APP_DIR, ...segments, "page.tsx");
}

const REQUIRED_STATIC_ROUTES = [
  "/login",
  "/dashboard",
  "/vocabulary",
  "/students",
  "/sets",
  "/settings",
  "/settings/shortcuts",
] as const;

const REQUIRED_DYNAMIC_ROUTES = [
  "/vocabulary/[senseId]",
  "/students/[studentId]",
  "/students/[studentId]/vocabulary",
  "/students/[studentId]/review",
  "/sets/[setId]",
] as const;

describe("route manifest", () => {
  it("covers every required static route", () => {
    const manifest = new Set(ROUTE_DEFINITIONS.map((r) => r.path));
    for (const route of REQUIRED_STATIC_ROUTES) {
      expect(manifest.has(route), `missing from manifest: ${route}`).toBe(true);
    }
  });

  it("covers every required dynamic route", () => {
    const manifest = new Set(ROUTE_DEFINITIONS.map((r) => r.path));
    for (const route of REQUIRED_DYNAMIC_ROUTES) {
      expect(manifest.has(route), `missing from manifest: ${route}`).toBe(true);
    }
  });

  it("helper functions build correct paths", () => {
    expect(ROUTES.vocabularySense("abc")).toBe("/vocabulary/abc");
    expect(ROUTES.student("s1")).toBe("/students/s1");
    expect(ROUTES.studentVocabulary("s1")).toBe("/students/s1/vocabulary");
    expect(ROUTES.studentReview("s1")).toBe("/students/s1/review");
    expect(ROUTES.set("x")).toBe("/sets/x");
  });
});

describe("route files exist", () => {
  it.each([
    ...REQUIRED_STATIC_ROUTES,
    ...REQUIRED_DYNAMIC_ROUTES,
  ])("has page.tsx for %s", (route) => {
    const file = pageFileFor(route);
    expect(existsSync(file), `missing page file: ${file}`).toBe(true);
  });
});
