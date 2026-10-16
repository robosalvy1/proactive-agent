"""``/inbox watch`` and ``/inbox sources``: proactive watching of connected sources
(``cron/attention_watch.py``, ``cron/attention_sources.py``)."""

from __future__ import annotations

from datetime import datetime

WATCH_USAGE = "Usage: /inbox watch [on [15m|30m|1h|2h|3h|4h] | off | now]"
SOURCES_USAGE = "Usage: /inbox sources [refresh | discover | remove <n> | restore <n>]"


def _every(text: str):
    from cron.attention_watch import EVERY_CHOICES
    from hermes_cli.inbox_cmd import parse_duration

    if not text:
        return None, ""
    duration = parse_duration(text)
    minutes = int(duration.total_seconds() // 60) if duration else 0
    if minutes not in EVERY_CHOICES:
        return None, "Watch every 15m, 30m, 1h, 2h, 3h or 4h."
    return minutes, ""


def _watch_status(now: datetime) -> str:
    from cron import attention_sources as sources
    from cron import attention_store as store
    from cron.attention_watch import watch_state

    with store.transaction() as conn:
        state = watch_state(conn)
        active = sources.list_sources(conn)
    if not state["enabled"]:
        return ("Proactive watch is off. `/inbox watch on` gives each connected source (calendar, email, "
                "MCP servers, connected apps, …) its own watcher. Each run is a model call; default every 1h "
                "outside quiet hours.")
    names = ", ".join(row["label"] for row in active) or "nothing connected yet"
    return f"Proactive watch: on · every {state['every']}m outside quiet hours\nWatching: {names}"


def handle_watch(rest: str, settings, now: datetime) -> str:
    from cron import attention_watch, jobs

    verb, _, arg = rest.partition(" ")
    if verb == "on":
        every, error = _every(arg.strip())
        if error:
            return error
        attention_watch.set_watch(True, every, now)
        result = attention_watch.refresh(now, settings)
        return (_watch_status(now) + f"\nNew watchers: {result['created']} · weekly discovery: Wednesdays 03:00"
                + ("" if settings.deliver else "\nItems go to your home channel; set attention.deliver to choose."))
    if verb == "off":
        attention_watch.set_watch(False, None, now)
        result = attention_watch.sync_watchers(now, settings)
        return f"Proactive watch is off. Removed {result['removed']} watcher job(s); sources stay listed."
    if verb == "now":
        result = attention_watch.refresh(now, settings)
        with_jobs = _source_rows()
        for row in with_jobs:
            if row.get("job_id"):
                jobs.trigger_job(row["job_id"])
        return f"Checking {result['watching']} source(s) on the next tick. Results arrive in /inbox."
    if verb:
        return WATCH_USAGE
    return _watch_status(now)


def _source_rows(statuses=None) -> list[dict]:
    from cron import attention_sources as sources
    from cron import attention_store as store

    with store.transaction() as conn:
        return sources.list_sources(conn, statuses or (sources.ACTIVE,))


def _list_sources() -> str:
    from cron import attention_sources as sources

    rows = _source_rows((sources.ACTIVE, sources.MISSING, sources.REMOVED))
    if not rows:
        return "No connected sources found yet. /inbox sources refresh checks now."
    lines = [f"Connected sources · {sum(r['status'] == sources.ACTIVE for r in rows)} active"]
    for i, row in enumerate(rows, 1):
        state = "" if row["status"] == sources.ACTIVE else f" — {row['status']}"
        watcher = " · watching" if row.get("job_id") else ""
        lines.append(f"{i}. {row['label']} [{row['kind']}]{state}{watcher}\n   found by {row['found_by']}: "
                     f"{row['evidence']}")
    lines.append("/inbox sources remove N · restore N · refresh · discover")
    return "\n".join(lines)


def handle_sources(rest: str, settings, now: datetime) -> str:
    from cron import attention_sources as sources
    from cron import attention_store as store
    from cron import attention_watch, jobs

    verb, _, arg = rest.partition(" ")
    if verb in ("remove", "restore"):
        rows = _source_rows((sources.ACTIVE, sources.MISSING, sources.REMOVED))
        if not arg.strip().isdigit() or not 0 < int(arg) <= len(rows):
            return SOURCES_USAGE
        row = rows[int(arg) - 1]
        changed = (sources.remove_source if verb == "remove" else sources.restore_source)(row["key"], now)
        attention_watch.sync_watchers(now, settings)
        if not changed:
            return f"{row['label']} is already {'removed' if verb == 'remove' else 'listed'}."
        return f"{'Removed' if verb == 'remove' else 'Restored'}: {row['label']}."
    if verb == "refresh":
        result = attention_watch.refresh(now, settings)
        added = ", ".join(result["added"]) or "nothing new"
        return f"Indexed connected sources: {added}." + (
            f" Missing now: {', '.join(result['missing'])}." if result["missing"] else "")
    if verb == "discover":
        with store.transaction() as conn:
            job_id = store.get_state(conn, attention_watch.DISCOVERY_JOB_KEY)
        if not job_id or not jobs.get_job(job_id):
            return "Discovery runs while the watch is on. /inbox watch on first."
        jobs.trigger_job(job_id)
        return "Discovery runs on the next tick (a model with read-only checks). New sources appear here."
    if verb:
        return SOURCES_USAGE
    return _list_sources()


def watch_status_line() -> str:
    from cron import attention_store as store

    if not store.current_attention_file().exists():
        return "Proactive watch: off (/inbox watch on)"
    from cron.attention_watch import watch_state

    with store.transaction() as conn:
        state = watch_state(conn)
    if not state["enabled"]:
        return "Proactive watch: off (/inbox watch on)"
    return f"Proactive watch: on · every {state['every']}m · {len(_source_rows())} source(s) (/inbox sources)"
