import { describe, expect, it } from "vitest";

import { calendarCallback, eventStart, groupByDay, isHappeningNow, type CalendarEvent } from "./calendar";

const timed = (id: string, start: Date, minutes = 30): CalendarEvent => ({
  id, title: id, start: start.toISOString(), end: new Date(start.getTime() + minutes * 60000).toISOString(), all_day: false,
});

describe("calendar tile", () => {
  const now = new Date(2026, 9, 16, 10, 0);
  const labels = { today: "Today", tomorrow: "Tomorrow" };

  it("groups into today, tomorrow and named days, keeping running events in today", () => {
    const events = [
      timed("running", new Date(2026, 9, 16, 9, 45)),
      timed("lunch", new Date(2026, 9, 16, 12, 0)),
      { id: "bday", title: "bday", start: "2026-10-17", end: "2026-10-18", all_day: true },
      timed("trip", new Date(2026, 9, 19, 8, 0)),
    ];
    const days = groupByDay(events, now, labels, "en-US");
    expect(days.map((d) => [d.label, d.events.map((e) => e.id)])).toEqual([
      ["Today", ["running", "lunch"]],
      ["Tomorrow", ["bday"]],
      ["Monday, Oct 19", ["trip"]],
    ]);
  });

  it("reads all-day dates in local time and flags what's on now", () => {
    expect(eventStart({ id: "a", title: "a", start: "2026-10-17", end: "2026-10-18", all_day: true }).getDate()).toBe(17);
    expect(isHappeningNow(timed("running", new Date(2026, 9, 16, 9, 45)), now)).toBe(true);
    expect(isHappeningNow(timed("later", new Date(2026, 9, 16, 12, 0)), now)).toBe(false);
  });

  it("only treats its own OAuth return as a calendar callback", () => {
    expect(calendarCallback("http://127.0.0.1:9119/home?code=x&state=cal_abc")).not.toBeNull();
    expect(calendarCallback("http://127.0.0.1:9119/home?error=access_denied&state=cal_abc")).not.toBeNull();
    expect(calendarCallback("http://127.0.0.1:9119/home?code=x&state=other")).toBeNull();
    expect(calendarCallback("http://127.0.0.1:9119/home")).toBeNull();
  });
});
