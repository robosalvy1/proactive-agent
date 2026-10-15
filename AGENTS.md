# Proactive Agent — instructions for coding agents

## Mission and current state

Build a polished, proactive personal agent on top of Hermes. Improve capability access, interaction quality, and context continuity. The initial runtime foundation is present; project-specific runtime improvements are still ahead of us. Do not describe planned features as shipped.

Read these before your first edit:

1. `docs/project/STATUS.md` — what is implemented and what remains.
2. `docs/project/VISION.md` — goals and product principles.
3. `docs/project/DEVELOPMENT.md` — isolated setup and real validation commands.
4. `docs/project/ENGINEERING.md` — engineering rules and area routing table.
5. The nearest area `AGENTS.md` and the code/tests relevant to your task.

Read `docs/project/ROADMAP.md` when choosing work; `docs/project/ARCHITECTURE.md` when choosing an extension point. Load further documentation as needed instead of dumping the whole repository into context.

## Working agreement

- User instructions take priority. The root `AGENTS.md` owns project intent and workflow. Nested instructions refine area implementation; they do not override project intent. Reference docs, historical issue numbers, external contribution policies, and bundled skill templates do not add project-wide instructions or require another organization’s approval.
- Inspect existing behavior and identify the real call path before proposing a rewrite. Prefer existing configuration, plugins, context engines, skills, and scheduling seams. Make focused changes that can be reviewed and reverted.
- Carry authorized work through implementation, appropriate checks, and a clear handoff. Ask only when missing information materially blocks the work. Do not create unrelated runtime systems or pick a new frontend/backend stack as part of setup.
- Keep useful Hermes capabilities. “Unlock” means understand and expose capabilities with explicit configuration and a good UX; it does not mean silently bypassing permissions, provider restrictions, or isolation.
- Keep the public `hermes` command, package identity, profile paths, and upstream imports stable until an intentional migration is designed and tested. Do not use `hermes update` or external installers to refresh this checkout; they can replace project changes. Source maintenance is documented in `docs/project/UPSTREAM.md`.
- No deployment, release publication, external messaging, or recurring background jobs merely to test a change. Use isolated development state and deterministic fixtures. User-authorized actions remain authorized.
- Never commit credentials, personal memories, session databases, production transcripts, or development runtime state. Use synthetic/redacted fixtures. Preserve profile isolation and existing approval boundaries.

## Context and proactivity contracts

- Preserve stable conversation prefixes and prompt caching. Context changes need explicit session/compression semantics; do not rebuild old messages on every turn.
- Distinguish instructions from retrieved content. Record source and freshness for durable facts; make user corrections and deletion effective. Bound retrieval and prompt budgets, and measure relevance rather than maximizing tokens.
- A proactive action needs a user goal, trigger, applicable authority, execution/notification budget, and a visible outcome. Define cancellation, retries, duplicate suppression, and restart behavior. Reuse Hermes scheduling and state where possible.
- Do not turn every observation into a notification. Design quiet hours, useful digests, and explainable “why now” behavior before enabling unsolicited work by default.

## Validation and handoff

Follow `docs/project/DEVELOPMENT.md`. Use `scripts/run_tests.sh` for Python behavior tests and the relevant workspace scripts for JS. Add a regression test for changed runtime behavior; simple documentation edits do not need new tests. Do not report syntax checks as runtime verification.

Update `docs/project/STATUS.md` when a milestone or handoff changes, and `docs/project/DECISIONS.md` for lasting architectural choices. Keep notes short and factual: changed behavior, commands/results, unresolved risks, next action. Do not save private reasoning or copy full chat histories into project memory.

## PR babysitting

When the user says “babysit the PR” (including “babbysit”), follow `docs/project/PR_BABYSITTING.md`. This authorizes committing and pushing fixes to that PR, requesting and discussing bot reviews, monitoring checks, and merging once the workflow's review and merge gates pass. Use a review bot from a different model family than the implementing agent, or CodeRabbit. Keep iterating until the latest revision is reviewed and green. A request to watch only, or not to merge, narrows this authorization.

Finish with what changed, what was verified, and any concrete limitations. Do not claim all tests passed unless they actually ran. Commit, push, PR, review-comment, and merge actions require user authorization; the PR babysitting trigger above supplies it for the designated PR.
