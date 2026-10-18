import { ArrowUpRight, Plus, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { usePersonalCopy } from "../copy";
import { greeting } from "../lib/sky";
import type { TileOf } from "../lib/tiles";
import { TileShell, tileChip, tileInput, type TileControls } from "./TileShell";

interface ShortcutsTileProps {
  tile: TileOf<"shortcuts">;
  controls: TileControls;
  userName: string | null;
  onAsk: (text: string) => void;
  onChange: (settings: Partial<TileOf<"shortcuts">["settings"]>) => void;
}

export function ShortcutsTile({ tile, controls, userName, onAsk, onChange }: ShortcutsTileProps) {
  const p = usePersonalCopy();
  const [draft, setDraft] = useState("");
  const suggested = [
    !userName && p.suggestName,
    new Date().getHours() < 14 ? p.suggestPlanDay : p.suggestRecapDay,
    p.suggestRemember,
  ].filter((s): s is string => Boolean(s));
  const items = tile.settings.items ?? suggested;
  const title = userName ? p.greetingTitle.replace("{greeting}", greeting(new Date())).replace("{user}", userName) : greeting(new Date());

  const add = () => {
    if (!draft.trim()) return;
    onChange({ items: [...items, draft.trim()] });
    setDraft("");
  };

  const settings = (
    <div className="flex flex-col gap-2">
      {items.map((item, i) => (
        <div key={`${item}-${i}`} className="flex items-center gap-2">
          <input
            className={tileInput}
            value={item}
            aria-label={p.shortcutPlaceholder}
            onChange={(e) => onChange({ items: items.map((v, j) => (j === i ? e.target.value : v)) })}
          />
          <button type="button" aria-label={`${p.removeTile.replace("{tile}", item)}`} onClick={() => onChange({ items: items.filter((_, j) => j !== i) })} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-neutral-500 hover:bg-white">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      {items.length < 6 && (
        <form className="flex items-center gap-2" onSubmit={(e) => (e.preventDefault(), add())}>
          <input className={tileInput} value={draft} placeholder={p.shortcutPlaceholder} onChange={(e) => setDraft(e.target.value)} />
          <button type="submit" disabled={!draft.trim()} aria-label={p.addShortcut} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-white disabled:opacity-30">
            <Plus className="h-4 w-4" />
          </button>
        </form>
      )}
      {tile.settings.items && (
        <button type="button" onClick={() => onChange({ items: null })} className="self-start text-[13px] text-neutral-500 hover:text-neutral-800">
          {p.resetShortcuts}
        </button>
      )}
    </div>
  );

  return (
    <TileShell title={title} icon={<Sparkles />} controls={controls} settings={settings}>
      <div className="flex flex-wrap gap-2">
        {items.map((item, i) => (
          <button key={`${item}-${i}`} type="button" className={tileChip} disabled={controls.editing} onClick={() => onAsk(item)}>
            {item}
            <ArrowUpRight className="h-4 w-4 shrink-0 text-neutral-400" />
          </button>
        ))}
      </div>
    </TileShell>
  );
}
