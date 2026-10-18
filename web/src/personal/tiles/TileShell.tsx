import { ChevronDown, ChevronUp, Settings2, X } from "lucide-react";
import type { ReactNode } from "react";

import { cn, timeAgo } from "@/lib/utils";
import { Glass } from "../Glass";
import { usePersonalCopy } from "../copy";

export interface TileControls {
  editing: boolean;
  settingsOpen: boolean;
  first: boolean;
  last: boolean;
  onToggleSettings?: () => void;
  /** Enter Customize with this tile's settings open, for empty states that need setup. */
  onEdit: () => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  /** A card the agent added: its own title, and a byline saying who, why, and from where. */
  title?: string;
  byline?: { agent: string; reason?: string; source?: string; updatedAt?: number };
}

interface TileShellProps {
  title: string;
  icon: ReactNode;
  controls: TileControls;
  action?: ReactNode;
  settings?: ReactNode;
  children: ReactNode;
}

const control =
  "flex h-9 w-9 items-center justify-center rounded-full text-neutral-600 transition hover:bg-white hover:text-neutral-900 disabled:opacity-30 disabled:hover:bg-transparent";

/** Frame shared by every tile; edit controls only appear in Customize mode, so touch and pointer behave the same. */
export function TileShell({ title, icon, controls, action, settings, children }: TileShellProps) {
  const p = usePersonalCopy();
  const shown = controls.title || title;
  const label = (template: string) => template.replace("{tile}", shown);
  const byline = controls.byline;
  return (
    <Glass className={cn("p-4 transition sm:p-5", controls.editing && "ring-2 ring-white/70")}>
      <div className="mb-3 flex min-h-9 items-center gap-2.5 text-[16px] text-neutral-800">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-neutral-700 [&>svg]:h-5 [&>svg]:w-5">{icon}</span>
        <span className="min-w-0 flex-1 truncate font-medium">{shown}</span>
        {controls.editing ? (
          <div className="-mr-1.5 flex items-center">
            <button type="button" className={control} disabled={controls.first} onClick={() => controls.onMove(-1)} aria-label={label(p.moveUp)}>
              <ChevronUp className="h-4 w-4" />
            </button>
            <button type="button" className={control} disabled={controls.last} onClick={() => controls.onMove(1)} aria-label={label(p.moveDown)}>
              <ChevronDown className="h-4 w-4" />
            </button>
            {controls.onToggleSettings && (
              <button
                type="button"
                className={cn(control, controls.settingsOpen && "bg-white text-neutral-900")}
                onClick={controls.onToggleSettings}
                aria-expanded={controls.settingsOpen}
                aria-label={label(p.tileSettings)}
              >
                <Settings2 className="h-4 w-4" />
              </button>
            )}
            <button type="button" className={cn(control, "hover:text-rose-600")} onClick={controls.onRemove} aria-label={label(p.removeTile)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          action
        )}
      </div>
      {controls.editing && controls.settingsOpen && settings && (
        <div className="personal-rise mb-3 rounded-2xl bg-white/70 p-3">{settings}</div>
      )}
      {children}
      {byline && (
        <div className="mt-3 border-t border-neutral-900/5 pt-2.5 text-[12px] leading-[18px] text-neutral-500">
          {byline.reason && <p className="text-[13px] leading-5 text-neutral-600">{byline.reason}</p>}
          <p>
            {[
              p.addedBy.replace("{agent}", byline.agent),
              byline.source && p.cardFrom.replace("{source}", byline.source),
              byline.updatedAt && p.cardUpdated.replace("{time}", timeAgo(byline.updatedAt)),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      )}
    </Glass>
  );
}

export const tileRow = "rounded-2xl bg-white/80 px-4 py-3";
export const tileChip =
  "inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-white/85 px-3 py-2 text-left text-[15px] text-neutral-900 transition hover:bg-white active:scale-[0.98]";
export const tileButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-neutral-900 px-4 text-[15px] font-medium text-white transition hover:bg-neutral-800 active:scale-[0.98] disabled:opacity-40";
export const tileInput =
  "w-full rounded-xl border border-white/80 bg-white/90 px-3 py-2.5 text-[16px] text-neutral-900 outline-none placeholder:text-neutral-400 focus:ring-2 focus:ring-sky-300";

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[14px] text-neutral-600">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex rounded-full bg-neutral-900/5 p-0.5">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            onClick={() => onChange(o.value)}
            className={cn("min-h-9 rounded-full px-3 text-[14px] transition", value === o.value ? "bg-white font-medium text-neutral-900 shadow-sm" : "text-neutral-600")}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
