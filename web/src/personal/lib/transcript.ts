import type { GatewayEvent, TranscriptMessage } from "@hermes/shared";

/** One rendered row of the personal chat. Purely presentational: the backend owns the transcript. */
export type Bubble =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string; streaming: boolean }
  | { id: string; kind: "activity"; toolId: string; label: string; done: boolean }
  | { id: string; kind: "notice"; text: string; tone: "error" | "info" };

export interface TranscriptState {
  bubbles: Bubble[];
  busy: boolean;
  nextId: number;
}

export const EMPTY_TRANSCRIPT: TranscriptState = { bubbles: [], busy: false, nextId: 0 };

export type TranscriptAction =
  | { type: "history"; messages: TranscriptMessage[]; running?: boolean }
  | { type: "sent"; text: string }
  | { type: "failed"; message: string }
  | { type: "event"; event: GatewayEvent };

const asText = (value: unknown): string => (typeof value === "string" ? value : "");

/** "web_search" → "Web search". Tool labels from the bridge are preferred when present. */
export function toolLabel(name: string, labels?: { text?: string }[] | null): string {
  const label = labels?.find((l) => l.text)?.text;
  if (label) return label;
  const words = name.replace(/[_.-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Working";
}

type NewBubble = Bubble extends infer B ? (B extends Bubble ? Omit<B, "id"> : never) : never;

function push(state: TranscriptState, bubble: NewBubble): TranscriptState {
  const id = `b${state.nextId}`;
  return { ...state, nextId: state.nextId + 1, bubbles: [...state.bubbles, { ...bubble, id } as Bubble] };
}

function streamingIndex(bubbles: Bubble[]): number {
  const last = bubbles.length - 1;
  const bubble = bubbles[last];
  return bubble?.kind === "assistant" && bubble.streaming ? last : -1;
}

function seal(state: TranscriptState): TranscriptState {
  const i = streamingIndex(state.bubbles);
  if (i < 0) return state;
  const bubbles = state.bubbles.slice();
  const bubble = bubbles[i] as Extract<Bubble, { kind: "assistant" }>;
  bubbles[i] = { ...bubble, streaming: false };
  return { ...state, bubbles };
}

/** Assistant text already shown since the latest user message, to avoid painting a reply twice. */
function shownSinceUser(bubbles: Bubble[], text: string): boolean {
  for (let i = bubbles.length - 1; i >= 0; i--) {
    const bubble = bubbles[i];
    if (bubble.kind === "user") return false;
    if (bubble.kind === "assistant" && bubble.text.trim() === text.trim()) return true;
  }
  return false;
}

function onDelta(state: TranscriptState, text: string | null): TranscriptState {
  if (text === null) return seal(state);
  if (!text) return state;
  const i = streamingIndex(state.bubbles);
  if (i < 0) return push({ ...state, busy: true }, { kind: "assistant", text, streaming: true });
  const bubbles = state.bubbles.slice();
  const bubble = bubbles[i] as Extract<Bubble, { kind: "assistant" }>;
  bubbles[i] = { ...bubble, text: bubble.text + text };
  return { ...state, bubbles, busy: true };
}

function onComplete(state: TranscriptState, payload: Record<string, unknown>): TranscriptState {
  const finalText = asText(payload.text);
  let next = seal({ ...state, busy: false });
  if (finalText.trim() && !shownSinceUser(next.bubbles, finalText)) {
    next = push(next, { kind: "assistant", text: finalText, streaming: false });
  }
  const error = asText(payload.error) || (payload.status === "error" ? asText(payload.failure_reason) : "");
  if (error) next = push(next, { kind: "notice", text: error, tone: "error" });
  return next;
}

function onToolComplete(state: TranscriptState, toolId: string): TranscriptState {
  const bubbles = state.bubbles.map((b) =>
    b.kind === "activity" && b.toolId === toolId ? { ...b, done: true } : b,
  );
  return { ...state, bubbles };
}

function onEvent(state: TranscriptState, event: GatewayEvent): TranscriptState {
  const payload = (event.payload ?? {}) as Record<string, unknown>;
  switch (event.type) {
    case "message.start":
      return { ...state, busy: true };
    case "message.delta":
      return onDelta(state, payload.text === null ? null : asText(payload.text));
    case "message.interim": {
      const sealed = seal(state);
      const text = asText(payload.text);
      if (payload.already_streamed || !text.trim()) return sealed;
      return push(sealed, { kind: "assistant", text, streaming: false });
    }
    case "tool.start":
      return push(seal(state), {
        kind: "activity",
        toolId: asText(payload.tool_id),
        label: toolLabel(asText(payload.name), payload.labels as { text?: string }[] | null),
        done: false,
      });
    case "tool.complete":
      return onToolComplete(state, asText(payload.tool_id));
    case "message.complete":
      return onComplete(state, payload);
    case "error":
      return push({ ...seal(state), busy: false }, { kind: "notice", text: asText(payload.message), tone: "error" });
    default:
      return state;
  }
}

function fromHistory(messages: TranscriptMessage[], running = false): TranscriptState {
  let state: TranscriptState = { ...EMPTY_TRANSCRIPT, busy: running };
  for (const message of messages) {
    if (message.display_kind === "hidden") continue;
    const text = asText(message.text ?? message.content);
    if (!text.trim()) continue;
    if (message.role === "user") state = push(state, { kind: "user", text });
    else if (message.role === "assistant") state = push(state, { kind: "assistant", text, streaming: false });
  }
  return state;
}

export function transcriptReducer(state: TranscriptState, action: TranscriptAction): TranscriptState {
  switch (action.type) {
    case "history":
      return fromHistory(action.messages, action.running);
    case "sent":
      return push({ ...seal(state), busy: true }, { kind: "user", text: action.text });
    case "failed":
      return push({ ...state, busy: false }, { kind: "notice", text: action.message, tone: "error" });
    case "event":
      return onEvent(state, action.event);
  }
}
