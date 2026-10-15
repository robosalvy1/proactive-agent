"""Short cron copy shared by commands and model-facing confirmations."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from hermes_cli.cli_commands_session_tools import _t


def schedule_label(job: dict[str, Any]) -> str:
    schedule = job.get("schedule_display") or job.get("schedule") or "?"
    if isinstance(schedule, dict):
        schedule = schedule.get("display") or schedule.get("value") or schedule.get("expr") or "?"
    return str(schedule)


def next_run_label(value: Any) -> str:
    if not value:
        return "?"
    from hermes_time import get_timezone
    try:
        stamp = datetime.fromisoformat(str(value))
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(get_timezone())
        return stamp.strftime("%a %d %b at %H:%M %Z").strip()
    except ValueError:
        return str(value)


def job_confirmation(job: dict[str, Any], *, updated: bool = False) -> str:
    from hermes_time import get_timezone
    key = "cron.compact_updated" if updated else "cron.compact_created"
    text = _t(key, name=job.get("name") or "Reminder", schedule=schedule_label(job), timezone=str(get_timezone()))
    if not job.get("enabled", True) or job.get("state") == "paused":
        text += " " + _t("cron.compact_paused")
    elif job.get("next_run_at"):
        text += " " + _t("cron.compact_next", value=next_run_label(job["next_run_at"]))
    deliver = job.get("deliver") or "local"
    # A local-only job must never sound like a reminder will arrive in chat.
    if deliver == "local" or deliver == ["local"]:
        text += " " + _t("cron.compact_local")
    elif deliver != "origin":
        text += " " + _t("cron.compact_destination", target=", ".join(deliver) if isinstance(deliver, list) else deliver)
    return text


def compact_job_lines(job: dict[str, Any]) -> list[str]:
    from cron.jobs import effective_job_state
    from hermes_cli.cron import _job_warnings, _last_run_display, _next_run_row
    name = job.get("name") or job.get("prompt_preview") or job.get("id") or job.get("job_id") or "Reminder"
    state = effective_job_state(job)
    lines = [f"{name} · {schedule_label(job)} · {state}"]
    if job.get("next_run_at") and state not in {"paused", "completed", "disabled"}:
        label, value = _next_run_row(job)
        lines.append(f"  {label}: {next_run_label(value) if label == 'Next run' else value}")
    status = job.get("last_status")
    delivery_warning = (status == "delivery_failed" and job.get("last_delivery_error")) or (
        status == "delivery_queued" and job.get("last_delivery_queued"))
    if status and status != "ok" and not delivery_warning:
        lines.append(f"  {_last_run_display(job)}")
    lines.extend(f"  {line}" for line in _job_warnings(job))
    return lines


def scheduler_warning(result: dict[str, Any]) -> str | None:
    if not result.get("warning"):
        return None
    if result.get("gateway_running") is False:
        return _t("cron.compact_scheduler_offline")
    return str(result["warning"])
