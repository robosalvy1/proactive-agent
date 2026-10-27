"""Cached chat calls for end-to-end memory evals, through Hermes' own provider routing.

Point ``HERMES_HOME`` at a disposable eval profile that holds the provider credential
(for example ``hermes auth add openai-codex``); never a personal profile. Responses are
cached on disk by (provider, model, messages), so reruns and resumed runs are free.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Hermes checkout root.

_LOCK = threading.Lock()
_DB = None
_CLIENTS = {}


def _cache():
    global _DB
    if _DB is None:
        path = os.path.expanduser(os.environ.get('MEMORY_EVAL_LLM_CACHE')
                                  or os.path.join(tempfile.gettempdir(), 'memory_eval_llm_cache.sqlite'))
        _DB = sqlite3.connect(path, check_same_thread=False)
        _DB.execute('CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, response TEXT, seconds REAL)')
    return _DB


def _client(provider, model):
    from agent.auxiliary_client import resolve_provider_client

    if (provider, model) not in _CLIENTS:
        client, resolved = resolve_provider_client(provider, model=model)
        if client is None:
            raise RuntimeError(f'No credential for {provider}; sign the eval profile in first.')
        _CLIENTS[(provider, model)] = (client, resolved or model)
    return _CLIENTS[(provider, model)]


def complete_tools(messages, tools, *, model, provider='openai-codex', retries=6):
    """One tool-enabled turn: ``{'content': str, 'tool_calls': [{'id', 'name', 'arguments'}]}``."""
    def call(response):
        message = response.choices[0].message
        calls = [{'id': c.id, 'name': c.function.name, 'arguments': c.function.arguments}
                 for c in (getattr(message, 'tool_calls', None) or [])]
        return json.dumps({'content': message.content or '', 'tool_calls': calls})
    return json.loads(complete(messages, model=model, provider=provider, retries=retries,
                               tools=[{'type': 'function', 'function': t} for t in tools], _parse=call))


def complete(messages, *, model, provider='openai-codex', retries=6, tools=None, _parse=None):
    key = hashlib.sha256(json.dumps([provider, model, messages] + ([tools] if tools else []),
                                    sort_keys=True).encode()).hexdigest()
    with _LOCK:
        hit = _cache().execute('SELECT response FROM calls WHERE key=?', (key,)).fetchone()
    if hit:
        return hit[0]
    client, resolved = _client(provider, model)
    attempt = waited = 0
    while True:
        started = time.monotonic()
        try:
            response = client.chat.completions.create(model=resolved, messages=messages,
                                                      **({'tools': tools} if tools else {}))
            text = _parse(response) if _parse else (response.choices[0].message.content or '')
            break
        except Exception as exc:  # Provider/network errors: back off and retry.
            if 'usage_limit' in str(exc) and waited < 3 * 3600:
                # Subscription window exhausted: wait for the reset instead of failing the run.
                print(f'  usage limit reached; waiting 10 min ({waited // 60} min so far)', flush=True)
                time.sleep(600)
                waited += 600
                continue
            attempt += 1
            if attempt >= retries:
                raise
            wait = min(120, 5 * 2 ** attempt)
            print(f'  llm retry {attempt} after {type(exc).__name__}: {str(exc)[:120]} (sleep {wait}s)', flush=True)
            time.sleep(wait)
    with _LOCK:
        _cache().execute('INSERT OR REPLACE INTO calls VALUES (?,?,?)', (key, text, time.monotonic() - started))
        _cache().commit()
    return text
