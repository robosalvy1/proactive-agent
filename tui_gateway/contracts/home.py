"""Home navigation/recall actions shared by local and canonical gateways."""
from typing import Literal

from .base import Params, Result
from .registry import method


class HomeActionParams(Params):
    session_id: str | None = None
    profile: str | None = None
    action: Literal["", "status", "overview", "share", "exclude", "off", "on", "dream",
                    "dream status", "dream on", "dream off", "dream now", "dream notes", "dream clear"] = ""
    cwd: str | None = None


class HomeActionResult(Result):
    output: str
    session_id: str | None = None


method("home.action", params=HomeActionParams, result=HomeActionResult,
       doc="Resolve the persistent Home conversation or manage profile-owned cross-chat recall.")
