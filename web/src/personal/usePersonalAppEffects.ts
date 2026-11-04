import { useEffect, useRef } from "react";

import type { CalendarNoticeValue } from "./PersonalAppChrome";

/** Cmd/Ctrl+K opens search. */
export function useSearchShortcut(onOpen: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpen]);
}

/** The agent may have added or updated a card during a turn, so reload the board when one ends. */
export function useRefreshAfterTurn(busy: boolean, refresh: () => unknown) {
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) void refresh();
    wasBusy.current = busy;
  }, [busy, refresh]);
}

/** Hide the calendar notice after a while; errors stay longer. */
export function useNoticeTimeout(notice: CalendarNoticeValue, dismiss: () => void) {
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(dismiss, notice.tone === "ok" ? 3500 : 8000);
    return () => window.clearTimeout(timer);
  }, [notice, dismiss]);
}
