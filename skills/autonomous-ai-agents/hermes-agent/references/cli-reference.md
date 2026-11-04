# Tandem CLI Reference

Live sources when anything looks stale: `hermes --help`, `hermes <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
hermes [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
tandem chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
tandem setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
tandem model                Interactive model/provider picker
tandem fallback [add|remove|list]  Fallback provider chain
tandem config [show|edit|get|set|unset|path|env-path|check|migrate]
tandem login / logout       OAuth sign-in / clear stored auth
tandem doctor [--fix]       Check dependencies and config
tandem status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
tandem tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

tandem skills list|browse|search QUERY|inspect ID
tandem skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
tandem skills config        Enable/disable skills per platform
tandem skills check|update|uninstall|publish PATH
tandem skills tap add REPO  Add a GitHub repo as a skill source
tandem bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
tandem mcp add NAME (--url or --command) | remove | list | test NAME
tandem mcp catalog | install NAME     Curated catalog install
tandem mcp configure NAME             Toggle tool selection
tandem mcp serve                      Run Tandem as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
tandem gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `tandem photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
tandem sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
tandem cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
tandem webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
tandem profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
tandem profile rename A B | alias NAME | export NAME | import FILE
tandem profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
tandem auth                 Interactive credential manager
tandem auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
tandem auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
tandem desktop / gui        Native desktop app
tandem dashboard            Web admin panel + embedded chat (--stop / --status)
tandem proxy                OpenAI-compatible local proxy backed by an OAuth provider
tandem portal               Quick setup / sign in via Nous Portal
tandem kanban <verb>        Multi-agent work-queue board
hermes project              Named multi-folder workspaces
tandem skin list|use|set    Switch/tweak skins (see references/themes.md)
tandem pets <verb>          Pet mascots (see references/petdex.md)
tandem memory setup|status|off|reset   Memory provider
tandem secrets bitwarden|onepassword   External secret stores
tandem moa                  Mixture-of-Agents slots
tandem hooks / security / backup / import / checkpoints / console
tandem logs [-f] [errors]   View agent/error logs
tandem send                 One-off message through a gateway platform
tandem pairing / plugins / insights / journey / computer-use
tandem acp                  ACP server (IDE integration)
tandem completion bash|zsh|fish
tandem update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `tandem photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `tandem config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `tandem tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `tandem skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `tandem model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `tandem config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.hermes/logs/gateway.log` (or `tandem logs`) |
| Sessions | `tandem sessions browse` (reads state.db) |
