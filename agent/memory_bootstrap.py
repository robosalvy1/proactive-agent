"""Profile/session initialization metadata for memory providers."""
from contextlib import suppress
from typing import Any

from agent.agent_init_params import _GATEWAY_IDENTITY_PARAMS
from hermes_constants import get_hermes_home


def memory_provider_init_kwargs(agent, platform) -> dict[str, Any]:
    """Bind providers to the owning session/profile, including off-turn identity."""
    kwargs = {
        "session_id": agent.session_id,
        "platform": platform or "cli",
        "hermes_home": str(get_hermes_home()),
        "agent_context": platform if platform in ("cron", "subagent") else "primary",
    }
    if kwargs["platform"] == "cli":
        kwargs["warning_callback"] = agent._emit_warning
        kwargs["status_callback"] = agent._emit_status
    if agent._session_db:
        with suppress(Exception):
            title = agent._session_db.get_session_title(agent.session_id)
            if title:
                kwargs["session_title"] = title
                source = agent._session_db.get_session_title_source(agent.session_id)
                if source:
                    kwargs["session_title_source"] = source
    for name in _GATEWAY_IDENTITY_PARAMS:
        value = getattr(agent, f"_{name}")
        if value:
            kwargs[name] = value
    if agent.session_cwd:
        kwargs["cwd"] = agent.session_cwd
    with suppress(Exception):
        from hermes_cli.profiles import get_active_profile_name
        kwargs["agent_identity"] = get_active_profile_name()
        kwargs["agent_workspace"] = "hermes"
    return kwargs
