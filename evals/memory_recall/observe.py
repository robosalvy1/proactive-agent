"""Prototype memory observer: dated, self-contained observations from conversation sessions.

Experimental (Memory v2 research). Each session is observed independently, so results are
cached per session and reused across every benchmark question whose history contains it;
conflicts between old and new observations are left to recency at read time.
"""
import hashlib
import json

from llm import complete

SYSTEM = """You are the memory observer for a long-term personal assistant. You read past \
conversations between the user and the assistant and write down everything a future assistant \
would need to remember to serve this user well and to answer later questions about their life.

Write observations that are:
- Self-contained and specific: third person ("The user ..."), with the exact names, numbers, \
amounts, titles, brands, places and quantities that were mentioned. Never write "something" when \
the conversation said what it was.
- Dated: resolve relative times ("last weekend", "two months ago", "yesterday") against the \
session date and give absolute dates. Put the date the event happened in event_date (YYYY-MM-DD, \
or YYYY-MM if only the month is known); use null when it is unknown.
- Complete: biography, work, education, family, friends, pets, health, home, possessions, \
purchases, hobbies, trips, events attended, routines, counts ("third time this year"), plans, \
goals, likes, dislikes and preferences (including ones only implied by what they ask for), and \
any change of state ("moved", "no longer", "switched to", "now has"). Mark a change of state with \
kind "update" and say what it replaces when known.
- Also record specific things the ASSISTANT told the user that they may ask about again \
(recommendations, names, lists, numbers, instructions), as kind "assistant", e.g. "The assistant \
recommended the novel X by Y."
Skip greetings, generic knowledge with no tie to the user, and the assistant's generic advice.

Return JSON only: {"sessions": [{"id": "<session id>", "observations": [{"text": "...", \
"kind": "fact|preference|event|plan|update|assistant", "event_date": "YYYY-MM-DD" or null}]}]}
Include every session id you were given, with an empty list when nothing is worth keeping."""

MAX_TURN_CHARS = 2500


def session_key(session_id, date, turns):
    blob = json.dumps([date, [(t['role'], t['content']) for t in turns]], ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _render(sessions):
    parts = []
    for sid, date, turns in sessions:
        lines = [f'<session id="{sid}" date="{date}">']
        for turn in turns:
            text = turn['content'].strip()
            if len(text) > MAX_TURN_CHARS:
                text = text[:MAX_TURN_CHARS] + ' [...]'
            lines.append(f"{turn['role'].upper()}: {text}")
        lines.append('</session>')
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def first_object(text):
    """The first JSON object in a model reply, or {} if there is none or it is malformed."""
    start = text.find('{')
    try:
        data = json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse(text):
    """Malformed replies yield no sessions, so observe_batch retries each session on its own."""
    entries = first_object(text).get('sessions')
    found = {}
    for entry in entries if isinstance(entries, list) else []:
        obs = entry.get('observations') if isinstance(entry, dict) else None
        if isinstance(obs, list):
            found[str(entry.get('id'))] = [{**o, 'kind': str(o.get('kind') or 'fact')} for o in obs  # render_log needs kind.
                                           if isinstance(o, dict) and str(o.get('text', '')).strip()]
    return found


def observe_batch(sessions, *, model, provider='openai-codex'):
    """sessions: [(id, date, turns)] → {id: [observation, ...]}; one LLM call."""
    messages = [{'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': _render(sessions)}]
    found = _parse(complete(messages, model=model, provider=provider))
    missing = [s for s in sessions if s[0] not in found]
    if missing and len(sessions) > 1:
        # A dropped session id in a batched answer: observe it on its own.
        for one in missing:
            found.update(observe_batch([one], model=model, provider=provider))
    for sid, _, _ in sessions:
        found.setdefault(sid, [])
    return found


def render_log(observations, *, limit_chars=None):
    """Chronological observation log, newest last, each line dated by session and event."""
    rows = sorted(observations, key=lambda o: (o['session_date'], o.get('event_date') or ''))
    lines = []
    for o in rows:
        when = o['session_date'].split(' (')[0]
        event = f" (event: {o['event_date']})" if o.get('event_date') else ''
        lines.append(f"[{when}] {o['kind']}: {o['text']}{event}")
    text = '\n'.join(lines)
    if limit_chars and len(text) > limit_chars:
        text = text[-limit_chars:]
        text = text[text.index('\n') + 1:] if '\n' in text else text
    return text
