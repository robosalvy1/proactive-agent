"""Build outbound proxy content without mutating local transcript text."""

from typing import Any


def build_proxy_messages(
    message: str, context_prompt: str, history: list[dict[str, Any]], notes: list[str],
) -> list[dict[str, Any]]:
    """Attach current-turn notes to the user content, leaving the prefix unchanged."""
    messages = [{"role": "system", "content": context_prompt}] if context_prompt else []
    messages.extend(
        {"role": msg.get("role"), "content": msg.get("content")}
        for msg in history if msg.get("role") in {"user", "assistant"} and msg.get("content")
    )
    outbound = message + "\n\n" + "\n\n".join(notes) if notes else message
    messages.append({"role": "user", "content": outbound})
    return messages
