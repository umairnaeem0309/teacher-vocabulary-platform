"use client";

import { useQuery } from "@tanstack/react-query";

import type { FilterFacets, SearchFilters } from "@/lib/search-types";
import { LEARNING_STATES } from "@/lib/search-types";
import { listStudents } from "@/lib/students-client";

interface FilterPanelProps {
  facets: FilterFacets | undefined;
  filters: SearchFilters;
  onChange: (filters: SearchFilters) => void;
}

/**
 * Layer-2 filter sidebar (sections 21/23) rendered as a persistent card.
 * All filters compose server-side (section 22) — this panel only edits the
 * filter object; the table page owns the request. Groups are collapsible
 * <details> so the rail stays dense, with hover/selection affordances and
 * a per-group count badge (HCI: state is visible at a glance).
 */
export function FilterPanel({ facets, filters, onChange }: FilterPanelProps) {
  // §30: the assignment viewpoint needs the teacher's student list.
  const students = useQuery({
    queryKey: ["students", "list", false],
    queryFn: () => listStudents(false),
    staleTime: 5 * 60_000,
  });

  function toggle(list: string[], value: string): string[] {
    return list.includes(value)
      ? list.filter((v) => v !== value)
      : [...list, value];
  }

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  const SUMMARY =
    "cursor-pointer rounded-md px-1 py-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500 transition-colors hover:bg-neutral-50 hover:text-neutral-800";

  function CheckGroup(
    title: string,
    values: string[] | undefined,
    selected: string[],
    key: keyof SearchFilters,
  ) {
    if (!values?.length) return null;
    return (
      <details open={selected.length > 0} className="border-b border-neutral-200 pb-2">
        <summary className={SUMMARY}>
          {title}
          {selected.length > 0 && ` (${selected.length})`}
        </summary>
        <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1">
          {values.map((v) => (
            <label
              key={v}
              className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-sm hover:bg-neutral-50"
            >
              <input
                type="checkbox"
                checked={selected.includes(v)}
                onChange={() => set(key, toggle(selected, v) as never)}
                className="accent-neutral-900"
              />
              {v}
            </label>
          ))}
        </div>
      </details>
    );
  }

  return (
    <aside className="w-60 shrink-0 space-y-3 self-start rounded-xl border border-neutral-200 bg-white p-3 text-sm shadow-sm">
      <div className="px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Filters
        </h2>
        <p className="mt-0.5 text-xs text-neutral-400">
          All filters combine server-side.
        </p>
      </div>

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

      <details className="border-b border-neutral-200 pb-2" open={filters.student_id !== null}>
        <summary className={SUMMARY}>Student assignment (§30)</summary>
        <select
          className="mt-2 w-full rounded-lg border border-neutral-300 bg-white px-2 py-1.5 focus:border-neutral-500 focus:outline-none"
          value={filters.student_id ?? ""}
          onChange={(e) =>
            set("student_id", e.target.value || null)
          }
        >
          <option value="">— any student —</option>
          {(students.data?.students ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.display_name}
            </option>
          ))}
        </select>
        <div className="mt-2 flex gap-3 text-sm">
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              name="assigned"
              checked={filters.assigned === null}
              onChange={() => set("assigned", null)}
              className="accent-neutral-900"
            />
            all
          </label>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              name="assigned"
              checked={filters.assigned === true}
              onChange={() => set("assigned", true)}
              disabled={filters.student_id === null}
              className="accent-neutral-900"
            />
            assigned
          </label>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              name="assigned"
              checked={filters.assigned === false}
              onChange={() => set("assigned", false)}
              disabled={filters.student_id === null}
              className="accent-neutral-900"
            />
            not assigned
          </label>
        </div>

        {/* §19: learning state, due, difficult and teacher-priority filters
            (all scoped to the selected student, matching the SQL). */}
        <div className="mt-3 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
            Learning state
          </p>
          <div className="flex flex-wrap gap-x-2 gap-y-1">
            {LEARNING_STATES.map((s) => (
              <label
                key={s}
                className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-sm hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  checked={filters.learning_states.includes(s)}
                  disabled={filters.student_id === null}
                  onChange={() =>
                    set("learning_states", toggle(filters.learning_states, s))
                  }
                  className="accent-neutral-900"
                />
                {s}
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={filters.due_only === true}
                disabled={filters.student_id === null}
                onChange={() => set("due_only", filters.due_only ? null : true)}
                className="accent-neutral-900"
              />
              due now
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={filters.difficult_only === true}
                disabled={filters.student_id === null}
                onChange={() =>
                  set("difficult_only", filters.difficult_only ? null : true)
                }
                className="accent-neutral-900"
              />
              difficult (lapsed)
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={filters.teacher_priority_only === true}
                disabled={filters.student_id === null}
                onChange={() =>
                  set("teacher_priority_only", filters.teacher_priority_only ? null : true)
                }
                className="accent-neutral-900"
              />
              teacher priority
            </label>
          </div>
        </div>
      </details>

      <details className="border-b border-neutral-200 pb-2">
        <summary className={SUMMARY}>Min priority</summary>
        <select
          className="mt-2 w-full rounded-lg border border-neutral-300 bg-white px-2 py-1.5 focus:border-neutral-500 focus:outline-none"
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
        <summary className={SUMMARY}>Category</summary>
        <select
          className="mt-2 w-full rounded-lg border border-neutral-300 bg-white px-2 py-1.5 focus:border-neutral-500 focus:outline-none"
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

      <details
        className="border-b border-neutral-200 pb-2"
        open={filters.translation_availability !== null}
      >
        <summary className={SUMMARY}>Translation (§42)</summary>
        <select
          className="mt-2 w-full rounded-lg border border-neutral-300 bg-white px-2 py-1.5 focus:border-neutral-500 focus:outline-none"
          value={filters.translation_availability ?? ""}
          onChange={(e) => set("translation_availability", e.target.value || null)}
        >
          <option value="">— any —</option>
          <option value="reliable">reliable translation</option>
          <option value="multiple">multiple translations</option>
          <option value="uncertain">uncertain translation</option>
          <option value="missing">missing translation</option>
        </select>
      </details>

      <details className="border-b border-neutral-200 pb-2">
        <summary className={SUMMARY}>Max frequency rank</summary>
        <input
          type="number"
          min={1}
          className="mt-2 w-full rounded-lg border border-neutral-300 px-2 py-1.5 focus:border-neutral-500 focus:outline-none"
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
        className="w-full rounded-lg border border-neutral-300 px-2 py-1.5 text-xs font-medium hover:bg-neutral-100"
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
            student_id: null,
            assigned: null,
            learning_states: [],
            due_only: null,
            difficult_only: null,
            teacher_priority_only: null,
            translation_availability: null,
          })
        }
      >
        Clear all filters
      </button>
    </aside>
  );
}
