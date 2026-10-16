"""Shared Home actions used by the classic CLI and structured frontend transports."""
from __future__ import annotations

from hermes_state_home import HomeStore

USAGE = "/home [status | overview | share | exclude | link <session-id> | unlink <session-id> | links | index [clear] | sources | forget <message-id> | supersede <old-id> <new-id> | off | on | dream [on|off|now|status|notes|clear]]"


def format_overview(rows: list[dict]) -> str:
    """A readable, source-linked view; raw excerpts do not certify work as complete."""
    from agent.redact import redact_sensitive_text
    from datetime import UTC, datetime

    if not rows:
        return "No participating chat updates yet."
    lines = ["Recent context from your chats (quoted excerpts):"]
    for row in rows:
        when = datetime.fromtimestamp(row["timestamp"], UTC).strftime("%b %d, %H:%M UTC")
        title = redact_sensitive_text(str(row["title"])[:100], force=True)
        text = redact_sensitive_text(str(row["content"] or "")[:400], force=True, redact_url_credentials=True)
        speaker = "You" if row["role"] == "user" else "Assistant"
        lines.append(f"\n{title} · {when} · message {row['id']}\n{speaker}: {text}\n{row.get('link', '')}")
    return "\n".join(lines)


def home_action(db, session_id: str, action: str = "", *, cwd: str | None = None,
                principal_id: str | None = None) -> dict:
    store = HomeStore(db, principal_id=principal_id)
    action = action.strip()
    if action:
        from hermes_cli.home_controls import source_action
        result = source_action(db, session_id, action, principal_id=principal_id)
        if result is not None:
            return result
    verb, _, argument = action.partition(' ')
    if verb.lower() in {'link', 'unlink', 'links'}:
        from hermes_state_home_links import list_links, set_link
        if verb.lower() == 'links' and not argument:
            links = list_links(store, caller_session_id=session_id)
            output = '\n'.join(f"{item['session_id']} · {item['source']} · {'linked' if item['valid'] else 'inactive'}"
                               for item in links) or 'No private conversations linked.'
            return {'output': output}
        if verb.lower() == 'links' or not argument.strip() or len(argument.split()) != 1:
            raise ValueError(USAGE)
        set_link(store, argument.strip(), verb.lower() == 'link', caller_session_id=session_id)
        return {'output': ('Private conversation linked to Home for future recall.' if verb.lower() == 'link' else
                           'Private conversation unlinked. Future Home recall stops; existing context, native memory, and explicit history search are unchanged.')}
    action = action.lower()
    if action == 'dream' or action.startswith('dream '):
        from hermes_cli.home_dreams import dream_action
        return dream_action(db, action, principal_id=principal_id)
    if not action:
        target = store.ensure_home(cwd=cwd)
        return {"session_id": target, "output": "Home is ready. New personal chats share context with Home; /home exclude stops recall for a chat."}
    if action == "status":
        status = store.status()
        state = "on" if status["enabled"] else "off"
        target = status["session_id"] or "not created"
        return {"output": f"Home recall: {state}. Home conversation: {target}."}
    if action in ("off", "on"):
        store.set_enabled(action == "on")
        return {"output": f"Home recall is {action}."}
    if action in ("share", "exclude"):
        store.set_shared(session_id, action == "share")
        return {"output": ("This chat participates in Home recall." if action == "share" else
                           "This chat is excluded from future Home recall. Existing chat context, native memory, and explicit session search are unchanged.")}
    if action == "overview":
        target = store.status()["session_id"]
        if not target:
            return {"output": "Open /home first."}
        return {"output": format_overview(store.recall(target, "", overview=True))}
    raise ValueError(USAGE)


def handle_cli_home(cli, command: str) -> None:
    """Navigation goes through the existing resume handler and its ownership guards."""
    from hermes_cli.cli_commands_session_tools import _cp

    if getattr(cli, "_agent_running", False):
        return _cp("Wait for the current turn before changing Home.")

    db = getattr(cli, "_session_db", None)
    if db is None:
        return _cp("Home requires an available session database.")
    try:
        selected = db.get_session(cli.session_id) or {}
        result = home_action(db, cli.session_id, command.partition(" ")[2], cwd=getattr(cli, "cwd", None),
                             principal_id=selected.get('user_id'))
    except ValueError as exc:
        return _cp(str(exc))
    _cp(result["output"])
    if result.get("session_id"):
        cli._handle_resume_command(f"/resume {result['session_id']}")
