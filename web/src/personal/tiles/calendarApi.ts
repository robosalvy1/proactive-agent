import { fetchJSON } from "@/lib/api";
import type { CalendarStatus } from "../lib/calendar";

const q = (profile: string, extra = "") => `?profile=${encodeURIComponent(profile)}${extra}`;
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** The calendar tile's backend: Hermes's Google Workspace sign-in (shared with the google-workspace skill). */
export const calendarApi = {
  status: (profile: string, days: number) => fetchJSON<CalendarStatus>(`/api/personal/calendar${q(profile, `&days=${days}&limit=10`)}`),
  saveClient: (profile: string, clientJson: string) => fetchJSON(`/api/personal/calendar/client${q(profile)}`, post({ client_json: clientJson })),
  start: (profile: string) =>
    fetchJSON<{ auth_url: string; manual: boolean }>(`/api/personal/calendar/start${q(profile)}`, post({ origin: window.location.origin })),
  finish: (profile: string, codeOrUrl: string) => fetchJSON(`/api/personal/calendar/finish${q(profile)}`, post({ code_or_url: codeOrUrl })),
  disconnect: (profile: string) => fetchJSON(`/api/personal/calendar${q(profile)}`, { method: "DELETE" }),
};
