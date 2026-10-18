# web/ + hermes_cli/web_routers/ — the dashboard (`hermes dashboard` → `/chat`)

Project authority: the root `AGENTS.md` and `docs/project/` define goals and workflow. This file describes this area’s implementation contracts. External issue references are technical history, not approval requirements or a separate contribution policy.

Applies on top of the root `AGENTS.md`. Backend routers: `hermes_cli/web_routers/*.py`, one file per
dashboard surface, mounted by `hermes_cli/web_server.py` (+ `web_server_*.py` siblings). Frontend:
`web/src/`. Shared JSON-RPC/WS client: `apps/shared` (`@hermes/shared`), also used by the desktop.

## The dashboard embeds the REAL `hermes --tui` — not a rewrite

`hermes_cli/pty_bridge.py` + the `@app.websocket("/api/pty")` endpoint in `web_server.py`:

- `web/src/pages/ChatPage.tsx` mounts xterm.js `Terminal` with the WebGL renderer, `@xterm/addon-fit`
  (container-driven resize) and `@xterm/addon-unicode11` (wide-character widths).
- `/api/pty?token=…` upgrades to a WebSocket; auth uses the same ephemeral `_SESSION_TOKEN` as REST,
  passed as a query param because browsers cannot set `Authorization` on a WS upgrade.
- The server spawns exactly what `hermes --tui` would spawn, through `ptyprocess` (POSIX PTY — WSL
  works, native Windows does not).
- Frames are raw PTY bytes each way; resize travels as `\x1b[RESIZE:<cols>;<rows>]`, intercepted
  on the server and applied with `TIOCSWINSZ`.

**Do not re-implement the primary chat experience in React.** Transcript, composer/input flow
(including slash-command behaviour), and the PTY-backed terminal belong to the embedded TUI; anything
added to Ink shows up here automatically. If you are rebuilding the transcript or composer for the
dashboard, stop and extend Ink (`tui_gateway/AGENTS.md`).

**Exception: the personal home (`/home`, `web/src/personal/`).** At the user's direction this is a
React chat surface in the style of a consumer assistant. It still owns no agent behavior: it drives the
existing `/api/ws` JSON-RPC (`session.resume`/`session.create`, `prompt.submit`, `session.interrupt`),
binds to the Home thread via `/api/home/open`, and answers `approval`/`clarify` server requests with
cards instead of bypassing them. Its board is stored per profile on the server (`hermes_cli/personal_board.py`); the
person configures it, and the agent may only add catalog cards through the `home_cards` tool, which the home renders. The
calendar tile signs in through Hermes's Google Workspace OAuth (`hermes_cli/personal_calendar.py`,
same files and scopes as the google-workspace skill). Avatar color is saved per profile via
`PUT /api/personal/preferences`. Keep slash commands, tool detail, and power-user flows in the embedded
TUI at `/chat`; extend the personal surface only with presentation and gateway calls that already exist.

**Structured React UI around the TUI is fine when it is not a second chat surface.** Sidebar
widgets, inspectors, summaries, status panels (`ChatSidebar`, `ModelPickerDialog`, `ToolCall`)
complement the embedded TUI. Keep their state independent of the PTY child's session and surface
their failures non-destructively so the terminal pane keeps working.

## `dashboard` vs `serve`

`dashboard` and `serve` share `cmd_dashboard` / `start_server` but are independent surfaces — neither
launches the other. `serve` is the headless backend the desktop app spawns (`headless_backend=True`:
`cmd_dashboard` skips `_build_web_ui` and exports `HERMES_SERVE_HEADLESS=1` so `mount_spa()`
disables the SPA even if a stray `web_dist/` exists — only JSON-RPC/WS/API is reachable). The
desktop has no build/runtime dependency on this frontend. Details: `apps/desktop/src/AGENTS.md`.

## Rules

- Auth: every new REST route and WS endpoint uses the same session token; never a second scheme.
- Routers are one-file-per-surface; a new surface is a new `web_routers/<surface>.py`, not a growing
  `web_server.py`.
- Tests: Python in `tests/hermes_cli/` (routers, pty bridge); JS in the `web/` vitest suite. Python
  tests must not assert about `package.json` / `.tsx` sources (root testing rules). Root TypeScript
  style rules apply.
