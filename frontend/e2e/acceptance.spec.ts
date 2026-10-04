import { expect, test, type Page } from "@playwright/test";

/**
 * Section 59 — CRITICAL ACCEPTANCE TEST (run by Phase 27 end-to-end testing).
 *
 * Drives the real UI in Chrome through the exact 22-step workflow:
 * login → vocabulary browser → semantic "vacation" search → TRAVEL / A2 /
 * HIGH+ filters → student John → NOT ASSIGNED → multi-select → assign with
 * the §29 report → John's profile → DUE filter → review → EASY → FSRS next
 * date → due counts change.
 *
 * Fixtures come from scripts/phase27_seed_acceptance.py (global setup):
 * acceptance teacher + student "John" who already has 6 overdue cards, so
 * step 14 (DUE) has something real to filter.
 */

const EMAIL = process.env.E2E_TEACHER_EMAIL ?? "acceptance@example.com";
const PASSWORD =
  process.env.E2E_TEACHER_PASSWORD ?? "acceptance-teacher-Passw0rd!";

/** Open a collapsible filter group in the sidebar (closed by default). */
async function openGroup(page: Page, re: RegExp) {
  const group = page.locator("details").filter({ hasText: re }).first();
  await expect(group).toBeVisible();
  const isOpen = await group.evaluate(
    (el) => (el as HTMLDetailsElement).open,
  );
  if (!isOpen) await group.locator("summary").click();
  return group;
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Sign-in lands on the dashboard (the app's home base).
  await expect(page).toHaveURL(/\/dashboard/);
}

test("§59 critical acceptance workflow", async ({ page }) => {
  test.setTimeout(300_000);

  // 1. Login as teacher.
  await login(page);

  // 2. Navigate to the vocabulary browser through the sidebar navigation.
  await page
    .locator("aside")
    .getByRole("link", { name: "Vocabulary", exact: true })
    .click();
  await expect(page).toHaveURL(/\/vocabulary/);
  await expect(page.getByRole("heading", { name: "Vocabulary" })).toBeVisible();

  // 3. Search "vacation".
  const search = page.getByPlaceholder(
    "Search headwords, translations, definitions…",
  );
  await search.fill("vacation");
  const modeSelect = page
    .locator("select")
    .filter({ has: page.locator('option[value="semantic"]') })
    .first();
  await modeSelect.selectOption("semantic");

  // 4. Receive relevant semantic results (first query loads the model).
  const rows = page.locator("tbody tr");
  await expect(rows.first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/[\d,]+ senses/)).toBeVisible();

  // 5. Filter TRAVEL.
  const categoryGroup = await openGroup(page, /^Category/);
  await categoryGroup.locator("select").selectOption("travel");

  // 6. Filter A2. (The panel is URL-driven, so click and then retry the
  // assertion instead of trusting check()'s single post-click read.)
  const cefrGroup = await openGroup(page, /^CEFR/);
  const a2 = cefrGroup
    .locator("label")
    .filter({ hasText: /^A2$/ })
    .locator("input");
  await a2.click();
  await expect(a2).toBeChecked();

  // 7. Filter HIGH+.
  const priorityGroup = await openGroup(page, /^Min priority/);
  await priorityGroup.locator("select").selectOption({ label: "HIGH+" });

  // 8. Select student John.
  const studentGroup = await openGroup(page, /Student assignment/);
  await studentGroup.locator("select").first().selectOption({ label: "John" });

  // 9. Filter NOT ASSIGNED (same URL-driven control as step 6).
  const notAssigned = studentGroup
    .locator("label")
    .filter({ hasText: /^not assigned$/ })
    .locator("input");
  await notAssigned.click();
  await expect(notAssigned).toBeChecked();

  // 10. Select multiple senses.
  await expect(rows.first()).toBeVisible({ timeout: 60_000 });
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThanOrEqual(1);
  const selectCount = Math.min(3, rowCount);
  for (let i = 0; i < selectCount; i++) {
    const box = rows.nth(i).locator("input[type='checkbox']");
    await box.click();
    await expect(box).toBeChecked();
  }

  // 11-12. Assign and receive the §29 report.
  const chip = page.locator("span").filter({ hasText: /\d+ selected/ }).first();
  await chip.locator("select").first().selectOption({ label: "John" });
  await chip.getByRole("button", { name: "Assign", exact: true }).click();
  const note = page.getByText(/\d+ assigned, \d+ already had them/);
  await expect(note).toBeVisible({ timeout: 30_000 });

  // 13. Open John's profile.
  await page.goto("/students");
  await page.getByRole("link", { name: "John", exact: true }).click();
  await expect(page).toHaveURL(/\/students\/[0-9a-f-]+/);
  await expect(page.getByText("Review dashboard")).toBeVisible();

  const readOverdue = async () => {
    const chipText = await page
      .locator("span")
      .filter({ hasText: /^Overdue \d+$/ })
      .first()
      .textContent();
    return Number((chipText ?? "Overdue 0").replace(/\D+/g, "")) || 0;
  };
  const overdueBefore = await readOverdue();
  expect(overdueBefore).toBeGreaterThan(0);

  // 14. Filter DUE on John's vocabulary.
  await page.getByRole("link", { name: "Filter vocabulary →" }).click();
  await expect(page).toHaveURL(/\/vocabulary$/);
  const showSelect = page
    .locator("select")
    .filter({ has: page.locator('option[value="due"]') })
    .first();
  await showSelect.selectOption("due");
  await expect(page.getByText(/\d+ of \d+ shown/)).toBeVisible();
  const shown = await page.getByText(/(\d+) of (\d+) shown/).textContent();
  const dueCount = Number((shown ?? "0 of 0").match(/^(\d+)/)?.[1] ?? "0");
  expect(dueCount).toBeGreaterThan(0);

  // 15. Start review.
  await page.goBack();
  await page.getByRole("link", { name: "Start review" }).click();
  await expect(page).toHaveURL(/\/review/);

  // 16. Present vocabulary.
  const headword = (await page.locator("h1").first().textContent())?.trim();
  expect(headword).toBeTruthy();

  // 17-18. Reveal and mark EASY.
  await page.getByRole("button", { name: /Reveal \(Space\)/ }).click();
  await page.getByRole("button", { name: /EASY/ }).click();

  // 19-20. FSRS updates and the next review date appears.
  const recorded = page.getByText(/Recorded EASY — next due .+/);
  await expect(recorded).toBeVisible({ timeout: 30_000 });

  // 21-22. Return later: due vocabulary reflects the updated FSRS state.
  await page.goBack();
  await expect(page.getByText("Recent reviews")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("EASY").first()).toBeVisible();
  const overdueAfter = await readOverdue();
  expect(overdueAfter).toBeLessThan(overdueBefore);
});

test.describe("responsive behavior (§53)", () => {
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "laptop", width: 1280, height: 800 },
    { name: "tablet", width: 768, height: 1024 },
  ];

  for (const viewport of viewports) {
    test(`workbench stays usable at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      // Already authenticated via the shared storage state from global
      // setup — §59 alone spends the suite's one real HTTP login (§39).
      await page.goto("/vocabulary");

      const rows = page.locator("tbody tr");
      await expect(rows.first()).toBeVisible({ timeout: 60_000 });
      await expect(
        page.getByPlaceholder("Search headwords, translations, definitions…"),
      ).toBeVisible();
      await expect(page.getByText("Clear all filters")).toBeVisible();

      // No horizontal scrolling of the document on any target viewport.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
