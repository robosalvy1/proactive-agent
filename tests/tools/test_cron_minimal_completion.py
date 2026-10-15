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
