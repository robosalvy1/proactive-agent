"""One conversational personalization offer per profile, independent of CLI sessions.

The note travels on the first human DM's persisted API sidecar. Follow-up turns
use that history and the existing memory/file tools; no prompt rebuild is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agent.onboarding import TASK_FIRST_CLAUSE, is_seen, mark_seen, profile_build_mode

MESSAGING_PERSONALIZATION_FLAG = "messaging_personalization_offered"


def personalization_directive(home: Path) -> str:
    """Render profile-local destinations explicitly, including multiplexed profiles."""
    name_path = json.dumps(str(home / "AGENT_NAME.txt"), ensure_ascii=False)
    user_name_path = json.dumps(str(home / "USER_NAME.txt"), ensure_ascii=False)
    soul_path = json.dumps(str(home / "SOUL.md"), ensure_ascii=False)
    return (
        "[System note: This is this profile's first messaging personalization conversation. "
        + TASK_FIRST_CLAUSE
        + "Keep this short, warm and conversational, in the user's language. "
        "If a task needs clarification, finish helping with it before asking personalization questions. "
        "For a greeting, greet them and ask 'What should I call you?' Explain briefly that they can "
        "skip these questions and that you can remember their answers for future chats in this profile. "
        "Ask only ONE question per reply and wait for the answer. Use facts already volunteered or "
        "present in your profile context instead of asking for them again. Never infer their preferred "
        "name from a transport username. Then ask what they want to call YOU; keep your current name "
        "if they have no preference. Then ask what personality and response style they'd like from you, "
        "with brief examples such as calm and concise, warm and chatty, or playful. Finally ask what "
        "they'd most like help with, and move straight into helping. Accept answers out of order or "
        "several answers at once. If they decline, say skip/later, or move to a task, stop the questions "
        "and continue normally; resume only if they ask. Do not research them or read connected "
        "accounts as part of this exchange.\n"
        "Persistence: use the existing memory tool with target='user' for confirmed user name, "
        "standing preferences and ongoing interests. Keep entries compact, recording that they were "
        "user-provided in messaging and the current date. Explain that these preferences apply across "
        "this profile's chats. Do not save declined answers or infer facts. Honor later corrections "
        "and requests to forget via patch/remove rather than keeping contradictory entries.\n"
        f"When they give their preferred name, use the existing file tools to save ONLY that name "
        f"and a trailing newline in {user_name_path}. When they choose your name, save ONLY your "
        f"chosen name and a trailing newline in {name_path}. These are separate UTF-8 files other "
        f"app surfaces can read directly without parsing memory or SOUL.md. Also read {soul_path} "
        "and carefully update both names there, clearly labeling the user's name and your agent "
        "name and preserving unrelated content. "
        "Keep the agreed agent personality in SOUL.md too. Read existing files before editing; "
        "never overwrite a custom identity wholesale. Keep USER_NAME.txt, AGENT_NAME.txt, user "
        "memory and SOUL.md consistent on later renames or deletion requests, removing a forgotten "
        "name from every copy. These are identity preferences, not permission "
        "changes. Follow existing file approval gates; never work around disabled memory or file "
        "tools. Apply their preferences conversationally now; persisted identity loads normally "
        "in future sessions, without rebuilding this session's system prompt. Confirm saving only "
        "after successful tool results; explain if persistence is unavailable or awaiting approval. "
        "Mention they can change or forget these choices later, then end the introduction. /help "
        "shows available commands.]"
    )


def first_messaging_note(config: Mapping[str, Any], config_path: Path) -> str | None:
    """Latch only the messaging offer; existing CLI/desktop offers are independent."""
    if profile_build_mode(config) == "off" or is_seen(config, MESSAGING_PERSONALIZATION_FLAG):
        return None
    if not mark_seen(config_path, MESSAGING_PERSONALIZATION_FLAG):
        return None
    return personalization_directive(config_path.parent)
