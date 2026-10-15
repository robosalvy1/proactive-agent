# Project status

Last updated: 2026-10-15.

## Established

- Hermes source imported at the exact revision in `UPSTREAM.json`, retaining its MIT license, tests, and lockfiles. Agent instructions are now maintained for this project.
- Project-specific root `AGENTS.md`, product vision, architecture map, work queue, development instructions, and decision log.
- Upstream workflows archived outside the active workflows directory; upstream repository ownership and bot configuration archived as well.
- A limited foundation workflow for Python metadata and syntax checks. This is not upstream CI parity.

## Foundation verification

- Parsed `pyproject.toml` with Python's `tomllib` and compiled `agent/`, `cron/`, `gateway/`, `hermes_cli/`, and `pm/` successfully with Python 3.14.4.
- Compared every imported upstream tracked file with the pinned checkout: no missing files or unintended content changes; intentional documentation/automation adaptations are listed in `UPSTREAM.md`.
- Checked project documentation links and preserved upstream files that broad ignore patterns would otherwise hide from the initial commit.

## Not implemented or verified yet

- No project-specific context engine, proactive workflow, or UI redesign has shipped.
- Dependencies have not been provisioned; no provider has been configured and no live agent has been launched as part of the foundation setup.
- The Hermes runtime test suite and full lint suite have not been run for this initial import.
- Upstream update/install/distribution routes still exist in the source; project-specific distribution is not ready.

## Next action

Complete P0 in [ROADMAP.md](ROADMAP.md), then establish fork test/lint CI before changing runtime behavior. Record verified capability locations and concrete blockers. Preserve the distinction between imported features and behavior verified in this environment.

## Instruction cleanup

Project instructions now stand on their own: no required upstream root guide, external contribution skill, blanket ban on new providers/integrations, or third-party approval workflow. Engineering contracts remain in area guides. Contributor entrypoints and persona Markdown identify Proactive Agent; provenance remains in maintenance records and the license. This cleanup changes Markdown only.

## PR babysitting workflow

Added the invocation and authority in root AGENTS.md, with reviewer selection, feedback iteration, monitoring, and merge gates in PR_BABYSITTING.md. Bot availability has not been verified and no PR review or merge has been started by this documentation change.

## Messaging personalization

Added a first-private-message personalization directive across the shared messaging gateway, including runtime-registered adapters. Prior CLI/desktop conversations do not suppress it. The offer flag is profile-local and survives app changes and restarts. It asks one question at a time about both names, personality/style, and intended help; tasks take priority and users can skip. `onboarding.profile_build: off` disables it. Groups, internal events, local sessions, webhooks, and continuing conversations do not start it.

The directive uses existing memory/file tools: confirmed user facts go to user memory, names go to separate profile-local `USER_NAME.txt` and `AGENT_NAME.txt` files, and labeled names/personality also go to `SOUL.md`. Renames/forgetting must update all copies. File writes and progression remain model-driven and use existing approval gates; there is no separate onboarding state machine. Each app already appears in its session context's `Source` field. Future adapters inherit this through standard routing and accurate source metadata, documented in `gateway/platforms/ADDING_A_PLATFORM.md`.

Development validation passed 42 focused messaging tests, 5 future-adapter/persistence tests, and existing agent/TUI onboarding regressions. The original dirty checkout's full lint check found unrelated concurrent changes and ignored development state; isolated PR validation is pending. No live provider conversation, external delivery, or actual name-file writes through messaging services were tested. Next action: isolated PR checks, independent review, then a user-authorized live conversation to assess question quality and file writes.
