"""Home controls use the same profile/session ownership as other local controls."""
from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()


@_registry.method("home.action")
@_registry.profile_scoped
def _home_action(rid, params):
    from hermes_cli.home import home_action

    session = None
    if params.get("session_id"):
        session, error = _sess_nowait(params, rid)
        if error:
            return error
        if session.get("running"):
            return _err(rid, 4001, "Wait for the current turn before changing Home.")
        if params.get("action") in {"share", "exclude"}:
            _ensure_session_db_row(session)
    with (_session_db(session) if session else _profile_db(params, writer=True)) as db:
        if db is None:
            return _db_unavailable_error(rid, code=5007)
        key = _session_lookup_key(session) if session else ""
        try:
            result = home_action(db, key, params.get("action", ""), cwd=params.get("cwd"))
        except ValueError as exc:
            return _err(rid, 4001, str(exc))
        return _ok(rid, result)


def register(server):
    bind_module(globals(), server)
