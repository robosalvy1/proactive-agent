"""Profile identity shown by the interactive terminal CLI."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _plain_name(raw: str) -> str:
    """Trim a name for display. Brackets are Rich markup in panel titles; a name never needs them."""
    return raw.strip().replace("[", "").replace("]", "").strip()[:80]


def read_agent_name(path: Path) -> str | None:
    """Read the onboarding name file, accepting only its first non-empty line."""
    try:
        raw = path.read_text(encoding="utf-8-sig").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return None
    return _plain_name(raw) or None


def get_agent_name() -> str:
    """Resolve the active profile's name, then the configured skin, then Hermes."""
    from hermes_constants import get_hermes_home

    name = read_agent_name(get_hermes_home() / "AGENT_NAME.txt")
    if name:
        return name
    try:
        from hermes_cli.skin_engine import get_active_skin

        return _plain_name(get_active_skin().get_branding("agent_name", "Hermes")) or "Hermes"
    except Exception:  # skin/config loading can fail many ways; the name falls back, not the CLI
        logger.debug("Could not read the skin's agent name", exc_info=True)
        return "Hermes"
