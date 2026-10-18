# Minimal responses

The approved response cleanup uses Hermes' existing configuration and presentation paths. Explicit saved settings take precedence; there is no migration that rewrites a user's profile.

## Behavior

- Scheduled deliveries contain the result by default. `cron.wrap_response: true` restores the technical header and management footer.
- Creation/edit confirmations use the job name, schedule/timezone, and relevant delivery state. Local-only and paused jobs are labelled clearly.
- `hermes cron list` and `/cron list` use compact name-first rows. `--details` exposes identifiers, prompts and technical fields; `--all` includes inactive jobs. Name lookup remains ambiguity-safe.
- Manual-run summaries omit IDs and repeat output only for local-only or failed runs. Queued, unverified and failed delivery never reads as confirmed delivery.
- Missing personality settings inherit the existing concise overlay, unless a manual `agent.system_prompt` is present. Explicit neutral/custom selections remain effective. This is resolved through normal session setup, not a mid-conversation prompt rewrite.
- Supported Responses transports default to low text verbosity. An explicit empty value leaves sizing to the provider; chat-completions transport remains unchanged.
- Routine reasoning, commentary, tool-progress chatter, memory-update notices and turn/token statistics are off by default. Task outcomes, approvals, warning notifications and long-running indicators remain available.
- TUI thinking/tools follow the collapsed detail default; explicit section settings and `/details` still work. Desktop starts in its existing Simple mode and persists either explicit mode choice.
- Tool previews are bounded; desktop product summaries omit internal identifiers. Technical payloads remain available.
- Classic CLI startup uses a one-line banner. Resume shows one bounded exchange by default; `display.resume_display: full` expands the last answer, `resume_exchanges` controls history length, and `minimal` omits the recap.
- CLI provider errors lead with an actionable explanation. Verbose mode includes raw diagnostic detail. Failed cron listings report the failure instead of pretending there are no jobs.

## Validation

Validation uses synthetic state and mocked delivery only. No live provider, personal profile, external notification, or recurring job is needed. Check receipts and limitations are recorded in [PR #1](https://github.com/robosalvy1/proactive-agent/pull/1) and project status.

Presentation choices do not remove job identifiers from storage or APIs, change scheduling semantics, alter model replay records, or bypass approval boundaries. Model-written brevity remains guidance rather than a hard response-length limit. Existing explicit verbose settings remain explicit until changed by the user.
