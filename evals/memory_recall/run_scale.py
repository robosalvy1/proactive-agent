"""Scale scenario: a long older history, then the dataset's facts as the newest chats.

    python run_scale.py --code-root . --out scale.json --base-url http://127.0.0.1:18556/v1 \\
        --model sentence-transformers/all-MiniLM-L6-v2 --min-similarity 0.30 --filler 6000

Measures how much recent history becomes semantically searchable after one explicit
``/home index`` budget, recall on the dataset's paraphrase/exact queries, and latency.
"""
import argparse
import json
import math
import os
import random
import statistics
import struct
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('--code-root', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--base-url', required=True)
ap.add_argument('--model', required=True)
ap.add_argument('--min-similarity', type=float, default=0.55)
ap.add_argument('--filler', type=int, default=6000)
ap.add_argument('--index-budget', type=float, default=20.0, help='seconds for the explicit /home index drain')
ap.add_argument('--work-dir', default='')
ARGS = ap.parse_args()
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))
sys.path.insert(0, str(HERE))
from dataset import QUERIES, SESSIONS
from score import score_run

PROFILE = Path(ARGS.work_dir or tempfile.mkdtemp(prefix='memory-scale-')) / 'profile'
PROFILE.mkdir(parents=True, exist_ok=False)
os.environ['HERMES_HOME'] = str(PROFILE)
(PROFILE / 'config.yaml').write_text(
    'memory:\n  home_recall:\n    enabled: true\n'
    f'    base_url: {ARGS.base_url}\n    model: {ARGS.model}\n    api_key_env: ""\n    timeout_seconds: 10\n'
    f'    min_similarity: {ARGS.min_similarity}\n')

from hermes_state import SessionDB
from hermes_state_home import HomeStore
from hermes_state_home_semantic import HomeIndex, merge_recall, prepare_semantic_query, semantic_rows_on

TOPICS = ['refactor the parser', 'plan a weekend hike', 'compare laptops', 'draft an email to the team',
          'debug a flaky test', 'summarize an article', 'pick a podcast', 'outline a blog post',
          'convert units for a recipe', 'review a pull request', 'brainstorm gift ideas', 'learn Spanish verbs']
WORDS = ('alpha beta gamma delta river stone cloud lantern harbor meadow copper velvet signal orbit '
         'quartz ember willow falcon cedar prism tundra mosaic').split()


def seed(db, rng):
    for s in range(math.ceil(ARGS.filler / 20)):
        sid = f'filler_{s:05d}'
        db.create_session(sid, 'cli')
        for _ in range(10):
            topic = rng.choice(TOPICS)
            db.append_message(sid, 'user', f'Can you help me {topic}? Notes: ' + ' '.join(rng.choices(WORDS, k=12)))
            db.append_message(sid, 'assistant', f'Sure, here is how to {topic}: ' + ' '.join(rng.choices(WORDS, k=20)))
    for sid, turns in SESSIONS:
        db.create_session(sid, 'cli')
        for role, text in turns:
            db.append_message(sid, role, text)


def index(db, home):
    t0 = time.perf_counter()
    try:
        if hasattr(HomeIndex, 'drain'):
            result = HomeIndex(db).drain(home, budget_seconds=ARGS.index_budget)
        else:
            result = HomeIndex(db).index(home)
        error = None
    except (ValueError, OSError) as exc:  # Bad config, or the endpoint timed out / is backing off.
        result, error = {}, f'{type(exc).__name__}: {exc}'
    with db._read_ctx() as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='home_recall_vectors'").fetchone()
        sessions = {row[0] for row in conn.execute(
            'SELECT m.session_id FROM home_recall_vectors v JOIN messages m ON m.id=v.message_id')} if exists else set()
        vectors = conn.execute('SELECT COUNT(*) FROM home_recall_vectors').fetchone()[0] if exists else 0
    gold = {sid for sid, _ in SESSIONS}
    return {'seconds': time.perf_counter() - t0, 'error': error, 'vectors': vectors,
            'dataset_sessions_indexed': len(sessions & gold), 'dataset_sessions': len(gold),
            **{k: v for k, v in result.items() if k in ('indexed', 'remaining', 'more', 'capacity_reached')}}


def queries(db, home):
    rows = {}
    for q in QUERIES:
        if q['kind'] not in ('paraphrase', 'exact'):
            continue
        t0 = time.perf_counter()
        plan = prepare_semantic_query(db, home, q['q'])
        t1 = time.perf_counter()
        with db._read_ctx() as conn:
            keyword = HomeStore(db).recall_on(conn, home, q['q'], overview=False)
            vector = semantic_rows_on(db, conn, None, home, plan)
        merged = merge_recall(keyword, vector)
        rows[q['id']] = {'hits': list(dict.fromkeys(r['source_session_id'] for r in merged)),
                         'embed_ms': (t1 - t0) * 1000, 'ms': (time.perf_counter() - t0) * 1000}
    return rows


def scoring_cost(rng):
    """Pure-Python scoring cost of the cap at common embedding dimensions (read-path loop shape)."""
    bench = {}
    for dims in (384, 1536, 3072):
        q = [rng.random() for _ in range(dims)]
        blob = struct.pack('<' + 'f' * dims, *[rng.random() for _ in range(dims)])
        t0 = time.perf_counter()
        for _ in range(4096):
            math.fsum(a * b for a, b in zip(q, struct.unpack('<' + 'f' * dims, blob)))
        bench[dims] = (time.perf_counter() - t0) * 1000
    return bench


def main():
    rng = random.Random(7)
    db = SessionDB(PROFILE / 'state.db')
    home = HomeStore(db).ensure_home()
    t0 = time.perf_counter()
    seed(db, rng)
    out = {'filler_messages': ARGS.filler, 'seed_seconds': time.perf_counter() - t0, 'index': index(db, home)}
    rows = queries(db, home)
    out['runs'] = {'home/hybrid': rows}
    out['score'] = score_run(rows)
    out['latency_ms'] = {k: statistics.median(r[k] for r in rows.values()) for k in ('embed_ms', 'ms')}
    out['scoring_ms_at_4096_vectors'] = scoring_cost(rng)
    Path(ARGS.out).write_text(json.dumps(out, indent=1))
    print('wrote', ARGS.out)


main()
