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

Development validation passed 42 focused messaging tests, 5 future-adapter/persistence tests, and existing agent/TUI onboarding regressions. The original dirty checkout's full lint check found unrelated concurrent changes and ignored development state. [PR #2](https://github.com/robosalvy1/proactive-agent/pull/2) isolates onboarding from that work; current isolated check results and review status are recorded on the PR. No live provider conversation, external delivery, or actual name-file writes through messaging services were tested. Next action: isolated PR checks, independent review, then a user-authorized live conversation to assess question quality and file writes.

Review follow-up: CodeRabbit identified duplicate claims from stale config, bot-authored DMs consuming onboarding, and refused input claiming the offer before sidecar staging. Claims now re-read persisted config under Hermes' existing cross-process file lock, exclude bots, and happen only after accepted inbound preparation and home-channel notices. Four new regressions failed before the fixes and passed afterward; stale opt-out and unreadable-config cases are also covered. `HERMES_PYTHON=/home/salvy/.t3/projects/proactive-agent/.venv/bin/python scripts/run_tests.sh tests/gateway/test_first_contact_dm.py tests/gateway/test_messaging_onboarding.py tests/gateway/test_messaging_platform_context.py tests/gateway/test_messaging_onboarding_claim.py tests/agent/test_onboarding.py tests/tui_gateway/test_first_contact_onboarding.py tests/gateway/test_local_context_ref_turn_text.py tests/gateway/test_auto_skill_title_input.py -q` passed **77 tests across eight files** in the isolated PR checkout. The complete `scripts/check` gate passed all **12 checks**, including zero code-health findings. Live messaging/model-driven name-file writes remain unverified.

Second review follow-up: moved the blocking claim to `asyncio.to_thread`, preserving routed profile context without stalling the gateway event loop. Proxy turns now consume staged sidecar notes into outbound user content through `gateway/proxy_messages.py`; local transcript text and existing system/history content stay unchanged. Two regressions failed before these fixes and passed afterward. Repeated the preceding eight-file canonical test slice plus `tests/gateway/test_messaging_onboarding_delivery.py` and `tests/gateway/test_proxy_mode.py`: **93 tests passed across ten files**, with **two macOS-only proxy tests skipped on Linux**. The complete repository gate passed all **12 checks** with zero code-health findings; changed-file Ruff and whitespace checks passed. Added test contract docstrings in response to the review documentation warning. No live remote agent or messaging service was contacted.
