import { ArrowUpRight, Check, ChartColumn, FileText, ListChecks, Minus, TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { usePersonalCopy } from "../copy";
import type { ListTicks, TileOf } from "../lib/tiles";
import { TileShell, type TileControls } from "./TileShell";

/*
 * Cards the agent fills with data it fetched itself. The agent supplies only words and numbers; the
 * look is fixed here so every card belongs to the home, whatever the agent put in it.
 */

interface ListCardProps {
  tile: TileOf<"list">;
  controls: TileControls;
  onAsk: (text: string) => void;
  onChange: (settings: ListTicks) => void;
}

export function ListCard({ tile, controls, onAsk, onChange }: ListCardProps) {
  const p = usePersonalCopy();
  const tickable = tile.settings.items.some((item) => typeof item.done === "boolean");
  return (
    <TileShell title={p.cardList} icon={<ListChecks />} controls={controls}>
      <ul className="flex flex-col gap-1.5">
        {tile.settings.items.map((item, i) => {
          const body = (
            <>
              <span className="min-w-0 flex-1">
                <span className={cn("block truncate text-[15px] text-neutral-900", item.done && "text-neutral-400 line-through")}>{item.text}</span>
                {item.detail && <span className="block truncate text-[13px] text-neutral-500">{item.detail}</span>}
              </span>
              {(item.url || item.prompt) && <ArrowUpRight className="h-4 w-4 shrink-0 text-neutral-400" />}
            </>
          );
          const row = "flex min-h-11 w-full items-center gap-3 rounded-2xl bg-white/80 px-3 py-2 text-left";
          return (
            <li key={i} className="flex items-center gap-2">
              {tickable && (
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={Boolean(item.done)}
                  aria-label={item.text}
                  onClick={() => onChange({ done: { [i]: !item.done } })}
                  className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition",
                    item.done ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 bg-white/80",
                  )}
                >
                  {item.done && <Check className="h-4 w-4" />}
                </button>
              )}
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer noopener" className={cn(row, "transition hover:bg-white")}>{body}</a>
              ) : item.prompt ? (
                <button type="button" onClick={() => onAsk(item.prompt!)} className={cn(row, "transition hover:bg-white active:scale-[0.99]")}>{body}</button>
              ) : (
                <div className={row}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </TileShell>
  );
}

const TRENDS = {
  up: <TrendingUp className="h-4 w-4 text-emerald-600" />,
  down: <TrendingDown className="h-4 w-4 text-rose-600" />,
  flat: <Minus className="h-4 w-4 text-neutral-400" />,
};

export function StatsCard({ tile, controls }: { tile: TileOf<"stats">; controls: TileControls }) {
  const p = usePersonalCopy();
  const { stats } = tile.settings;
  return (
    <TileShell title={p.cardStats} icon={<ChartColumn />} controls={controls}>
      <div className={cn("grid gap-2", stats.length === 1 ? "grid-cols-1" : stats.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
        {stats.map((stat, i) => (
          <div key={i} className="min-w-0 rounded-2xl bg-white/80 px-3 py-3">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-[24px] font-semibold leading-8 tabular-nums text-neutral-900">{stat.value}</span>
              {stat.trend && TRENDS[stat.trend]}
            </div>
            <div className="truncate text-[13px] text-neutral-500">{stat.label}</div>
          </div>
        ))}
      </div>
    </TileShell>
  );
}

export function TextCard({ tile, controls }: { tile: TileOf<"text">; controls: TileControls }) {
  const p = usePersonalCopy();
  return (
    <TileShell title={p.cardText} icon={<FileText />} controls={controls}>
      <p className="whitespace-pre-line rounded-2xl bg-white/80 px-4 py-3 text-[15px] leading-6 text-neutral-900">{tile.settings.text}</p>
    </TileShell>
  );
}
