import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type {
  ApprovalRequestParams,
  ClarifyRequestParams,
  ServerRequest,
  SessionCreateResult,
  SessionResumeResult,
} from "@hermes/shared";

import { fetchJSON } from "@/lib/api";
import { GatewayClient } from "@/lib/gatewayClient";
import { EMPTY_TRANSCRIPT, transcriptReducer } from "./lib/transcript";

/** Home is the default; Projects open ordinary stored chats; "new" mints a fresh one. */
export type ChatTarget = { kind: "home" } | { kind: "stored"; id: string } | { kind: "new"; nonce: number };

const targetKey = (target: ChatTarget) =>
  target.kind === "stored" ? `stored:${target.id}` : target.kind === "new" ? `new:${target.nonce}` : "home";
export type ConnectionPhase = "connecting" | "ready" | "error";

type Prompt<P> = Omit<ServerRequest, "params"> & { params: P };
export type ApprovalPrompt = Prompt<ApprovalRequestParams>;
export type ClarifyPrompt = Prompt<ClarifyRequestParams>;

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/**
 * One gateway socket per profile, bound to one runtime session at a time. The backend stays
 * authoritative for the transcript: we resume it, then fold live events into presentation state.
 */
export function usePersonalChat(profile: string, target: ChatTarget) {
  const [transcript, dispatch] = useReducer(transcriptReducer, EMPTY_TRANSCRIPT);
  const [phase, setPhase] = useState<ConnectionPhase>("connecting");
  const [error, setError] = useState("");
  const [storedId, setStoredId] = useState<string | null>(null);
  const [approval, setApproval] = useState<ApprovalPrompt | null>(null);
  const [clarify, setClarify] = useState<ClarifyPrompt | null>(null);
  const [client, setClient] = useState<GatewayClient | null>(null);
  const sid = useRef<string | null>(null);
  const profileParam = profile || undefined;

  useEffect(() => {
    const gw = new GatewayClient();
    const offEvent = gw.onEvent((event) => {
      if (!event.session_id || event.session_id !== sid.current) return;
      if (event.type === ("request.cancel" as typeof event.type)) {
        const id = (event.payload as { id?: string } | undefined)?.id;
        setApproval((current) => (current?.id === id ? null : current));
        setClarify((current) => (current?.id === id ? null : current));
        return;
      }
      dispatch({ type: "event", event });
    });
    const offRequest = gw.onRequest((request) => {
      if ((request.params as { session_id?: string }).session_id !== sid.current) return false;
      if (request.method === "approval") setApproval(request as unknown as ApprovalPrompt);
      else if (request.method === "clarify") setClarify(request as unknown as ClarifyPrompt);
      else return false;
      return true;
    });
    const offState = gw.onState((state) => {
      if (state === "open") setPhase("ready");
      else if (state === "error" || state === "closed") setPhase("error");
    });
    gw.connect()
      .then(() => setClient(gw))
      .catch((cause) => {
        setPhase("error");
        setError(message(cause));
      });
    return () => {
      offEvent();
      offRequest();
      offState();
      sid.current = null;
      setClient(null);
      gw.close();
    };
  }, [profile]);

  // A new destination starts from a clean slate before its history arrives.
  const openKey = `${profile}|${targetKey(target)}`;
  const [shownKey, setShownKey] = useState(openKey);
  if (shownKey !== openKey) {
    setShownKey(openKey);
    setStoredId(null);
    setApproval(null);
    setClarify(null);
    setError("");
    dispatch({ type: "history", messages: [] });
  }

  useEffect(() => {
    if (!client) return;
    let stale = false;
    sid.current = null;

    async function open(gw: GatewayClient) {
      if (target.kind === "new") {
        const created = await gw.request<SessionCreateResult>("session.create", { profile: profileParam });
        return { runtime: created.session_id, stored: created.stored_session_id, messages: created.messages, running: false };
      }
      const stored =
        target.kind === "stored"
          ? target.id
          : (
              await fetchJSON<{ session_id: string }>(
                `/api/home/open?profile=${encodeURIComponent(profile || "default")}`,
                { method: "POST" },
              )
            ).session_id;
      const resumed = await gw.request<SessionResumeResult>("session.resume", { session_id: stored, profile: profileParam });
      return {
        runtime: resumed.session_id,
        stored: resumed.stored_session_id ?? stored,
        messages: resumed.messages ?? [],
        running: Boolean(resumed.running),
      };
    }

    open(client)
      .then((opened) => {
        if (stale) return;
        sid.current = opened.runtime;
        setStoredId(opened.stored);
        dispatch({ type: "history", messages: opened.messages, running: opened.running });
      })
      .catch((cause) => {
        if (!stale) setError(message(cause));
      });
    return () => {
      stale = true;
    };
    // Re-open only when the destination changes, not on every render of an equal target object.
  }, [client, openKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = useCallback(
    (text: string) => {
      const session = sid.current;
      if (!client || !session || !text.trim()) return;
      dispatch({ type: "sent", text });
      client
        .request("prompt.submit", { session_id: session, text, profile: profileParam })
        .catch((cause) => dispatch({ type: "failed", message: message(cause) }));
    },
    [client, profileParam],
  );

  const interrupt = useCallback(() => {
    const session = sid.current;
    if (client && session) void client.request("session.interrupt", { session_id: session, profile: profileParam }).catch(() => {});
  }, [client, profileParam]);

  const answerApproval = useCallback(
    (choice: string) => {
      approval?.respond({ choice });
      setApproval(null);
    },
    [approval],
  );

  const answerClarify = useCallback(
    (answers: Record<string, string> | null) => {
      clarify?.respond(answers ? { answers, outcome: "submitted" } : { outcome: "cancelled" });
      setClarify(null);
    },
    [clarify],
  );

  return {
    transcript,
    phase,
    error,
    ready: phase === "ready" && storedId !== null && !error,
    storedId,
    approval,
    clarify,
    send,
    interrupt,
    answerApproval,
    answerClarify,
  };
}
