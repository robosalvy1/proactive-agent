"""Profile identity shown by the interactive terminal CLI."""

from __future__ import annotations

from pathlib import Path


def read_agent_name(path: Path) -> str | None:
    """Read the onboarding name file, accepting only its first non-empty line."""
    try:
        # Brackets are Rich markup in panel titles; a name never needs them.
        name = path.read_text(encoding="utf-8").splitlines()[0].strip().replace("[", "").replace("]", "")
    except (OSError, UnicodeError, IndexError):
        return None
    return name[:80] if name else None


def get_agent_name() -> str:
    """Resolve the active profile's name, then the configured skin, then Hermes."""
    from hermes_constants import get_hermes_home

    name = read_agent_name(get_hermes_home() / "AGENT_NAME.txt")
    if name:
        return name
    try:
        from hermes_cli.skin_engine import get_active_skin

        return get_active_skin().get_branding("agent_name", "Hermes")
    except Exception:
        return "Hermes"
