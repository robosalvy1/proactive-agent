/**
 * The tiles on the personal home. The board lives on the server per profile (hermes_cli/personal_board.py)
 * so the person and the agent see the same home. The person arranges and configures everything; the agent
 * may add cards from the same fixed catalog plus content cards (list, stats, text), which the home draws.
 */
export type LiveKind = "calendar" | "shortcuts" | "scheduled" | "recent" | "note" | "clock";
export type ContentKind = "list" | "stats" | "text";
export type TileKind = LiveKind | ContentKind;

export interface ListItem {
  text: string;
  detail?: string;
  url?: string;
  /** Tapping the item asks the agent this. */
  prompt?: string;
  done?: boolean;
}

export interface Stat {
  value: string;
  label: string;
  trend?: "up" | "down" | "flat";
}

export interface TileSettingsMap {
  calendar: { days: 1 | 3 | 7 };
  /** null keeps the localized suggestions until the person writes their own. */
  shortcuts: { items: string[] | null };
  scheduled: Record<string, never>;
  recent: { count: 3 | 5 };
  note: { text: string };
  clock: { zones: string[] };
  list: { items: ListItem[] };
  stats: { stats: Stat[] };
  text: { text: string };
}

/** Who put the tile there, and for the agent's cards, why and from where. */
export interface TileMeta {
  added_by: "user" | "agent";
  title?: string;
  reason?: string;
  source?: string;
  updated_at?: number;
}

export type Tile = { [K in TileKind]: { id: string; kind: K; settings: TileSettingsMap[K] } & TileMeta }[TileKind];
export type TileOf<K extends TileKind> = Extract<Tile, { kind: K }>;

/** What the person can add from the picker; content cards only come from the agent. */
export const TILE_KINDS: readonly LiveKind[] = ["calendar", "shortcuts", "scheduled", "recent", "note", "clock"];
const CONTENT_KINDS: readonly ContentKind[] = ["list", "stats", "text"];
export const isContentKind = (kind: TileKind): kind is ContentKind => (CONTENT_KINDS as readonly string[]).includes(kind);
/** Kinds that make sense more than once on a board. */
const REPEATABLE = new Set<TileKind>(["note", "clock", "list", "stats", "text"]);
const MAX_SHORTCUTS = 6;
const MAX_ZONES = 4;

/** Where older homes kept the board in this browser; read once to import it to the server. */
export const tilesStorageKey = (profile: string) => `hermes.personal.tiles.v2:${profile || "default"}`;

const DEFAULTS: { [K in TileKind]: () => TileSettingsMap[K] } = {
  calendar: () => ({ days: 3 }),
  shortcuts: () => ({ items: null }),
  scheduled: () => ({}),
  recent: () => ({ count: 3 }),
  note: () => ({ text: "" }),
  clock: () => ({ zones: [] }),
  list: () => ({ items: [] }),
  stats: () => ({ stats: [] }),
  text: () => ({ text: "" }),
};

const str = (value: unknown, limit: number) => (typeof value === "string" || typeof value === "number" ? String(value).slice(0, limit) : "");
const httpUrl = (value: unknown) => (typeof value === "string" && /^https?:\/\//i.test(value) ? value : undefined);

function listItem(raw: unknown): ListItem | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const text = str(r.text, 120);
  if (!text) return null;
  const item: ListItem = { text };
  if (str(r.detail, 80)) item.detail = str(r.detail, 80);
  const url = httpUrl(r.url);
  if (url) item.url = url;
  else if (str(r.prompt, 200)) item.prompt = str(r.prompt, 200);
  if (typeof r.done === "boolean") item.done = r.done;
  return item;
}

function stat(raw: unknown): Stat | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!str(r.value, 24) || !str(r.label, 40)) return null;
  const out: Stat = { value: str(r.value, 24), label: str(r.label, 40) };
  if (r.trend === "up" || r.trend === "down" || r.trend === "flat") out.trend = r.trend;
  return out;
}

const isZone = (zone: unknown): zone is string => {
  if (typeof zone !== "string" || !zone) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
};

/** Keep only well-formed settings so a hand-edited or older entry can't break a tile. */
const SANITIZE: { [K in TileKind]: (raw: Record<string, unknown>) => TileSettingsMap[K] } = {
  calendar: (raw) => ({ days: raw.days === 1 || raw.days === 7 ? raw.days : 3 }),
  shortcuts: (raw) => ({
    items: Array.isArray(raw.items)
      ? raw.items.filter((i): i is string => typeof i === "string" && Boolean(i.trim())).slice(0, MAX_SHORTCUTS)
      : null,
  }),
  scheduled: () => ({}),
  recent: (raw) => ({ count: raw.count === 5 ? 5 : 3 }),
  note: (raw) => ({ text: typeof raw.text === "string" ? raw.text.slice(0, 4000) : "" }),
  clock: (raw) => ({ zones: Array.isArray(raw.zones) ? [...new Set(raw.zones.filter(isZone))].slice(0, MAX_ZONES) : [] }),
  list: (raw) => ({ items: Array.isArray(raw.items) ? raw.items.map(listItem).filter((i): i is ListItem => i !== null).slice(0, 8) : [] }),
  stats: (raw) => ({ stats: Array.isArray(raw.stats) ? raw.stats.map(stat).filter((s): s is Stat => s !== null).slice(0, 3) : [] }),
  text: (raw) => ({ text: str(raw.text, 600) }),
};

function meta(entry: Record<string, unknown>): TileMeta {
  if (entry.added_by !== "agent") return { added_by: "user" };
  const out: TileMeta = { added_by: "agent" };
  if (str(entry.title, 40)) out.title = str(entry.title, 40);
  if (str(entry.reason, 160)) out.reason = str(entry.reason, 160);
  if (str(entry.source, 60)) out.source = str(entry.source, 60);
  if (typeof entry.updated_at === "number") out.updated_at = entry.updated_at;
  return out;
}

export const makeTile = <K extends TileKind>(kind: K, id: string): TileOf<K> =>
  ({ id, kind, settings: DEFAULTS[kind](), added_by: "user" }) as unknown as TileOf<K>;

export const defaultBoard = (): Tile[] => [
  makeTile("shortcuts", "shortcuts"),
  makeTile("calendar", "calendar"),
  makeTile("scheduled", "scheduled"),
];

const isKind = (value: unknown): value is TileKind =>
  typeof value === "string" && ([...TILE_KINDS, ...CONTENT_KINDS] as readonly string[]).includes(value);

export function parseTiles(raw: string | null): Tile[] {
  if (raw === null) return defaultBoard();
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return defaultBoard();
  }
  return sanitizeTiles(parsed);
}

/** Keep only well-formed tiles, whether from the server or an older browser board. */
export function sanitizeTiles(parsed: unknown): Tile[] {
  if (!Array.isArray(parsed)) return defaultBoard();
  const seen = new Set<string>();
  const tiles: Tile[] = [];
  for (const entry of parsed) {
    if (!entry || typeof entry !== "object") continue;
    const record = entry as Record<string, unknown>;
    const { id, kind, settings } = record;
    if (!isKind(kind) || typeof id !== "string" || seen.has(id)) continue;
    if (isContentKind(kind) && record.added_by !== "agent") continue;
    if (!REPEATABLE.has(kind) && tiles.some((t) => t.kind === kind)) continue;
    seen.add(id);
    const values = settings && typeof settings === "object" ? (settings as Record<string, unknown>) : {};
    tiles.push({ id, kind, settings: SANITIZE[kind](values), ...meta(record) } as Tile);
  }
  return tiles;
}

export const canAdd = (tiles: Tile[], kind: TileKind) =>
  !isContentKind(kind) && (REPEATABLE.has(kind) || !tiles.some((t) => t.kind === kind));

export const addTile = (tiles: Tile[], kind: TileKind, id: string): Tile[] =>
  canAdd(tiles, kind) ? [...tiles, makeTile(kind, id)] : tiles;

export const removeTile = (tiles: Tile[], id: string): Tile[] => tiles.filter((t) => t.id !== id);

export function moveTile(tiles: Tile[], id: string, delta: -1 | 1): Tile[] {
  const from = tiles.findIndex((t) => t.id === id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= tiles.length) return tiles;
  const next = tiles.slice();
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** The person can tick a list card's items; everything else on a content card is the agent's. */
export type ListTicks = { done: Record<string, boolean> };

export function updateTile<K extends TileKind>(tiles: Tile[], id: string, settings: Partial<TileSettingsMap[K]> | ListTicks): Tile[] {
  return tiles.map((t) => {
    if (t.id !== id) return t;
    if (t.kind === "list") {
      const done = (settings as Partial<ListTicks>).done;
      if (!done) return t;
      return { ...t, settings: { items: t.settings.items.map((item, i) => (typeof done[String(i)] === "boolean" ? { ...item, done: done[String(i)] } : item)) } };
    }
    if (isContentKind(t.kind)) return t;
    return { ...t, settings: SANITIZE[t.kind]({ ...t.settings, ...settings } as Record<string, unknown>) } as Tile;
  });
}
