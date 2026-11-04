"""Seed the synthetic history into a disposable profile and record ranked session hits.

    python run_home.py ours --code-root . --out ours.json --base-url http://127.0.0.1:18555/v1 \\
        --model BAAI/bge-small-en-v1.5
    python run_home.py upstream --code-root /path/to/upstream-hermes --out upstream.json

Uses only synthetic data; the profile lives under ``--work-dir`` (a temp dir by default).
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument('system', choices=('ours', 'upstream'))
    ap.add_argument('--code-root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--base-url', default='')
    ap.add_argument('--model', default='')
    ap.add_argument('--min-similarity', type=float)
    ap.add_argument('--work-dir', default='')
    return ap.parse_args()


ARGS = parse()
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))
sys.path.insert(0, str(HERE))
from dataset import QUERIES, SESSIONS

PROFILE = Path(ARGS.work_dir or tempfile.mkdtemp(prefix='memory-eval-')) / 'profile'
PROFILE.mkdir(parents=True, exist_ok=False)
os.environ['HERMES_HOME'] = str(PROFILE)
if ARGS.system == 'ours' and ARGS.base_url:
    (PROFILE / 'config.yaml').write_text(
        'memory:\n  home_recall:\n    enabled: true\n'
        f'    base_url: {ARGS.base_url}\n    model: {ARGS.model}\n    api_key_env: ""\n    timeout_seconds: 10\n'
        + (f'    min_similarity: {ARGS.min_similarity}\n' if ARGS.min_similarity is not None else ''))

from hermes_state import SessionDB

DB = SessionDB(PROFILE / 'state.db')
FIRST_USER_MESSAGE = {}


def seed():
    for sid, turns in SESSIONS:
        DB.create_session(sid, 'cli')
        for role, text in turns:
            DB.append_message(sid, role, text)
        row = DB._read_one("SELECT id FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1", (sid,))
        FIRST_USER_MESSAGE[sid] = row[0]


def unique(seq):
    return list(dict.fromkeys(s for s in seq if s))


def run_upstream():
    from tools.session_search_tool import session_search

    seed()
    DB.create_session('current-chat', 'cli')
    runs = {}
    for variant in ('raw', 'kw'):
        rows = {}
        for q in QUERIES:
            t0 = time.perf_counter()
            payload = json.loads(session_search(q['q'] if variant == 'raw' else q['kw'], limit=10, db=DB,
                                                current_session_id='current-chat'))
            rows[q['id']] = {'hits': unique(r.get('session_id') for r in payload.get('results', [])),
                             'ms': (time.perf_counter() - t0) * 1000}
        runs[f'session_search/{variant}'] = rows
    return {'runs': runs}


def home_queries(home, semantic, only=None):
    from hermes_state_home import HomeStore
    from hermes_state_home_semantic import merge_recall, prepare_semantic_query, semantic_rows_on

    rows = {}
    for q in QUERIES:
        if only and q['kind'] not in only:
            continue
        t0 = time.perf_counter()
        plan = prepare_semantic_query(DB, home, q['q']) if semantic else None
        with DB._read_ctx() as conn:
            keyword = HomeStore(DB).recall_on(conn, home, q['q'], overview=False)
            vector = semantic_rows_on(DB, conn, None, home, plan) if semantic else []
        merged = merge_recall(keyword, vector)
        rows[q['id']] = {'hits': unique(r['source_session_id'] for r in merged),
                         'message_ids': [r['id'] for r in merged], 'ms': (time.perf_counter() - t0) * 1000}
    return rows


def build_index(home):
    from hermes_state_home_semantic import HomeIndex

    index, t0, calls = HomeIndex(DB), time.perf_counter(), 0
    if hasattr(index, 'drain'):
        result, calls = index.drain(home, budget_seconds=600), 1
    else:  # Pre-v2 explicit cursor: repeat as the CLI instructed.
        while True:
            result, calls = index.index(home), calls + 1
            if not result['more']:
                break
    return {'calls': calls, 'seconds': time.perf_counter() - t0, 'last': result}


def run_ours():
    from hermes_state_home import HomeStore
    from hermes_state_home_controls import HomeSourceControls

    home = HomeStore(DB).ensure_home()
    seed()
    out = {'runs': {'home/keyword': home_queries(home, False)}}
    if not ARGS.base_url:
        return out
    out['index'] = build_index(home)
    out['runs']['home/hybrid'] = home_queries(home, True)
    controls = HomeSourceControls(DB)
    for q in QUERIES:
        if q['kind'] == 'correction':
            controls.supersede(FIRST_USER_MESSAGE[q['stale']], FIRST_USER_MESSAGE[q['gold']])
    out['runs']['home/hybrid+supersede'] = home_queries(home, True, only={'correction', 'paraphrase'})
    # Forget only the message a user would point at, as /home forget does.
    controls.forget(FIRST_USER_MESSAGE['s_pin'])
    out['runs']['home/hybrid+forget'] = home_queries(home, True, only={'forget'})
    return out


result = run_upstream() if ARGS.system == 'upstream' else run_ours()
result.update(system=ARGS.system, embedding_model=ARGS.model or None)
Path(ARGS.out).write_text(json.dumps(result, indent=1))
print('wrote', ARGS.out)
