import { Globe2, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { usePersonalCopy } from "../copy";
import type { TileOf } from "../lib/tiles";
import { TileShell, tileInput, tileRow, type TileControls } from "./TileShell";

const cityOf = (zone: string) => zone.split("/").pop()!.replace(/_/g, " ");

function offsetLabel(zone: string, now: Date): string {
  const local = new Date(now.toLocaleString("en-US"));
  const there = new Date(now.toLocaleString("en-US", { timeZone: zone }));
  const hours = Math.round((there.getTime() - local.getTime()) / 36e5 * 2) / 2;
  if (!hours) return "";
  return `${hours > 0 ? "+" : "−"}${Math.abs(hours)}h`;
}

const allZones = (): string[] => {
  const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  return supported ? supported("timeZone") : [];
};

export function ClockTile({ tile, controls, onChange }: { tile: TileOf<"clock">; controls: TileControls; onChange: (settings: { zones: string[] }) => void }) {
  const p = usePersonalCopy();
  const [now, setNow] = useState(() => new Date());
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);
  const zones = useMemo(() => allZones(), []);
  const listId = `zones-${tile.id}`;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const add = () => {
    const match = zones.find((z) => z.toLowerCase() === draft.trim().toLowerCase() || cityOf(z).toLowerCase() === draft.trim().toLowerCase());
    if (!match) return setInvalid(true);
    onChange({ zones: [...tile.settings.zones, match] });
    setDraft("");
    setInvalid(false);
  };

  const time = (zone?: string) => now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: zone });

  const settings = (
    <div className="flex flex-col gap-2">
      {tile.settings.zones.map((zone) => (
        <div key={zone} className="flex items-center justify-between gap-2 rounded-xl bg-white/90 py-1 pl-3 pr-1 text-[15px]">
          {cityOf(zone)}
          <button type="button" aria-label={p.removeTile.replace("{tile}", cityOf(zone))} onClick={() => onChange({ zones: tile.settings.zones.filter((z) => z !== zone) })} className="flex h-9 w-9 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      {tile.settings.zones.length < 4 && (
        <form className="flex items-center gap-2" onSubmit={(e) => (e.preventDefault(), add())}>
          <input className={tileInput} list={listId} value={draft} placeholder={p.clockPlaceholder} aria-label={p.clockAdd} aria-invalid={invalid} onChange={(e) => (setDraft(e.target.value), setInvalid(false))} />
          <datalist id={listId}>{zones.map((z) => <option key={z} value={z} />)}</datalist>
          <button type="submit" disabled={!draft.trim()} aria-label={p.clockAdd} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-white disabled:opacity-30">
            <Plus className="h-4 w-4" />
          </button>
        </form>
      )}
      {invalid && <p className="text-[13px] text-rose-700">{p.clockInvalid}</p>}
    </div>
  );

  return (
    <TileShell title={p.tileClock} icon={<Globe2 />} controls={controls} settings={settings}>
      <div className="grid grid-cols-2 gap-2">
        <div className={tileRow}>
          <div className="text-[13px] text-neutral-500">{p.clockLocal}</div>
          <div className="text-[24px] font-medium tracking-tight text-neutral-900">{time()}</div>
        </div>
        {tile.settings.zones.map((zone) => (
          <div key={zone} className={tileRow}>
            <div className="flex justify-between gap-2 text-[13px] text-neutral-500">
              <span className="truncate">{cityOf(zone)}</span>
              <span>{offsetLabel(zone, now)}</span>
            </div>
            <div className="text-[24px] font-medium tracking-tight text-neutral-900">{time(zone)}</div>
          </div>
        ))}
      </div>
      {!tile.settings.zones.length && !controls.editing && (
        <button type="button" onClick={controls.onEdit} className="mt-2 inline-flex min-h-10 items-center gap-1.5 text-[14px] text-neutral-600 hover:text-neutral-900">
          <Plus className="h-4 w-4" />
          {p.clockEmpty}
        </button>
      )}
    </TileShell>
  );
}
