import { CalendarClock } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type CronJob } from "@/lib/api";
import { usePersonalCopy } from "../copy";
import { TileShell, tileRow, type TileControls } from "./TileShell";

function relativeFuture(iso: string): string {
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  if (Math.abs(minutes) < 60 * 36) return rtf.format(Math.round(minutes / 60), "hour");
  return rtf.format(Math.round(minutes / 1440), "day");
}

/** Jobs the person scheduled, so proactive work is visible before it runs. */
export function ScheduledTile({ profile, controls }: { profile: string; controls: TileControls }) {
  const p = usePersonalCopy();
  const [jobs, setJobs] = useState<CronJob[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getCronJobs(profile)
      .then((all) => live && setJobs(all.sort((a, b) => (a.next_run_at ?? "~").localeCompare(b.next_run_at ?? "~")).slice(0, 4)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [profile]);

  return (
    <TileShell title={p.tileScheduled} icon={<CalendarClock />} controls={controls}>
      {failed ? (
        <p className="text-[15px] text-neutral-600">{p.loadFailed}</p>
      ) : jobs?.length ? (
        <ul className="flex flex-col gap-2">
          {jobs.map((job) => (
            <li key={job.id} className={tileRow}>
              <div className="truncate text-[16px] text-neutral-900">{job.name || job.prompt || job.id}</div>
              <div className="text-[13px] text-neutral-500">
                {!job.enabled ? p.paused : job.next_run_at ? p.nextRun.replace("{when}", relativeFuture(job.next_run_at)) : (job.schedule_display ?? "")}
              </div>
            </li>
          ))}
        </ul>
      ) : jobs ? (
        <p className="text-[15px] text-neutral-600">{p.nothingScheduled}</p>
      ) : (
        <div className="h-14 animate-pulse rounded-2xl bg-white/50" />
      )}
    </TileShell>
  );
}
