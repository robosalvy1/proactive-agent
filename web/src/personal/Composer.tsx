import { ArrowUp, LoaderCircle, Mic, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { usePersonalCopy } from "./copy";
import { cn } from "@/lib/utils";
import { useVoiceNote } from "./useVoiceNote";

interface ComposerProps {
  agentName: string;
  disabled: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

const iconButton =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-neutral-700 transition hover:bg-white/70 disabled:opacity-40";

export function Composer({ agentName, disabled, busy, onSend, onStop }: ComposerProps) {
  const p = usePersonalCopy();
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const appendTranscript = useCallback(
    (spoken: string) => setText((current) => (current.trim() ? `${current.trimEnd()} ${spoken}` : spoken)),
    [],
  );
  const voice = useVoiceNote(appendTranscript);

  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  useEffect(() => {
    if (!disabled) input.current?.focus();
  }, [disabled]);

  const submit = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const recording = voice.phase === "recording";

  return (
    <div className="flex flex-col gap-2">
      {voice.error && <p role="alert" className="px-6 text-sm text-rose-900">{voice.error}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className={cn(
          "personal-soft flex items-end gap-1 rounded-[32px] border border-white/50 bg-white/60 py-2.5 pl-6 pr-2.5 shadow-[0_12px_40px_-16px_rgba(20,45,90,0.35)] backdrop-blur-2xl transition focus-within:bg-white/75",
          recording && "ring-2 ring-rose-300/70",
        )}
      >
        <textarea
          ref={input}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={recording ? p.stopRecording : p.messagePlaceholder.replace("{agent}", agentName)}
          aria-label={p.messagePlaceholder.replace("{agent}", agentName)}
          className="max-h-[180px] min-h-10 flex-1 resize-none bg-transparent py-2 text-[17px] leading-6 text-neutral-900 outline-none placeholder:text-neutral-500"
        />
        {voice.supported && (
          <button
            type="button"
            className={cn(iconButton, recording && "bg-rose-500 text-white hover:bg-rose-500")}
            disabled={disabled || voice.phase === "transcribing"}
            onClick={recording ? voice.stop : voice.start}
            aria-label={recording ? p.stopRecording : p.voice}
            title={voice.phase === "transcribing" ? p.transcribing : p.voice}
          >
            {voice.phase === "transcribing" ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Mic className="h-5 w-5" />}
          </button>
        )}
        {busy && !text.trim() ? (
          <button type="button" className={cn(iconButton, "bg-neutral-900 text-white hover:bg-neutral-800")} onClick={onStop} aria-label={p.stop}>
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="submit"
            className={cn(iconButton, "bg-neutral-900 text-white hover:bg-neutral-800")}
            disabled={disabled || !text.trim()}
            aria-label={p.send}
          >
            <ArrowUp className="h-5 w-5" />
          </button>
        )}
      </form>
    </div>
  );
}
