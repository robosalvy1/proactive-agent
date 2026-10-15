"""Compact cron output keeps state honest while retaining explicit diagnostics."""
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

import pytest

from hermes_cli.cli_cron_lines import cron_list_lines, cron_overview_lines
from hermes_cli.cron_presentation import job_confirmation


@pytest.fixture
def job():
    return {"job_id": "internal-123", "name": "Morning brief", "schedule": "every 60m",
            "enabled": True, "state": "scheduled", "repeat": "forever", "deliver": "origin",
            "next_run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}


def render(result, **kwargs):
    with patch("hermes_cli.cli_commands_mixin._cron_api", return_value=result):
        return "\n".join(cron_list_lines(**kwargs))


def test_compact_list_hides_ids_and_prompt_while_details_remain_available(job):
    job["prompt_preview"] = "Internal task instructions"
    result = {"success": True, "jobs": [job]}
    text = render(result)
    assert "Morning brief" in text and "Next run" in text
    assert "internal-123" not in text and "Internal task instructions" not in text
    detailed = render(result, details=True)
    assert "internal-123" in detailed and "Internal task instructions" in detailed


@pytest.mark.parametrize("overview", [False, True])
def test_failed_list_is_never_reported_as_empty(overview):
    with patch("hermes_cli.cli_commands_mixin._cron_api", return_value={"success": False, "error": "store unavailable"}):
        text = "\n".join(cron_overview_lines() if overview else cron_list_lines())
    assert "store unavailable" in text
    assert "No scheduled jobs" not in text


def test_compact_list_preserves_overdue_failure_and_scheduler_warning(job):
    job.update(next_run_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
               last_status="delivery_failed", last_delivery_error="chat unavailable")
    text = render({"success": True, "jobs": [job], "warning": "Scheduler is offline"})
    assert "Overdue" in text
    assert "chat unavailable" in text
    assert "Scheduler is offline" in text


def test_paused_job_does_not_advertise_a_next_run(job):
    job.update(enabled=False, state="paused")
    text = render({"success": True, "jobs": [job]})
    assert "paused" in text
    assert "Next run" not in text


def test_confirmation_preserves_timezone_paused_and_local_only_state(job):
    job.update(enabled=False, state="paused", deliver="local")
    with patch("hermes_time.get_timezone", return_value=UTC):
        text = job_confirmation(job)
    assert "Morning brief" in text and "UTC" in text
    assert "Paused" in text and "no chat delivery" in text
    assert "internal-123" not in text and "Next:" not in text


@pytest.mark.parametrize("deliver", ["origin", ["origin"], ("origin",)])
def test_origin_delivery_has_no_redundant_destination_label(job, deliver):
    job["deliver"] = deliver
    text = job_confirmation(job)
    assert "Delivery:" not in text
    assert "no chat delivery" not in text


@pytest.mark.parametrize("deliver", ["local", ["local"], [], None])
def test_local_delivery_forms_keep_the_local_only_warning(job, deliver):
    job["deliver"] = deliver
    assert "no chat delivery" in job_confirmation(job)
