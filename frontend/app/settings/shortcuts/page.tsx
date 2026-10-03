"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ROUTES } from "@/lib/routes";
import {
  bindingLabel,
  resetShortcuts,
  saveShortcuts,
  useShortcuts,
  type ShortcutConfig,
} from "@/lib/shortcuts";

/**
 * Keyboard shortcut settings (§35 / master §34: "shortcuts must be
 * configurable in settings"). Bindings persist in localStorage and are
 * consumed by the live review screen.
 */
const FIELDS: { key: keyof ShortcutConfig; label: string; help: string }[] = [
  { key: "reveal", label: "Reveal answer", help: "show the Polish/definition" },
  { key: "hard", label: "HARD", help: "rate Again" },
  { key: "medium", label: "MEDIUM", help: "rate Hard" },
  { key: "easy", label: "EASY", help: "rate Good" },
];

export default function ShortcutsSettingsPage() {
  const stored = useShortcuts();
  // Edited fields live in a draft overlay so the visible value is always
  // `draft[field] ?? stored[field]` — no setState-in-effect needed.
  const [draft, setDraft] = useState<Partial<ShortcutConfig>>({});
  const [saved, setSaved] = useState(false);

  const config: ShortcutConfig = { ...stored, ...draft };

  function update(key: keyof ShortcutConfig, value: string) {
    setSaved(false);
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    saveShortcuts(config);
    setDraft({});
    setSaved(true);
  }

  function onReset() {
    resetShortcuts();
    setDraft({});
    setSaved(true);
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-8">
      <Link href={ROUTES.settings} className="text-sm underline">
        ← Back to settings
      </Link>
      <h1 className="mt-3 text-xl font-semibold">Keyboard shortcuts</h1>
      <p className="mt-1 text-sm text-neutral-600">
        Configure the keys used on the review screen. Use one key or several
        alternatives separated by commas (for example{" "}
        <code className="rounded bg-neutral-100 px-1">1,h</code>). Write{" "}
        <code className="rounded bg-neutral-100 px-1">space</code> for the
        space bar.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        {FIELDS.map((field) => (
          <label key={field.key} className="block">
            <span className="text-sm font-medium">{field.label}</span>
            <span className="ml-2 text-xs text-neutral-500">{field.help}</span>
            <input
              value={config[field.key]}
              onChange={(e) => update(field.key, e.target.value)}
              className="mt-1 block w-64 rounded border border-neutral-300 px-2 py-1 font-mono"
            />
            <span className="mt-0.5 block text-xs text-neutral-400">
              currently: {bindingLabel(config[field.key]) || "—"}
            </span>
          </label>
        ))}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-800"
          >
            Save shortcuts
          </button>
          <button
            type="button"
            onClick={onReset}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100"
          >
            Reset to defaults
          </button>
          {saved && (
            <span className="text-sm text-green-700">Saved.</span>
          )}
        </div>
      </form>

      <p className="mt-6 text-xs text-neutral-500">
        Defaults: reveal <code>space</code>, HARD <code>1 / h</code>, MEDIUM{" "}
        <code>2 / m</code>, EASY <code>3 / e</code>.
      </p>
    </main>
  );
}
