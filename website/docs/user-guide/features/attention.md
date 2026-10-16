---
sidebar_position: 18
title: "Proactive Inbox (Attention)"
description: "One inbox and gate for everything the agent notices on its own: urgent items interrupt, the rest arrives in a digest, and commitments you mention get a check-in before they lapse."
---

# Proactive Inbox (`/inbox`)

The attention layer gives the agent one place to put things it notices without being asked: results from recurring scheduled jobs, and check-ins on commitments you mentioned in chat. A deterministic gate decides what happens to each item:

- **Interrupt now**: an alert sent immediately. Allowed only outside quiet hours, within a daily budget, and when your level allows interruptions.
- **Next digest**: batched into a short digest at fixed times (default 08:30, 13:00 and 18:30).
- **Inbox only**: kept in `/inbox` and never pushed.

It is **off by default**. Nothing is held, digested or extracted until you enable it.

```bash
hermes config set attention.enabled true
```

When enabled it starts at level `quiet`, which means digests only and no interruptions.

## What feeds the inbox

| Source | What happens |
|---|---|
| Recurring cron jobs | A successful run goes to the inbox instead of being delivered every time. An identical result is not captured twice. A job can mark a time-critical result by starting its reply with `[ALERT]`; the job is told about this marker automatically. One-shot reminders, `[SILENT]` runs and failure alerts keep their normal delivery. |
| Open loops | When you state a commitment or deadline in chat ("I need to renew my passport by Friday", "remind me to call mom"), the agent records it. It checks in about 24 hours before the deadline, sends an urgent alert about 2 hours before (or when it passes), and asks once after 3 days about undated items. Mentioning that something is done or cancelled ("renewed the passport already") closes it. |

### How open loops are detected

A cheap text filter runs first. Only messages with a commitment phrase plus a time phrase, an explicit "remind me" or "don't forget", or a completion phrase matching a tracked loop lead to one small auxiliary model call (`auxiliary.open_loops`). Every extracted loop must quote your own words; anything the model invents is discarded. Assistant suggestions are never recorded as your commitments. Extraction runs after the turn on a background thread and never changes the conversation or its prompt cache. It is skipped for cron runs, subagents, and sessions with memory disabled.

## Watching your connected sources

`/inbox watch on` makes the agent keep an eye on everything you have connected: calendars, mail, task trackers, code hosts, notes and any MCP server or connected app.

```text
/inbox watch on [15m|30m|1h|2h|3h|4h]   # default 1h
/inbox watch                             # status
/inbox watch now                         # check every source on the next tick
/inbox watch off                         # remove the watcher jobs; the source list stays
/inbox sources                           # what is connected and how it was found
/inbox sources remove N | restore N      # stop or resume watching one source
/inbox sources refresh                   # re-index now
/inbox sources discover                  # run the discovery check now
```

How it works:

- **Index (no model).** The cron tick re-checks what is connected at most once an hour, on a background thread. It covers enabled `mcp_servers`, apps the connector gateway reports as connected, the Google Workspace token, `himalaya`, an authenticated `gh`, `NOTION_API_KEY` and, on macOS, `remindctl`. A source that disappears is marked `missing` and its watcher stops.
- **Discovery (a model, weekly).** Every Wednesday at 03:00 one run looks for what the index cannot see: a CLI with stored auth, credentials in an unusual place, a connection that is configured but broken. It checks read-only and must say how it verified each source. New sources show up in `/inbox sources`, and connection problems arrive as one inbox item.
- **Watchers (a model per source).** Each source gets its own cron job named `Watch: <source>`. It has only that source's tools, runs outside quiet hours, and knows what is already in your inbox and the commitments you mentioned. It looks for what matters for that kind of source: conflicts, meetings to prepare for, moved events; mail that needs a reply, deadlines, bills, security alerts; tasks due or assigned; review requests. It answers with structured items or `[SILENT]`. Each item has a stable key, so the same event or message is never reported twice.

Watchers are told to stay read-only and to treat everything they read as data, not instructions. What they find can inform you, ask you something or offer to do something ("I can draft a reply"). Nothing is sent or changed without you. Their items go through the same gate as everything else: quiet hours, the interruption budget and digests apply, and `/inbox less` mutes one source's pushes.

Items are delivered to `attention.deliver`, or your home channel when that is empty. Proactive messages are also added to that chat's history, so you can just reply ("yes, draft it").

Each watcher run is a model call: five sources checked hourly between 08:00 and 22:00 is about 70 calls a day. Change the interval with `/inbox watch on 2h`, or edit one watcher like any cron job (`/cron`), for example to pin a cheaper model. Deleting a watcher job removes its source until you restore it.

## Levels

| Level | Interrupts | Default daily budget |
|---|---|---|
| `off` | — (layer disabled) | 0 |
| `quiet` | never; alerts wait for the digest | 0 |
| `balanced` | alerts with urgency ≥ 7 | 3 |
| `eager` | alerts with urgency ≥ 5 | 6 |

Interruptions over the budget move to the next digest. An alert during quiet hours waits until they end or until the next digest, whichever comes first.

## Commands

| Command | What it does |
|---|---|
| `/inbox` | Open items, most urgent first, with their state (`sending now`, `next digest 13:00`, `sent 08:30`, `inbox only`). |
| `/inbox show <n\|id>` | Full text and the reason it was surfaced. |
| `/inbox done <n\|id>` | Mark handled. For an open-loop check-in this also closes the loop. |
| `/inbox dismiss <n\|id>` | Not relevant. Cancels the loop for open-loop check-ins. |
| `/inbox snooze <n\|id> [30m\|2h\|1d]` | Hide until then; it comes back in the next digest. |
| `/inbox less <n\|id>` | Mute that kind of item (for example one cron job): it stays in the inbox and is never pushed. `/inbox more <category>` undoes it. |
| `/inbox loops` | Tracked commitments; `/inbox loops done N` / `cancel N`. |
| `/inbox log` | Recent gate decisions with reasons, including suppressed ones. |
| `/inbox digest` | Preview what the next digest will contain. |
| `/inbox status` | Level, quiet hours, digest times, interruptions used today. |

Items are referenced by inbox number or by the short id shown in digests (`[3f2a91]`). `/inbox` works in the CLI, the TUI and Desktop, and on messaging platforms.

## Where items are delivered

Items from cron jobs use the job's own `deliver` target. Open loops from a messaging chat go back to that chat. Items without a target (for example an open loop mentioned in the local CLI) stay in `/inbox` unless you set a fallback:

```yaml
attention:
  deliver: telegram   # any cron deliver value: telegram, discord:<chat>, bot-chat, ...
```

Interruptions and digests are sent by the cron ticker, so the gateway, Desktop backend or `hermes cron tick` must be running. A digest slot is recorded before it is sent: a crash can skip one digest but never repeats it. Items that could not be delivered wait for the next slot.

## Configuration

```yaml
attention:
  enabled: false
  level: quiet                 # off | quiet | balanced | eager
  quiet_hours: "22:00-08:00"   # profile timezone; may wrap midnight; "" = none
  digest_times: ["08:30", "13:00", "18:30"]
  max_interrupts_per_day: null # null = the level's default
  route_cron: true             # recurring cron results go through the inbox
  open_loops: true             # track commitments mentioned in chat
  deliver: ""                  # fallback target for items without one
auxiliary:
  open_loops:                  # model for open-loop extraction (default: auto)
    provider: auto
    model: ""
```

`route_cron: false` keeps every recurring job on direct delivery; `/inbox less` on one job's item keeps that job in the inbox without pushing it. State lives in `<profile>/cron/attention.db`. Items expire after 7 days.
