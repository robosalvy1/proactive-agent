import { Button } from "@nous-research/ui/ui/components/button";
import { House } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/i18n";
import { fetchJSON } from "@/lib/api";

interface HomeChatButtonProps {
  profile: string;
  onOpen: (sessionId: string) => void;
}

/** Mount with a profile key: an old request cannot navigate a newly selected profile. */
export function HomeChatButton({ profile, onOpen }: HomeChatButtonProps) {
  const { t } = useI18n();
  const request = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => () => request.current?.abort(), []);

  async function openHome() {
    if (busy) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await fetchJSON<{ session_id: string }>(
        `/api/home/open?profile=${encodeURIComponent(profile)}`,
        { method: "POST", signal: controller.signal },
      );
      if (!controller.signal.aborted) onOpen(result.session_id);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : (t.common.loadFailed ?? "Unable to open Home."));
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <div className="mx-2 mb-2 flex flex-col gap-1">
      <Button outlined size="sm" prefix={<House />} disabled={busy} onClick={openHome}>
        {busy ? t.common.loading : (t.sessions.homeChat ?? "Home")}
      </Button>
      {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
    </div>
  );
}
