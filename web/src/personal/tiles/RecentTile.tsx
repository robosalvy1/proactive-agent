import { MessageCircle, Plus } from "lucide-react";

import type { SessionInfo } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { usePersonalCopy } from "../copy";
import type { TileOf } from "../lib/tiles";
import { Segmented, TileShell, type TileControls } from "./TileShell";

interface RecentTileProps {
  tile: TileOf<"recent">;
  controls: TileControls;
  sessions: SessionInfo[] | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onChange: (settings: { count: 3 | 5 }) => void;
}

export function RecentTile({ tile, controls, sessions, onOpen, onNew, onChange }: RecentTileProps) {
  const p = usePersonalCopy();
  const settings = (
    <Segmented label={p.recentCount} value={tile.settings.count} onChange={(count) => onChange({ count })} options={[{ value: 3, label: "3" }, { value: 5, label: "5" }]} />
  );
  const action = (
    <button type="button" onClick={onNew} aria-label={p.newChat} title={p.newChat} className="-mr-1.5 flex h-9 w-9 items-center justify-center rounded-full text-neutral-600 hover:bg-white hover:text-neutral-900">
      <Plus className="h-4 w-4" />
    </button>
  );
  return (
    <TileShell title={p.tileRecent} icon={<MessageCircle />} controls={controls} settings={settings} action={action}>
      {sessions?.length ? (
        <ul className="-mx-1 flex flex-col">
          {sessions.slice(0, tile.settings.count).map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => onOpen(s.id)} className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-3 text-left transition hover:bg-white/70">
                <span className="truncate text-[15px] text-neutral-900">{s.title || s.preview || p.untitled}</span>
                <span className="shrink-0 text-[13px] text-neutral-500">{timeAgo(s.last_active)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[15px] text-neutral-600">{sessions ? p.noRecent : "…"}</p>
      )}
    </TileShell>
  );
}
