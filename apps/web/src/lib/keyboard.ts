"use client";

import { useEffect, useRef } from "react";

/** True while the user types into a field: single-key shortcuts must not fire. */
export function isTyping(event: KeyboardEvent): boolean {
  const el = event.target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "range"].includes(type);
  }
  return el.getAttribute("role") === "slider" ? false : false;
}

export interface Shortcut {
  /** e.g. "z", "shift+a", "?" */
  combo: string;
  handler: (event: KeyboardEvent) => void;
  enabled?: boolean;
}

function matches(event: KeyboardEvent, combo: string): boolean {
  const parts = combo.toLowerCase().split("+");
  const key = parts.pop();
  const shift = parts.includes("shift");
  const mod = parts.includes("mod");
  if (mod !== (event.metaKey || event.ctrlKey) || event.altKey) return false;
  if (key === "?") return event.key === "?";
  return event.shiftKey === shift && event.key.toLowerCase() === key;
}

/** Page-level single-key shortcuts, ignored while typing or when a dialog is open. */
export function useShortcuts(shortcuts: Shortcut[]) {
  const ref = useRef(shortcuts);
  useEffect(() => {
    ref.current = shortcuts;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isTyping(event)) return;
      if (document.querySelector("[role=dialog][data-state=open]")) return;
      for (const s of ref.current) {
        if (s.enabled !== false && matches(event, s.combo)) {
          event.preventDefault();
          s.handler(event);
          return;
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
