"""Quiet presentation and answer sizing preserve explicit configuration."""
from types import SimpleNamespace

import pytest

from agent.agent_init import _apply_agent_section, _apply_display_config


@pytest.mark.parametrize("display,commentary,memory", [
    ({}, False, "off"),
    ({"show_commentary": True, "memory_notifications": "verbose"}, True, "verbose"),
    ({"show_commentary": "false", "memory_notifications": False}, False, "off"),
    ({"memory_notifications": True}, False, "on"),
])
def test_display_settings_control_presentation_without_disabling_review(display, commentary, memory):
    agent = SimpleNamespace()
    _apply_display_config(agent, {"display": display}, "cli")
    assert agent.show_commentary is commentary
    assert agent.memory_notifications == memory


@pytest.mark.parametrize("configured,expected", [({}, "low"), ({"text_verbosity": "high"}, "high"), ({"text_verbosity": ""}, None)])
def test_answer_verbosity_defaults_low_and_allows_provider_default(configured, expected):
    agent = SimpleNamespace()
    agent.run_budget_seconds = None
    _apply_agent_section(agent, {"agent": {"environment_probe": False, **configured}})
    assert agent.text_verbosity == expected
