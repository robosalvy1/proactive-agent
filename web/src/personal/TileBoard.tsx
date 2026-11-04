import { CalendarClock, CalendarDays, Check, Globe2, MessageCircle, Plus, SlidersHorizontal, Sparkles, StickyNote } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { SessionInfo } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Glass } from "./Glass";
import { usePersonalCopy } from "./copy";
import { canAdd, TILE_KINDS, type LiveKind, type ListTicks, type Tile, type TileKind } from "./lib/tiles";
import { ListCard, StatsCard, TextCard } from "./tiles/AgentCards";
import { CalendarTile } from "./tiles/CalendarTile";
import { ClockTile } from "./tiles/ClockTile";
import { NoteTile } from "./tiles/NoteTile";
import { RecentTile } from "./tiles/RecentTile";
import { ScheduledTile } from "./tiles/ScheduledTile";
import { ShortcutsTile } from "./tiles/ShortcutsTile";
import type { TileControls } from "./tiles/TileShell";
import type { useTiles } from "./useTiles";

const ICONS: Record<LiveKind, ReactNode> = {
  calendar: <CalendarDays className="h-5 w-5" />,
  shortcuts: <Sparkles className="h-5 w-5" />,
  scheduled: <CalendarClock className="h-5 w-5" />,
  recent: <MessageCircle className="h-5 w-5" />,
  note: <StickyNote className="h-5 w-5" />,
  clock: <Globe2 className="h-5 w-5" />,
};
const CONFIGURABLE = new Set<TileKind>(["calendar", "shortcuts", "recent", "clock"]);

interface TileBoardProps {
  board: ReturnType<typeof useTiles>;
  profile: string;
  agentName: string;
  userName: string | null;
  recent: SessionInfo[] | null;
  calendarVersion: number;
  onAsk: (text: string) => void;
  onOpenSession: (id: string) => void;
  onNewChat: () => void;
}

export function TileBoard({ board, profile, agentName, userName, recent, calendarVersion, onAsk, onOpenSession, onNewChat }: TileBoardProps) {
  const p = usePersonalCopy();
  const [editing, setEditing] = useState(false);
  const [openSettings, setOpenSettings] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const tiles = board.tiles ?? [];
  const meta: Record<LiveKind, { title: string; hint: string }> = {
    calendar: { title: p.tileCalendar, hint: p.tileCalendarHint },
    shortcuts: { title: p.tileShortcuts, hint: p.tileShortcutsHint },
    scheduled: { title: p.tileScheduled, hint: p.tileScheduledHint },
    recent: { title: p.tileRecent, hint: p.tileRecentHint },
    note: { title: p.tileNote, hint: p.tileNoteHint },
    clock: { title: p.tileClock, hint: p.tileClockHint },
  };

  const controlsFor = (tile: Tile, index: number): TileControls => ({
    editing,
    settingsOpen: openSettings === tile.id,
    first: index === 0,
    last: index === tiles.length - 1,
    onToggleSettings: CONFIGURABLE.has(tile.kind) ? () => setOpenSettings((id) => (id === tile.id ? null : tile.id)) : undefined,
    onEdit: () => {
      setEditing(true);
      setOpenSettings(tile.id);
    },
    onMove: (delta) => board.move(tile.id, delta),
    onRemove: () => board.remove(tile.id),
    ...(tile.added_by === "agent" && {
      title: tile.title,
      byline: { agent: agentName, reason: tile.reason, source: tile.source, updatedAt: tile.updated_at },
    }),
  });

  const render = (tile: Tile, controls: TileControls) => {
    const onChange = (settings: object) => board.update(tile.id, settings);
    switch (tile.kind) {
      case "calendar":
        return <CalendarTile tile={tile} controls={controls} profile={profile} agentName={agentName} version={calendarVersion} onChange={onChange} />;
      case "shortcuts":
        return <ShortcutsTile tile={tile} controls={controls} userName={userName} onAsk={onAsk} onChange={onChange} />;
      case "scheduled":
        return <ScheduledTile profile={profile} controls={controls} />;
      case "recent":
        return <RecentTile tile={tile} controls={controls} sessions={recent} onOpen={onOpenSession} onNew={onNewChat} onChange={onChange} />;
      case "note":
        return <NoteTile tile={tile} controls={controls} onChange={onChange} />;
      case "clock":
        return <ClockTile tile={tile} controls={controls} onChange={onChange} />;
      case "list":
        return <ListCard tile={tile} controls={controls} onAsk={onAsk} onChange={(ticks: ListTicks) => board.update(tile.id, ticks)} />;
      case "stats":
        return <StatsCard tile={tile} controls={controls} />;
      case "text":
        return <TextCard tile={tile} controls={controls} />;
    }
  };

  const addable = TILE_KINDS.filter((kind) => canAdd(tiles, kind));
  const pill = "flex min-h-12 flex-1 items-center justify-center gap-2 rounded-full border border-white/50 px-4 text-[16px] backdrop-blur-2xl transition active:scale-[0.98]";

  return (
    <div className="flex flex-col gap-3 sm:gap-4">
      {tiles.map((tile, i) => (
        <div key={tile.id} className="personal-rise">{render(tile, controlsFor(tile, i))}</div>
      ))}
      {board.tiles === null && [0, 1].map((i) => <div key={i} className="h-36 animate-pulse rounded-[28px] bg-white/30" />)}
      {board.tiles !== null && !tiles.length && <p className="px-2 py-4 text-center text-[15px] text-white/90 drop-shadow-sm">{p.emptyBoard}</p>}

      {picking && (
        <Glass className="personal-rise grid grid-cols-1 gap-1 bg-white/75 p-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {addable.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => {
                board.add(kind);
                setPicking(false);
              }}
              className="flex items-start gap-3 rounded-2xl px-3 py-3 text-left transition hover:bg-white"
            >
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-neutral-800 shadow-sm">{ICONS[kind]}</span>
              <span className="min-w-0">
                <span className="block text-[15px] font-medium text-neutral-900">{meta[kind].title}</span>
                <span className="block text-[13px] leading-5 text-neutral-500">{meta[kind].hint}</span>
              </span>
            </button>
          ))}
        </Glass>
      )}

      <div className="flex gap-2">
        <button type="button" aria-expanded={picking} onClick={() => setPicking((v) => !v)} className={cn(pill, "bg-white/50 text-neutral-900 hover:bg-white/65")}>
          <Plus className={cn("h-5 w-5 transition", picking && "rotate-45")} />
          {p.addTile}
        </button>
        {tiles.length > 0 && (
          <button
            type="button"
            aria-pressed={editing}
            onClick={() => {
              setEditing((v) => !v);
              setOpenSettings(null);
            }}
            className={cn(pill, "flex-none", editing ? "bg-neutral-900 text-white" : "bg-white/35 text-neutral-800 hover:bg-white/55")}
          >
            {editing ? <Check className="h-5 w-5" /> : <SlidersHorizontal className="h-5 w-5" />}
            {editing ? p.done : p.customize}
          </button>
        )}
      </div>
    </div>
  );
}
