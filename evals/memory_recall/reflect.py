"""Prototype reflector: condense dated observations into a bounded, structured user profile.

The profile is what a thoughtful assistant "just knows" about the user at the start of a chat:
standing constraints, people, commitments with dates, goals and current state, so a request can
be connected to things the user did not mention. Experimental (Memory v2 research).
"""
from llm import complete
from observe import render_log

from hermes_state_home_observations import PROFILE_PROMPT as SYSTEM  # The product's own prompt.


def reflect(observations, *, model, provider='openai-codex', words=700, as_of=None):
    """observations: dicts with text/kind/event_date/session_date → profile markdown."""
    header = f'Today is {as_of}.\n\n' if as_of else ''
    messages = [{'role': 'system', 'content': SYSTEM.format(words=words)},
                {'role': 'user', 'content': header + 'Observations, oldest first:\n' + render_log(observations)}]
    return complete(messages, model=model, provider=provider).strip()
