# Home thread: research and implementation plan

Date: 2026-10-15. Status: initial implementation complete; see [HOME_THREAD.md](HOME_THREAD.md) for implemented behavior, validation, and limits.

## Implementation refinement

The first implementation uses canonical transcript evidence and the existing FTS index rather than adding the proposed extracted-record schema and ingestion queue. This supplies immediate, restart-safe cross-chat recall without duplicate fact storage, model extraction calls, or new background jobs. Home routing and participation use existing profile-owned metadata; workers read through the owning runtime's receipt protocol. The sections below retain the larger design direction, including future correction/deletion and proactive coordination requirements; they are not a list of shipped capabilities. In particular, no “Chat only” privacy guarantee or learned-fact forgetting interface is implemented.

The subsequent user-requested [dreaming implementation](DREAMING.md) adds a bounded candidate-note store and opt-in idle reflection through existing housekeeping. It uses source fingerprints and exact quotations, durable per-pass/day budgets and cancellation revisions. This does not implement the stronger fact-level forgetting or sanitized-context boundary proposed below.

## Product proposal

Build one persistent personal agent with a **Home** conversation and as many separate chats as the user wants, available from both the CLI and web dashboard. Home is the place to ask “where are we?” across ongoing work. Each chat retains its own transcript, working directory, model selection, execution state, and approvals. Relevant knowledge can travel between participating chats without merging their transcripts.

Example: discuss a June trip in a Travel chat, record an agreed budget there, then ask Home what needs attention. Home can recall the budget and unresolved booking, cite the Travel messages, and offer to resume that chat. A Coding chat does not receive the trip transcript just because both exist. Learning about an unfinished booking does not authorize purchasing it.

“God thread” is an informal product description. Use “Home” in the interface. Continuity must survive closing every frontend; it must not depend on a permanently running model conversation.

## Research: what the products actually document

Sources accessed 2026-10-15. These establish public behavior and design patterns, not independently verified performance.

- **Muse:** Meta's [design article](https://introducing.muse.ai/) explicitly describes a long main conversation, side chats for separate context, memory across conversations, concurrent requests, and background work whose results are filtered before notifying the user. It also describes editable memory files, an activity view, goals, and deterministic approval controls. The [launch announcement](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) describes remembering preferences, forgetting learned information, and checking with the user before sensitive actions. This supports a main-chat-plus-side-chats product. These sources do not specify its retrieval ranking, compaction algorithm, database schema, or concurrency protocol; we should not claim to reproduce those internals.
- **Letta:** its [Conversations announcement](https://www.letta.com/blog/conversations/) documents one agent with concurrent, independent conversations, shared memory, and searchable messages across those conversations. This is a particularly close architectural precedent for preserving multiple chats. Its [memory blocks documentation](https://docs.letta.com/v1-sdk/memory/memory-blocks) describes bounded, persistent sections prepended to model context, including shared blocks. That establishes a useful separation between agent identity, memory, and conversation history. Directly refreshing such a block inside Hermes' existing system prompt would violate this project's caching contract.

Synthesis for this project: combine a persistent relationship, separate working conversations, bounded cross-chat recall, and visible work state. A single unbounded prompt is not required to deliver that experience. Background execution is a separate layer with separate authority and notification rules.

## What is already in this checkout

The following is **source inspection only**, not a completed P0 capability audit or evidence that the runtime works in this environment.

| Capability | Concrete seam inspected | Implication |
| --- | --- | --- |
| Classic CLI conversations | `hermes_cli/cli_session_mixin.py`: `new_session`, recent-session listing, boundary handling | Extend existing new/resume behavior. |
| TUI sessions and shared backend | `tui_gateway/methods_session.py`: creation/resume; `tui_gateway/session_registry.py`; `tui_gateway/contracts/sessions.py` | Home resolution should return an ordinary resumable conversation through existing session ownership rules. |
| Web chat | `web/src/pages/ChatPage.tsx`; `hermes_cli/web_routers/chat_ws.py`; `web/AGENTS.md` | The dashboard embeds Ink over a PTY. Extend its session list/navigation and the shared TUI; keep its transcript and composer there. |
| Durable transcripts | `hermes_state_common.py`, `hermes_state_schema.py`, `hermes_state_messages.py` | Existing profile-owned SQLite state, message UIDs, compression lineage, and resume resolution are the storage foundation. |
| Concurrent writers | `hermes_state_compression.py`: session turn leases; `agent/turn_facade_lease.py` | Reuse conversation leases; independent chats may execute independently. Do not make Home a global execution lock. |
| Curated memory | `tools/memory_tool_store.py`: `MemoryStore`, frozen prompt snapshots, locked file edits; `tools/memory_tool.py`: write gates | Preserve `MEMORY.md` / `USER.md`, existing permissions, and compatibility. Flat notes alone do not provide the proposed structured continuity records. |
| Recall and ingestion | `agent/memory_provider.py`, `agent/memory_manager.py`; `agent/turn_context.py`: `_memory_turn_start_and_prefetch`, `compose_user_api_content`, `_stamp_api_content_sidecar`; `agent/turn_finalizer.py` | Existing provider lifecycle and append-only per-turn recall are the starting points. `sync_turn` is asynchronous, so it cannot alone guarantee durable capture. |
| History retrieval | `tools/session_search_tool.py` | Existing FTS5 search, scoped reads, and source links can support evidence lookup. It also supports explicit cross-profile reads: automatic continuity needs a narrower scope. |
| Compression | `agent/context_engine.py`: `compress`, `select_context`, `on_turn_complete` | Keep the existing compressor initially. Request replacement can change the cache prefix; turn-complete observation is explicitly best-effort. Neither should become the sole durable event source. |
| Ongoing execution and outcomes | `hermes_cli/goals.py`; `tui_gateway/session_notifications.py`; `cron/` | Session goal continuation and addressed completion routing already exist. A personal overview should link them; a new global planner or scheduler is unnecessary for the first slice. |

Existing regression suites to consult include `tests/tools/test_session_search.py`, `tests/tools/test_memory_tool.py`, `tests/agent/test_memory_provider.py`, `tests/agent/test_context_engine_select_context.py`, `tests/hermes_state/test_session_turn_lease.py`, `tests/tui_gateway/test_session_resume_db_ownership.py`, `tests/hermes_cli/test_pty_session.py`, and the existing TUI/dashboard PTY end-to-end tests.

## User-facing contract

- The feature is opt-in per personal profile. It adds a pinned Home entry and preserves ordinary New chat, rename, resume, branch, archive, and delete behavior. Existing launch defaults remain unchanged until the user chooses Home as their landing chat.
- Home resumes the same logical conversation across restarts and compression. Its name is cosmetic; renaming another chat to “Home” cannot change routing.
- Both classic CLI and Ink expose a proposed `/home` command plus their existing new/resume controls. Ink's session picker identifies Home; the dashboard's existing `ChatSessionList` offers the same destination. Web links resolve the current resumable tip through the backend.
- Participating chats show “Shared with Home.” Existing chats require explicit inclusion; after feature enablement, new personal chats may default to participation with a visible choice at creation. No silent ingestion of historical conversations, other profiles, messaging groups, or other users.
- A proposed “Chat only” mode disables continuity publication and recall. It must also gate native memory reads/writes, background extraction, external memory hooks, automatic session search, and searches from other participating chats that could discover it. Ship the label only after all those paths are covered. Until then, a separate Hermes profile is the supported boundary for separate memory. This is a context-sharing control, not a sandbox against arbitrary filesystem access by authorized tools.
- A shared fact has an inspectable source, age, scope, and status. Users can correct it, forget it, or exclude its source chat. Home shows short summaries and source links; the original detailed work stays in its chat.
- Unread updates are stored even when no UI is open. An overview request may read them; it does not silently launch a new task. Existing approvals belong to the original task and cannot be approved by an overview summary.

## Proposed implementation shape

Use the existing profile's `state.db`, with focused `hermes_state_<topic>.py` siblings and additive migrations. Keep command/package names and profile paths unchanged. Do not introduce a hosted memory dependency or another scheduler. Exact DDL and API signatures are implementation-review outputs, not adopted schemas in this document.

### 1. Stable Home identity and chat participation

Add a profile-owned Home binding to a canonical conversation anchor and explicit participation metadata for logical chats. Resolve that anchor through existing compression/resume semantics on use. Do not overload `parent_session_id` to mean “belongs to Home”: it already represents transcript lineage/branches. Do not treat a transient UI session ID or PTY channel as a durable chat ID.

Creation is transactional and idempotent: two clients asking for Home get one binding. Follow existing authority/admission and conversation lease paths when opening it. A second writer to the same Home conversation gets existing attach/busy behavior; a different chat keeps running.

Specify and test lifecycle rules: compression keeps identity; a new ordinary chat gets its own identity; a branch gets its own participation decision; reset ends a Home segment but preserves the Home role for its explicit replacement. Archiving Home hides its history from normal lists but `/home` explicitly resumes it. Deleting Home clears the binding and excludes/deletes derived records according to the deletion contract; recreate only on the next explicit Home request. Never repoint it to an unrelated “latest” session. Exports/imports do not overwrite a destination profile's Home binding.

### 2. Source-linked continuity records

Add bounded records for a decision, preference, open item, or outcome. Proposed fields: stable record ID, scope/owner, source conversation and message UID(s), kind, concise content, created/observed/verified timestamps, revision, active/superseded/forgotten status, and optional related goal/task ID. Treat model extractions as candidates; separate explicit user statements from inferred claims and tool-reported outcomes. Assistant suggestions alone are not user decisions, grants of authority, or verified completion.

Start with explicit user-approved publication of a decision/open item and deterministic outcome capture. Add automatic candidate extraction only after evaluation and a bounded auxiliary-call policy exist. Keep curated native memory as its existing store; do not maintain a second editable copy of `MEMORY.md` in SQLite. Continuity records describe sourced work state, with one authoritative record per item and revisions for corrections.

Publication checks participation and ownership inside the write transaction. Use message UIDs plus logical conversation identity to avoid duplicate extraction across resume, fork, replay, and compression; inherited fork messages must not be republished as new evidence. For editable records use compare-and-swap revisions; divergent updates remain a visible conflict until resolved. Explicit user correction supersedes an older inference rather than relying on last-write-wins.

For durable automatic processing, add a small transactional pending-work record at the successful transcript persistence boundary, rather than relying on `on_turn_complete` or in-memory `sync_turn`. Process it on the next foreground turn/startup initially. Use bounded batches, recorded attempts/errors, a recoverable worker claim, and a unique source/version key. A restart may replay processing without duplicating records. This is a local indexing queue, not authorization to continue the user's task or start a daemon. Failed/interrupted turns cannot mark work complete.

### 3. Bounded, cache-safe recall

Reuse the memory manager's turn-start and API-content sidecar flow. Implement a built-in continuity source with additive host integration, preserving the configured external provider slot and native memory tools. Do not require swapping the user's memory provider or context engine. Confirm initialization, skip-memory flags, profile binding, and cleanup on all frontends before choosing the final class placement.

At turn start: validate principal/profile and participation, take a consistent record revision snapshot, filter excluded/forgotten/superseded sources, retrieve relevant records, and freeze one context packet for that turn and its retries. Prefer current topic/linked work, explicit statements, and fresh verified evidence. Start with SQLite filters/FTS and source links; defer embeddings until fixtures show a recall gap.

Proposed initial limits to measure: at most 8 records and 1,500 tokens of injected continuity, further reduced to available model headroom; no synchronous summarization LLM on the recall path. Limit storage candidate lengths and search work as well as returned tokens. Keep the global Home overview bounded and paginated. Low relevance returns no injection. Recall/storage errors leave chat usable and expose a non-destructive status, with no broader-scope fallback.

Append recalled data through the existing current-user API sidecar or an explicit tool result. Preserve exact previously sent bytes and the stable system prompt on normal turns. Recalled data must be labeled as evidence, not instructions or permission. Review `build_memory_context_block`'s current wording (it calls memory authoritative reference data) before reusing it for fallible extracted records. Do not use request-wide `select_context` reconstruction for this feature.

### 4. Correction and deletion semantics

Forgetting immediately tombstones the record, cancels pending re-extraction, and invalidates recall caches. Source exclusion/deletion removes derived search visibility and pending ingestion; normal archive does not mean forget. Keep a minimal suppression marker so retained raw transcripts cannot automatically re-create forgotten facts. A source-message edit/rewind invalidates dependent records; a compression copy preserves evidence identity. Storage deletion and “forget learned fact” are separate, clearly named actions.

Already-sent model context cannot be erased while simultaneously preserving its cached bytes. A forget/exclude/correction affecting recalled content must end the affected active context segment and resume from sanitized authoritative state before another model call. Use an explicit history/compression boundary under existing mutation guards; clear replay sidecars, summaries, external-provider recall, and in-flight retrieval results that contain revoked material. Include a revision check immediately before request dispatch to reject a stale packet. A correction appends the replacement evidence; forgotten material is not quoted back as part of that notice.

If an affected chat is busy, serialize the change with its lease: cancel/finish the in-flight call as supported, persist revocation, and prevent its next dispatch from using stale state. Clearly report when completion is pending; do not report immediate removal from an already-dispatched provider request. Define equivalent deletion/invalidation capability for any external provider before advertising the guarantee with that provider enabled. Previously exported data is outside local deletion's reach.

### 5. Overview first, proactive coordination later

Home's first overview answers on demand: current open items, recent meaningful outcomes, conflicts needing input, and links to source chats. Store updates as facts/events; do not run an LLM turn in Home whenever another chat changes. This avoids contention and unnecessary model/notification cost.

Later, link authorized `/goal`, cron, and delegation results to those records. Reuse existing execution and owner-addressed notification paths. Before enabling unsolicited work, specify goal, trigger, authority, spend/iteration/deadline limits, notification cap, quiet hours, cancellation, duplicate keys, bounded retries, and restart behavior. Completion notices stay associated with the originating work; Home may summarize the same event without consuming its approval or executing it twice. Home receives no ambient authority over every side chat.

## Delivery sequence and acceptance gates

1. **Foundation evidence (P0/P1 prerequisites).** Prepare the isolated PM/test environments from `DEVELOPMENT.md`, map the above flows with synthetic data, run focused existing tests, and establish fork validation for touched areas. Record setup blockers rather than treating source inspection as runtime proof. Do not require a production provider or production chat import.
2. **Home navigation with multiple chats.** Add Home binding, lifecycle handling, feature configuration, and classic CLI/Ink/dashboard entrypoints through existing session controls. Done when Home + two side chats survive switches/restart/compression independently; simultaneous Home opens converge; separate-chat work remains usable; ownership/permission behavior is unchanged. Shared recall is not yet advertised.
3. **Explicit continuity vertical slice.** Add participation controls, sourced records, revisioned corrections/deletion, bounded recall, and inspection. Done when a synthetic Travel decision is recalled from Home and a relevant participating chat with a source link, stays absent from excluded chats/profiles, and cannot return after forgetting, replay, or restart. Cover all native/external memory and search paths before labeling “Chat only.”
4. **Reliable capture and overview.** Add transactional pending ingestion, bounded optional extraction, conflict presentation, and an on-demand Home overview. Done when crash/retry/compression/branch fixtures produce no duplicate facts, no lost committed ingestion, and no invented completed tasks. Show indexing lag/errors. Compare extraction quality and cost before enabling defaults.
5. **One authorized proactive workflow (P3).** Attach a selected existing goal/job result, implement the interruption policy above, and test restart/cancel/duplicate behavior using a local dry run. This is a later milestone, not part of a hidden always-on Home loop.

Each step should be a separately reviewable change. The first useful feature is Home navigation; the first proof of the larger idea is step 3, not a broad UI redesign.

## Verification plan

Use deterministic synthetic fixtures and a stub model where model requests must be inspected. Add behavior tests with implementation; no tests are needed just for this plan.

- **Continuity:** known relevant decisions retrieved with source/freshness; irrelevant topics omitted; explicit corrections win; assistant suggestions and failed tool outputs cannot become confirmed facts/outcomes.
- **Multiple chats:** three independent transcripts; classic CLI and Ink new/resume; dashboard switch/reconnect and duplicate tabs; concurrent distinct chats; two clients opening/writing Home; no result delivered into the wrong chat.
- **Boundaries:** two profile homes in one process, including off-turn ingestion; excluded chat retrieval by query, direct ID, browse, and source links; native/provider memory writes and background reviews; group/other-user sessions excluded; no environment mutation.
- **Lifecycle:** restart around transcript commit/indexing commit, retry exhaustion, rewind/edit/delete/branch/import, compression tip rotation, lease expiry, and two concurrent conflicting publications.
- **Cache and deletion:** captured requests have an identical old prefix on ordinary turns; retries reuse recall; forgetting forces an explicit sanitized boundary; no revoked fact survives sidecars, summaries, pending work, external recall, or late worker completion.
- **Budgets:** fixture-level relevant-record recall and irrelevant-record rate, injected tokens, retrieval latency, auxiliary extraction calls/cost, and ingestion lag. Initial targets: all required facts in the curated positive fixtures, zero leaks/revocations missed, strict token cap, and zero model calls for idle Home updates. Latency/cost thresholds follow measurements on a provisioned environment.

After isolated setup, select the smallest relevant Python suites with `scripts/run_tests.sh`, including the existing suites listed above and new continuity/Home tests. For changed wire models run `python scripts/gen_gateway_contracts.py` and `scripts/run_tests.sh tests/tui_gateway/contracts/test_generated.py -v`. For frontend changes use `npm run check --workspace ui-tui`, `npm run check --workspace web`, and `npm run check --workspace @hermes/shared` as applicable, plus focused real PTY interaction checks. Run `python scripts/check` and `git diff --check` for implementation changes. A live smoke check needs a configured disposable provider and is reported separately from stubbed tests.

## Open implementation questions

- Confirm the canonical logical conversation identity across reset, branch, compression, and all transports before writing the migration. Existing lineage alone must not accidentally group independent forks.
- Complete the visibility/deletion audit of built-in notes, session search, and each enabled external provider. Home can ship before automatic sharing; “Chat only” cannot ship as a promise that only one path enforces.
- Validate a sanitized context boundary across providers before claiming effective deletion in active chats. This may require a small generic host API rather than a plugin-only implementation.
- Automatic extraction, embeddings, project-level sharing, multi-user Home, and notification defaults remain later choices. The recommended MVP uses explicit publication and personal-profile scope.
