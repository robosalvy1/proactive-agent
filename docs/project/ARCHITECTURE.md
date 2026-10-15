# Architecture and code map

## Current foundation

The imported Hermes source is the executable foundation. There is no separate Proactive Agent runtime layer yet. Keep small improvements in existing modules; use established plugins where they fit. Read `docs/project/ENGINEERING.md` and nested `AGENTS.md` files before edits.

## Useful starting points

| Work | Source to inspect | Behavior to preserve |
| --- | --- | --- |
| Agent execution | `run_agent.py`, `agent/turn_*.py` | Turn lifecycle, cancellation, provider behavior |
| Context and memory | `agent/`, `plugins/context_engine/`, `plugins/memory/` | Stable prompt prefixes, compression, profile isolation |
| Persistent state | `hermes_state.py`, `hermes_state_*.py` | Session contracts and migrations |
| Proactive execution | `cron/`, `gateway/`, `tools/cronjob_tools*` | Job ownership, duplicate handling, scoped state |
| Capability access | `tools/registry.py`, `toolsets.py`, `plugins/`, `skills/` | Discovery, configuration, permissions |
| Setup and CLI polish | `hermes_cli/`, `cli.py` | Profile-aware config and actionable errors |
| UI polish | `ui-tui/`, `tui_gateway/`, `apps/desktop/`, `web/` | Existing transport and interaction contracts |
| Dependencies | `pm/`, `pyproject.toml`, `uv.lock` | PM ownership, lock consistency |
| Behavioral evidence | `tests/`, `evals/` | Isolated state, deterministic replay |

These are navigation hints, not a claim that every existing feature meets our product goals. The first task verifies the seams against current code.

## Proposed direction to validate

Use a persistent goal as the common unit linking user intent, relevant context, triggers, execution history, and outcomes. Start by mapping existing Hermes state rather than introducing another database or scheduler.

Context assembly should make relevance, freshness, token budget, and source traceable. New context must respect session caching and compression boundaries. A background run must bind its owning profile and carry only the authority granted to that goal.

A proactive workflow should move through trigger, relevance/authority/budget checks, execution, recorded outcome, and optional notification. Cancellation, retry, duplicate delivery, and restart behavior belong in the first vertical slice.

These are design constraints; concrete schemas and APIs require evidence from the capability audit and an entry in [DECISIONS.md](DECISIONS.md).
