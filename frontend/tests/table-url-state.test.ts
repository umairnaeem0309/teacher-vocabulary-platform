/**
 * Unit tests for the vocabulary table's URL state mapping: the round trip
 * must be lossless and every deviation from defaults must serialize.
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_TABLE_STATE,
  isDefaultState,
  paramsToState,
  stateToParams,
} from "@/lib/table-url-state";

describe("stateToParams / paramsToState", () => {
  it("round-trips a fully populated state", () => {
    const state = {
      query: "  bank  ",
      mode: "semantic" as const,
      sort: "priority" as const,
      filters: {
        cefr: ["A2", "B1"],
        pos: ["noun", "verb"],
        priority_levels: ["VERY HIGH", "HIGH"],
        priority_min: "MEDIUM",
        category_key: "food",
        frequency_bands: ["top1000"],
        max_frequency_rank: 3000,
        flags: ["rare", "british"],
        student_id: "7a0e9a10-0000-4000-8000-000000000001",
        assigned: false,
      },
      page: 3,
      pageSize: 100,
    };
    const params = stateToParams(state);
    const parsed = paramsToState(params);
    expect(parsed.query).toBe("bank");
    expect(parsed.mode).toBe("semantic");
    expect(parsed.sort).toBe("priority");
    expect(parsed.filters).toEqual(state.filters);
    expect(parsed.page).toBe(3);
    expect(parsed.pageSize).toBe(100);
  });

  it("produces empty params for the default state", () => {
    expect(stateToParams(DEFAULT_TABLE_STATE).size).toBe(0);
    expect(isDefaultState(DEFAULT_TABLE_STATE)).toBe(true);
  });

  it("parses garbage numerics defensively", () => {
    const params = new URLSearchParams("page=-4&size=99999&maxrank=abc");
    const state = paramsToState(params);
    expect(state.page).toBe(0);
    expect(state.pageSize).toBe(200); // clamped to the backend MAX_LIMIT
    expect(state.filters.max_frequency_rank).toBeNull();
  });

  it("ignores unknown modes and sorts", () => {
    const state = paramsToState(new URLSearchParams("mode=bogus&sort=bogus"));
    expect(state.mode).toBe("lexical");
    expect(state.sort).toBe("headword");
  });

  it("trims lists and drops empty tokens", () => {
    const state = paramsToState(new URLSearchParams("cefr= A2 ,, B1 ,"));
    expect(state.filters.cefr).toEqual(["A2", "B1"]);
  });
});
