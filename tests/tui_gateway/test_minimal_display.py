"""Presentation defaults are quiet; explicit display choices still win."""
from unittest.mock import patch

from tui_gateway import server as agent_factory
from gateway.display_config import resolve_display_setting


def test_raw_backend_defaults_are_quiet_without_requiring_a_config_file():
    with patch.object(agent_factory, "_display_cfg", return_value={}):
        assert agent_factory._load_tool_progress_mode() == "off"
        assert agent_factory._load_memory_notifications() == "off"
        assert agent_factory._load_show_reasoning() is False
    for platform in ("telegram", "discord", "slack", "signal"):
        assert resolve_display_setting({}, platform, "tool_progress") == "off"
        assert resolve_display_setting({}, platform, "interim_assistant_messages") is False


def test_explicit_presentation_choices_remain_available():
    display = {"tool_progress": "verbose", "memory_notifications": "on", "show_reasoning": True}
    with patch.object(agent_factory, "_display_cfg", return_value=display):
        assert agent_factory._load_tool_progress_mode() == "verbose"
        assert agent_factory._load_memory_notifications() == "on"
        assert agent_factory._load_show_reasoning() is True
    assert resolve_display_setting({"display": display}, "telegram", "tool_progress") == "verbose"
