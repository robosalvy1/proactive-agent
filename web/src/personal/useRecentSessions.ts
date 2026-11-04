import { useEffect, useState } from "react";

import { api, type SessionInfo } from "@/lib/api";

/** Recently active chats for the profile, without Home itself. */
export function useRecentSessions(profile: string, exclude: string | null) {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  useEffect(() => {
    let live = true;
    api
      .getSessions(24, 0, profile, "recent")
      .then((page) => live && setSessions(page.sessions))
      .catch(() => live && setSessions([]));
    return () => {
      live = false;
    };
  }, [profile]);
  return sessions?.filter((s) => s.id !== exclude) ?? null;
}
