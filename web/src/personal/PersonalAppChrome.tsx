import { CheckCircle2, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { ApprovalCard, ClarifyCard } from "./PromptCards";
import { usePersonalCopy } from "./copy";
import type { useCalendarReturn } from "./useCalendarReturn";
import type { usePersonalChat } from "./usePersonalChat";

type Chat = ReturnType<typeof usePersonalChat>;
export type CalendarNoticeValue = ReturnType<typeof useCalendarReturn>["notice"];

export function PromptSlot({ chat, agentName }: { chat: Chat; agentName: string }) {
  if (chat.approval) return <ApprovalCard prompt={chat.approval} agentName={agentName} onAnswer={chat.answerApproval} />;
  if (chat.clarify) return <ClarifyCard prompt={chat.clarify} agentName={agentName} onAnswer={chat.answerClarify} />;
  return null;
}

export function CalendarNotice({ notice }: { notice: NonNullable<CalendarNoticeValue> }) {
  const p = usePersonalCopy();
  const ok = notice.tone === "ok";
  return (
    <div
      role="status"
      className={cn(
        "personal-rise absolute left-1/2 top-[calc(max(1rem,env(safe-area-inset-top))+5.5rem)] z-30 flex max-w-[min(26rem,calc(100%-2rem))] -translate-x-1/2 items-center gap-2.5 rounded-full px-4 py-2.5 text-[14px] shadow-lg backdrop-blur-2xl sm:top-32",
        ok ? "bg-neutral-900 text-white" : "bg-white/90 text-rose-900",
      )}
    >
      {ok ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" /> : <TriangleAlert className="h-4 w-4 shrink-0" />}
      <span className="min-w-0">{ok ? p.calendarConnected : notice.text}</span>
    </div>
  );
}

export function ConnectionBanner({ chat, agentName }: { chat: Chat; agentName: string }) {
  const p = usePersonalCopy();
  const lost = chat.phase === "error";
  if (!agentName || !(lost || chat.error || !chat.ready)) return null;
  return (
    <div role="status" className="mb-3 flex items-center justify-between gap-3 rounded-full bg-white/60 px-5 py-2.5 text-[15px] text-neutral-700 backdrop-blur-xl">
      <span className="min-w-0 truncate">{lost ? p.connectionLost.replace("{agent}", agentName) : chat.error || p.connecting.replace("{agent}", agentName)}</span>
      {(lost || chat.error) && (
        <button type="button" onClick={() => window.location.reload()} className="shrink-0 font-medium text-neutral-900">
          {p.reload}
        </button>
      )}
    </div>
  );
}

export function TilesSheet({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const p = usePersonalCopy();
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40">
      <button type="button" aria-label={p.done} className="absolute inset-0 bg-slate-900/25 backdrop-blur-[2px]" onClick={onClose} />
      <div
        role="dialog"
        aria-modal
        aria-label={p.tiles}
        className="personal-sheet personal-safe-bottom absolute inset-x-0 bottom-0 mx-auto max-h-[88dvh] max-w-2xl overflow-y-auto overscroll-contain rounded-t-[32px] border-t border-white/60 bg-white/35 px-3 pt-2 shadow-[0_-20px_60px_-20px_rgba(20,45,90,0.45)] backdrop-blur-2xl sm:px-5"
      >
        <div className="sticky top-0 z-10 -mx-3 mb-2 flex items-center justify-between bg-gradient-to-b from-white/30 to-transparent px-4 pb-2 pt-1 sm:-mx-5 sm:px-6">
          <span aria-hidden className="absolute left-1/2 top-1 h-1.5 w-10 -translate-x-1/2 rounded-full bg-neutral-900/20" />
          <span className="pt-3 text-[18px] font-semibold text-neutral-900">{p.tiles}</span>
          <button ref={closeButton} type="button" onClick={onClose} aria-label={p.done} className="mt-2 flex h-10 w-10 items-center justify-center rounded-full bg-white/70 text-neutral-800">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
