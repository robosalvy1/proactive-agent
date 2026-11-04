import { CalendarDays, ExternalLink, LoaderCircle, RotateCw, Upload, Video } from "lucide-react";
import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import { errorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { usePersonalCopy } from "../copy";
import { eventStart, groupByDay, isHappeningNow, type CalendarEvent, type CalendarStatus } from "../lib/calendar";
import type { TileOf } from "../lib/tiles";
import { calendarApi } from "./calendarApi";
import { Segmented, TileShell, tileButton, tileInput, type TileControls } from "./TileShell";

interface CalendarTileProps {
  tile: TileOf<"calendar">;
  controls: TileControls;
  profile: string;
  agentName: string;
  /** Bumped after an OAuth return so the tile reloads. */
  version: number;
  onChange: (settings: { days: 1 | 3 | 7 }) => void;
}

const CONSOLE_URL = "https://console.cloud.google.com/apis/credentials";

function EventRow({ event, now }: { event: CalendarEvent; now: Date }) {
  const p = usePersonalCopy();
  const live = isHappeningNow(event, now);
  const time = event.all_day ? p.calendarAllDay : eventStart(event).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return (
    <li className={cn("flex items-center gap-3 rounded-2xl px-3 py-2.5", live ? "bg-neutral-900 text-white" : "bg-white/80")}>
      <span className={cn("w-[4.5rem] shrink-0 text-[13px] tabular-nums", live ? "text-emerald-300" : "text-neutral-500")}>
        {live ? p.calendarNow : time}
      </span>
      <a href={event.url ?? undefined} target="_blank" rel="noreferrer" className={cn("min-w-0 flex-1 truncate text-[15px]", live ? "text-white" : "text-neutral-900")}>
        {event.title}
      </a>
      {event.meeting_url && (
        <a
          href={event.meeting_url}
          target="_blank"
          rel="noreferrer"
          className={cn("inline-flex min-h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-[13px] font-medium", live ? "bg-emerald-400 text-neutral-900" : "bg-neutral-900/5 text-neutral-800")}
        >
          <Video className="h-3.5 w-3.5" />
          {p.calendarJoin}
        </a>
      )}
    </li>
  );
}

function ClientSetup({ profile, agentName, onSaved }: { profile: string; agentName: string; onSaved: () => void }) {
  const p = usePersonalCopy();
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async (json: string) => {
    setBusy(true);
    setError("");
    try {
      await calendarApi.saveClient(profile, json);
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) await save(await file.text());
  };

  if (!expanded)
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[14px] leading-5 text-neutral-600">{p.calendarSetupIntro.replaceAll("{agent}", agentName)}</p>
        <button type="button" onClick={() => setExpanded(true)} className={tileButton}>
          <CalendarDays className="h-4 w-4" />
          {p.calendarSetup}
        </button>
      </div>
    );

  return (
    <div className="personal-rise flex flex-col gap-3">
      <ol className="flex flex-col gap-1.5 text-[14px] leading-5 text-neutral-800">
        {[p.calendarSetupStep1.replaceAll("{agent}", agentName), p.calendarSetupStep2, p.calendarSetupStep3].map((step, i) => (
          <li key={step} className="flex gap-2.5">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-[11px] font-semibold text-white">{i + 1}</span>
            {step}
          </li>
        ))}
      </ol>
      <a href={CONSOLE_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 self-start text-[14px] font-medium text-sky-800 hover:underline">
        {p.calendarOpenConsole}
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        spellCheck={false}
        placeholder={p.calendarClientPlaceholder}
        aria-label={p.calendarClientPlaceholder}
        className={cn(tileInput, "resize-none font-mono text-[13px]")}
      />
      {error && <p role="alert" className="text-[13px] text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={busy || !text.trim()} onClick={() => save(text)} className={cn(tileButton, "flex-1")}>
          {busy && <LoaderCircle className="h-4 w-4 animate-spin" />}
          {p.calendarSaveClient}
        </button>
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl bg-white/90 px-4 text-[15px] font-medium text-neutral-900 hover:bg-white">
          <Upload className="h-4 w-4" />
          {p.calendarUpload}
          <input type="file" accept=".json,application/json" className="sr-only" onChange={upload} />
        </label>
      </div>
    </div>
  );
}

function Connect({ profile, agentName, note, onConnected }: { profile: string; agentName: string; note?: string; onConnected: () => void }) {
  const p = usePersonalCopy();
  const [manual, setManual] = useState(false);
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const begin = async () => {
    setBusy(true);
    setError("");
    try {
      const { auth_url, manual: needsPaste } = await calendarApi.start(profile);
      if (!needsPaste) return window.location.assign(auth_url);
      window.open(auth_url, "_blank", "noopener");
      setManual(true);
    } catch (cause) {
      setError(errorMessage(cause));
    }
    setBusy(false);
  };

  const finish = async () => {
    setBusy(true);
    setError("");
    try {
      await calendarApi.finish(profile, pasted);
      onConnected();
    } catch (cause) {
      setError(errorMessage(cause));
    }
    setBusy(false);
  };

  return (
    <div className="flex flex-col gap-3">
      {note && <p className="text-[14px] leading-5 text-neutral-700">{note}</p>}
      <button type="button" onClick={begin} disabled={busy} className={tileButton}>
        {busy && !manual ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CalendarDays className="h-4 w-4" />}
        {p.calendarConnect}
      </button>
      {manual ? (
        <form className="flex flex-col gap-2" onSubmit={(e) => (e.preventDefault(), finish())}>
          <p className="text-[14px] leading-5 text-neutral-600">{p.calendarManualHint}</p>
          <input className={tileInput} value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder={p.calendarManualPlaceholder} aria-label={p.calendarManualPlaceholder} />
          <button type="submit" disabled={busy || !pasted.trim()} className={tileButton}>{p.calendarFinish}</button>
        </form>
      ) : (
        <p className="text-center text-[13px] text-neutral-500">{p.calendarConnectHint.replaceAll("{agent}", agentName)}</p>
      )}
      {error && <p role="alert" className="text-[13px] text-rose-700">{error}</p>}
    </div>
  );
}

export function CalendarTile({ tile, controls, profile, agentName, version, onChange }: CalendarTileProps) {
  const p = usePersonalCopy();
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [reload, setReload] = useState(0);
  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const days = tile.settings.days;

  useEffect(() => {
    let live = true;
    calendarApi
      .status(profile, days)
      .then((next) => live && setStatus(next))
      .catch((cause) => live && setStatus({ state: "error", error: errorMessage(cause) }));
    const timer = window.setInterval(() => setReload((n) => n + 1), 5 * 60 * 1000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [profile, days, version, reload]);

  const [confirming, setConfirming] = useState(false);
  const disconnect = async () => {
    setConfirming(false);
    await calendarApi.disconnect(profile).catch(() => {});
    refresh();
  };

  const connected = status?.state === "connected";
  const settings = (
    <div className="flex flex-col gap-3">
      <Segmented
        label={p.calendarRange}
        value={days}
        onChange={(next) => onChange({ days: next })}
        options={[{ value: 1, label: p.calendarDays1 }, { value: 3, label: p.calendarDays3 }, { value: 7, label: p.calendarDays7 }]}
      />
      {(connected || status?.state === "needs_scope") && (
        <>
          <p className="text-[13px] leading-5 text-neutral-500">{p.calendarAccount.replaceAll("{agent}", agentName)}</p>
          {confirming ? (
            <div role="alertdialog" className="flex flex-col gap-2 rounded-2xl bg-rose-50/90 p-3">
              <p className="text-[14px] leading-5 text-rose-900">{p.calendarDisconnectConfirm.replaceAll("{agent}", agentName)}</p>
              <div className="flex gap-2">
                <button type="button" onClick={disconnect} className="min-h-10 rounded-xl bg-rose-700 px-3 text-[14px] font-medium text-white">
                  {p.calendarDisconnect.replaceAll("{agent}", agentName)}
                </button>
                <button type="button" onClick={() => setConfirming(false)} className="min-h-10 rounded-xl bg-white px-3 text-[14px] font-medium text-neutral-800">
                  {p.cancel}
                </button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirming(true)} className="self-start text-[14px] font-medium text-rose-700 hover:underline">
              {p.calendarDisconnect.replaceAll("{agent}", agentName)}
            </button>
          )}
        </>
      )}
    </div>
  );

  const now = new Date();
  let body;
  if (!status) body = <div className="h-24 animate-pulse rounded-2xl bg-white/50" />;
  else if (status.state === "needs_client") body = <ClientSetup profile={profile} agentName={agentName} onSaved={refresh} />;
  else if (status.state === "needs_auth") body = <Connect profile={profile} agentName={agentName} onConnected={refresh} />;
  else if (status.state === "needs_scope")
    body = <Connect profile={profile} agentName={agentName} note={p.calendarNeedsScope.replaceAll("{agent}", agentName)} onConnected={refresh} />;
  else if (status.state === "error")
    body = (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-[14px] leading-5 text-neutral-700">{status.error}</p>
        <button type="button" onClick={refresh} className="inline-flex min-h-10 items-center gap-1.5 text-[14px] font-medium text-neutral-900">
          <RotateCw className="h-4 w-4" />
          {p.retry}
        </button>
      </div>
    );
  else if (!status.events.length) body = <p className="text-[15px] text-neutral-600">{p.calendarEmpty}</p>;
  else
    body = (
      <div className="flex flex-col gap-3">
        {groupByDay(status.events, now, { today: p.calendarToday, tomorrow: p.calendarTomorrow }).map((day) => (
          <section key={day.key} className="flex flex-col gap-1.5">
            <h3 className="px-1 text-[12px] font-semibold uppercase tracking-wide text-neutral-500">{day.label}</h3>
            <ul className="flex flex-col gap-1.5">
              {day.events.map((event) => <EventRow key={event.id} event={event} now={now} />)}
            </ul>
          </section>
        ))}
      </div>
    );

  return (
    <TileShell title={p.tileCalendar} icon={<CalendarDays />} controls={controls} settings={settings}>
      {body}
    </TileShell>
  );
}
