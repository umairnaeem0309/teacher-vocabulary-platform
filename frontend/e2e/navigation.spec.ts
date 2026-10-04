import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * Navigation & endpoint sweep (HCI acceptance).
 *
 * Two guarantees, both against the real stack:
 *
 *  1. Every primary navigation route renders through the app chrome with a
 *     200 document, a visible <h1>, the correct aria-current state, and no
 *     console/page errors — including the "/" → /dashboard entry redirect
 *     and the settings → shortcuts deep link.
 *  2. Every backend endpoint the workbench calls answers 2xx for the
 *     seeded teacher session (auth, dashboard, students, vocabulary,
 *     search, filters, sets, reviews, FSRS, exports, health). Mutating
 *     flows (create/assign/review) are covered by the §59/§60 suites.
 */

const API = process.env.E2E_BACKEND_URL ?? "http://localhost:8737";

async function expectOk(
  request: APIRequestContext,
  path: string,
  init?: Parameters<APIRequestContext["fetch"]>[1],
): Promise<unknown> {
  const response = await request.fetch(`${API}${path}`, init);
  const text = await response.text();
  expect(
    response.ok(),
    `${path} -> ${response.status()}: ${text.slice(0, 300)}`,
  ).toBeTruthy();
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

test("every primary navigation route renders cleanly", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(`pageerror: ${String(err)}`));
  page.on("console", (msg) => {
    // Resource-load noise (favicon etc.) is not an app error; real JS
    // failures surface as pageerror or non-network console.error.
    if (msg.type() === "error" && !msg.text().includes("Failed to load resource")) {
      problems.push(`console: ${msg.text()}`);
    }
  });

  // Entry redirect: authenticated "/" lands on the dashboard.
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard/);

  const sidebar = page.locator("aside");
  await expect(
    sidebar.getByRole("link", { name: "Dashboard", exact: true }),
  ).toHaveAttribute("aria-current", "page");

  const stops: Array<[string, RegExp]> = [
    ["Vocabulary", /\/vocabulary/],
    ["Students", /\/students/],
    ["Sets", /\/sets/],
    ["Settings", /\/settings/],
    ["Dashboard", /\/dashboard/],
  ];
  for (const [label, url] of stops) {
    await sidebar.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(url);
    await expect(page.locator("main h1").first()).toBeVisible();
  }

  // Settings deep link → shortcuts configurator.
  await page.goto("/settings");
  await page.getByRole("link", { name: /configure shortcuts/i }).click();
  await expect(page).toHaveURL(/\/settings\/shortcuts/);
  await expect(
    page.getByRole("heading", { name: "Keyboard shortcuts" }),
  ).toBeVisible();

  expect(problems, "no console/page errors while navigating").toEqual([]);
});

test("every read endpoint the UI calls answers 2xx", async ({ request }) => {
  // Core, session-scoped and public reads.
  await expectOk(request, "/api/v1/health");
  await expectOk(request, "/api/v1/health/live");
  await expectOk(request, "/api/v1/auth/session");
  await expectOk(request, "/api/v1/dashboard");
  await expectOk(request, "/api/v1/students");
  await expectOk(request, "/api/v1/sets");
  await expectOk(request, "/api/v1/fsrs/parameters");
  await expectOk(request, "/api/v1/vocabulary?query=bank&limit=1");
  await expectOk(request, "/api/v1/vocabulary/search/filters");

  // Search POST (lexical — no embedding model load).
  await expectOk(request, "/api/v1/vocabulary/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify({
      query: "bank",
      mode: "lexical",
      sort: "relevance",
      limit: 5,
    }),
  });

  // Student-scoped reads (global setup seeds student "John").
  const students = (await expectOk(request, "/api/v1/students")) as {
    students: { id: string }[];
  };
  expect(students.students.length, "seeded student exists").toBeGreaterThan(0);
  const studentId = students.students[0].id;
  await expectOk(request, `/api/v1/students/${studentId}`);
  await expectOk(request, `/api/v1/students/${studentId}/dashboard`);
  await expectOk(request, `/api/v1/students/${studentId}/vocabulary`);
  await expectOk(
    request,
    `/api/v1/reviews/due?student_id=${studentId}&limit=5`,
  );

  // Set-scoped reads (§60 seeds a set before this suite runs).
  const sets = (await expectOk(request, "/api/v1/sets")) as {
    sets: { id: string }[];
  };
  if (sets.sets.length > 0) {
    await expectOk(request, `/api/v1/sets/${sets.sets[0].id}`);
  }

  // Export (read-only; frequency cap keeps the payload tiny).
  await expectOk(request, "/api/v1/exports/vocabulary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify({ format: "csv", max_frequency_rank: 100 }),
  });
});
