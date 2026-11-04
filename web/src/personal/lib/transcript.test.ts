import { describe, expect, it } from "vitest";
import type { GatewayEvent } from "@hermes/shared";

import { EMPTY_TRANSCRIPT, toolLabel, transcriptReducer, type TranscriptAction, type TranscriptState } from "./transcript";

const ev = (type: string, payload: Record<string, unknown> = {}): TranscriptAction => ({
  type: "event",
  event: { type, payload, session_id: "s1" } as unknown as GatewayEvent,
});

const run = (...actions: TranscriptAction[]): TranscriptState => actions.reduce(transcriptReducer, EMPTY_TRANSCRIPT);
const view = (state: TranscriptState) => state.bubbles.map((bubble) => Object.fromEntries(Object.entries(bubble).filter(([key]) => key !== "id")));

describe("personal transcript", () => {
  it("streams one reply and seals it when the turn completes", () => {
    const state = run(
      { type: "sent", text: "screenshot on mac?" },
      ev("message.start"),
      ev("message.delta", { text: "Press " }),
      ev("message.delta", { text: "Shift-Command-3." }),
      ev("message.complete", { text: "Press Shift-Command-3.", status: "complete" }),
    );
    expect(view(state)).toEqual([
      { kind: "user", text: "screenshot on mac?" },
      { kind: "assistant", text: "Press Shift-Command-3.", streaming: false },
    ]);
    expect(state.busy).toBe(false);
  });

  it("shows tool activity between reply segments and marks it done", () => {
    const state = run(
      { type: "sent", text: "weather?" },
      ev("message.delta", { text: "Checking." }),
      ev("message.delta", { text: null }),
      ev("tool.start", { tool_id: "t1", name: "web_search" }),
      ev("tool.complete", { tool_id: "t1", name: "web_search" }),
      ev("message.delta", { text: "Sunny." }),
      ev("message.complete", { text: "Sunny." }),
    );
    expect(view(state)).toEqual([
      { kind: "user", text: "weather?" },
      { kind: "assistant", text: "Checking.", streaming: false },
      { kind: "activity", toolId: "t1", label: "Web search", done: true },
      { kind: "assistant", text: "Sunny.", streaming: false },
    ]);
  });

  it("paints a non-streamed reply from completion, and surfaces errors", () => {
    expect(view(run({ type: "sent", text: "hi" }, ev("message.complete", { text: "Hello!" })))).toEqual([
      { kind: "user", text: "hi" },
      { kind: "assistant", text: "Hello!", streaming: false },
    ]);
    const failed = run({ type: "sent", text: "hi" }, ev("message.complete", { status: "error", error: "Provider rate limit" }));
    expect(view(failed).at(-1)).toEqual({ kind: "notice", text: "Provider rate limit", tone: "error" });
    expect(failed.busy).toBe(false);
  });

  it("does not repeat interim commentary that already streamed", () => {
    const state = run(ev("message.delta", { text: "Looking" }), ev("message.interim", { text: "Looking", already_streamed: true }));
    expect(view(state)).toEqual([{ kind: "assistant", text: "Looking", streaming: false }]);
  });

  it("rebuilds visible history, skipping hidden and tool rows", () => {
    const state = run({
      type: "history",
      running: true,
      messages: [
        { role: "user", text: "remember my sister's birthday" },
        { role: "tool", text: "{}", name: "memory" },
        { role: "user", text: "internal", display_kind: "hidden" },
        { role: "assistant", text: "Saved: March 4." },
      ],
    });
    expect(view(state)).toEqual([
      { kind: "user", text: "remember my sister's birthday" },
      { kind: "assistant", text: "Saved: March 4.", streaming: false },
    ]);
    expect(state.busy).toBe(true);
  });

  it("prefers bridge labels for tools", () => {
    expect(toolLabel("tool_call", [{ text: "Gmail · search" }])).toBe("Gmail · search");
    expect(toolLabel("browser.navigate")).toBe("Browser navigate");
  });
});
