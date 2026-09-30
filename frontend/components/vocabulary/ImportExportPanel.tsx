"use client";

import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  downloadVocabularyExport,
  importVocabulary,
  previewVocabularyImport,
  type ExportFormat,
  type ImportPreview,
  type ImportReport,
} from "@/lib/io-client";
import type { SearchFilters } from "@/lib/search-types";

/**
 * Export/import workbench tools (Phase 22, sections 38/99).
 *
 * Export downloads master vocabulary honoring the current workbench
 * filter selection (minus the student-viewpoint filters, which the
 * backend rejects). Import is two-step: preview (validate only) then
 * explicit "Import now" — the server re-validates and never overwrites
 * existing master vocabulary (insert-only, D024).
 */

const STATUS_STYLES: Record<ImportPreview["rows"][number]["status"], string> = {
  new: "bg-green-100 text-green-800",
  existing_match: "bg-blue-100 text-blue-800",
  conflict: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-700",
};

export function ImportExportPanel({
  filters,
}: {
  filters: SearchFilters;
}) {
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [fileFormat, setFileFormat] = useState<string>("csv");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const exportMasterFilters = {
    cefr: filters.cefr,
    pos: filters.pos,
    priority_levels: filters.priority_levels,
    priority_min: filters.priority_min,
    category_key: filters.category_key,
    frequency_bands: filters.frequency_bands,
    max_frequency_rank: filters.max_frequency_rank,
    flags: filters.flags,
    format,
  };

  const previewMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("no file");
      return previewVocabularyImport(file, fileFormat);
    },
    onSuccess: (data) => {
      setPreview(data);
      setReport(null);
      setImportError(null);
    },
    onError: (err) =>
      setImportError(
        err instanceof Error ? err.message : "Could not preview the file.",
      ),
  });

  const commitMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("no file");
      return importVocabulary(file, fileFormat);
    },
    onSuccess: (data) => {
      setReport(data);
      setPreview(null);
      setImportError(null);
      if (fileInput.current) fileInput.current.value = "";
    },
    onError: (err) =>
      setImportError(
        err instanceof Error ? err.message : "Could not import the file.",
      ),
  });

  function onExport() {
    setExportBusy(true);
    setExportError(null);
    downloadVocabularyExport(exportMasterFilters)
      .catch((err: unknown) =>
        setExportError(
          err instanceof Error ? err.message : "Export failed.",
        ),
      )
      .finally(() => setExportBusy(false));
  }

  function onFileChosen(f: File | null) {
    setFile(f);
    setPreview(null);
    setReport(null);
    setImportError(null);
    const ext = f?.name.split(".").pop()?.toLowerCase();
    if (ext === "xlsx") setFileFormat("xlsx");
    else if (ext === "json") setFileFormat("json");
    else setFileFormat("csv");
  }

  return (
    <div className="space-y-4 rounded border border-neutral-200 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="text-xs text-neutral-500">Format</span>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as ExportFormat)}
            className="block rounded border border-neutral-300 px-2 py-1"
          >
            <option value="csv">CSV</option>
            <option value="xlsx">Excel (XLSX)</option>
            <option value="json">JSON</option>
          </select>
        </label>
        <button
          type="button"
          onClick={onExport}
          disabled={exportBusy}
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {exportBusy ? "Exporting…" : "Export current selection"}
        </button>
        <p className="max-w-md text-xs text-neutral-500">
          Exports master vocabulary with the current filters (student
          filters are not included).
        </p>
        {exportError && (
          <span className="text-sm text-red-600">{exportError}</span>
        )}
      </div>

      <div className="border-t border-neutral-100 pt-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="text-xs text-neutral-500">Import file</span>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,.xlsx,.json,text/csv,application/json"
              onChange={(e) => onFileChosen(e.target.files?.[0] ?? null)}
              className="block rounded border border-neutral-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            disabled={!file || previewMut.isPending}
            onClick={() => previewMut.mutate()}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100 disabled:opacity-50"
          >
            {previewMut.isPending ? "Validating…" : "Validate (preview)"}
          </button>
        </div>
        {importError && (
          <p className="mt-2 text-sm text-red-600">{importError}</p>
        )}

        {preview && (
          <div className="mt-3 space-y-2">
            <p className="text-sm">
              {preview.total_rows} row(s):{" "}
              <span className="text-green-700">
                {preview.counts.new} new
              </span>
              ,{" "}
              <span className="text-blue-700">
                {preview.counts.existing_match} already present
              </span>
              ,{" "}
              <span className="text-amber-700">
                {preview.counts.conflict} conflict(s)
              </span>
              ,{" "}
              <span className="text-red-600">
                {preview.counts.error} error(s)
              </span>
            </p>
            {preview.rows.some((r) => r.status !== "new") && (
              <ul className="max-h-48 space-y-0.5 overflow-auto text-xs">
                {preview.rows
                  .filter((r) => r.status !== "new")
                  .slice(0, 50)
                  .map((r) => (
                    <li key={r.line}>
                      <span
                        className={`inline-block w-28 rounded px-1 text-center ${STATUS_STYLES[r.status]}`}
                      >
                        {r.status}
                      </span>{" "}
                      line {r.line}: {r.headword || "(no headword)"} —{" "}
                      {r.errors[0] ?? r.detail}
                    </li>
                  ))}
              </ul>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={
                  preview.counts.error > 0 ||
                  preview.total_rows === 0 ||
                  commitMut.isPending
                }
                onClick={() => commitMut.mutate()}
                className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-40"
              >
                {commitMut.isPending
                  ? "Importing…"
                  : `Import ${preview.would_insert_senses} new sense(s)`}
              </button>
              <span className="text-xs text-neutral-500">
                Insert-only: existing vocabulary is never overwritten.
              </span>
            </div>
          </div>
        )}

        {report && (
          <div className="mt-3 rounded border border-green-200 bg-green-50 p-2 text-sm">
            Imported: {report.inserted_senses} new sense(s),{" "}
            {report.translations_added} translation(s),{" "}
            {report.examples_added} example(s), {report.flags_added}{" "}
            flag(s); {report.existing_senses_touched} existing sense(s)
            merged; {report.skipped_count} skipped.
          </div>
        )}
      </div>
    </div>
  );
}
