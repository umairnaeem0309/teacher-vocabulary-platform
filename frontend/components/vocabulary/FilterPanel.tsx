"use client";

import type { FilterFacets, SearchFilters } from "@/lib/search-types";

interface FilterPanelProps {
  facets: FilterFacets | undefined;
  filters: SearchFilters;
  onChange: (filters: SearchFilters) => void;
}

/**
 * Layer-2 filter sidebar (sections 21/23). All filters compose server-side
 * (section 22) — this panel only edits the filter object; the table page
 * owns the request. Groups are collapsible to keep the workbench dense.
 */
export function FilterPanel({ facets, filters, onChange }: FilterPanelProps) {
  function toggle(list: string[], value: string): string[] {
    return list.includes(value)
      ? list.filter((v) => v !== value)
      : [...list, value];
  }

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  function CheckGroup(
    title: string,
    values: string[] | undefined,
    selected: string[],
    key: keyof SearchFilters,
  ) {
    if (!values?.length) return null;
    return (
      <details open={selected.length > 0} className="border-b border-neutral-200 pb-2">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-neutral-500">
          {title}
          {selected.length > 0 && ` (${selected.length})`}
        </summary>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {values.map((v) => (
            <label key={v} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(v)}
                onChange={() => set(key, toggle(selected, v) as never)}
              />
              {v}
            </label>
          ))}
        </div>
      </details>
    );
  }

  return (
    <aside className="w-56 shrink-0 space-y-3 text-sm">
      {CheckGroup("CEFR", facets?.cefr, filters.cefr, "cefr")}
      {CheckGroup("Part of speech", facets?.part_of_speech, filters.pos, "pos")}
      {CheckGroup(
        "Priority",
        facets?.priority_levels,
        filters.priority_levels,
        "priority_levels",
      )}
      {CheckGroup(
        "Frequency band",
        facets?.frequency_bands,
        filters.frequency_bands,
        "frequency_bands",
      )}
      {CheckGroup("Flags", facets?.flags, filters.flags, "flags")}

      <details className="border-b border-neutral-200 pb-2">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Min priority
        </summary>
        <select
          className="mt-2 w-full rounded border border-neutral-300 px-2 py-1"
          value={filters.priority_min ?? ""}
          onChange={(e) => set("priority_min", e.target.value || null)}
        >
          <option value="">—</option>
          {(facets?.priority_levels ?? []).map((level) => (
            <option key={level} value={level}>
              {level}+
            </option>
          ))}
        </select>
      </details>

      <details className="border-b border-neutral-200 pb-2">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Category
        </summary>
        <select
          className="mt-2 w-full rounded border border-neutral-300 px-2 py-1"
          value={filters.category_key ?? ""}
          onChange={(e) => set("category_key", e.target.value || null)}
        >
          <option value="">—</option>
          {(facets?.categories ?? []).map((cat) => (
            <option key={cat.key} value={cat.key}>
              {cat.name}
            </option>
          ))}
        </select>
      </details>

      <details className="border-b border-neutral-200 pb-2">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Max frequency rank
        </summary>
        <input
          type="number"
          min={1}
          className="mt-2 w-full rounded border border-neutral-300 px-2 py-1"
          value={filters.max_frequency_rank ?? ""}
          onChange={(e) =>
            set(
              "max_frequency_rank",
              e.target.value ? Number.parseInt(e.target.value, 10) : null,
            )
          }
          placeholder="e.g. 3000"
        />
      </details>

      <button
        type="button"
        className="w-full rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
        onClick={() =>
          onChange({
            cefr: [],
            pos: [],
            priority_levels: [],
            priority_min: null,
            category_key: null,
            frequency_bands: [],
            max_frequency_rank: null,
            flags: [],
          })
        }
      >
        Clear all filters
      </button>
    </aside>
  );
}
