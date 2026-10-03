/**
 * Configurable keyboard shortcuts (§35 / master §34: shortcuts "must be
 * configurable in settings"). Stored per-browser in localStorage so the
 * teacher can tune the review keys without a backend round-trip.
 *
 * Bindings are comma-separated alternatives (e.g. "1,h"); the space bar is
 * stored as the literal token "space". A store is exposed through
 * ``useShortcuts`` so every mounted screen stays in sync when the settings
 * page saves (localStorage + a same-tab notification event).
 */

import { useMemo, useSyncExternalStore } from "react";

export interface ShortcutConfig {
  /** Reveal the answer. */
  reveal: string;
  /** Rate the card HARD. */
  hard: string;
  /** Rate the card MEDIUM. */
  medium: string;
  /** Rate the card EASY. */
  easy: string;
}

export const SHORTCUT_STORAGE_KEY = "vocab.shortcuts.v1";
const CHANGE_EVENT = "vocab-shortcuts-changed";

export const DEFAULT_SHORTCUTS: ShortcutConfig = {
  reveal: "space",
  hard: "1,h",
  medium: "2,m",
  easy: "3,e",
};

/** Normalize a keyboard event to a comparable token ("a", "1", "space", …). */
export function eventToken(event: KeyboardEvent): string {
  if (event.code === "Space" || event.key === " ") return "space";
  return event.key.toLowerCase();
}

/** Does the event satisfy a comma-separated binding list? */
export function matchesBinding(event: KeyboardEvent, binding: string): boolean {
  const token = eventToken(event);
  return binding
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .includes(token);
}

/** Human-friendly label for one binding list ("1, h"). */
export function bindingLabel(binding: string): string {
  return binding
    .split(",")
    .map((part) => {
      const token = part.trim().toLowerCase();
      if (!token) return "";
      if (token === "space") return "Space";
      return token.length === 1 ? token.toUpperCase() : token;
    })
    .filter(Boolean)
    .join(", ");
}

/** Parse the stored JSON (empty/malformed → defaults). Pure and stable. */
export function parseShortcuts(raw: string | null): ShortcutConfig {
  if (!raw) return DEFAULT_SHORTCUTS;
  try {
    const parsed = JSON.parse(raw) as Partial<ShortcutConfig>;
    return {
      reveal: parsed.reveal?.trim() || DEFAULT_SHORTCUTS.reveal,
      hard: parsed.hard?.trim() || DEFAULT_SHORTCUTS.hard,
      medium: parsed.medium?.trim() || DEFAULT_SHORTCUTS.medium,
      easy: parsed.easy?.trim() || DEFAULT_SHORTCUTS.easy,
    };
  } catch {
    return DEFAULT_SHORTCUTS;
  }
}

function subscribe(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  window.addEventListener(CHANGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(CHANGE_EVENT, callback);
  };
}

function getSnapshot(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(SHORTCUT_STORAGE_KEY) ?? "";
}

function getServerSnapshot(): string {
  return "";
}

/**
 * Current shortcuts, reactive to saves in this tab and other tabs.
 *
 * The snapshot is the raw stored string (a value type) so React's identity
 * check is stable; parsing happens in a memo keyed on that string.
 */
export function useShortcuts(): ShortcutConfig {
  const raw = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return useMemo(() => parseShortcuts(raw), [raw]);
}

export function saveShortcuts(config: ShortcutConfig): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify(config));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function resetShortcuts(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SHORTCUT_STORAGE_KEY);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
