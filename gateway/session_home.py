"""Home is a personal local-client control, never an ambient messaging permission."""
import asyncio
from functools import partial

from hermes_state_runtime import RuntimeStoreError


def handlers(connection):
    return {"home.action": partial(home_action, connection)}


async def home_action(connection, ref, params):
    authority, actor = connection.authority, connection.actor
    if actor.profile_id != authority.profile_id:
        raise RuntimeStoreError("profile_mismatch")
    if (getattr(authority, "_native_legacy_transports", {}).get(actor.transport_id) != actor
            or not {"session:read", "session:create"} <= actor.capabilities):
        raise RuntimeStoreError("permission_denied")
    action = params.get("action", "")
    if action not in {"status", "overview"} and "session:control" not in actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    target = ""
    if ref.session_id:
        authority.authorize(actor, ref, "session:read")
        target = authority.physical_target(ref)
        if authority._handle(ref).execution_state != "idle":
            raise RuntimeStoreError("session_busy")
    from hermes_cli.home import home_action as apply_home_action
    from gateway.session_runtime_workers import tracked_write

    try:
        operation = partial(apply_home_action, authority.db, target, action,
                            cwd=params.get("cwd"), principal_id=actor.subject)
        if action in {"status", "overview"}:
            return await asyncio.to_thread(operation)
        authority._require_admission_open()
        return await tracked_write(authority, operation)
    except ValueError as exc:
        raise RuntimeStoreError("invalid_params") from exc
