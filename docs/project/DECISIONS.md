# Decision log

Record durable decisions with date, context, chosen approach, and consequences. Keep alternatives only when they explain a material tradeoff.

## 2026-10-15 — Proactive output goes through one attention layer on the cron tick

All proactive output (recurring cron results, open-loop check-ins) becomes an item in a profile-local SQLite store (`<profile>/cron/attention.db`, `cron/attention*.py`). A deterministic gate routes each item to an immediate interruption, the next digest, or the inbox only; the gateway's existing cron tick sends due items under its per-home lock. Choices: no second scheduler; no model on the gate or idle ticks; a separate DB rather than a `state.db` migration, because items are delivery state owned by cron, not transcript state; digests are at-most-once per slot. Open-loop extraction is a post-turn auxiliary call behind a regex pre-filter, with verbatim-evidence validation. Consequences: everything is off by default (`attention.enabled`) and starts at level `quiet`; delivery requires a running ticker (gateway, desktop backend or `hermes cron tick`); open loops may later migrate into the Home plan's continuity records. Details: [PROACTIVITY_PLAN.md](PROACTIVITY_PLAN.md).

## 2026-10-15 — Connected sources are watched by per-source cron jobs, found by index plus weekly discovery

Every connected source (MCP server, connected app, credentialed skill) gets its own watcher: an ordinary cron job with only that source's toolsets, whose JSON output becomes deduplicated attention items. Sources are found by a headless hourly index and a weekly model discovery pass that records evidence for anything it adds. Choices: reuse cron jobs, so users can pause, run, delete and inspect history as usual; scope tools per source for cost and prompt-injection containment; watcher output is never delivered raw; deleting a watcher latches its source as removed. Consequences: each watcher run is a model call (cost scales with sources × frequency); watchers are read-only by instruction, not by a tool-level guarantee, when they hold `terminal`.

## 2026-10-15 — Bound Home reflection and preserve source authority

Home dreaming now adds opt-in reflection to the existing gateway housekeeping loop. Store a bounded set of source-linked candidate notes and durable reservations/cadence/day counters in profile-owned `state_meta`; do not overwrite native memory or introduce another scheduler. Use existing auxiliary provider resolution with one completion attempt per reservation, capped input/output and no tool execution. Preserve source quotations, invalidate changed/excluded evidence on reads and before publication, and retain a physical reservation while a revoked request finishes. Notes remain fallible data on the current-user recall sidecar; no unsolicited notifications or task continuation. [DREAMING.md](DREAMING.md) defines the implemented controls, budgets and limits.

## 2026-10-15 — Preserve multiple chats in the Home thread direction

The requested “God thread” feature retains multiple chats in both CLI and web. A persistent Home binding resolves an ordinary conversation through existing compression and local reset lineage. New personal chats participate after explicit Home enablement; older chats require explicit sharing. Separate transcripts and existing turn ownership remain intact.

The initial continuity source reads bounded, dated transcript excerpts through existing SQLite FTS. It stores only routing/participation metadata in `state_meta`, avoiding a second learned-fact store and extraction queue before those prove necessary. Managed workers use an owner-mediated read, not direct database access. Recall enters the current-user API sidecar, preserving existing prompt prefixes and the configured external memory provider. Exclusion affects future Home retrieval only; native notes, explicit history search, and previously sent context keep their existing semantics. [HOME_THREAD.md](HOME_THREAD.md) documents the implemented scope; [HOME_THREAD_PLAN.md](HOME_THREAD_PLAN.md) retains future design gates.


## 2026-10-15 — Use Hermes source as the foundation

The user wants to start with Hermes and evolve a polished, proactive harness with excellent context. Import the upstream source into this repository, retaining its license and recording the exact revision in `UPSTREAM.json`. Agents can edit existing execution paths and reuse the upstream test suite directly.

Keep current Python/package/command names until a separate migration is justified. Project documentation distinguishes new direction from existing Hermes behavior. This initial import is a snapshot, without importing upstream Git history; future upstream updates require an explicit reviewed comparison.

## 2026-10-15 — Separate project intent from retained upstream guidance

The root `AGENTS.md` owns this project's goals and working agreement. Technical guidance is consolidated in `docs/project/ENGINEERING.md`; nested guides describe area contracts. Long-term notes live in a small set of project docs, while task-specific private data stays out of Git.

## 2026-10-15 — Start with limited automation

Archive upstream workflows and upstream bot/ownership configuration rather than enabling deployment, publication, or organization-specific runners in a new repository. Enable a minimal read-only foundation check. Full fork lint/test CI is an explicit next milestone, not an implied guarantee of this setup.

## 2026-10-15 — Own all active development instructions

Remove duplicate upstream onboarding and external contribution governance from the active instruction path. Keep technical contracts and truthful source attribution. Core changes, providers, and integrations are allowed when justified by project goals. Normalize area instructions, contribution entrypoints, and persona Markdown without changing code, dependency files, or automation.

## 2026-10-15 — PR babysitting authorizes the review-to-merge loop

The user can invoke “babysit the PR” (including “babbysit”) to authorize review requests, feedback replies, fixes, commits/pushes, monitoring, and merge after current-revision checks and review gates pass. Require a review bot from a different model family or CodeRabbit. Keep the trigger in AGENTS.md and details in PR_BABYSITTING.md. This is an instruction workflow, not an installed review integration or background service.

## 2026-10-15 — Personalize inside the connected messaging app

Use a profile-local messaging-offer flag independent of CLI/desktop session counts. On the first empty human DM, stage a conversational directive on the existing persisted user-message sidecar; subsequent answers use normal history and existing memory/file tools. No new core tool, store, scheduler, or mid-session system-prompt mutation. Respect `onboarding.profile_build: off`; groups and internal turns do not start the exchange. The offer is once per profile across transports, not a separate identity for every sender using a shared bot. Bot-authored DMs are excluded. The claim re-reads persisted config under the existing cross-process file-lock primitive, and runs only after inbound preparation and home-channel notices succeed; refused input cannot consume the offer. The blocking claim runs in a context-preserving worker thread. Proxy delivery snapshots the existing pending notes into outbound user content and acknowledges only that snapshot after HTTP 200 acceptance, preserving local transcript text and the existing system/history prefix. Pre-acceptance failures/cancellation keep notes available for a later turn; newly staged notes are merged rather than replacing an undelivered offer. This retry state uses existing process-local conversation state, not a durable outbox: restart or an explicit conversation boundary may discard an undelivered note while the profile claim remains recorded.

Both names have explicit UTF-8 file destinations in the active profile: `USER_NAME.txt` and `AGENT_NAME.txt`, each containing only the name and a newline. The directive also maintains labeled names and agent personality in `SOUL.md`, with user facts/preferences in the existing user memory. Renames and forgetting must update all applicable copies. Writes use existing tools/approval gates; these instructions do not guarantee model compliance, and disabled tools or failed/pending writes must be reported honestly. Session history resumes an interrupted exchange; there is no separate resumable onboarding state machine.

## 2026-10-16 — Keep optional Home reads outside worker write receipts

Use an authenticated `worker.home.recall` read with profile, process identity, adoption digest, epoch, session and generation fences. It consumes no write sequence and stores no replayed evidence. A lost read response must not leave an unacknowledged journal entry or make later transcript persistence fail. Keep strict receipt replay for durable mutations.
