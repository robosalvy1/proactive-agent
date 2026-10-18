import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJSON } from "@/lib/api";
import { moveTile, parseTiles, removeTile, sanitizeTiles, tilesStorageKey, updateTile, type Tile, type TileKind } from "./lib/tiles";

interface BoardResponse {
  rev: number;
  exists: boolean;
  tiles: unknown;
}

const POLL_MS = 30_000;
const SAVE_DELAY_MS = 400;
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

/**
 * The home's tile board for this profile, shared with the agent through the server. Changes apply
 * locally at once and are saved in the background; the board is re-read on focus, every 30s, and
 * when a chat turn finishes, so cards the agent adds show up without a reload.
 */
export function useTiles(profile: string) {
  const [state, setState] = useState<{ profile: string; tiles: Tile[] | null }>({ profile, tiles: null });
  const [error, setError] = useState(false);
  const pending = useRef(0);
  const settingsQueue = useRef(new Map<string, { settings: Record<string, unknown>; timer: number }>());
  const q = `?profile=${encodeURIComponent(profile)}`;

  if (state.profile !== profile) setState({ profile, tiles: null });

  const apply = useCallback((board: BoardResponse) => {
    setState({ profile, tiles: sanitizeTiles(board.tiles) });
    setError(false);
  }, [profile]);

  const refresh = useCallback(async () => {
    if (pending.current > 0 || settingsQueue.current.size > 0) return;
    try {
      const board = await fetchJSON<BoardResponse>(`/api/personal/board${q}`);
      if (pending.current > 0 || settingsQueue.current.size > 0) return;
      if (!board.exists) {
        // A board this browser kept before the home moved to the server comes along once.
        let legacy: string | null = null;
        try {
          legacy = localStorage.getItem(tilesStorageKey(profile));
        } catch {
          /* storage blocked */
        }
        if (legacy !== null) {
          apply(await fetchJSON<BoardResponse>(`/api/personal/board/import${q}`, json("POST", { tiles: parseTiles(legacy) })));
          try {
            localStorage.removeItem(tilesStorageKey(profile));
          } catch {
            /* storage blocked */
          }
          return;
        }
      }
      apply(board);
    } catch {
      setError(true);
    }
  }, [apply, profile, q]);

  const send = useCallback(
    async (path: string, init: RequestInit) => {
      pending.current += 1;
      try {
        const board = await fetchJSON<BoardResponse>(`/api/personal/board${path}${q}`, init);
        pending.current -= 1;
        if (pending.current === 0) apply(board);
      } catch {
        pending.current -= 1;
        setError(true);
        void refresh();
      }
    },
    [apply, q, refresh],
  );

  const local = (change: (tiles: Tile[]) => Tile[]) => setState((s) => (s.tiles ? { ...s, tiles: change(s.tiles) } : s));

  useEffect(() => {
    const first = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    const queue = settingsQueue.current;
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      for (const entry of queue.values()) window.clearTimeout(entry.timer);
      queue.clear();
    };
  }, [refresh]);

  const update = (id: string, settings: object) => {
    local((t) => updateTile(t, id, settings));
    // Typing in a note shouldn't be one request per key: merge and save once it settles.
    const queue = settingsQueue.current;
    const entry = queue.get(id);
    if (entry) window.clearTimeout(entry.timer);
    const merged = { ...entry?.settings, ...(settings as Record<string, unknown>) };
    if ("done" in merged && entry?.settings.done) merged.done = { ...(entry.settings.done as object), ...(settings as { done?: object }).done };
    queue.set(id, {
      settings: merged,
      timer: window.setTimeout(() => {
        queue.delete(id);
        void send(`/tiles/${encodeURIComponent(id)}`, json("PATCH", { settings: merged }));
      }, SAVE_DELAY_MS),
    });
  };

  return {
    tiles: state.profile === profile ? state.tiles : null,
    error,
    refresh,
    add: (kind: TileKind) => void send("/tiles", json("POST", { kind })),
    remove: (id: string) => {
      local((t) => removeTile(t, id));
      void send(`/tiles/${encodeURIComponent(id)}`, json("DELETE"));
    },
    move: (id: string, delta: -1 | 1) => {
      local((t) => moveTile(t, id, delta));
      void send(`/tiles/${encodeURIComponent(id)}/move`, json("POST", { delta }));
    },
    update,
  };
}
