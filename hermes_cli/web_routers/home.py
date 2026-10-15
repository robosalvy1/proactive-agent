"""Home navigation for the dashboard's existing PTY-backed chat surface."""
from fastapi import APIRouter, HTTPException

from hermes_cli.web_deps import late
from hermes_cli.web_routers._common import destructive_profile, scoped_to_thread

router = APIRouter()
_open_home_db = late("_open_session_db_for_profile", "hermes_cli.web_server_sessions")


@router.post("/api/home/open")
async def open_home(profile: str | None = None):
    """Profile/token auth is the dashboard middleware's existing boundary."""
    from hermes_state_home import HomeStore
    from hermes_cli.web_server_sessions import _with_session_maintenance

    def open_target():
        from hermes_cli.sessions_owner import live_owner

        if endpoint := live_owner():
            import asyncio
            from hermes_cli.gateway_client import connect_gateway

            async def request_owner():
                async with connect_gateway(endpoint) as client:
                    return await client.rpc("home.action")
            result = asyncio.run(request_owner())
            return {"session_id": result["session_id"]}

        def create_offline():
            db = _open_home_db(profile, read_only=False)
            try:
                return {"session_id": HomeStore(db).ensure_home()}
            finally:
                db.close()
        return _with_session_maintenance(profile, create_offline)

    profile = destructive_profile(profile, "POST /api/home/open")
    try:
        return await scoped_to_thread(profile, open_target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
