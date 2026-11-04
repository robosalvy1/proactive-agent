# Home dreaming

Dreaming is an opt-in, quiet review of recent participating chats. It saves short candidate notes about decisions, preferences, unfinished requests, and connections between chats. Home can retrieve those notes on later turns alongside the original conversation evidence. Chats remain independent.

## Controls

Use these slash commands in the classic CLI, Ink, or the dashboard's embedded terminal:

```text
/home
/home dream on
/home dream status
/home dream notes
/home dream now
/home dream off
/home dream clear
```

`on` enables automatic idle reviews in the existing gateway housekeeping loop. The gateway must remain running; no separate daemon or cron job is installed. `now` requests one foreground review, including while automatic dreaming is off. It skips the idle and cadence waits, but still respects active-turn leases, duplicate reservations, unchanged-source suppression and the daily call budget. Opening Home alone does not enable dreaming.

`status` shows enablement, running/last result and current note count. `notes` shows candidate text, creation dates, quoted source messages and session links. `off` pauses automatic reviews and revokes an in-flight result; previously saved valid notes remain available. `clear` removes dream notes, revokes an in-flight result, and checkpoints currently visible sources so unchanged chats will not regenerate them. New messages can be reviewed again. These controls do not erase native notes, external memory, exported data or already-sent model context.

Changing settings cannot unsend an already-dispatched model request. Its physical reservation remains held until it returns or expires, and a revoked response cannot publish notes. Gateway drain/retirement and shutdown discard late results and track physical work through existing owner tasks.

## Limits and model routing

- At most **four completion attempts per profile per UTC day**, including manual and failed runs. Automatic passes are at least six hours apart and need five quiet minutes. Active turn leases and owner work defer automatic reflection.
- One completion attempt per reservation; no transient, credit-cap or provider fallback retry ladder. An unavailable route or invalid response records failure and leaves the sources eligible. The next automatic attempt waits for its cadence; `now` allows an explicit retry within the daily budget.
- Up to three chats and **16,000 characters of JSON source data**, using recent evidence from the newest 128 eligible session rows and up to 24 conversational messages per logical chat. Individual source messages are truncated to 1,600 characters; oversized chats use fewer recent messages. Unchanged chats may provide context for connections, but entirely unchanged input makes no model call.
- A **1,200 output-token cap**, with a 30-second request timeout passed through the existing provider adapters. Stream-only/native adapters retain their transport timeout semantics. A provider that rejects the output cap fails; dreaming does not retry without it. This is a request/token budget, not a fixed monetary price.
- Up to six new candidate notes per pass and 32 stored notes. Each note has at most 500 characters and four exact source quotations. Home recall returns at most four relevant notes within a 2,400-character note allocation; notes and raw evidence together retain Home's 6,000-character cap. Recall itself makes no model call.

The model route is `auxiliary.home_dream`, defaulting to the profile's existing automatic auxiliary route. Choose **Home dreaming** in the existing model picker or configure its provider/model under that key. This is profile configuration, not the current chat's temporary model override. No provider credentials were added or configured during development.

## Source and authority rules

Dreaming reuses Home participation: older chats require explicit sharing, exclusions apply, and other profiles/principals, messaging groups, jobs, subagents and hidden chats are excluded. Reflection state is bound to the principal that enables it. Only plain conversational user/assistant rows are reviewed; hidden content, machinery notifications, tool outputs and synthetic compression summaries are omitted. Supported secret patterns are redacted before egress.

The model receives no tools. Its output must match a closed JSON schema, and every citation must name a supplied message and quote an exact substring. Original source timestamps travel with both the review input and stored citations; the review's creation time is separate. Decisions, preferences and open items require user-message citations. Connections require two separate chats and at least one user citation. This checks evidence provenance; it cannot prove that the model's interpretation is correct. Notes are labeled fallible candidates, never instructions, approvals or verified completion records. There are no unsolicited notifications, purchases, messages or task continuations.

Each note records source fingerprints. New conversational messages (including distant corrections), edits, rewind, deletion, hidden state and exclusion invalidate affected notes for future reads and late-result publication. Invalid notes are filtered on each read and pruned on subsequent completed passes. The bounded review window can also make an older note unavailable. This favors fresh evidence over retaining unchecked summaries indefinitely. Already-sent context remains stable under the existing prompt-cache contract; neither exclusion nor `clear` retroactively scrubs an active model conversation.

## Runtime and verification

State uses one bounded `state_meta` record in the existing profile database, not another memory service or scheduler. Reservations, day counters, cadence, source checkpoints and notes commit transactionally. A crash after reservation spends the attempt and preserves the cooldown; replay cannot duplicate notes. The reservation expires after ten minutes, and expired results cannot publish. Read/reflect/write phases release the SQLite transaction during the model request, then revalidate sources and settings before publication. Managed workers receive notes through the existing owner-mediated Home read. Notes never overwrite `MEMORY.md`, `USER.md`, prior messages or the stable system prompt.

Deterministic tests cover strict source citations, sharing/principal boundaries, corrections and revocation, input/output limits, spending and restart gates, concurrent claims, cancellation while physically running, profile scope after enqueue, and actual housekeeping registration. A local HTTP provider verifies one request on success, 503 and 402, auxiliary observer hooks, configured routing and the output cap. An agent-loop test verifies note injection and unchanged historical prompt bytes after the source changes. No live model quality benchmark, production transcripts or recurring test job was used. Exact check receipts are in [STATUS.md](STATUS.md).
