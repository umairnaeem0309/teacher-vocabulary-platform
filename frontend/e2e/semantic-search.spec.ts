import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * Section 61 — SEMANTIC SEARCH ACCEPTANCE TESTS. *
 *     Verifies semantic retrieval for every example query required by §21/§61
 * ("vacation", "cooking", "airport problems", "hotel problems", "things
 * needed when traveling", "describing personality") against the real
 * corpus — 71k+ senses with bge-m3 embeddings built by the pipeline, not
 * synthetic fixtures — and then that
 *
 *     semantic search + CEFR + priority + student + not assigned
 *
 * compose server-side (§22: proper backend filtering, never client-side
 * filtering of a truncated result).
 *
 * The §59 workflow covers the same ground through the UI; these tests pin
 * the retrieval contract itself through the HTTP API the UI uses.
 */

const API = process.env.E2E_BACKEND_URL ?? "http://localhost:8737";
/** Cold semantic queries embed with the local model — allow a slow first call. */
const SEMANTIC_TIMEOUT = 150_000;

interface Hit {
  sense_id: string;
  headword: string;
  definition_preview: string | null;
  translations: string[];
  cefr_level: string | null;
  priority_level: string | null;
}

interface SearchBody {
  total: number;
  mode: string;
  hits: Hit[];
}

async function search(
  request: APIRequestContext,
  body: Record<string, unknown>,
  timeout = SEMANTIC_TIMEOUT,
): Promise<SearchBody> {
  const response = await request.fetch(`${API}/api/v1/vocabulary/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(body),
    timeout,
  });
  const text = await response.text();
  expect(
    response.ok(),
    `POST /vocabulary/search -> ${response.status()}: ${text.slice(0, 300)}`,
  ).toBeTruthy();
  return JSON.parse(text) as SearchBody;
}

async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.fetch(`${API}${path}`);
  const text = await response.text();
  expect(response.ok(), `GET ${path} -> ${response.status()}`).toBeTruthy();
  return JSON.parse(text) as T;
}

const CASES: { query: string; relevant: RegExp }[] = [
  {
    query: "vacation",
    relevant: /vacation|holiday|weekend|break|leave|\brest\b|travel|journey|tour/i,
  },
  {
    query: "cooking",
    relevant: /cook|recipe|food|kitchen|bake|fry|meal|heat/i,
  },
  {
    query: "airport problems",
    relevant:
      /problem|airport|flight|delay|luggage|passport|cancel|airfield|queue|boarding/i,
  },
  {
    query: "hotel problems",
    relevant:
      /problem|hotel|reception|booking|reservation|room|guest|complaint|stay/i,
  },
  {
    query: "things needed when traveling",
    relevant:
      /travel|luggage|passport|ticket|suitcase|\bcase\b|visa|\bbag\b|journey/i,
  },
  {
    query: "describing personality",
    relevant:
      /personality|character|trait|\bself\b|behav|disposition|temper|attitude/i,
  },
];

test("§61 semantic retrieval works for every example query", async ({
  request,
}) => {
  test.setTimeout(300_000);

  // Representative data: the CORPUS (not a handful of rows) backs the
  // vector search (§62: never benchmark/test against ten records).
  //
  // Asserted once, against the catalogue itself: an empty query is a
  // filtered browse, so its total IS the corpus size (measured 2026-10-07:
  // 71,157 senses after the Phase 31 rebuild; a ten-record fixture fails
  // this by four orders of magnitude).
  //
  // This used to be asserted per query as `total > 1000`, which was only
  // ever true while `total` was the whole-corpus count for ANY query (the
  // Phase 14 bug this suite's §61 work fixed). Now that totals are honest,
  // a semantic total is the number of senses within the cosine cutoff of
  // that particular query — a density measure, not a corpus measure. The
  // measured values (2026-10-07, full 71k embeddings, after D032 scoped the
  // semantic channel to vocabulary POS): vacation 1,435; cooking 17,627;
  // airport problems 213; hotel problems 193; things needed when traveling
  // 5,600; describing personality 9,608. Density legitimately varies by an
  // order of magnitude, and the multi-word "problems" queries sit lowest
  // while scoring the MOST relevant top hits (hotel problems: 11/12) — so
  // the per-query floor only has to separate "millions of vectors behind
  // this" from fixture scale.
  const catalogue = await search(request, {
    query: "",
    mode: "hybrid",
    sort: "relevance",
    limit: 1,
  });
  expect(catalogue.total, "corpus size").toBeGreaterThan(10_000);

  for (const { query, relevant } of CASES) {
    const result = await search(request, {
      query,
      mode: "semantic",
      sort: "relevance",
      limit: 12,
    });

    expect(result.mode, query).toBe("semantic");
    expect(result.total, `${query}: corpus-backed neighbours`).toBeGreaterThan(
      100,
    );
    expect(result.hits.length, `${query}: results returned`).toBeGreaterThanOrEqual(
      8,
    );

    // The query is a concept, not a phrase: relevant vocabulary must come
    // back even though the literal phrase never occurs (§21).
    const relevantHits = result.hits.filter((h) =>
      relevant.test(
        `${h.headword} ${h.definition_preview ?? ""} ${h.translations.join(" ")}`,
      ),
    ).length;
    expect(
      relevantHits,
      `${query}: top hits should be semantically relevant ` +
        `(got ${relevantHits}/${result.hits.length}: ` +
        `${result.hits.map((h) => h.headword).join(", ")})`,
    ).toBeGreaterThanOrEqual(3);
  }
});

test("§61 semantic + CEFR + priority + student + not-assigned compose", async ({
  request,
}) => {
  test.setTimeout(180_000);

  // Student John with real assignments (seeded by global setup).
  const students = await get<{ students: { id: string; display_name: string }[] }>(
    request,
    "/api/v1/students",
  );
  const john = students.students.find((s) => s.display_name === "John");
  expect(john, "seeded student John exists").toBeTruthy();

  const vocabulary = await get<{
    items: { sense: { id: string } }[];
  }>(request, `/api/v1/students/${john!.id}/vocabulary`);
  expect(vocabulary.items.length, "John has assigned vocabulary").toBeGreaterThan(0);
  const assignedIds = new Set(vocabulary.items.map((i) => i.sense.id));

  // §22 example, with the semantic layer on top: vacation + A2 + HIGH+ +
  // viewpoint John + NOT ASSIGNED — all evaluated in SQL (§22).
  const filtered = await search(request, {
    query: "vacation",
    mode: "semantic",
    sort: "relevance",
    limit: 50,
    filters: {
      student_id: john!.id,
      assigned: false,
      cefr: ["A2"],
      priority_min: "HIGH+",
    },
  });

  expect(filtered.total, "combined filters still yield results").toBeGreaterThan(0);
  expect(filtered.hits.length).toBeGreaterThan(0);
  for (const hit of filtered.hits) {
    expect(hit.cefr_level, `${hit.headword}: CEFR filter honored`).toBe("A2");
    expect(
      ["HIGH", "VERY HIGH"],
      `${hit.headword}: priority_min HIGH+ honored (${hit.priority_level})`,
    ).toContain(hit.priority_level);
    expect(
      assignedIds.has(hit.sense_id),
      `${hit.headword}: must NOT be assigned to John (§30)`,
    ).toBe(false);
  }

  // The combined result can only shrink versus the unfiltered semantic set.
  const unfiltered = await search(request, {
    query: "vacation",
    mode: "semantic",
    sort: "relevance",
    limit: 50,
    filters: { cefr: ["A2"], priority_min: "HIGH+" },
  });
  expect(filtered.total).toBeLessThanOrEqual(unfiltered.total);
});
