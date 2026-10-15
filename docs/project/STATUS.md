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
- Development dependencies are now provisioned in isolated state for response-polish validation; no provider has been configured and no live agent has been launched as part of this work.
- The full Hermes runtime test suite has not been run. Focused runtime and lint validation is recorded below.
- Upstream update/install/distribution routes still exist in the source; project-specific distribution is not ready.

## Next action

Complete P0 in [ROADMAP.md](ROADMAP.md), then establish fork test/lint CI before changing runtime behavior. Record verified capability locations and concrete blockers. Preserve the distinction between imported features and behavior verified in this environment.

## Instruction cleanup

Project instructions now stand on their own: no required upstream root guide, external contribution skill, blanket ban on new providers/integrations, or third-party approval workflow. Engineering contracts remain in area guides. Contributor entrypoints and persona Markdown identify Proactive Agent; provenance remains in maintenance records and the license. This cleanup changes Markdown only.

## PR babysitting workflow

Added the invocation and authority in root AGENTS.md, with reviewer selection, feedback iteration, monitoring, and merge gates in PR_BABYSITTING.md. Bot availability has not been verified and no PR review or merge has been started by this documentation change.

## Minimal response cleanup

Implemented the approved response-polish changes on the feature branch: concise defaults, clean scheduled deliveries, name-first cron summaries with explicit details, quieter UI defaults, bounded resume output, and actionable errors. [RESPONSE_POLISH.md](RESPONSE_POLISH.md) records the behavior and controls.

Provisioned an isolated PM-managed Python test environment and JS workspace dependencies. Focused Python/TUI/desktop regressions and the 12-check staged lint gate have passed during development; final acceptance and the desktop type check are still in progress. No live provider, personal profile, external delivery, or recurring test job was used. Full-suite runtime verification remains outstanding.
