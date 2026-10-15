"""Manual-run summaries preserve delivery evidence without duplicating delivered content."""
from unittest.mock import patch

import pytest

from tools.cronjob_tools import _manual_run_completion


@pytest.mark.parametrize("record,expected", [
    ({}, "delivered"),
    ({"last_delivery_error": "chat unavailable"}, "delivery failed"),
    ({"last_delivery_queued": True}, "not yet confirmed"),
    ({"last_delivery_unverified": ["chat"]}, "delivery unverified"),
])
def test_delivered_job_completion_is_short_and_honest(record, expected):
    with patch("tools.cronjob_tools.get_job", return_value=record), patch("tools.cronjob_tools._latest_job_output_excerpt") as excerpt:
        result = _manual_run_completion({"success": True}, "internal-id", "Morning brief", "telegram:chat", 0)
    assert expected in result["summary"].lower()
    assert "internal-id" not in result["summary"]
    excerpt.assert_not_called()


def test_local_only_completion_still_includes_requested_result():
    with patch("tools.cronjob_tools.get_job", return_value={}), patch("tools.cronjob_tools._latest_job_output_excerpt", return_value="Your report"):
        result = _manual_run_completion({"success": True}, "internal-id", "Morning brief", "local", 0)
    assert "saved locally" in result["summary"] and "Your report" in result["summary"]


@pytest.mark.parametrize("with_delivery_error", [False, True])
def test_completion_errors_are_redacted_and_bounded_even_when_redaction_is_disabled(with_delivery_error):
    token = "sk-demo0123456789abcdef0123456789abcdef"
    run_error = f"Run failed at https://demo-user:synthetic-password@host.invalid/?api_key={token} " + "r" * 1500
    delivery_error = f"Delivery failed at https://demo-user:synthetic-password@host.invalid/?api_key={token} " + "d" * 1500
    record = {"last_delivery_error": delivery_error} if with_delivery_error else {}
    res = {"success": False, "error": run_error}
    with patch("tools.cronjob_tools.get_job", return_value=record), patch("tools.cronjob_tools._latest_job_output_excerpt", return_value=None), patch("agent.redact._redact_enabled", return_value=False):
        result = _manual_run_completion(res, "internal-id", "Morning brief", "telegram:chat", 0)
    for text in (result["summary"], result["error"]):
        assert token not in text
        assert "synthetic-password" not in text
        assert "demo-user" not in text
    assert len(result["summary"]) < 1150
    assert len(result["error"]) <= 500
    assert "Failed" in result["summary"] or "failed" in result["summary"]
    assert res["error"] == run_error
