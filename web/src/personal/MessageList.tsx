import { Check, LoaderCircle, TriangleAlert } from "lucide-react";
import { useEffect, useRef } from "react";

import { Markdown } from "@/components/Markdown";
import { cn } from "@/lib/utils";
import type { Bubble } from "./lib/transcript";

interface MessageListProps {
  bubbles: Bubble[];
  intro: string[];
  busy: boolean;
  footer?: React.ReactNode;
}

function AssistantBubble({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className="personal-rise personal-prose max-w-[min(36rem,100%)] self-start rounded-[26px] bg-white px-6 py-4 text-[17px] leading-[1.45] text-neutral-900 shadow-[0_6px_24px_-14px_rgba(20,45,90,0.35)]">
      <Markdown content={text} streaming={streaming} />
    </div>
  );
}

function BubbleRow({ bubble }: { bubble: Bubble }) {
  switch (bubble.kind) {
    case "user":
      return (
        <div className="personal-rise personal-soft max-w-[min(30rem,85%)] self-end whitespace-pre-wrap rounded-[26px] border border-white/50 bg-white/45 px-6 py-3.5 text-[17px] leading-[1.45] text-neutral-900 backdrop-blur-xl">
          {bubble.text}
        </div>
      );
    case "assistant":
      return <AssistantBubble text={bubble.text} streaming={bubble.streaming} />;
    case "activity":
      return (
        <div
          className={cn(
            "personal-rise flex items-center gap-2.5 self-start rounded-full px-5 py-3 text-[15px] font-medium transition-colors",
            bubble.done ? "bg-neutral-900 text-white" : "bg-white/60 text-neutral-700 backdrop-blur-xl",
          )}
        >
          {bubble.done ? (
            <Check className="h-4 w-4 text-emerald-400" strokeWidth={3} />
          ) : (
            <LoaderCircle className="h-4 w-4 animate-spin" />
          )}
          {bubble.label}
        </div>
      );
    case "notice":
      return (
        <div role="alert" className="personal-rise flex max-w-[36rem] items-start gap-2.5 self-start rounded-[22px] bg-rose-50/90 px-5 py-3 text-[15px] text-rose-900">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {bubble.text}
        </div>
      );
  }
}

function TypingDots() {
  return (
    <div aria-label="Thinking" className="personal-rise flex gap-1.5 self-start rounded-full bg-white px-5 py-4">
      {[0, 1, 2].map((i) => (
        <span key={i} className="personal-dot h-2 w-2 rounded-full bg-neutral-400" style={{ animationDelay: `${i * 160}ms` }} />
      ))}
    </div>
  );
}

/** Scrolls under the header with a soft fade, like messages drifting into the sky. */
export function MessageList({ bubbles, intro, busy, footer }: MessageListProps) {
  const end = useRef<HTMLDivElement>(null);
  const last = bubbles[bubbles.length - 1];
  const waiting = busy && !(last?.kind === "assistant" && last.streaming) && last?.kind !== "activity";

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [bubbles, waiting, footer]);

  return (
    <div className="personal-fade-top min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div role="log" aria-live="polite" className="flex min-h-full flex-col justify-end gap-3 px-0.5 pb-5 pt-[calc(max(1rem,env(safe-area-inset-top))+6rem)] sm:gap-4 sm:px-1 sm:pt-36">
        {bubbles.length === 0 &&
          intro.map((line, i) => (
            <div key={line} style={{ animationDelay: `${i * 220}ms` }} className="personal-rise self-start">
              <AssistantBubble text={line} />
            </div>
          ))}
        {bubbles.map((bubble) => (
          <BubbleRow key={bubble.id} bubble={bubble} />
        ))}
        {waiting && <TypingDots />}
        {footer}
        <div ref={end} />
      </div>
    </div>
  );
}
