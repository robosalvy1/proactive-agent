export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location?: string | null;
  meeting_url?: string | null;
  url?: string | null;
}

export type CalendarStatus =
  | { state: "needs_client" }
  | { state: "needs_auth" }
  | { state: "needs_scope" }
  | { state: "connected"; events: CalendarEvent[] }
  | { state: "error"; error: string };

export interface CalendarDay {
  key: string;
  label: string;
  events: CalendarEvent[];
}

/** All-day dates are calendar dates, not instants: read them in local time, not UTC. */
export function eventStart(event: CalendarEvent): Date {
  if (!event.all_day) return new Date(event.start);
  const [y, m, d] = event.start.split("-").map(Number);
  return new Date(y, m - 1, d);
}

const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;

export function groupByDay(events: CalendarEvent[], now: Date, labels: { today: string; tomorrow: string }, locale?: string): CalendarDay[] {
  const today = dayKey(now);
  const tomorrow = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
  const days: CalendarDay[] = [];
  for (const event of events) {
    const start = eventStart(event);
    // An event already underway belongs to today.
    const key = start < now ? today : dayKey(start);
    let day = days.find((d) => d.key === key);
    if (!day) {
      const label = key === today ? labels.today : key === tomorrow ? labels.tomorrow : start.toLocaleDateString(locale, { weekday: "long", month: "short", day: "numeric" });
      day = { key, label, events: [] };
      days.push(day);
    }
    day.events.push(event);
  }
  return days;
}

export function isHappeningNow(event: CalendarEvent, now: Date): boolean {
  return !event.all_day && new Date(event.start) <= now && now < new Date(event.end);
}

/** The loopback callback lands on /home with our state prefix; anything else isn't ours. */
export function calendarCallback(href: string): string | null {
  const url = new URL(href);
  const state = url.searchParams.get("state");
  return state?.startsWith("cal_") && (url.searchParams.has("code") || url.searchParams.has("error")) ? href : null;
}
