import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * Section 60 — DUPLICATE ACCEPTANCE TEST.
 *
 * Part 1: "BANK — financial institution" discovered through every path
 * listed in §60 (search, topic, semantic search, set, CEFR filter) and
 * assigned each time must always resolve to exactly ONE student
 * vocabulary record — the master sense ID is the identity (§9), no
 * matter how the sense was found (§29 layered duplicate prevention).
 *
 * Part 2: "BANK — financial institution" vs "BANK — side of river" are
 * two distinct master senses, so they may create two distinct student
 * vocabulary records — and the financial one must still be exactly one.
 *
 * Discovery runs through the real UI (URL-driven table state, row
 * selection, bulk assign, set creation, set assignment); the invariant is
 * asserted against real API record counts after every path.
 */

const API = process.env.E2E_BACKEND_URL ?? "http://localhost:8737";
const STUDENT_NAME = "Duplicate Tester";
const SET_NAME = "BANK duplicate probe";

/** Definition text unique to BANK the financial institution (§9). */
const FINANCIAL_RE = /institution where one can place and borrow money/i;
/** Definition text unique to BANK the side of a river (§9). */
const RIVER_RE = /edge of river/i;

interface Hit {
  sense_id: string;
  headword: string;
  definition_preview: string | null;
  cefr_level: string | null;
}

async function api<T>(
  request: APIRequestContext,
  method: "get" | "post",
  path: string,
  data?: unknown,
): Promise<T> {
  const response = await request.fetch(`${API}${path}`, {
    method: method.toUpperCase(),
    headers: { "Content-Type": "application/json" },
    ...(data !== undefined ? { data: JSON.stringify(data) } : {}),
  });
  const body = await response.text();
  expect(
    response.ok(),
    `${method.toUpperCase()} ${path} -> ${response.status()}: ${body.slice(0, 300)}`,
  ).toBeTruthy();
  return JSON.parse(body) as T;
}

test("§60 one master sense stays one record across every discovery path", async ({
  page,
  request,
}) => {
  test.setTimeout(300_000);

  // ---------------------------------------------------------------- fixtures
  // Student (global setup resets the teacher's data before every run).
  const listed = await api<{ students: { id: string; display_name: string }[] }>(
    request,
    "get",
    "/api/v1/students",
  );
  const existing = listed.students.find((s) => s.display_name === STUDENT_NAME);
  const studentId = existing
    ? existing.id
    : (
        await api<{ id: string }>(request, "post", "/api/v1/students", {
          display_name: STUDENT_NAME,
        })
      ).id;

  const search = (body: Record<string, unknown>) =>
    api<{ total: number; hits: Hit[] }>(
      request,
      "post",
      "/api/v1/vocabulary/search",
      body,
    );

  // Resolve both master senses by identity (§9), not by spelling.
  const lookup = await search({
    query: "bank",
    mode: "lexical",
    sort: "relevance",
    limit: 50,
  });
  const financial = lookup.hits.find((h) =>
    FINANCIAL_RE.test(h.definition_preview ?? ""),
  );
  const river = lookup.hits.find((h) =>
    RIVER_RE.test(h.definition_preview ?? ""),
  );
  expect(financial, "BANK — financial institution master sense exists").toBeTruthy();
  expect(river, "BANK — side of river master sense exists").toBeTruthy();
  const fin = financial as Hit;
  const riv = river as Hit;
  expect(fin.headword.toLowerCase()).toBe("bank");
  expect(riv.headword.toLowerCase()).toBe("bank");
  expect(fin.sense_id).not.toBe(riv.sense_id);
  expect(fin.cefr_level).toBeTruthy();

  /** How many student_vocabulary rows exist for any sense of "bank". */
  const bankRecords = async () => {
    const voc = await api<{
      items: { id: string; sense: { id: string; headword: string } }[];
    }>(request, "get", `/api/v1/students/${studentId}/vocabulary`);
    return voc.items.filter((i) => i.sense.headword.toLowerCase() === "bank");
  };

  // Reusable UI interactions on the vocabulary workbench.
  const financialRow = page
    .locator("tbody tr")
    .filter({ hasText: /place and borrow money/ });

  const assignSelected = async (expectNote: RegExp) => {
    const chip = page.locator("span").filter({ hasText: /\d+ selected/ }).first();
    await expect(chip).toBeVisible();
    await chip.locator("select").first().selectOption({ label: STUDENT_NAME });
    await chip.getByRole("button", { name: "Assign", exact: true }).click();
    // The chip disappears only after the mutation succeeded (§29 report
    // is rendered in the same commit), so the note seen afterwards is fresh.
    await expect(chip).toBeHidden({ timeout: 30_000 });
    await expect(page.getByText(expectNote)).toBeVisible();
  };

  const selectFinancialRow = async (timeout = 60_000) => {
    await expect(financialRow).toHaveCount(1, { timeout });
    const box = financialRow.locator("input[type='checkbox']");
    await box.click();
    await expect(box).toBeChecked();
  };

  // ------------------------------------------------- path 1: search (UI)
  await page.goto("/vocabulary?q=bank&mode=lexical&sort=relevance");
  await selectFinancialRow();
  await assignSelected(/^1 assigned, 0 already had them/);
  expect(await bankRecords()).toHaveLength(1);

  // ---------------------------------------------------- path 2: topic (UI)
  await page.goto(
    "/vocabulary?q=bank&mode=lexical&sort=relevance&cat=money-banking",
  );
  await selectFinancialRow();
  await assignSelected(/^0 assigned, 1 already had them/);
  expect(await bankRecords()).toHaveLength(1);

  // ----------------------------------------------------- path 3: CEFR (UI)
  await page.goto(
    `/vocabulary?q=bank&mode=lexical&sort=relevance&cefr=${fin.cefr_level}`,
  );
  await selectFinancialRow();
  await assignSelected(/^0 assigned, 1 already had them/);
  expect(await bankRecords()).toHaveLength(1);

  // ------------------------------------------------ path 4: semantic (UI)
  await page.goto(
    "/vocabulary?q=" +
      encodeURIComponent("financial institution money deposit") +
      "&mode=semantic&sort=relevance",
  );
  // Cold query embedding (model load on the very first semantic request)
  // can take a while — allow extra headroom here.
  await selectFinancialRow(120_000);
  await assignSelected(/^0 assigned, 1 already had them/);
  expect(await bankRecords()).toHaveLength(1);

  // --------------------------------------------- path 5: set (UI + set page)
  // Add the sense to a brand-new set from the table's bulk chip…
  await selectFinancialRow();
  {
    const chip = page.locator("span").filter({ hasText: /\d+ selected/ }).first();
    await expect(chip).toBeVisible();
    await chip.locator("select").nth(1).selectOption("__new__");
    await chip.getByPlaceholder("new set name").fill(SET_NAME);
    await chip.getByRole("button", { name: "Add", exact: true }).click();
    await expect(chip).toBeHidden({ timeout: 30_000 });
    await expect(
      page.getByText(/^1 added to the set, 0 were already in it/),
    ).toBeVisible();
  }
  // …then assign the set itself: same master sense, same single record.
  await page.goto("/sets");
  await page.getByRole("link", { name: SET_NAME, exact: true }).click();
  await expect(page).toHaveURL(/\/sets\/[0-9a-f-]+/);
  await page.locator("select").selectOption({ label: STUDENT_NAME });
  await page.getByRole("button", { name: "Assign set" }).click();
  await expect(
    page.getByText(/^0 assigned to the student, 1 already had them/),
  ).toBeVisible({ timeout: 30_000 });

  const afterPaths = await bankRecords();
  expect(afterPaths, "five discovery paths, still one record").toHaveLength(1);
  expect(afterPaths[0].sense.id).toBe(fin.sense_id);

  // --------------------------------------------- part 2: two senses → two rows
  const riverReport = await api<{ new: number; already_assigned: number }>(
    request,
    "post",
    "/api/v1/assignments",
    { student_id: studentId, sense_ids: [riv.sense_id] },
  );
  expect(riverReport.new).toBe(1);
  expect(riverReport.already_assigned).toBe(0);

  const final = await bankRecords();
  expect(final, "financial + river = two records").toHaveLength(2);
  expect(new Set(final.map((r) => r.sense.id)).size, "two master senses").toBe(2);
  expect(new Set(final.map((r) => r.id)).size, "two student rows").toBe(2);
  expect(
    final.filter((r) => r.sense.id === fin.sense_id),
    "financial institution: still exactly one record",
  ).toHaveLength(1);
});
