"""Home navigation/recall actions shared by local and canonical gateways."""
from pydantic import Field

from .base import Params, Result
from .registry import method


class HomeActionParams(Params):
    session_id: str | None = None
    profile: str | None = None
    # Arguments include case-sensitive canonical session IDs; the shared parser
    # validates verbs and argument shapes on both legacy and native transports.
    action: str = Field(default="", max_length=512)
    cwd: str | None = None


class HomeActionResult(Result):
    output: str
    session_id: str | None = None


method("home.action", params=HomeActionParams, result=HomeActionResult,
       doc="Resolve the persistent Home conversation or manage profile-owned cross-chat recall.")
