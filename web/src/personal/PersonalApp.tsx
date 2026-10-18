import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { LayoutDashboard, LayoutGrid, MessageSquarePlus, Search, Settings } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { useProfileScope } from "@/contexts/useProfileScope";
import { fetchJSON } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentBadge } from "./AgentBadge";
import { Composer } from "./Composer";
import { Glass } from "./Glass";
import { MessageList } from "./MessageList";
import { CalendarNotice, ConnectionBanner, PromptSlot, TilesSheet } from "./PersonalAppChrome";
import { SearchOverlay } from "./SearchOverlay";
import { SettingsPanel } from "./SettingsPanel";
import { Sky } from "./Sky";
import { TileBoard } from "./TileBoard";
import { usePersonalCopy } from "./copy";
import { isAvatarChoice, type AvatarChoice } from "./lib/avatar";
import { skyPhase, type SkyPhase } from "./lib/sky";
import { useCalendarReturn } from "./useCalendarReturn";
import { useNoticeTimeout, useRefreshAfterTurn, useSearchShortcut } from "./usePersonalAppEffects";
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

interface HomeHeaderProps {
  agent: string;
  userName: string | null;
  color: AvatarChoice;
  compact: boolean;
  thinking: boolean;
  away: boolean;
  onHome: () => void;
  onTiles: () => void;
  onSearch: () => void;
  onNewChat: () => void;
  onSettings: () => void;
}

function HomeHeader({ agent, userName, color, compact, thinking, away, onHome, onTiles, onSearch, onNewChat, onSettings }: HomeHeaderProps) {
  const p = usePersonalCopy();
  return (
    <header className="personal-safe-top absolute inset-x-0 top-0 z-20 grid grid-cols-[1fr_auto_1fr] items-start gap-2 px-3 sm:px-6 sm:pt-6">
      <div className="flex items-center">
        {compact && (
          <button type="button" onClick={onTiles} aria-label={p.tiles} className={roundButton}>
            <LayoutGrid className="h-5 w-5" />
          </button>
        )}
      </div>
      {agent ? (
        <AgentBadge name={agent} color={color} thinking={thinking} away={away} onHome={onHome} />
      ) : (
        <div className="h-[68px] w-24 animate-pulse rounded-[22px] bg-white/40" />
      )}
      <div className="flex items-center justify-end gap-2 sm:gap-3">
        <button
          type="button"
          onClick={onSearch}
          aria-label={p.search}
          className={cn(roundButton, "sm:w-auto sm:gap-2 sm:px-5 sm:text-[16px] sm:text-neutral-700")}
        >
          <Search className="h-[18px] w-[18px]" />
          <span className="hidden sm:inline">{p.search}</span>
        </button>
        <AccountMenu name={userName} onNewChat={onNewChat} onSettings={onSettings} />
      </div>
    </header>
  );
}

/** The avatar color the person just picked, else the saved one. */
function useAvatarColor(profile: string, saved: string | undefined) {
  const [picked, setPicked] = useState<{ profile: string; color: AvatarChoice } | null>(null);
  const color: AvatarChoice = picked?.profile === profile ? picked.color : isAvatarChoice(saved) ? saved : "auto";
  const pick = useCallback((next: AvatarChoice) => setPicked({ profile, color: next }), [profile]);
  return [color, pick] as const;
}

function targetKey(target: ChatTarget): string | number {
  if (target.kind === "stored") return target.id;
  if (target.kind === "new") return target.nonce;
  return "home";
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
  const [avatarColor, pickAvatarColor] = useAvatarColor(profile, identity?.avatar_color);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const chat = usePersonalChat(profile, target);
  const [homeId, setHomeId] = useState<string | null>(null);
  const recent = useRecentSessions(profile, homeId);

  if (target.kind === "home" && chat.storedId && chat.storedId !== homeId) setHomeId(chat.storedId);

  useEffect(() => {
    if (agent) document.title = agent;
  }, [agent]);

  const openSearch = useCallback(() => setSearching(true), []);
  useSearchShortcut(openSearch);
  useRefreshAfterTurn(chat.transcript.busy, board.refresh);
  const { notice, dismiss } = calendar;
  useNoticeTimeout(notice, dismiss);

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
          <HomeHeader
            agent={agent}
            userName={userName}
            color={avatarColor}
            compact={compact}
            thinking={chat.transcript.busy}
            away={target.kind !== "home"}
            onHome={goHome}
            onTiles={() => setSheetOpen(true)}
            onSearch={openSearch}
            onNewChat={newChat}
            onSettings={() => setSettingsOpen(true)}
          />

          {notice && <CalendarNotice notice={notice} />}

          <div className="personal-safe-bottom flex min-h-0 w-full max-w-[44rem] flex-1 flex-col px-3 sm:px-6 sm:pb-6">
            <MessageList
              key={targetKey(target)}
              bubbles={chat.transcript.bubbles}
              intro={chat.ready ? intro : []}
              busy={chat.transcript.busy}
              footer={<PromptSlot chat={chat} agentName={agent} />}
            />
            <ConnectionBanner chat={chat} agentName={agent} />
            <Composer agentName={agent} disabled={!chat.ready} busy={chat.transcript.busy} onSend={chat.send} onStop={chat.interrupt} />
          </div>
        </main>
      </div>

      {compact && sheetOpen && <TilesSheet onClose={() => setSheetOpen(false)}>{tileBoard}</TilesSheet>}

      {settingsOpen && agent && (
        <SettingsPanel
          profile={profile}
          agentName={agent}
          color={avatarColor}
          compact={compact}
          onColor={pickAvatarColor}
          onClose={closeSettings}
        />
      )}
      {searching && <SearchOverlay profile={profile} onOpen={openSession} onClose={() => setSearching(false)} />}
    </div>
  );
}
