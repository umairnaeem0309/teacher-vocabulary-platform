/**
 * Import/export API functions (Phase 22, sections 38/99).
 *
 * Export returns a Blob download (the browser handles the file save);
 * import posts multipart form data through the shared error-envelope
 * client semantics (ApiError on non-2xx).
 */

import { apiBase, ApiError } from "@/lib/api";

export type ExportFormat = "csv" | "xlsx" | "json";

export interface ExportFilters {
  cefr?: string[];
  pos?: string[];
  priority_levels?: string[];
  priority_min?: string | null;
  category_key?: string | null;
  frequency_bands?: string[];
  max_frequency_rank?: number | null;
  flags?: string[];
  format: ExportFormat;
}

export interface ImportPreviewRow {
  line: number;
  headword: string;
  status: "new" | "existing_match" | "conflict" | "error";
  errors: string[];
  warnings: string[];
  detail: string;
}

export interface ImportPreview {
  total_rows: number;
  counts: { new: number; existing_match: number; conflict: number; error: number };
  rows: ImportPreviewRow[];
  would_insert_senses: number;
  would_skip: number;
  version: string;
}

export interface ImportReport {
  inserted_senses: number;
  existing_senses_touched: number;
  translations_added: number;
  examples_added: number;
  flags_added: number;
  skipped: Array<{ line: number; detail: string }>;
  skipped_count: number;
  version: string;
}

export async function downloadVocabularyExport(
  filters: ExportFilters,
): Promise<void> {
  const response = await fetch(`${apiBase()}/api/v1/exports/vocabulary`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });
  if (!response.ok) {
    // Reuse the envelope parser via ApiError construction.
    let message = response.statusText || "Export failed";
    try {
      const body = (await response.json()) as {
        error?: { message?: string };
      };
      if (body.error?.message) message = body.error.message;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, {
      code: "http_" + response.status,
      message,
      details: {},
      request_id: "-",
    });
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? `vocabulary-export.${filters.format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function parseEnvelopeError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || "Request failed";
  let details: Record<string, unknown> = {};
  let requestId = "-";
  try {
    const body = (await response.json()) as { error?: Record<string, unknown> };
    if (body.error) {
      code = (body.error.code as string) ?? code;
      message = (body.error.message as string) ?? message;
      details = (body.error.details as Record<string, unknown>) ?? {};
      requestId = (body.error.request_id as string) ?? requestId;
    }
  } catch {
    // keep fallbacks
  }
  return new ApiError(response.status, {
    code,
    message,
    details,
    request_id: requestId,
  });
}

async function postFile<T>(
  path: string,
  file: File,
  format: string,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  form.append("format", format);
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    throw await parseEnvelopeError(response);
  }
  return (await response.json()) as T;
}

export function previewVocabularyImport(
  file: File,
  format: string,
): Promise<ImportPreview> {
  return postFile<ImportPreview>("/api/v1/imports/vocabulary/preview", file, format);
}

export function importVocabulary(
  file: File,
  format: string,
): Promise<ImportReport> {
  return postFile<ImportReport>("/api/v1/imports/vocabulary", file, format);
}
