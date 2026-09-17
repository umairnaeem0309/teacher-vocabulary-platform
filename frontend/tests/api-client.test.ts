/**
 * API client tests: the client must translate the backend error envelope
 * into ApiError with code/details/request_id preserved (section 55).
 */
import { afterEach, describe, expect, it } from "vitest";

import { apiBase, ApiError, apiFetch } from "@/lib/api";

const ENVELOPE = {
  error: {
    code: "not_found",
    message: "The requested resource was not found.",
    details: { phase: 13 },
    request_id: "abc123",
  },
};

/** Run a request expected to fail; return the typed ApiError. */
async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected the request to fail with ApiError");
}

describe("apiBase", () => {
  it("falls back to localhost:8000", () => {
    expect(apiBase()).toBe("http://localhost:8000");
  });
});

describe("apiFetch error handling", () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  const originalFetch = globalThis.fetch;

  it("parses the error envelope into ApiError", async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(ENVELOPE), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      })) as typeof fetch;

    const err = await expectApiError(apiFetch("/api/v1/vocabulary/42"));
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.requestId).toBe("abc123");
    expect(err.details).toEqual({ phase: 13 });
  });

  it("falls back gracefully on non-JSON errors", async () => {
    globalThis.fetch = (async () =>
      new Response("<html>Bad Gateway</html>", { status: 502 })) as typeof fetch;

    const err = await expectApiError(apiFetch("/api/v1/anything"));
    expect(err.status).toBe(502);
    expect(err.code).toBe("http_502");
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })) as typeof fetch;

    await expect(apiFetch("/api/v1/health")).resolves.toEqual({ status: "ok" });
  });
});
