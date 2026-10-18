import { ShieldQuestion } from "lucide-react";
import { useState } from "react";

import type { ApprovalPrompt, ClarifyPrompt } from "./usePersonalChat";
import { usePersonalCopy } from "./copy";

const pill = "rounded-full px-4 py-2 text-[15px] font-medium transition";

/** Existing approval boundaries, rendered as a card in the conversation instead of being bypassed. */
export function ApprovalCard({ prompt, agentName, onAnswer }: { prompt: ApprovalPrompt; agentName: string; onAnswer: (choice: string) => void }) {
  const p = usePersonalCopy();
  const labels: Record<string, string> = {
    once: p.approveOnce,
    session: p.approveSession,
    always: p.approveAlways,
    deny: p.deny,
  };
  const choices = prompt.params.choices?.length ? prompt.params.choices : ["once", "deny"];
  return (
    <div role="alertdialog" aria-label={p.approvalTitle.replace("{agent}", agentName)} className="personal-rise flex max-w-[36rem] flex-col gap-3 self-start rounded-[26px] bg-white p-5 shadow-lg">
      <div className="flex items-center gap-2 text-[15px] font-semibold text-neutral-900">
        <ShieldQuestion className="h-5 w-5 text-amber-600" />
        {p.approvalTitle.replace("{agent}", agentName)}
      </div>
      {prompt.params.description && <p className="text-[15px] text-neutral-700">{prompt.params.description}</p>}
      {prompt.params.command && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-2xl bg-neutral-100 px-4 py-3 font-mono text-[13px] text-neutral-800">{prompt.params.command}</pre>
      )}
      <div className="flex flex-wrap gap-2">
        {choices.map((choice) => (
          <button
            key={choice}
            type="button"
            onClick={() => onAnswer(choice)}
            className={choice === "deny" ? `${pill} bg-neutral-100 text-neutral-800 hover:bg-neutral-200` : `${pill} bg-neutral-900 text-white hover:bg-neutral-800`}
          >
            {labels[choice] ?? choice}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ClarifyCard({ prompt, agentName, onAnswer }: { prompt: ClarifyPrompt; agentName: string; onAnswer: (answers: Record<string, string> | null) => void }) {
  const p = usePersonalCopy();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const questions = prompt.params.questions ?? [];
  const complete = questions.every((q) => answers[q.qid]?.trim());
  const set = (qid: string, value: string) => setAnswers((current) => ({ ...current, [qid]: value }));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (complete) onAnswer(answers);
      }}
      aria-label={p.clarifyTitle.replace("{agent}", agentName)}
      className="personal-rise flex max-w-[36rem] flex-col gap-4 self-start rounded-[26px] bg-white p-5 shadow-lg"
    >
      {questions.map((q) => (
        <fieldset key={q.qid} className="flex flex-col gap-2">
          <legend className="mb-1 text-[16px] font-medium text-neutral-900">{q.question}</legend>
          {q.choices?.length ? (
            <div className="flex flex-wrap gap-2">
              {q.choices.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  aria-pressed={answers[q.qid] === choice}
                  onClick={() => set(q.qid, choice)}
                  className={answers[q.qid] === choice ? `${pill} bg-neutral-900 text-white` : `${pill} bg-neutral-100 text-neutral-800 hover:bg-neutral-200`}
                >
                  {choice}
                </button>
              ))}
            </div>
          ) : (
            <input
              value={answers[q.qid] ?? ""}
              onChange={(e) => set(q.qid, e.target.value)}
              placeholder={p.clarifyPlaceholder}
              className="rounded-2xl bg-neutral-100 px-4 py-2.5 text-[15px] text-neutral-900 outline-none focus:ring-2 focus:ring-sky-300"
            />
          )}
        </fieldset>
      ))}
      <div className="flex gap-2">
        <button type="submit" disabled={!complete} className={`${pill} bg-neutral-900 text-white hover:bg-neutral-800 disabled:opacity-40`}>
          {p.clarifySubmit}
        </button>
        <button type="button" onClick={() => onAnswer(null)} className={`${pill} bg-neutral-100 text-neutral-800 hover:bg-neutral-200`}>
          {p.clarifySkip}
        </button>
      </div>
    </form>
  );
}
