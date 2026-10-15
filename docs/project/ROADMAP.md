# Initial work queue

Items are ready to investigate, not promises of implemented functionality. Work in order unless the user directs otherwise. Keep each implementation slice reviewable.

## P0 — Verify the foundation

**Task:** prepare an isolated development instance and audit existing capabilities.

Read `DEVELOPMENT.md`, `docs/project/ENGINEERING.md`, and the relevant nested instructions. Run the smallest credential-free test slice first, then an interactive session if a development provider is configured. Produce `docs/project/CAPABILITIES.md` mapping existing context/memory, scheduling, background execution, plugins, settings, and UI flows to concrete source files and tests. Mark each as verified, present but unverified, configurable but hidden, or missing.

**Done when:** setup steps and actual results are recorded; at least one canonical test slice passes; blockers are explicit; proposed changes point to existing extension seams. Audit update/install routes before distributing this fork, since imported code still targets upstream in places.

## P1 — Establish fork validation

**Task:** adapt upstream lint and focused test workflows to standard runners and this repository's history, without bringing back release/publishing automation.

**Done when:** a sample behavior change fails its regression test before the fix and passes afterward; lint and tests run in CI without provider credentials; required local commands match CI.

## P2 — Deliver context continuity

**Task:** choose one repeatable multi-session task from the audit and improve how its goals, decisions, preferences, or unresolved work survive a session boundary.

The initial [Home thread implementation](HOME_THREAD.md) adds stable CLI/Ink/web navigation and bounded, source-linked transcript recall alongside independent chats. Deterministic integration tests cover request assembly, profile/owner boundaries, resets, and exclusions. The [larger design](HOME_THREAD_PLAN.md) still requires measured retrieval quality, learned-fact correction/forgetting semantics, and separate authorization/notification design before proactive coordination.

**Done when:** a synthetic before/after fixture demonstrates improved retrieval; source/freshness and correction/deletion behavior are documented; token use is bounded; session caching and profile-isolation regressions are covered. Record the storage/assembly decision before adding a new subsystem.

## P3 — Deliver one proactive workflow

**Task:** choose one user-enabled workflow with a concrete trigger and useful outcome, reusing Hermes scheduling and state.

**Done when:** authority and execution/notification budgets are explicit; pause/cancel, duplicates, retries, quiet hours, and restart behavior are tested; users can see what ran and why; the workflow is off until configured. A local dry run uses synthetic data and sends no external messages.

## P4 — Polish the daily loop

**Task:** improve setup → first useful task → progress/cancel → resume → outcome on the existing surface selected with the user.

**Done when:** a reproducible walkthrough demonstrates fewer confusing steps and clearer failures; interaction checks cover changed flows; relevant latency/cost measurements and remaining rough edges are recorded.

## Copyable first-task brief

> Read AGENTS.md and complete P0 in docs/project/ROADMAP.md. Use an isolated Hermes home, inspect actual source before drawing conclusions, and document commands and results. Produce a capability map and recommend the smallest context and proactive slices. Do not implement a parallel scheduler, memory store, or new UI during the audit.
