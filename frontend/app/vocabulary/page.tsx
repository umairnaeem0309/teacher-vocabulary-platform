"use client";

import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  getCoreRowModel,
  useLegacyTable,
} from "@tanstack/react-table/legacy";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import { flexRender } from "@tanstack/react-table";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";

import { FilterPanel } from "@/components/vocabulary/FilterPanel";
import { ImportExportPanel } from "@/components/vocabulary/ImportExportPanel";
import { ApiError } from "@/lib/api";
import { assignSenses } from "@/lib/assignments-client";
import { addSetItems, createSet, listSets } from "@/lib/sets-client";
import { listStudents } from "@/lib/students-client";
import { browseVocabulary, fetchFilterFacets, postSearch } from "@/lib/search-client";
import type { SearchHit, SearchMode, SortKey } from "@/lib/search-types";
import { paramsToState, stateToParams } from "@/lib/table-url-state";
import type { TableState } from "@/lib/table-url-state";
import { ROUTES } from "@/lib/routes";

const COLUMNS = [
  { key: "headword", label: "Headword", sort: "headword" as SortKey },
  { key: "pos", label: "POS", sort: "pos" as SortKey },
  { key: "cefr", label: "CEFR", sort: "cefr" as SortKey },
  { key: "translations", label: "Polish", sort: "polish" as SortKey },
  { key: "definition", label: "Definition", sort: null },
  { key: "priority", label: "Priority", sort: "priority" as SortKey },
  { key: "frequency", label: "Freq.", sort: "frequency" as SortKey },
  { key: "score", label: "Score", sort: "relevance" as SortKey },
] as const;

/** §20/§37: clipboard formats for copying the current selection. */
const COPY_FORMATS = [
  { key: "en", label: "English", withPl: false, withDef: false },
  { key: "en-pl", label: "English — Polish", withPl: true, withDef: false },
  { key: "en-def", label: "English — definition", withPl: false, withDef: true },
  {
    key: "en-pl-def",
    label: "English — Polish — definition",
    withPl: true,
    withDef: true,
  },
] as const;

/** Render one vocabulary row in the requested clipboard format (§37). */
function formatCopyLine(
  hit: SearchHit,
  opts: { withPl: boolean; withDef: boolean },
): string {
  const parts = [hit.headword];
  if (opts.withPl) parts.push(hit.translations.slice(0, 3).join(", ") || "—");
  if (opts.withDef) parts.push(hit.definition_preview ?? "—");
  return parts.join(" — ");
}

/**
 * Dense vocabulary workbench (sections 23/39): spreadsheet-style table
 * over the Phase 14 search engine. Query/filters/sort/pagination live in
 * the URL (shareable views); selection is client-side for bulk actions.
 *
 * HCI layout (top to bottom):
 *   1. Page header — title, purpose line, live result count.
 *   2. Search & view card — dominant search field, labelled Mode/Sort.
 *   3. Selection action bar — appears only with a selection or a note.
 *   4. Filter rail (card) + results card (table, empty/error states,
 *      pagination footer) + export/import drawer.
 */
export default function VocabularyPageWrapper() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto w-full max-w-[110rem] px-4 py-6 md:px-6">
          <p className="text-sm text-neutral-500">Loading the workbench…</p>
        </main>
      }
    >
      <VocabularyPage />
    </Suspense>
  );
}

function VocabularyPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const state = useMemo(() => paramsToState(new URLSearchParams(searchParams)), [searchParams]);

  function updateState(next: Partial<TableState>, resetPage = true) {
    const merged: TableState = { ...state, ...next, ...(resetPage ? { page: 0 } : {}) };
    router.replace(`/vocabulary?${stateToParams(merged).toString()}`, { scroll: false });
  }

  const isRelevance = state.sort === "relevance";
  const hasQuery = state.query.trim().length > 0;
  const effectiveSort: SortKey = isRelevance && !hasQuery ? "priority" : state.sort;

  const requestBody = useMemo(
    () => ({
      query: state.query,
      mode: state.mode,
      filters: state.filters,
      sort: effectiveSort,
      limit: state.pageSize,
      offset: state.page * state.pageSize,
    }),
    [state, effectiveSort],
  );

  const results = useQuery({
    queryKey: ["vocabulary", "table", requestBody],
    queryFn: () => (hasQuery ? postSearch(requestBody) : browseVocabulary(requestBody)),
    placeholderData: keepPreviousData,
  });

  const facets = useQuery({
    queryKey: ["vocabulary", "facets"],
    queryFn: fetchFilterFacets,
    staleTime: 10 * 60_000,
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [assignTo, setAssignTo] = useState("");
  const [assignNote, setAssignNote] = useState<string | null>(null);
  const [copyNote, setCopyNote] = useState<string | null>(null);
  const students = useQuery({
    queryKey: ["students", "list", false],
    queryFn: () => listStudents(false),
    staleTime: 5 * 60_000,
  });
  const assign = useMutation({
    mutationFn: () =>
      assignSenses({ student_id: assignTo, sense_ids: [...selected] }),
    onSuccess: (report) => {
      setAssignNote(
        `${report.new} assigned, ${report.already_assigned} already had them${
          report.failed.length ? `, ${report.failed.length} failed` : ""
        }.`,
      );
      setSelected(new Set());
      void results.refetch();
    },
    onError: (err) =>
      setAssignNote(
        err instanceof ApiError ? err.message : "Assignment failed.",
      ),
  });
  const allSets = useQuery({
    queryKey: ["sets", "list"],
    queryFn: listSets,
    staleTime: 5 * 60_000,
  });
  const [setMode, setSetMode] = useState(""); // "" | existing set id | "__new__"
  const [newSetName, setNewSetName] = useState("");
  const addToSet = useMutation({
    mutationFn: async () => {
      if (setMode === "__new__") {
        const created = await createSet({ name: newSetName });
        return addSetItems(created.id, [...selected]);
      }
      return addSetItems(setMode, [...selected]);
    },
    onSuccess: (report) => {
      setAssignNote(
        `${report.new} added to the set, ${report.already_in_set} were already in it.`,
      );
      setSelected(new Set());
      setSetMode("");
      setNewSetName("");
      queryClient.invalidateQueries({ queryKey: ["sets"] });
    },
    onError: (err) =>
      setAssignNote(
        err instanceof ApiError ? err.message : "Could not add to the set.",
      ),
  });
  const hits: SearchHit[] = results.data?.hits ?? [];
  const total = results.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));

  function toggleRow(senseId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(senseId)) next.delete(senseId);
      else next.add(senseId);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) =>
      prev.size > 0 ? new Set() : new Set(hits.map((h) => h.sense_id)),
    );
  }

  /** §20/§37: copy the selected rows as plain text for a message to students. */
  async function copySelected(opts: { withPl: boolean; withDef: boolean }) {
    const rows = hits.filter((h) => selected.has(h.sense_id));
    const text = rows.map((h) => formatCopyLine(h, opts)).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopyNote(`Copied ${rows.length} sense${rows.length === 1 ? "" : "s"}.`);
    } catch {
      setCopyNote("Clipboard unavailable — copy is blocked by the browser.");
    }
  }

  const columns: LegacyColumnDef<SearchHit>[] = useMemo(
    () =>
      COLUMNS.map((col) => ({
        id: col.key,
        header: col.label,
        cell: (info: { row: { original: SearchHit } }) =>
          renderCell(col.key, info.row.original),
      })),
    [],
  );

  // Server-driven table: pagination/sorting happen in SQL (section 22);
  // TanStack provides the headless row/header model only.
  const table = useLegacyTable<SearchHit>({
    data: hits,
    columns,
    getCoreRowModel: getCoreRowModel<SearchHit>(),
    manualPagination: true,
    manualSorting: true,
    pageCount,
  });

  return (
    <main className="mx-auto w-full max-w-[110rem] px-4 py-6 md:px-6">
      {/* 1. Page header: identity + live result count */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Vocabulary</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Search the corpus, narrow it with filters, then copy or assign the
            selection.
          </p>
        </div>
        <p className="text-sm text-neutral-500" aria-live="polite">
          <span className="font-semibold text-neutral-800">
            {total.toLocaleString()}
          </span>{" "}
          senses{results.isFetching ? "…" : ""}
        </p>
      </div>

      {/* 2. Search & view controls */}
      <div className="mt-4 rounded-xl border border-neutral-200 bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[16rem] flex-1">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5" />
            </svg>
            <input
              type="search"
              value={state.query}
              onChange={(e) => updateState({ query: e.target.value })}
              placeholder="Search headwords, translations, definitions…"
              className="w-full rounded-lg border border-neutral-300 py-2 pl-9 pr-3 text-sm focus:border-neutral-500 focus:outline-none focus:ring-2 focus:ring-neutral-200"
            />
          </div>

          <label className="flex items-center gap-1.5 text-xs font-medium text-neutral-500">
            Mode
            <select
              value={state.mode}
              onChange={(e) => updateState({ mode: e.target.value as SearchMode })}
              className="rounded-lg border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-900 focus:border-neutral-500 focus:outline-none"
            >
              <option value="lexical">Lexical</option>
              <option value="semantic">Semantic</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-xs font-medium text-neutral-500">
            Sort
            <select
              value={state.sort}
              onChange={(e) => updateState({ sort: e.target.value as SortKey })}
              className="rounded-lg border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-900 focus:border-neutral-500 focus:outline-none"
            >
              <option value="relevance">Sort: relevance</option>
              <option value="headword">Sort: headword</option>
              <option value="polish">Sort: Polish</option>
              <option value="cefr">Sort: CEFR</option>
              <option value="topic">Sort: topic</option>
              <option value="pos">Sort: part of speech</option>
              <option value="priority">Sort: priority</option>
              <option value="frequency">Sort: frequency</option>
              <option value="student_status">Sort: student status</option>
            </select>
          </label>
        </div>

        {/* Feedback: fetch failure is explicit, never a silently empty table */}
        {results.isError && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <p className="text-sm text-red-700">
              Could not load results —{" "}
              {results.error instanceof ApiError
                ? results.error.message
                : "is the backend running on port 8000?"}
            </p>
            <button
              type="button"
              onClick={() => results.refetch()}
              className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        )}
      </div>

      {/* 3. Selection action bar (only when there is something to act on) */}
      {(selected.size > 0 || assignNote || copyNote) && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2">
          {selected.size > 0 && (
            <span className="flex flex-wrap items-center gap-2 rounded-lg bg-neutral-900 px-2.5 py-1.5 text-xs text-white">
              {selected.size} selected
              <select
                value={assignTo}
                onChange={(e) => setAssignTo(e.target.value)}
                className="rounded bg-neutral-800 px-1.5 py-1 text-white"
              >
                <option value="">assign to…</option>
                {(students.data?.students ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.display_name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!assignTo || assign.isPending}
                onClick={() => assign.mutate()}
                className="rounded bg-white px-2 py-1 text-xs font-medium text-neutral-900 disabled:opacity-40"
              >
                {assign.isPending ? "Assigning…" : "Assign"}
              </button>
              <select
                value={setMode}
                onChange={(e) => setSetMode(e.target.value)}
                className="rounded bg-neutral-800 px-1.5 py-1 text-white"
              >
                <option value="">add to set…</option>
                {(allSets.data?.sets ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
                <option value="__new__">＋ new set…</option>
              </select>
              {setMode === "__new__" && (
                <input
                  value={newSetName}
                  onChange={(e) => setNewSetName(e.target.value)}
                  placeholder="new set name"
                  maxLength={200}
                  className="w-32 rounded bg-neutral-800 px-1.5 py-1 text-white placeholder-neutral-400"
                />
              )}
              <button
                type="button"
                disabled={
                  !setMode ||
                  addToSet.isPending ||
                  (setMode === "__new__" && !newSetName.trim())
                }
                onClick={() => addToSet.mutate()}
                className="rounded bg-white px-2 py-1 text-xs font-medium text-neutral-900 disabled:opacity-40"
              >
                {addToSet.isPending ? "Adding…" : "Add"}
              </button>
              <span className="flex items-center gap-1 border-l border-neutral-600 pl-2">
                <span className="text-neutral-400">copy:</span>
                {COPY_FORMATS.map((fmt) => (
                  <button
                    key={fmt.key}
                    type="button"
                    title={`Copy: ${fmt.label}`}
                    onClick={() => copySelected(fmt)}
                    className="rounded bg-neutral-700 px-1.5 py-1 text-xs text-white hover:bg-neutral-600"
                  >
                    {fmt.label === "English"
                      ? "EN"
                      : fmt.key === "en-pl"
                        ? "EN+PL"
                        : fmt.key === "en-def"
                          ? "EN+def"
                          : "all"}
                  </button>
                ))}
              </span>
            </span>
          )}
          {assignNote && (
            <span className="text-xs text-neutral-600">{assignNote}</span>
          )}
          {copyNote && (
            <span className="text-xs text-neutral-600">{copyNote}</span>
          )}
        </div>
      )}

      {/* 4. Filter rail + results */}
      <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-start">
        <FilterPanel
          facets={facets.data}
          filters={state.filters}
          onChange={(filters) => updateState({ filters })}
        />

        <section className="min-w-0 flex-1">
          <div
            className={`overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm ${
              results.isFetching ? "opacity-70 transition-opacity" : "transition-opacity"
            }`}
          >
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  {table.getHeaderGroups().map((hg) => (
                    <tr
                      key={hg.id}
                      className="border-b border-neutral-200 bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500"
                    >
                      <th className="w-8 px-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={hits.length > 0 && selected.size === hits.length}
                          onChange={toggleAll}
                          aria-label="Select page"
                          className="accent-neutral-900"
                        />
                      </th>
                      {hg.headers.map((header) => {
                        const col = COLUMNS.find(
                          (c) => c.key === header.column.id,
                        );
                        const sortable =
                          col?.sort !== null && col?.sort !== undefined;
                        return (
                          <th
                            key={header.id}
                            className={`px-3 py-2.5 font-medium ${
                              sortable
                                ? "cursor-pointer select-none hover:text-neutral-900"
                                : ""
                            }`}
                            onClick={
                              sortable
                                ? () => updateState({ sort: col.sort as SortKey })
                                : undefined
                            }
                          >
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                            {state.sort === col?.sort && " ▾"}
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className={`cursor-pointer border-b border-neutral-100 transition-colors hover:bg-neutral-50 ${
                        selected.has(row.original.sense_id) ? "bg-neutral-100" : ""
                      }`}
                      onClick={() =>
                        router.push(ROUTES.vocabularySense(row.original.sense_id))
                      }
                    >
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selected.has(row.original.sense_id)}
                          onChange={() => toggleRow(row.original.sense_id)}
                          aria-label={`Select ${row.original.headword}`}
                          className="accent-neutral-900"
                        />
                      </td>
                      {row.getVisibleCells().map((cell) => (
                        <td
                          key={cell.id}
                          className="px-3 py-2 align-top"
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {hits.length === 0 && (
                    <tr>
                      <td
                        colSpan={COLUMNS.length + 1}
                        className="px-3 py-10 text-center text-sm text-neutral-500"
                      >
                        {results.isLoading
                          ? "Loading…"
                          : results.isError
                            ? "Results could not be loaded — see the message above."
                            : "No senses match the current search."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination footer */}
            <div className="flex items-center justify-between border-t border-neutral-100 px-4 py-3 text-sm">
              <span className="text-neutral-500">
                Page {state.page + 1} of {pageCount}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={state.page === 0}
                  onClick={() => updateState({ page: state.page - 1 }, false)}
                  className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-50 disabled:opacity-40"
                >
                  ← Prev
                </button>
                <button
                  type="button"
                  disabled={state.page + 1 >= pageCount}
                  onClick={() => updateState({ page: state.page + 1 }, false)}
                  className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-50 disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          </div>

          <details className="mt-4 overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-neutral-600 hover:text-neutral-900">
              Export / import
            </summary>
            <div className="border-t border-neutral-100 px-4 py-3">
              <ImportExportPanel filters={state.filters} />
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}

function renderCell(key: string, hit: SearchHit): ReactNode {
  switch (key) {
    case "headword":
      return (
        <span className="font-medium text-neutral-900">
          {hit.headword || <em>(blank)</em>}
        </span>
      );
    case "pos":
      return hit.part_of_speech ?? "—";
    case "cefr":
      return hit.cefr_level ? (
        <span className="inline-flex items-center rounded-md border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-xs font-medium text-neutral-700">
          {hit.cefr_level}
        </span>
      ) : (
        "—"
      );
    case "translations":
      return hit.translations.slice(0, 3).join(", ") || "—";
    case "definition":
      return (
        <span className="text-neutral-600">
          {hit.definition_preview?.slice(0, 120) ?? "—"}
        </span>
      );
    case "priority":
      return hit.priority_level ? (
        <span
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${
            hit.priority_level === "HIGH" || hit.priority_level === "VERY HIGH"
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-neutral-200 bg-neutral-50 text-neutral-700"
          }`}
        >
          {hit.priority_level}
        </span>
      ) : (
        "—"
      );
    case "frequency":
      return hit.frequency_rank?.toLocaleString() ?? "—";
    case "score":
      return hit.score.toFixed(3);
    default:
      return null;
  }
}
