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
import { SessionBar } from "@/components/SessionBar";
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
  { key: "pos", label: "POS", sort: null },
  { key: "cefr", label: "CEFR", sort: null },
  { key: "translations", label: "Polish", sort: null },
  { key: "definition", label: "Definition", sort: null },
  { key: "priority", label: "Priority", sort: "priority" as SortKey },
  { key: "frequency", label: "Freq.", sort: "frequency" as SortKey },
  { key: "score", label: "Score", sort: "relevance" as SortKey },
] as const;

/**
 * Dense vocabulary workbench (sections 23/39): spreadsheet-style table
 * over the Phase 14 search engine. Query/filters/sort/pagination live in
 * the URL (shareable views); selection is client-side for future bulk
 * actions (sets/assign arrive in later phases).
 */
export default function VocabularyPageWrapper() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-[110rem] px-4 py-8">Loading…</main>}>
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
    <main className="mx-auto max-w-[110rem] px-4 py-2">
      <SessionBar />
      <h1 className="px-1 text-xl font-semibold">Vocabulary</h1>
      <div className="mt-2 flex gap-4">
        <FilterPanel
          facets={facets.data}
          filters={state.filters}
          onChange={(filters) => updateState({ filters })}
        />

        <section className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={state.query}
              onChange={(e) => updateState({ query: e.target.value })}
              placeholder="Search headwords, translations, definitions…"
              className="w-96 rounded border border-neutral-300 px-3 py-1.5"
            />
            <select
              value={state.mode}
              onChange={(e) => updateState({ mode: e.target.value as SearchMode })}
              className="rounded border border-neutral-300 px-2 py-1.5"
            >
              <option value="lexical">Lexical</option>
              <option value="semantic">Semantic</option>
              <option value="hybrid">Hybrid</option>
            </select>
            <select
              value={state.sort}
              onChange={(e) => updateState({ sort: e.target.value as SortKey })}
              className="rounded border border-neutral-300 px-2 py-1.5"
            >
              <option value="relevance">Sort: relevance</option>
              <option value="headword">Sort: headword</option>
              <option value="priority">Sort: priority</option>
              <option value="frequency">Sort: frequency</option>
            </select>
            <span className="text-sm text-neutral-500">
              {results.isFetching ? "…" : `${total.toLocaleString()} senses`}
            </span>
            {selected.size > 0 && (
              <span className="flex items-center gap-2 rounded bg-neutral-900 px-2 py-1 text-xs text-white">
                {selected.size} selected
                <select
                  value={assignTo}
                  onChange={(e) => setAssignTo(e.target.value)}
                  className="rounded bg-neutral-800 px-1 py-0.5 text-white"
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
                  className="rounded bg-white px-2 py-0.5 text-xs font-medium text-neutral-900 disabled:opacity-40"
                >
                  {assign.isPending ? "Assigning…" : "Assign"}
                </button>
                <select
                  value={setMode}
                  onChange={(e) => setSetMode(e.target.value)}
                  className="rounded bg-neutral-800 px-1 py-0.5 text-white"
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
                    className="w-32 rounded bg-neutral-800 px-1 py-0.5 text-white placeholder-neutral-400"
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
                  className="rounded bg-white px-2 py-0.5 text-xs font-medium text-neutral-900 disabled:opacity-40"
                >
                  {addToSet.isPending ? "Adding…" : "Add"}
                </button>
              </span>
            )}
            {assignNote && (
              <span className="text-xs text-neutral-600">{assignNote}</span>
            )}
          </div>

          <table className="mt-2 w-full border-collapse text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-neutral-300 text-left">
                  <th className="w-8 py-1">
                    <input
                      type="checkbox"
                      checked={hits.length > 0 && selected.size === hits.length}
                      onChange={toggleAll}
                      aria-label="Select page"
                    />
                  </th>
                  {hg.headers.map((header) => {
                    const col = COLUMNS.find((c) => c.key === header.column.id);
                    const sortable = col?.sort !== null && col?.sort !== undefined;
                    return (
                      <th
                        key={header.id}
                        className={`py-1 pr-3 ${sortable ? "cursor-pointer select-none hover:text-neutral-900" : ""}`}
                        onClick={
                          sortable
                            ? () => updateState({ sort: col.sort as SortKey })
                            : undefined
                        }
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
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
                  className={`cursor-pointer border-b border-neutral-100 hover:bg-neutral-50 ${
                    selected.has(row.original.sense_id) ? "bg-neutral-100" : ""
                  }`}
                  onClick={() => router.push(ROUTES.vocabularySense(row.original.sense_id))}
                >
                  <td className="py-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(row.original.sense_id)}
                      onChange={() => toggleRow(row.original.sense_id)}
                      aria-label={`Select ${row.original.headword}`}
                    />
                  </td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="py-1 pr-3 align-top">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
              {hits.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS.length + 1} className="py-8 text-center text-neutral-500">
                    {results.isLoading ? "Loading…" : "No senses match the current search."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="mt-2 flex items-center justify-between text-sm">
            <span className="text-neutral-500">
              Page {state.page + 1} of {pageCount}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={state.page === 0}
                onClick={() => updateState({ page: state.page - 1 }, false)}
                className="rounded border border-neutral-300 px-2 py-1 disabled:opacity-40"
              >
                ← Prev
              </button>
              <button
                type="button"
                disabled={state.page + 1 >= pageCount}
                onClick={() => updateState({ page: state.page + 1 }, false)}
                className="rounded border border-neutral-300 px-2 py-1 disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          </div>

          <details className="mt-4">
            <summary className="cursor-pointer text-sm text-neutral-600 hover:text-neutral-900">
              Export / import
            </summary>
            <div className="mt-2">
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
      return <span className="font-medium">{hit.headword || <em>(blank)</em>}</span>;
    case "pos":
      return hit.part_of_speech ?? "—";
    case "cefr":
      return hit.cefr_level ?? "—";
    case "translations":
      return hit.translations.slice(0, 3).join(", ") || "—";
    case "definition":
      return (
        <span className="text-neutral-600">
          {hit.definition_preview?.slice(0, 120) ?? "—"}
        </span>
      );
    case "priority":
      return hit.priority_level ?? "—";
    case "frequency":
      return hit.frequency_rank?.toLocaleString() ?? "—";
    case "score":
      return hit.score.toFixed(3);
    default:
      return null;
  }
}
