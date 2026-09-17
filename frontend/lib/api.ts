/**
 * Typed API client for the FastAPI backend (Phase 1 foundation).
 *
 * Implements the client side of the uniform error envelope (section 55):
 * every non-2xx response is parsed into `ApiError` carrying the backend
 * error code, message, details and correlation ID so the UI can show
 * actionable errors and report `request_id` to the teacher.
 */

const DEFAULT_API_BASE = "http://localhost:8000";

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_BASE;
}

export interface ErrorEnvelopeBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(status: number, body: ErrorEnvelopeBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || "Request failed";
  let details: Record<string, unknown> = {};
  let requestId = "-";
  try {
    const body = (await response.json()) as { error?: Partial<ErrorEnvelopeBody> };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
      requestId = body.error.request_id ?? requestId;
    }
  } catch {
    // Non-JSON error body (proxy, network appliance) — keep fallbacks.
  }
  return new ApiError(response.status, { code, message, details, request_id: requestId });
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
