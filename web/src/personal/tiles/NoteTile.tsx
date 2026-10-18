import { StickyNote } from "lucide-react";
import { useLayoutEffect, useRef } from "react";

import { usePersonalCopy } from "../copy";
import type { TileOf } from "../lib/tiles";
import { TileShell, type TileControls } from "./TileShell";

export function NoteTile({ tile, controls, onChange }: { tile: TileOf<"note">; controls: TileControls; onChange: (settings: { text: string }) => void }) {
  const p = usePersonalCopy();
  const area = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 72)}px`;
  }, [tile.settings.text]);

  return (
    <TileShell title={p.tileNote} icon={<StickyNote />} controls={controls}>
      <textarea
        ref={area}
        value={tile.settings.text}
        onChange={(e) => onChange({ text: e.target.value })}
        placeholder={p.notePlaceholder}
        aria-label={p.tileNote}
        className="w-full resize-none rounded-2xl bg-amber-50/85 px-4 py-3 text-[16px] leading-6 text-neutral-900 outline-none placeholder:text-neutral-400 focus:ring-2 focus:ring-amber-200"
      />
    </TileShell>
  );
}
