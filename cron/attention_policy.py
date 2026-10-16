"""Attention policy: settings, quiet hours, digest slots and the capture-time route decision.

Pure functions over a settings snapshot and an explicit ``now`` (tz-aware, profile timezone), so
the gate is deterministic and testable without a model, a store or a clock. The store applies the
route; ``cron/attention_flush.py`` re-checks quiet hours and the interrupt budget at send time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Optional

LEVELS = ("off", "quiet", "balanced", "eager")

# Per level: minimum urgency that may interrupt (None = never) and the default daily budget.
_LEVEL_INTERRUPT_THRESHOLD = {"off": None, "quiet": None, "balanced": 7, "eager": 5}
_LEVEL_DEFAULT_BUDGET = {"off": 0, "quiet": 0, "balanced": 3, "eager": 6}

# Below this urgency an item is kept in the inbox only: never pushed, never digested.
INBOX_ONLY_BELOW = 3

ROUTE_NOW = "now"
ROUTE_DIGEST = "digest"
ROUTE_INBOX = "inbox"
ROUTE_DROP = "drop"

_HHMM = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


@dataclass(frozen=True)
class AttentionSettings:
    enabled: bool
    level: str
    quiet_start: Optional[time]
    quiet_end: Optional[time]
    digest_times: tuple[time, ...]
    max_interrupts_per_day: int
    route_cron: bool
    open_loops: bool
    deliver: str

    @property
    def active(self) -> bool:
        return self.enabled and self.level != "off"

    @property
    def interrupt_threshold(self) -> Optional[int]:
        return _LEVEL_INTERRUPT_THRESHOLD[self.level]


def parse_hhmm(value: Any) -> Optional[time]:
    match = _HHMM.match(str(value or ""))
    return time(int(match.group(1)), int(match.group(2))) if match else None


def _parse_quiet_hours(value: Any) -> tuple[Optional[time], Optional[time]]:
    parts = str(value or "").split("-")
    if len(parts) != 2:
        return None, None
    start, end = parse_hhmm(parts[0]), parse_hhmm(parts[1])
    if start is None or end is None or start == end:
        return None, None
    return start, end


def settings_from_config(cfg: Optional[dict]) -> AttentionSettings:
    """Resolve ``attention.*`` with defaults from DEFAULT_CONFIG for absent or malformed keys."""
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    defaults = DEFAULT_CONFIG["attention"]
    raw = (cfg or {}).get("attention")
    block = {**defaults, **(raw if isinstance(raw, dict) else {})}

    level = str(block.get("level") or "").strip().lower()
    if level not in LEVELS:
        level = defaults["level"]
    quiet_start, quiet_end = _parse_quiet_hours(block.get("quiet_hours"))
    raw_times = block.get("digest_times")
    if not isinstance(raw_times, (list, tuple)):
        raw_times = defaults["digest_times"]
    digest_times = tuple(sorted({t for t in (parse_hhmm(v) for v in raw_times) if t is not None}))
    budget = block.get("max_interrupts_per_day")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        budget = _LEVEL_DEFAULT_BUDGET[level]
    if _LEVEL_INTERRUPT_THRESHOLD[level] is None:
        budget = 0
    return AttentionSettings(
        enabled=block.get("enabled") is True,
        level=level,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        digest_times=digest_times,
        max_interrupts_per_day=budget,
        route_cron=block.get("route_cron") is not False,
        open_loops=block.get("open_loops") is not False,
        deliver=str(block.get("deliver") or "").strip(),
    )


def load_settings() -> AttentionSettings:
    """Settings for the active profile (same loader cron uses)."""
    from hermes_cli.config import load_config_readonly

    return settings_from_config(load_config_readonly() or {})


def in_quiet_hours(settings: AttentionSettings, now: datetime) -> bool:
    start, end = settings.quiet_start, settings.quiet_end
    if start is None or end is None:
        return False
    current = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def local_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def latest_digest_slot(settings: AttentionSettings, now: datetime) -> Optional[datetime]:
    """The most recent configured digest instant at or before ``now`` (today or yesterday)."""
    if not settings.digest_times:
        return None
    today = local_day_start(now)
    candidates = [
        datetime.combine(day.date(), slot, tzinfo=now.tzinfo)
        for day in (today, today - timedelta(days=1))
        for slot in settings.digest_times
    ]
    past = [c for c in candidates if c <= now]
    return max(past) if past else None


def next_digest_slot(settings: AttentionSettings, now: datetime) -> Optional[datetime]:
    if not settings.digest_times:
        return None
    today = local_day_start(now)
    candidates = [
        datetime.combine(day.date(), slot, tzinfo=now.tzinfo)
        for day in (today, today + timedelta(days=1))
        for slot in settings.digest_times
    ]
    return min(c for c in candidates if c > now)


def decide_route(settings: AttentionSettings, *, kind: str, urgency: int, muted: bool) -> tuple[str, str]:
    """Capture-time route and its reason. Quiet hours and the budget are applied at send time."""
    if muted:
        return ROUTE_INBOX, "category muted with /inbox less"
    if urgency < INBOX_ONLY_BELOW:
        return ROUTE_INBOX, f"low urgency ({urgency})"
    threshold = settings.interrupt_threshold
    if kind == "alert" and threshold is not None and urgency >= threshold:
        return ROUTE_NOW, f"alert urgency {urgency} >= {threshold} ({settings.level})"
    if kind == "alert" and threshold is None:
        return ROUTE_DIGEST, f"level {settings.level} never interrupts"
    return ROUTE_DIGEST, "held for the next digest"
