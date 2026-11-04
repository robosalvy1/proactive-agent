import { describe, expect, it } from "vitest";

import { addTile, canAdd, defaultBoard, makeTile, moveTile, parseTiles, removeTile, sanitizeTiles, tilesStorageKey, updateTile, type Tile } from "./tiles";

describe("personal tiles", () => {
  it("starts with a useful default board and keeps an emptied board empty", () => {
    expect(defaultBoard().map((t) => t.kind)).toEqual(["shortcuts", "calendar", "scheduled"]);
    expect(parseTiles(null)).toEqual(defaultBoard());
    expect(parseTiles("[]")).toEqual([]);
    expect(parseTiles("{oops")).toEqual(defaultBoard());
  });

  it("drops unknown kinds, duplicates and malformed settings from stored boards", () => {
    const stored = JSON.stringify([
      { id: "w", kind: "weather", settings: {} },
      { id: "c", kind: "calendar", settings: { days: 99 } },
      { id: "c2", kind: "calendar", settings: { days: 7 } },
      { id: "n1", kind: "note", settings: { text: 42 } },
      { id: "n2", kind: "note", settings: { text: "milk" } },
      { id: "n2", kind: "note", settings: { text: "dup id" } },
      { id: "z", kind: "clock", settings: { zones: ["Asia/Tokyo", "Mars/Olympus", "Asia/Tokyo"] } },
    ]);
    expect(parseTiles(stored)).toEqual([
      { id: "c", kind: "calendar", settings: { days: 3 }, added_by: "user" },
      { id: "n1", kind: "note", settings: { text: "" }, added_by: "user" },
      { id: "n2", kind: "note", settings: { text: "milk" }, added_by: "user" },
      { id: "z", kind: "clock", settings: { zones: ["Asia/Tokyo"] }, added_by: "user" },
    ]);
  });

  it("adds single-use tiles once but notes and clocks repeatedly", () => {
    const board = [makeTile("calendar", "c")];
    expect(canAdd(board, "calendar")).toBe(false);
    expect(addTile(board, "calendar", "c2")).toBe(board);
    expect(addTile(addTile(board, "note", "n1"), "note", "n2").map((t) => t.id)).toEqual(["c", "n1", "n2"]);
  });

  it("reorders, edits and removes by id", () => {
    const board = [makeTile("shortcuts", "s"), makeTile("calendar", "c"), makeTile("recent", "r")];
    expect(moveTile(board, "r", -1).map((t) => t.id)).toEqual(["s", "r", "c"]);
    expect(moveTile(board, "s", -1)).toBe(board);
    const edited = updateTile<"shortcuts">(board, "s", { items: ["  ", "Plan my week", "Draft a reply"] });
    expect(edited[0].settings).toEqual({ items: ["Plan my week", "Draft a reply"] });
    expect(removeTile(edited, "c").map((t) => t.id)).toEqual(["s", "r"]);
  });

  it("scopes boards per profile", () => {
    expect(tilesStorageKey("work")).not.toBe(tilesStorageKey("default"));
    expect(tilesStorageKey("")).toBe(tilesStorageKey("default"));
  });

  it("keeps the agent's cards with their byline but never lets the person add content kinds", () => {
    const tiles = sanitizeTiles([
      { id: "l", kind: "list", added_by: "agent", title: "Open PRs", reason: "Review queue", source: "GitHub", updated_at: 1,
        settings: { items: [{ text: "Fix login", url: "javascript:alert(1)", prompt: "Summarize it" }, { nope: 1 }] } },
      { id: "forged", kind: "text", added_by: "user", settings: { text: "not from the agent" } },
      { id: "c", kind: "calendar", added_by: "agent", title: "Today", settings: { days: 1 } },
    ]);
    expect(tiles).toEqual([
      { id: "l", kind: "list", added_by: "agent", title: "Open PRs", reason: "Review queue", source: "GitHub", updated_at: 1,
        settings: { items: [{ text: "Fix login", prompt: "Summarize it" }] } },
      { id: "c", kind: "calendar", added_by: "agent", title: "Today", settings: { days: 1 } },
    ]);
    expect(canAdd([], "list")).toBe(false);
    expect(canAdd(tiles, "calendar")).toBe(false);
  });

  it("lets the person tick list items without rewriting the agent's content", () => {
    const list = sanitizeTiles([{ id: "l", kind: "list", added_by: "agent", settings: { items: [{ text: "Milk" }, { text: "Eggs", done: false }] } }]);
    const ticked = updateTile(list, "l", { done: { "1": true } });
    expect((ticked[0] as Extract<Tile, { kind: "list" }>).settings.items).toEqual([{ text: "Milk" }, { text: "Eggs", done: true }]);
    const text = sanitizeTiles([{ id: "t", kind: "text", added_by: "agent", settings: { text: "Hi" } }]);
    expect(updateTile(text, "t", { text: "rewritten" } as never)).toEqual(text);
  });
});
