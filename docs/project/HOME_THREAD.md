# Home thread

Implemented locally on 2026-10-15. This is an initial continuity feature, not a reproduction of Muse's undisclosed memory internals. Optional [dreaming](DREAMING.md) now adds bounded, source-linked reflection during gateway idle time.

## Using it

Run `/home` in the classic CLI or Ink TUI, or press **Home** above **New chat** in the dashboard's chat list. The first explicit open enables Home recall in that profile and creates one ordinary conversation. Repeated opens resume the same logical conversation, including through compression and canonical local resets. Independent chats keep their transcripts, execution state, and existing new/resume controls. No frontend needs to remain open for the binding or source messages to persist.

New personal CLI/web chats created after enablement participate automatically. Older chats require `/home share` from that chat. `/home exclude` excludes the current logical chat from future Home recall, as both a source and a recipient. `/home off` disables automatic Home recall for the profile; `/home on` re-enables it. `/home status` reports the setting. Opening `/home` explicitly enables it again.

Ask Home a topical question to recall relevant messages from participating chats, or ask for an overview/updates. `/home overview` displays recent dated excerpts and source links directly, without a model call. These are conversation excerpts, including assistant claims; they are not verified task completion records. Existing source links use Hermes' session navigation format.

## How it works

- `HomeStore` stores the Home anchor, enablement time, and sharing overrides in existing profile-owned `state_meta`. Creation is transactional and idempotent. Branches are independent; compression and native reset lineage preserve the logical anchor. Deleting the Home source allows recreation only on an explicit open.
- Evidence stays in existing canonical message rows and their FTS index. Search considers personal sources only, validates participation and principal, excludes the current logical chat, hidden/rewound content, tool rows, and synthetic compression summaries. It includes up to two following conversational messages to expose nearby corrections.
- Topic search scans ranked hits lazily in pages of 128, up to 4,096 hits, checking participation before accepting at most eight excerpts. Overview considers the newest 128 personal session rows. Rendered recall is capped at 6,000 characters, with individual excerpts capped at 900, and redacts supported secret patterns. This is a character bound, not an exact tokenizer budget.
- The built-in memory provider adds evidence through the existing current-user API sidecar, including the opt-in native app-server path. It preserves previously sent content and the system prefix. It coexists with native notes and the selected external provider; skip-memory remains respected. Recall makes no model call. Optional `/home dream on` adds bounded reflection through existing gateway housekeeping, with separate candidate notes and an auxiliary call budget; it adds no scheduler or embeddings.
- Managed workers request recall through an authenticated, assignment-fenced owner read, separate from the durable write journal. Recall failures warn once and leave later transcript writes usable. They do not acquire direct database access. Home controls require native local authority. Dashboard mutations use the live owner when present and existing exclusive maintenance when offline.

## Scope and limits

Home recall is personal and profile-local. Groups, messaging transports, jobs, subagents, hidden chats, and other principals are excluded. Existing profile and turn ownership/approval controls still apply. Reading unfinished work never authorizes executing it.

`exclude` means future **Home retrieval**, not private chat or forgetting. It does not clear content already sent in active contexts, native `MEMORY.md`/`USER.md`, external memory, or explicit session-search access. Use separate Hermes profiles when separate memory is required. No private-chat label is exposed.

Retrieval is keyword-based. Dream notes can add useful phrasing and cross-chat connections, but paraphrases can still miss and old matches can crowd the candidate limit. The excerpts carry dates and sources rather than being promoted into asserted facts. Overview is recent context, not a complete task ledger. Revisioned fact-level forgetting, semantic retrieval, full lifecycle evaluation, and proactive task coordination remain future work. No live-provider quality benchmark has been run.

## Research basis

Meta publicly describes [Muse's main conversation, side chats, cross-chat memory and filtered background updates](https://introducing.muse.ai/). Its [security architecture](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) describes the runtime, durable state, and authority boundaries. Its [Muse Wonder model card](https://research.meta.ai/static/muse-wonder-model-card) describes long-history memory evaluation with updates and distractors. These do not publish an exact production retrieval/consolidation algorithm.

[Letta Conversations](https://www.letta.com/blog/conversations/) supplies a close public precedent for independent conversations sharing agent memory. [Anthropic's context engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) supports bounded relevant context and durable notes. The local implementation uses Hermes' existing seams; the broader proposal and future acceptance gates remain in [HOME_THREAD_PLAN.md](HOME_THREAD_PLAN.md).

## Validation

Deterministic tests cover concurrent/idempotent creation, restart, compression and canonical reset, source deletion, exclusions, opt-in history, other profiles/principals, an old decision after 140 unrelated chats, bounded evidence, nearby corrections, managed-worker admission, gateway controls, both dashboard owner paths, and sidecar registration. A real agent loop against a local mock HTTP model verifies source evidence reaches the request while stored user text and the old prompt prefix remain stable. No external provider or production transcripts are used.

Frontend tests exercise Home navigation through existing resume controls, busy state, delayed/stale responses, profile changes, and retryable failures. Exact final check receipts and remaining validation blockers are recorded in [STATUS.md](STATUS.md).
