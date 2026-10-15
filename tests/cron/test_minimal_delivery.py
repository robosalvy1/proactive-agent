"""Scheduled output is clean by default; wrapping remains an explicit choice."""
from unittest.mock import patch

import pytest

from cron.scheduler_delivery import _deliver_result
from gateway.config import GatewayConfig, Platform, PlatformConfig


@pytest.mark.parametrize("wrap", [None, False, True])
def test_delivery_wrapper_is_opt_in(wrap):
    config = GatewayConfig()
    config.platforms[Platform.TELEGRAM] = PlatformConfig(enabled=True)
    raw = {} if wrap is None else {"cron": {"wrap_response": wrap}}
    job = {"id": "internal-id", "name": "Morning brief", "deliver": "telegram:chat"}
    with patch("cron.scheduler.load_config", return_value=raw), patch("gateway.config.load_gateway_config", return_value=config), patch("cron.scheduler_delivery._deliver_standalone") as send:
        assert _deliver_result(job, "Your morning brief") is None
    text = send.call_args.args[1]
    if wrap:
        assert "internal-id" in text and "To stop or manage" in text
        assert "Your morning brief" in text
    else:
        assert text == "Your morning brief"
