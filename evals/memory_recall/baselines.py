"""Upstream Hermes and OpenClaw memory, replayed on a magic scenario for comparison.

Both are simulated generously with their own prompts and tools; only the model calls go through the
cached eval client.

* ``hermes``: after every past chat the background memory review runs (upstream fires it every 10
  user turns, so short chats would usually get none) with the real ``memory`` tool and its
  1,375/2,200-character USER.md/MEMORY.md stores. The answer turn sees the frozen memory snapshot
  plus the memory and session-search guidance, and may call the real ``session_search`` (FTS5) over
  the same past chats.
* ``openclaw``: after every past chat the agent updates its files per the default AGENTS.md
  template (daily note, USER.md, MEMORY.md). The answer turn sees USER.md and MEMORY.md as
  bootstrap files plus the "Memory Recall" section, and may call ``memory_search``. That is a
  hybrid search (0.7 vector + 0.3 keyword) over memory files and session transcripts, as with
  ``experimental.sessionMemory``. Dreaming/scheduled maintenance is not simulated.
"""
import json
import math
import operator
from pathlib import Path
import re
import threading

from llm import complete, complete_tools

_dot = getattr(math, 'sumprod', None) or (lambda a, b: sum(map(operator.mul, a, b)))  # 3.11-safe

_TLS = threading.local()


def _patch_memory_dir():
    from tools import memory_tool

    if not getattr(memory_tool, '_eval_patched', False):
        memory_tool.get_memory_dir = lambda: _TLS.memory_dir
        memory_tool._eval_patched = True


def tool_loop(messages, tools, handlers, *, model, provider, max_rounds=6):
    """Run a tool-using turn to completion; returns (final text, [tool results])."""
    messages, results = list(messages), []
    for _ in range(max_rounds):
        turn = complete_tools(messages, tools, model=model, provider=provider)
        if not turn['tool_calls']:
            return turn['content'], results
        messages.append({'role': 'assistant', 'content': turn['content'] or None, 'tool_calls': [
            {'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}}
            for c in turn['tool_calls']]})
        for call in turn['tool_calls']:
            try:
                args = json.loads(call['arguments'] or '{}')
                output = handlers[call['name']](**args) if call['name'] in handlers else \
                    json.dumps({'error': f"unknown tool {call['name']}"})
            except Exception as exc:  # health: allow BLE001 -- eval tool loop: the error goes back to the model, as in the real loops
                output = json.dumps({'error': f'{type(exc).__name__}: {exc}'})
            output = output[:12000]
            results.append(f"{call['name']}({call['arguments']}) ->\n{output}")
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': output})
    final = complete(messages + [{'role': 'user', 'content': 'Answer now without further tool calls.'}],
                     model=model, provider=provider)
    return final, results


def _turns(turns):
    return [{'role': t['role'], 'content': t['content']} for t in turns if t['content'].strip()]


# --- Hermes -----------------------------------------------------------------------------------

def hermes(scenario, sessions, workdir, *, system, writer_model, answer_model, provider):
    from agent.background_review import _MEMORY_REVIEW_PROMPT
    from agent.prompt_builder import MEMORY_GUIDANCE, SESSION_SEARCH_GUIDANCE
    from hermes_state import SessionDB
    from tools.memory_tool import MEMORY_SCHEMA, memory_tool
    from tools.memory_tool_store import MemoryStore
    from tools.session_search_tool import SESSION_SEARCH_SCHEMA, session_search
    from datetime import datetime

    _patch_memory_dir()
    workdir.mkdir(parents=True)
    _TLS.memory_dir = workdir / 'memories'
    _TLS.memory_dir.mkdir()
    store = MemoryStore(2200, 1375)

    def snapshot():
        store.load_from_disk()
        return '\n\n'.join(b for b in (store.format_for_system_prompt('memory'),
                                       store.format_for_system_prompt('user')) if b)

    for sid, date, turns in sessions:
        memory = snapshot()
        head = f'You are Hermes, a personal assistant. Current date: {date}.\n\n{MEMORY_GUIDANCE}' + \
            (f'\n\n{memory}' if memory else '')
        messages = [{'role': 'system', 'content': head}, *_turns(turns),
                    {'role': 'user', 'content': _MEMORY_REVIEW_PROMPT}]
        store.reset_consolidation_failures()
        tool_loop(messages, [MEMORY_SCHEMA], {'memory': lambda **a: memory_tool(**a, store=store)},
                  model=writer_model, provider=provider, max_rounds=4)

    db = SessionDB(workdir / 'state.db')
    try:
        for sid, date, turns in sessions:
            db.create_session(sid, 'cli')
            for n, turn in enumerate(turns):
                if turn['content'].strip():
                    db.append_message(sid, turn['role'], turn['content'],
                                      timestamp=datetime.fromisoformat(date).timestamp() + 60 * n)
        memory = snapshot()
        head = f'{system}\n\n{MEMORY_GUIDANCE}\n\n{SESSION_SEARCH_GUIDANCE}' + (f'\n\n{memory}' if memory else '')
        allowed = {'query', 'limit', 'sort', 'detail', 'session_id', 'around_message_id', 'window', 'role_filter'}
        search = lambda **a: session_search(db=db, **{k: v for k, v in a.items() if k in allowed})
        reply, results = tool_loop(
            [{'role': 'system', 'content': head},
             {'role': 'user', 'content': f"(Today is {scenario['request']['date']}.)\n{scenario['request']['text']}"}],
            [SESSION_SEARCH_SCHEMA], {'session_search': search}, model=answer_model, provider=provider)
    finally:
        db.close()
    return reply, '\n\n'.join([memory or '(memory empty)', *results])


# --- OpenClaw ---------------------------------------------------------------------------------

OPENCLAW_MEMORY = """## Memory

Use files for continuity across sessions:

- **Daily notes:** `memory/YYYY-MM-DD.md` holds raw logs; create `memory/` if needed.
- **User model:** `USER.md` holds stable preferences and profile facts as active directives.
- **Long-term:** `MEMORY.md` holds durable non-profile facts and decisions.

Capture decisions, context, and things to remember. Skip secrets unless asked to keep them.

### USER.md - Durable User Directives

- Write stable preferences, communication style, relationships, and active-project context as imperative directives such as `Always`, `Never`, or `Prefer`.
- Precede each directive with `<!-- observed: YYYY-MM-DD | status: active -->`.
- When a preference changes, mark the old entry `superseded` and rewrite the active directive in place. Never leave contradictory active directives.

### MEMORY.md - Durable Facts and Decisions

- Load **only in the main session** (direct chats with your human). Never load it in shared contexts (Discord, group chats, sessions with other people).
- Read, edit, and update it freely in main sessions.
- Save significant events, decisions, lessons, and durable non-profile facts as a curated summary, not raw logs.

### Write It Down

Before writing memory files, read them first. Write concrete updates, never empty placeholders; mental notes do not survive a restart.

- Asked to "remember this": update the daily note or relevant file."""

OPENCLAW_RECALL = """## Memory Recall
Before answering anything about prior work, decisions, dates, people, preferences, or todos: run memory_search without corpus to search the configured sources. If low confidence after search, say you checked.
Session hits are search snippets only; exact session history is unavailable with the enabled tools.
Citations are disabled: do not mention file paths or line numbers in replies unless the user explicitly asks."""

OPENCLAW_WRITE = """[This chat is ending.] Following the Memory section of AGENTS.md, write down anything from this \
conversation worth keeping before the context is lost. Current files are shown above. Return JSON only:
{"daily_note_append": "markdown to append to memory/<today>.md, or empty", \
"user_md": "the complete new USER.md, or null to leave it unchanged", \
"memory_md": "the complete new MEMORY.md, or null to leave it unchanged"}"""

MEMORY_SEARCH_SCHEMA = {
    'name': 'memory_search',
    'description': ('Mandatory recall step: semantically search MEMORY.md, memory/*.md and session transcripts '
                    'before answering questions about prior work, decisions, dates, people, preferences, or todos.'),
    'parameters': {'type': 'object', 'properties': {
        'query': {'type': 'string'},
        'maxResults': {'type': 'integer', 'description': 'default 6'},
        'minScore': {'type': 'number', 'description': 'default 0.35'}}, 'required': ['query']},
}


def _embed(texts, base_url, model):
    import assoc

    return assoc.embed(texts, base_url, model)


def _chunks(path, text, size=1600, overlap=320):
    out, start = [], 0
    while start < len(text):
        out.append((path, text[start:start + size]))
        start += size - overlap
    return out


def openclaw(scenario, sessions, *, system, writer_model, answer_model, provider, base_url, embed_model,
             min_score=0.30):
    files = {'USER.md': '', 'MEMORY.md': ''}
    for sid, date, turns in sessions:
        daily = f'memory/{date}.md'
        shown = '\n\n'.join(f'## {name}\n{files.get(name) or "(empty)"}' for name in ('USER.md', 'MEMORY.md', daily))
        head = f'You are a personal assistant running on OpenClaw. Current date: {date}.\n\n' \
               f'# AGENTS.md (excerpt)\n{OPENCLAW_MEMORY}\n\n# Workspace files\n{shown}'
        text = complete([{'role': 'system', 'content': head}, *_turns(turns),
                         {'role': 'user', 'content': OPENCLAW_WRITE.replace('<today>', date)}],
                        model=writer_model, provider=provider)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        try:
            update = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            update = {}
        if update.get('daily_note_append'):
            files[daily] = (files.get(daily, '') + '\n' + update['daily_note_append']).strip()
        for key, name in (('user_md', 'USER.md'), ('memory_md', 'MEMORY.md')):
            if isinstance(update.get(key), str):
                files[name] = update[key]

    chunks = [c for name, body in files.items() if body for c in _chunks(name, body)]
    for sid, date, turns in sessions:
        transcript = '\n'.join(f"{t['role'].title()}: {t['content']}" for t in turns if t['content'].strip())
        chunks += _chunks(f'sessions/{sid}.jsonl ({date})', transcript)
    vectors = _embed([c[1] for c in chunks], base_url, embed_model)

    def memory_search(query, maxResults=6, minScore=None, **_):
        q = _embed([query], base_url, embed_model)[0]
        terms = {w for w in re.findall(r'[a-z0-9]+', query.lower()) if len(w) > 2}
        scored = []
        for (path, body), vector in zip(chunks, vectors):
            words = set(re.findall(r'[a-z0-9]+', body.lower()))
            text_score = len(terms & words) / len(terms) if terms else 0.0
            scored.append((0.7 * _dot(q, vector) + 0.3 * text_score, path, body))
        threshold = min_score if minScore is None else float(minScore)
        hits = [h for h in sorted(scored, key=lambda h: -h[0]) if h[0] >= threshold][:max(1, min(int(maxResults), 20))]
        return json.dumps({'results': [{'path': p, 'score': round(s, 3), 'snippet': b[:700]} for s, p, b in hits]})

    boot = '\n\n'.join(f'## {name}\n{files[name]}' for name in ('USER.md', 'MEMORY.md') if files[name])
    head = f'{system}\n\n# AGENTS.md (excerpt)\n{OPENCLAW_MEMORY}\n\n{OPENCLAW_RECALL}' + \
        (f'\n\n# Project Context\n{boot}' if boot else '')
    reply, results = tool_loop(
        [{'role': 'system', 'content': head},
         {'role': 'user', 'content': f"(Today is {scenario['request']['date']}.)\n{scenario['request']['text']}"}],
        [MEMORY_SEARCH_SCHEMA], {'memory_search': memory_search}, model=answer_model, provider=provider)
    return reply, '\n\n'.join([boot or '(memory files empty)', *results])
