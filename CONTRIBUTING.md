# Contributing to Proactive Agent

Start with [AGENTS.md](AGENTS.md), [project status](docs/project/STATUS.md), and the [roadmap](docs/project/ROADMAP.md). This repository's user and project direction determine what to build. No external repository search, organization approval, Discord post, or separate development skill is required.

## Development and tests

Follow [local development](docs/project/DEVELOPMENT.md) for isolated state, PM-managed dependencies, and test setup. Read the [engineering guide](docs/project/ENGINEERING.md) and the nearest area `AGENTS.md` before editing code.

Use `scripts/run_tests.sh` for relevant Python behavior tests, `python scripts/check` for the normal lint/code-health workflow, and the relevant workspace scripts for JavaScript changes. Report checks actually run and any blockers. Documentation-only changes need link and consistency checks, not new runtime tests.

## Scope and design

Prefer existing code and extension seams. Core changes, new tools, memory/context providers, and in-tree plugins are allowed when they serve a concrete project goal. There is no blanket ban inherited from another project's contribution policy. Preserve prompt caching, profile isolation, dependency ownership, and permission boundaries; test intentional contract changes.

## Review and handoff

Explain the observable change, why it matters, validation results, and material limitations. Update project status and lasting decisions when needed. Follow user instructions for commits, pushes, and pull requests. Do not contact other maintainers or publish anything merely because reference documentation describes that workflow.

## JavaScript workspaces and website

Run `npm ci` at the root for desktop, TUI, dashboard, and shared workspaces; use the relevant `package.json` scripts and engines. The website has separate dependencies: `npm ci --prefix website`. Read each area's instructions before building or testing it.
