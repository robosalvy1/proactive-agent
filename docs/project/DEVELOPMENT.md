# Local development

## Prerequisites

Use Git and the native build tools required by the surface you work on. Hermes PM owns the Python runtime and dependencies; this baseline targets Python 3.14. JavaScript workspaces also require Node/npm versions accepted by their `package.json` engines. Use an ordinary terminal outside an installed Hermes app.

## Prepare an isolated checkout

From this repository root in Bash:

```bash
export HERMES_HOME="$PWD/.dev/hermes-home"
export HERMES_RUNTIME_DIR="$HERMES_HOME/tools"
source ./activate
```

These paths are ignored by Git. Keep the same environment variables for later commands. Activation provisions tools and dependencies and can download substantial assets. It does not install JS workspaces. Do not point this environment at your real Hermes profile or copy production secrets into the repository.

For PowerShell and platform prerequisites, follow the retained [PM developer workflow](../../website/docs/reference/package-management.md#developer-workflow), substituting this repository and a disposable development home.

Configure a development provider interactively with `hermes setup`, then launch `hermes` from the activated shell. Provider credentials and live calls are only needed for live runtime checks. This bootstrap does not configure them or start background services.

## Prepare tests

After activation, build a separate test interpreter:

```bash
python -m pm.build_env --source . --out .venv --group dev --group test
scripts/run_tests.sh tests/agent/ -v
```

The output `.venv` must not already exist. Reuse an existing prepared environment when valid; do not delete it blindly. The canonical runner detects it, isolates user state, and clears credentials. Select the smallest relevant test path for your change. Do not use bare pytest or mutate PM-owned environments with pip/uv.

For lint and code-health checks on normal feature branches:

```bash
python scripts/check
```

This checker compares Git history/index against a base; it is not a useful verdict on a completely untracked initial source import. The foundation CI below provides only syntax and repository checks. Once the baseline is committed, establish the project's lint/test CI using the retained tools before claiming parity with upstream CI.

For desktop, TUI, dashboard, and shared JS work, run `npm ci` at the root and use the relevant workspace's scripts and area instructions. The website is separate; see [CONTRIBUTING.md](../../CONTRIBUTING.md#javascript-workspaces-and-website).

## Initial foundation checks

```bash
git diff --check
python3 -c 'import pathlib, tomllib; tomllib.loads(pathlib.Path("pyproject.toml").read_text())'
python3 -m compileall -q agent cron gateway hermes_cli pm
```

These need no provider credentials and verify only whitespace, metadata parsing, and Python syntax. They do not establish runtime correctness or passing Hermes tests. The initial GitHub workflow parses metadata and compiles those source directories. Check whitespace locally for your own changes; inherited upstream formatting is retained in the source snapshot.

## Handoff

Record the behavior changed, exact checks run/results, and any unavailable dependency or live integration in the task handoff. Update [STATUS.md](STATUS.md) for milestone changes. Keep private runtime data in `.dev/`, never in documentation or fixtures.
