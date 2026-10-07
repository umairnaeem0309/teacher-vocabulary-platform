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
        learning_states: ["LEARNING", "REVIEWING"],
        due_only: true,
        difficult_only: true,
        teacher_priority_only: true,
        translation_availability: "reliable",
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
    // Falls back to the documented defaults: hybrid relevance search.
    expect(state.mode).toBe("hybrid");
    expect(state.sort).toBe("relevance");
  });

  it("defaults to the searching teacher's view, not a browse", () => {
    // The semantic and taxonomy layers are only reachable through
    // hybrid + relevance, so those must be the defaults.
    expect(DEFAULT_TABLE_STATE.mode).toBe("hybrid");
    expect(DEFAULT_TABLE_STATE.sort).toBe("relevance");
  });

  it("accepts the §21 sort keys and the §42 translation filter", () => {
    for (const sort of ["polish", "cefr", "topic", "pos", "student_status"]) {
      expect(paramsToState(new URLSearchParams(`sort=${sort}`)).sort).toBe(sort);
    }
    const state = paramsToState(new URLSearchParams("tavail=missing"));
    expect(state.filters.translation_availability).toBe("missing");
  });

  it("trims lists and drops empty tokens", () => {
    const state = paramsToState(new URLSearchParams("cefr= A2 ,, B1 ,"));
    expect(state.filters.cefr).toEqual(["A2", "B1"]);
  });

  it("parses §19 student-scope list and flag params", () => {
    const state = paramsToState(
      new URLSearchParams(
        "learning_states=LEARNING,REVIEWING&due=yes&difficult=yes&tprio=yes",
      ),
    );
    expect(state.filters.learning_states).toEqual(["LEARNING", "REVIEWING"]);
    expect(state.filters.due_only).toBe(true);
    expect(state.filters.difficult_only).toBe(true);
    expect(state.filters.teacher_priority_only).toBe(true);
  });

  it("leaves §19 flags unset when the params are absent", () => {
    const state = paramsToState(new URLSearchParams());
    expect(state.filters.learning_states).toEqual([]);
    expect(state.filters.due_only).toBeNull();
    expect(state.filters.difficult_only).toBeNull();
    expect(state.filters.teacher_priority_only).toBeNull();
  });
});
