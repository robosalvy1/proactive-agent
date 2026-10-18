import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/api-error";
import { calendarCallback } from "./lib/calendar";
import { calendarApi } from "./tiles/calendarApi";

/**
 * Google sends the person back to /home with ?code&state. Finish once, strip the code from the
 * address bar, and bump a version so a mounted calendar tile reloads.
 */
export function useCalendarReturn(profile: string) {
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const handled = useRef(false);

  useEffect(() => {
    const callback = calendarCallback(window.location.href);
    if (!callback || handled.current) return;
    handled.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    calendarApi
      .finish(profile, callback)
      .then(() => setNotice({ tone: "ok", text: "" }))
      .catch((cause) => setNotice({ tone: "error", text: errorMessage(cause) }))
      .finally(() => setVersion((v) => v + 1));
  }, [profile]);

  const dismiss = useCallback(() => setNotice(null), []);
  return { version, notice, dismiss };
}
