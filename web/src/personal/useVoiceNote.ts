import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJSON, getManagementProfile } from "@/lib/api";

export type VoicePhase = "idle" | "recording" | "transcribing";

const readDataUrl = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(blob);
  });

/** Record one voice note and hand back its transcript through the profile's configured speech-to-text. */
export function useVoiceNote(onTranscript: (text: string) => void) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const supported = typeof window !== "undefined" && "MediaRecorder" in window && Boolean(navigator.mediaDevices);

  useEffect(() => () => recorder.current?.stream.getTracks().forEach((t) => t.stop()), []);

  const start = useCallback(async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setPhase("transcribing");
        try {
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
          const result = await fetchJSON<{ transcript: string }>(
            `/api/audio/transcribe?profile=${encodeURIComponent(getManagementProfile() || "default")}`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ data_url: await readDataUrl(blob), mime_type: blob.type }),
            },
          );
          if (result.transcript) onTranscript(result.transcript);
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : String(cause));
        } finally {
          setPhase("idle");
        }
      };
      recorder.current = rec;
      rec.start();
      setPhase("recording");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setPhase("idle");
    }
  }, [onTranscript]);

  const stop = useCallback(() => recorder.current?.state === "recording" && recorder.current.stop(), []);

  return { phase, error, supported, start, stop };
}
