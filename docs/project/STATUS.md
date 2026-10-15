# Project status

Last updated: 2026-10-15.

## Home thread implementation

### Dreaming

Added opt-in `/home dream on` idle reflection through existing gateway housekeeping. It reviews bounded recent participating transcripts, stores short candidate notes with exact source quotations, and makes those notes available through Home's existing current-user sidecar and owner-mediated worker read. `/home dream now`, `status`, `notes`, `off`, and `clear` expose manual runs, inspection, pause and removal. Budgets persist across restart: four attempts per UTC day, six hours between automatic passes, at most three chats/16,000 input characters and 1,200 output tokens per attempt. Automatic runs need five quiet minutes and a running gateway. No tools, unsolicited notifications, task continuation, new daemon or cron job. [DREAMING.md](DREAMING.md) records the controls, source freshness and cancellation contracts.

Validation: `HERMES_TEST_FILE_RETRIES=0 HERMES_PYTHON="$PWD/.venv/bin/python" scripts/run_tests.sh` on `tests/hermes_state/{test_dreams,test_worker_dreams,test_worker_home}.py`, `tests/agent/{test_home_dream_model,test_home_memory}.py`, `tests/gateway/test_home_dreams.py`, and `tests/hermes_cli/test_home_dreams.py` passed **44 tests across seven files without retries**. A separate run on `tests/agent/test_home_wire.py`, `tests/hermes_cli/{test_home,test_commands}.py`, `tests/tui_gateway/test_home.py`, and `tests/tui_gateway/contracts/test_generated.py` passed **58 tests across five files**. Local HTTP fixtures verified configured auxiliary routing, observer hooks, one completion attempt on success/503/402, tool omission and the output cap; the real agent-loop fixture verified dream-note injection and preserved old prompt bytes after source invalidation. Existing housekeeping/profile-scope regressions also passed. Ink Home command tests passed **4 tests**, type checking and focused ESLint passed. Changed Python files passed Ruff; final code health passed with zero blocking/advisory findings; whitespace and documentation-link checks passed.

Final source-date follow-up: the same no-retry runner on `tests/hermes_state/{test_dreams,test_worker_dreams}.py`, `tests/agent/{test_home_dream_model,test_home_wire}.py`, `tests/gateway/test_home_dreams.py`, and `tests/hermes_cli/test_home_dreams.py` passed **35 tests across six files**. It verifies original source dates separately from review dates, excludes machine-generated notifications from user evidence, and checks caps even with conflicting auxiliary extra-body settings.

The full 12-check checker still flagged the previously recorded ignored dependency archive and unrelated Ruff finding; its new fail-open exception-boundary finding was resolved with a documented exception for logging only the provider error class, keeping transcripts/credentials out of error logs. Final health and changed-file Ruff passed. All execution used isolated fixtures; no production profile was enabled and no live-provider quality/cost benchmark was run. Notes are fallible, retrieval remains keyword-based, and source changes conservatively invalidate notes until rereview. Clearing/exclusion changes future recall, not already-sent context or native/external memory. Next action: use a disposable configured provider to evaluate note quality and cost before increasing the default budgets or adding semantic retrieval.

### Home foundation

Implemented stable Home navigation in classic CLI, Ink, and the dashboard, preserving ordinary independent chats. Explicit opening enables profile-local, bounded recall from participating personal transcripts; older chats require `/home share`. `/home exclude`, `/home off`, `/home status`, and `/home overview` expose controls. Home follows compression and canonical local resets; workers use owner-mediated recall and dashboard writes use the existing live-owner/exclusive-maintenance paths. [HOME_THREAD.md](HOME_THREAD.md) describes usage and limits; [HOME_THREAD_PLAN.md](HOME_THREAD_PLAN.md) retains primary-source research and future design gates.

Validation in isolated synthetic state: the final `HERMES_PYTHON="$PWD/.venv/bin/python" scripts/run_tests.sh` run on `tests/agent/{test_memory_agent_context,test_memory_provider_init,test_home_memory,test_home_wire}.py`, `tests/hermes_state/{test_home,test_worker_home}.py`, `tests/gateway/test_home.py`, `tests/hermes_cli/test_web_home.py`, and `tests/tui_gateway/test_home.py` passed **41 tests across nine files**. This includes a real agent loop against a local mock HTTP model, old-prefix preservation, worker ownership, and canonical reset. Earlier targeted runs also passed the existing 60 memory-provider tests, classic CLI Home test, and generated/canonical contract checks. Dashboard component regressions passed **7 tests**, and Ink Home command regressions passed **3 tests**. Web and Ink type checks passed. Changed Home Python files passed Ruff; code health passed with zero blocking/advisory findings; whitespace checks passed.

Rendered browser walkthrough used the actual dashboard session-list components and real authenticated API in an isolated harness: Home → New chat → Home returned the same Home ID, and a separate Travel chat remained selectable. This checks navigation, not a complete live PTY/model conversation. A delayed Home response after selecting another chat is covered by a regression test. The harness initially had authentication/bootstrap errors, corrected before the walkthrough; its Vite development imports also emitted browser-externalization warnings.

Repository-wide `scripts/check` was not green: it flagged an ignored dependency archive in `.dev/hermes-home/cache/uv/` and an unrelated Ruff finding at `tests/hermes_cli/test_history_commentary_display.py:528`. The Home Ruff and oversized-file findings from the earlier full check were fixed; the subsequent health run passed. No production state, external delivery, recurring job, or live provider was used. Recall is keyword-based, with source excerpts rather than a learned fact store. Exclusion affects future Home retrieval and does not scrub existing model context/native notes/explicit history search. Next quality milestone: evaluate paraphrases, distant corrections and distractors before adopting semantic retrieval or extracted facts; proactive coordination and learned-fact forgetting remain unimplemented.


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

Proxy retry follow-up: proxy requests now snapshot pending notes and acknowledge that snapshot only after HTTP 200 acceptance. Connection failure, HTTP rejection, or cancellation before acceptance leaves notes available for the next turn; staging fresh context preserves the undelivered offer, and acknowledging an older request preserves newer notes. Three failure/retry regressions failed before the fix and passed after it; a fourth test covers in-flight staging. The canonical runner on `tests/gateway/test_messaging_onboarding_delivery.py tests/gateway/test_proxy_mode.py tests/gateway/test_prompt_tail_freeze.py -q` passed **29 tests**, with **two macOS-only skips on Linux**. All **12 repository checks** passed with zero code-health findings. This uses existing process-local conversation state: restart or an explicit conversation boundary can discard an undelivered retry note, while the profile claim remains saved. Durable outbox/restart recovery remains outside this implementation.
