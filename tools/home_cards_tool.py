"""Let the agent put cards on the person's home (the dashboard's /home), without designing them.

Cards come from a fixed catalog rendered by the home itself: live cards bound to something this
profile already has (calendar, scheduled jobs, recent chats, clocks) and content cards (list, stats,
text) holding data the agent fetched with its own tools, with the source named. No colors, icons,
markup or layout. The agent can only change or remove its own cards; the person's tiles are theirs.
"""

import json

from tools.registry import registry, tool_error

ACTIONS = ("list", "add", "update", "remove")


def home_cards_tool(action: str, kind: str = "", card_id: str = "", title: str = "", reason: str = "",
                    source: str = "", settings: dict | None = None, user_requested: bool = False) -> str:
    from hermes_cli import personal_board
    from hermes_cli.personal_board import BoardError

    try:
        if action == "list":
            return json.dumps(personal_board.summary(personal_board.load()), ensure_ascii=False)
        if action == "add":
            _, card = personal_board.agent_add(kind, title=title, reason=reason, source=source,
                                                   settings=settings, user_requested=bool(user_requested))
            return json.dumps({"success": True, "card": card, "note": "It is at the top of the person's home."},
                              ensure_ascii=False)
        if action == "update":
            if not card_id:
                return tool_error("update needs card_id (from action='list').")
            _, card = personal_board.agent_update(card_id, title=title or None, reason=reason or None,
                                                  source=source or None, settings=settings)
            return json.dumps({"success": True, "card": card}, ensure_ascii=False)
        if action == "remove":
            if not card_id:
                return tool_error("remove needs card_id (from action='list').")
            personal_board.agent_remove(card_id)
            return json.dumps({"success": True, "removed": card_id}, ensure_ascii=False)
    except BoardError as exc:
        return tool_error(str(exc))
    return tool_error(f"action must be one of: {', '.join(ACTIONS)}.")


HOME_CARDS_SCHEMA = {
    "name": "home_cards",
    "description": (
        "Put a card on the person's home screen (the web home beside your chat), or update/remove one you added. "
        "The home draws every card itself; you choose only the kind and the data, never its look. "
        "Call action='list' first to see what's already there and what the person removed. "
        "Live kinds use what this profile already has: 'calendar' (needs Google Calendar connected; "
        "settings {days: 1|3|7}), 'scheduled' (scheduled jobs), 'recent' (recent chats; {count: 3|5}), "
        "'clock' ({zones: IANA names, up to 4}). Content kinds hold data you fetched yourself with your other "
        "tools and must name it in source: 'list' ({items: [{text, detail?, url? (https), prompt? (tapping asks "
        "you this), done?}], up to 8}), 'stats' ({stats: [{value, label, trend?: up|down|flat}], up to 3}), "
        "'text' ({text}, up to 600 chars, plain). Content cards are snapshots: update them when the data changes. "
        "Add a card only when it will keep helping the person, give a one-line reason, and don't re-add one "
        "they removed unless they ask. You cannot change the person's own tiles."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "kind": {"type": "string", "enum": ["calendar", "scheduled", "recent", "clock", "list", "stats", "text"],
                     "description": "For add."},
            "card_id": {"type": "string", "description": "For update/remove: an id from action='list'."},
            "title": {"type": "string", "description": "Short card title, up to 40 chars. Required for content kinds."},
            "reason": {"type": "string", "description": "Why this helps, shown to the person (up to 160 chars). Required for add."},
            "source": {"type": "string", "description": "Where content-card data came from, e.g. 'Linear', 'GitHub', 'your email'."},
            "settings": {"type": "object", "description": "The kind's data, as described above."},
            "user_requested": {"type": "boolean", "description": "True only when the person asked for this card."},
        },
        "required": ["action"],
    },
}


registry.register(
    name="home_cards",
    toolset="home",
    schema=HOME_CARDS_SCHEMA,
    handler=lambda args, **kw: home_cards_tool(
        action=args.get("action", ""), kind=args.get("kind", ""), card_id=args.get("card_id", ""),
        title=args.get("title", ""), reason=args.get("reason", ""), source=args.get("source", ""),
        settings=args.get("settings") if isinstance(args.get("settings"), dict) else None,
        user_requested=args.get("user_requested") is True),
    emoji="🗂️",
)
