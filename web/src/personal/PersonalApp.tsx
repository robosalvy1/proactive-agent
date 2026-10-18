import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { CheckCircle2, LayoutDashboard, LayoutGrid, MessageSquarePlus, Search, Settings, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { useProfileScope } from "@/contexts/useProfileScope";
import { fetchJSON } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentBadge } from "./AgentBadge";
import { Composer } from "./Composer";
import { Glass } from "./Glass";
import { MessageList } from "./MessageList";
import { ApprovalCard, ClarifyCard } from "./PromptCards";
import { SearchOverlay } from "./SearchOverlay";
import { SettingsPanel } from "./SettingsPanel";
import { Sky } from "./Sky";
import { TileBoard } from "./TileBoard";
import { usePersonalCopy } from "./copy";
import { isAvatarChoice, type AvatarChoice } from "./lib/avatar";
import { skyPhase, type SkyPhase } from "./lib/sky";
import { useCalendarReturn } from "./useCalendarReturn";
import { usePersonalChat, type ChatTarget } from "./usePersonalChat";
import { useRecentSessions } from "./useRecentSessions";
import { useTiles } from "./useTiles";
import "./personal.css";

interface Identity {
  agent_name: string;
  user_name: string | null;
  avatar_color?: string;
}

function useIdentity(profile: string): Identity | null {
  const [identity, setIdentity] = useState<Identity | null>(null);
  useEffect(() => {
    let live = true;
    fetchJSON<Identity>(`/api/personal/identity?profile=${encodeURIComponent(profile)}`)
      .then((next) => live && setIdentity(next))
      .catch(() => live && setIdentity({ agent_name: "Hermes", user_name: null }));
    return () => {
      live = false;
    };
  }, [profile]);
  return identity;
}

/** Dev builds accept ?sky=morning|day|evening|night to check each look without waiting for the clock. */
function previewPhase(): SkyPhase | null {
  if (!import.meta.env.DEV) return null;
  const value = new URLSearchParams(window.location.search).get("sky");
  return value === "morning" || value === "day" || value === "evening" || value === "night" ? value : null;
}

/** Re-render each minute so the sky and greeting follow the clock. */
function useMinute() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

const roundButton =
  "flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-white/50 bg-white/50 text-neutral-800 shadow-[0_6px_20px_-10px_rgba(20,45,90,0.4)] backdrop-blur-2xl transition hover:bg-white/70 active:scale-95 sm:h-12 sm:w-12";

function AccountMenu({ name, onNewChat, onSettings }: { name: string | null; onNewChat: () => void; onSettings: () => void }) {
  const p = usePersonalCopy();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const item = "flex min-h-11 w-full items-center gap-2.5 rounded-2xl px-3 text-left text-[15px] text-neutral-900 hover:bg-white";
  return (
    <div className="relative">
      <button
        type="button"
        aria-label={p.profileMenu}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br from-amber-200 via-rose-300 to-sky-400 text-[17px] font-semibold text-white shadow-md ring-2 ring-white/70 transition active:scale-95 sm:h-12 sm:w-12"
      >
        {(name?.trim()[0] ?? "·").toUpperCase()}
      </button>
      {open && (
        <>
          <button type="button" aria-hidden tabIndex={-1} className="fixed inset-0 z-20 cursor-default" onClick={() => setOpen(false)} />
          <Glass className="personal-rise absolute right-0 top-14 z-30 w-56 bg-white/85 p-2">
            <button type="button" className={item} onClick={() => (setOpen(false), onNewChat())}>
              <MessageSquarePlus className="h-4 w-4" />
              {p.newChat}
            </button>
            <button type="button" className={item} onClick={() => (setOpen(false), onSettings())}>
              <Settings className="h-4 w-4" />
              {p.settings}
            </button>
            <button type="button" className={item} onClick={() => navigate("/sessions")}>
              <LayoutDashboard className="h-4 w-4" />
              {p.openDashboard}
            </button>
          </Glass>
        </>
      )}
    </div>
  );
}

export default function PersonalApp() {
  const p = usePersonalCopy();
  const { profile: managed, currentProfile } = useProfileScope();
  const profile = managed || currentProfile || "default";
  const identity = useIdentity(profile);
  const agent = identity?.agent_name ?? "";
  const userName = identity?.user_name ?? null;
  const now = useMinute();
  const compact = useBelowBreakpoint(1024);
  const board = useTiles(profile);
  const calendar = useCalendarReturn(profile);
  const [target, setTarget] = useState<ChatTarget>({ kind: "home" });
  const [searching, setSearching] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pickedColor, setPickedColor] = useState<{ profile: string; color: AvatarChoice } | null>(null);
  const savedColor = identity?.avatar_color;
  const avatarColor: AvatarChoice =
    pickedColor?.profile === profile ? pickedColor.color : isAvatarChoice(savedColor) ? savedColor : "auto";
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const chat = usePersonalChat(profile, target);
  const [homeId, setHomeId] = useState<string | null>(null);
  const recent = useRecentSessions(profile, homeId);

  if (target.kind === "home" && chat.storedId && chat.storedId !== homeId) setHomeId(chat.storedId);

  useEffect(() => {
    if (agent) document.title = agent;
  }, [agent]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearching(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The agent may have added or updated a card during that turn.
  const busy = chat.transcript.busy;
  const { refresh: refreshBoard } = board;
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) void refreshBoard();
    wasBusy.current = busy;
  }, [busy, refreshBoard]);

  const { notice, dismiss } = calendar;
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(dismiss, notice.tone === "ok" ? 3500 : 8000);
    return () => window.clearTimeout(timer);
  }, [notice, dismiss]);

  const intro = useMemo(() => {
    if (!agent) return [];
    if (target.kind !== "home") return [p.introAsk];
    const hello = userName ? p.greetingKnown.replace("{user}", userName) : p.greetingUnknown;
    return [hello.replace("{agent}", agent), p.introMemory, p.introConnect, p.introAsk];
  }, [target.kind, userName, agent, p]);

  const open = useCallback((next: ChatTarget) => {
    setTarget(next);
    setSearching(false);
    setSheetOpen(false);
  }, []);
  const goHome = useCallback(() => open({ kind: "home" }), [open]);
  const newChat = useCallback(() => open({ kind: "new", nonce: Date.now() }), [open]);
  const openSession = useCallback((id: string) => open(id === homeId ? { kind: "home" } : { kind: "stored", id }), [homeId, open]);
  const ask = useCallback(
    (text: string) => {
      setSheetOpen(false);
      chat.send(text);
    },
    [chat],
  );

  const lost = chat.phase === "error";
  const phase = previewPhase() ?? skyPhase(now);
  const tileBoard = (
    <TileBoard
      board={board}
      profile={profile}
      agentName={agent}
      userName={userName}
      recent={recent}
      calendarVersion={calendar.version}
      onAsk={ask}
      onOpenSession={openSession}
      onNewChat={newChat}
    />
  );
  const promptCard = chat.approval ? (
    <ApprovalCard prompt={chat.approval} agentName={agent} onAnswer={chat.answerApproval} />
  ) : chat.clarify ? (
    <ClarifyCard prompt={chat.clarify} agentName={agent} onAnswer={chat.answerClarify} />
  ) : null;

  return (
    <div data-phase={phase} className="personal-root fixed inset-0 h-dvh overflow-hidden">
      <Sky phase={phase} mood="clear" />
      {!compact && <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-[clamp(360px,34vw,460px)] bg-white/10 backdrop-blur-[3px]" />}

      <div className={cn("relative grid h-full", compact ? "grid-cols-1" : "grid-cols-[clamp(360px,34vw,460px)_1fr]")}>
        {!compact && (
          <aside aria-label={p.tiles} className="min-h-0 overflow-y-auto p-6 [scrollbar-width:none]">
            {tileBoard}
          </aside>
        )}

        <main className="relative flex min-h-0 flex-col items-center">
          <header className="personal-safe-top absolute inset-x-0 top-0 z-20 grid grid-cols-[1fr_auto_1fr] items-start gap-2 px-3 sm:px-6 sm:pt-6">
            <div className="flex items-center">
              {compact && (
                <button type="button" onClick={() => setSheetOpen(true)} aria-label={p.tiles} className={roundButton}>
                  <LayoutGrid className="h-5 w-5" />
                </button>
              )}
            </div>
            {agent ? (
              <AgentBadge name={agent} color={avatarColor} thinking={chat.transcript.busy} away={target.kind !== "home"} onHome={goHome} />
            ) : (
              <div className="h-[68px] w-24 animate-pulse rounded-[22px] bg-white/40" />
            )}
            <div className="flex items-center justify-end gap-2 sm:gap-3">
              <button
                type="button"
                onClick={() => setSearching(true)}
                aria-label={p.search}
                className={cn(roundButton, "sm:w-auto sm:gap-2 sm:px-5 sm:text-[16px] sm:text-neutral-700")}
              >
                <Search className="h-[18px] w-[18px]" />
                <span className="hidden sm:inline">{p.search}</span>
              </button>
              <AccountMenu name={userName} onNewChat={newChat} onSettings={() => setSettingsOpen(true)} />
            </div>
          </header>

          {notice && (
            <div
              role="status"
              className={cn(
                "personal-rise absolute left-1/2 top-[calc(max(1rem,env(safe-area-inset-top))+5.5rem)] z-30 flex max-w-[min(26rem,calc(100%-2rem))] -translate-x-1/2 items-center gap-2.5 rounded-full px-4 py-2.5 text-[14px] shadow-lg backdrop-blur-2xl sm:top-32",
                notice.tone === "ok" ? "bg-neutral-900 text-white" : "bg-white/90 text-rose-900",
              )}
            >
              {notice.tone === "ok" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" /> : <TriangleAlert className="h-4 w-4 shrink-0" />}
              <span className="min-w-0">{notice.tone === "ok" ? p.calendarConnected : notice.text}</span>
            </div>
          )}

          <div className="personal-safe-bottom flex min-h-0 w-full max-w-[44rem] flex-1 flex-col px-3 sm:px-6 sm:pb-6">
            <MessageList
              key={target.kind === "stored" ? target.id : target.kind === "new" ? target.nonce : "home"}
              bubbles={chat.transcript.bubbles}
              intro={chat.ready ? intro : []}
              busy={chat.transcript.busy}
              footer={promptCard}
            />
            {(lost || chat.error || !chat.ready) && agent && (
              <div role="status" className="mb-3 flex items-center justify-between gap-3 rounded-full bg-white/60 px-5 py-2.5 text-[15px] text-neutral-700 backdrop-blur-xl">
                <span className="min-w-0 truncate">{lost ? p.connectionLost.replace("{agent}", agent) : chat.error || p.connecting.replace("{agent}", agent)}</span>
                {(lost || chat.error) && (
                  <button type="button" onClick={() => window.location.reload()} className="shrink-0 font-medium text-neutral-900">
                    {p.reload}
                  </button>
                )}
              </div>
            )}
            <Composer agentName={agent} disabled={!chat.ready} busy={chat.transcript.busy} onSend={chat.send} onStop={chat.interrupt} />
          </div>
        </main>
      </div>

      {compact && sheetOpen && (
        <div className="fixed inset-0 z-40">
          <button type="button" aria-label={p.done} className="absolute inset-0 bg-slate-900/25 backdrop-blur-[2px]" onClick={() => setSheetOpen(false)} />
          <div
            role="dialog"
            aria-modal
            aria-label={p.tiles}
            className="personal-sheet personal-safe-bottom absolute inset-x-0 bottom-0 mx-auto max-h-[88dvh] max-w-2xl overflow-y-auto overscroll-contain rounded-t-[32px] border-t border-white/60 bg-white/35 px-3 pt-2 shadow-[0_-20px_60px_-20px_rgba(20,45,90,0.45)] backdrop-blur-2xl sm:px-5"
          >
            <div className="sticky top-0 z-10 -mx-3 mb-2 flex items-center justify-between bg-gradient-to-b from-white/30 to-transparent px-4 pb-2 pt-1 sm:-mx-5 sm:px-6">
              <span aria-hidden className="absolute left-1/2 top-1 h-1.5 w-10 -translate-x-1/2 rounded-full bg-neutral-900/20" />
              <span className="pt-3 text-[18px] font-semibold text-neutral-900">{p.tiles}</span>
              <button type="button" onClick={() => setSheetOpen(false)} aria-label={p.done} className="mt-2 flex h-10 w-10 items-center justify-center rounded-full bg-white/70 text-neutral-800">
                <X className="h-5 w-5" />
              </button>
            </div>
            {tileBoard}
          </div>
        </div>
      )}

      {settingsOpen && agent && (
        <SettingsPanel
          profile={profile}
          agentName={agent}
          color={avatarColor}
          compact={compact}
          onColor={(color) => setPickedColor({ profile, color })}
          onClose={closeSettings}
        />
      )}
      {searching && <SearchOverlay profile={profile} onOpen={openSession} onClose={() => setSearching(false)} />}
    </div>
  );
}
