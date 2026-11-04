import { cn } from "@/lib/utils";
import { AgentAvatar } from "./AgentAvatar";
import { usePersonalCopy } from "./copy";
import type { AvatarChoice } from "./lib/avatar";

interface AgentBadgeProps {
  name: string;
  color: AvatarChoice;
  thinking: boolean;
  away: boolean;
  onHome: () => void;
}

/** The agent's presence at the top of the conversation: who you're talking to, and whether they're working. */
export function AgentBadge({ name, color, thinking, away, onHome }: AgentBadgeProps) {
  const p = usePersonalCopy();
  return (
    <button
      type="button"
      onClick={onHome}
      title={away ? p.backHome : name}
      aria-label={away ? `${name} · ${p.backHome}` : name}
      className={cn(
        "personal-glass group flex flex-col items-center gap-0.5 rounded-[22px] border border-white/70 bg-white/80 px-4 pb-1.5 pt-2 shadow-[0_8px_28px_-12px_rgba(20,45,90,0.35)] backdrop-blur-2xl transition",
        "hover:bg-white/90 active:scale-[0.97] sm:px-5 sm:pt-2.5",
      )}
    >
      <AgentAvatar name={name} color={color} thinking={thinking} className="h-9 w-9 sm:h-11 sm:w-11" />
      <span className="max-w-[9rem] truncate text-[13px] font-medium leading-tight text-neutral-800 sm:text-[14px]">{name}</span>
      <span className="sr-only" aria-live="polite">{thinking ? p.agentThinking.replace("{agent}", name) : ""}</span>
      {away && <span aria-hidden className="text-[11px] leading-none text-neutral-500">← {p.backHome}</span>}
    </button>
  );
}
