"""Home retrieval on LongMemEval-S (no LLM): does recall surface the evidence sessions/turns?

Each question gets a fresh disposable profile holding its haystack sessions at their original
dates; the question is asked from a new Home session. Retrieval is scored against the dataset's
``answer_session_ids`` (session level) and ``has_answer`` turns (turn level). Download the MIT
``longmemeval_s_cleaned.json`` from huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
outside the repository; never commit it, and convert it to JSONL (one question per line):

    python -c "import json,sys; [print(json.dumps(q)) for q in json.load(open(sys.argv[1]))]" \\
        ~/data/longmemeval_s_cleaned.json > ~/data/longmemeval_s.jsonl
    python run_longmemeval.py --code-root . --data ~/data/longmemeval_s.jsonl --out lme.json \\
        --base-url http://127.0.0.1:18555/v1 --model BAAI/bge-small-en-v1.5 --limit 100
"""
import argparse
import collections
from datetime import datetime
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('--code-root', required=True)
ap.add_argument('--data', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--base-url')
ap.add_argument('--model')
ap.add_argument('--min-similarity', type=float, default=0.55)
ap.add_argument('--limit', type=int, default=0, help='stratified sample size (0 = all)')
ap.add_argument('--seed', type=int, default=7)
ap.add_argument('--ids', help='comma-separated question ids to run')
ap.add_argument('--embed-batch', type=int, default=0,
                help='eval-only: smaller embedding batches for a slow local CPU embedder')
ap.add_argument('--save-context', action='store_true', help='store the exact context Home injects (for run_e2e.py)')
ARGS = ap.parse_args()

ROOT = Path(tempfile.mkdtemp(prefix='lme-'))
os.environ['HERMES_HOME'] = str(ROOT / 'home')
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))

from hermes_state import SessionDB
from hermes_state_home import HomeStore
import hermes_state_home_semantic as semantic


def sample(path):
    """Stratified by question type (abstention separate); only the picked questions are loaded."""
    path = os.path.expanduser(path)
    if not path.endswith('.jsonl'):
        raise SystemExit('Convert the dataset to JSONL first (one question per line) to bound memory.')
    meta = []
    with open(path) as handle:
        for line in handle:
            head = json.loads(line)
            meta.append((head['question_id'], head['question_type']))
    if ARGS.ids:
        wanted = set(ARGS.ids.split(','))
    elif not ARGS.limit or ARGS.limit >= len(meta):
        wanted = {qid for qid, _ in meta}
    else:
        rng, groups = random.Random(ARGS.seed), collections.defaultdict(list)
        for qid, kind in meta:
            groups[kind + ('_abs' if qid.endswith('_abs') else '')].append(qid)
        wanted = set()
        for name in sorted(groups):
            share = max(1, round(ARGS.limit * len(groups[name]) / len(meta)))
            wanted.update(rng.sample(groups[name], min(share, len(groups[name]))))
    with open(path) as handle:
        return [q for q in map(json.loads, handle) if q['question_id'] in wanted]


def epoch(date):
    # '2023/05/20 (Sat) 02:21'
    return datetime.strptime(date.split(' (')[0] + ' ' + date.split(') ')[1], '%Y/%m/%d %H:%M').timestamp()


def build(question, profile):
    profile.mkdir(parents=True)
    cfg = 'memory:\n  home_recall:\n    enabled: true\n'
    if ARGS.base_url:
        cfg += (f'    base_url: {ARGS.base_url}\n    model: {ARGS.model}\n    api_key_env: ""\n'
                f'    timeout_seconds: 10\n    min_similarity: {ARGS.min_similarity}\n    auto_index: false\n')
    else:
        cfg = 'memory: {}\n'
    (profile / 'config.yaml').write_text(cfg)
    db = SessionDB(profile / 'state.db')
    # Sessions that predate enabling Home take part only when explicitly shared.
    home = HomeStore(db).ensure_home()
    gold_turns = set()
    order = sorted(range(len(question['haystack_sessions'])), key=lambda i: question['haystack_dates'][i])
    for i in order:
        sid, base = question['haystack_session_ids'][i], epoch(question['haystack_dates'][i])
        db.create_session(sid, 'cli')
        for n, turn in enumerate(question['haystack_sessions'][i]):
            if not turn['content'].strip():
                continue
            db.append_message(sid, turn['role'], turn['content'], timestamp=base + n)
            if turn.get('has_answer'):
                gold_turns.add((sid, turn['content'][:200]))
    return db, home, gold_turns


def index(db, home):
    if not ARGS.base_url:
        return {}
    from agent.home_embeddings import load_embedding_config, reset_embedding_health

    t0, steps, retries, result = time.perf_counter(), 0, 0, {}
    while True:
        try:
            result = semantic.HomeIndex(db).index(home, refresh=steps == 0)
        except OSError:
            # A slow local CPU embedder is the eval's limit, not Home's: retry the same step.
            retries += 1
            if retries > 200:
                raise
            time.sleep(min(30, retries))
            reset_embedding_health(load_embedding_config(db))
            continue
        steps += 1
        if not result['more']:
            break
    return {'seconds': time.perf_counter() - t0, 'steps': steps, 'retries': retries}


def recall(db, home, query):
    t0 = time.perf_counter()
    plan = semantic.prepare_semantic_query(db, home, query) if ARGS.base_url else None
    with db._read_ctx() as conn:
        keyword = HomeStore(db).recall_on(conn, home, query, overview=False)
        vector = semantic.semantic_rows_on(db, conn, None, home, plan)
    merged = semantic.merge_recall(keyword, vector)
    ms = (time.perf_counter() - t0) * 1000
    context = ''
    if ARGS.save_context:
        from hermes_state_home_context import home_context_on
        with db._read_ctx() as conn:
            context = home_context_on(db, conn, None, home, query, semantic_plan=plan)['context']
    pack = lambda rows: [(r['source_session_id'], (r['content'] or '')[:200]) for r in rows]
    return {'keyword': pack(keyword), 'semantic': pack(vector), 'merged': pack(merged), 'ms': ms, 'context': context}


def score(hits, gold_sessions, gold_turns):
    sessions = list(dict.fromkeys(s for s, _ in hits))
    return {'session_any': bool(set(sessions) & gold_sessions),
            'session_all': gold_sessions <= set(sessions),
            'turn_any': any(h in gold_turns for h in hits),
            'first_gold_rank': next((i + 1 for i, s in enumerate(sessions) if s in gold_sessions), None),
            'returned': len(hits)}


def main():
    if ARGS.embed_batch:
        semantic.MAX_BATCH = ARGS.embed_batch
    questions = sample(ARGS.data)
    results = []
    if os.path.exists(ARGS.out):  # Resume: keep finished questions.
        results = json.load(open(ARGS.out))['results']
    done = {row['id'] for row in results}
    for n, q in enumerate(questions):
        if q['question_id'] in done:
            continue
        profile = ROOT / f'q{n}'
        db, home, gold_turns = build(q, profile)
        try:
            idx = index(db, home)
            got = recall(db, home, q['question'])
        finally:
            db.close()
            shutil.rmtree(profile, ignore_errors=True)
        gold = set(q['answer_session_ids'])
        row = {'id': q['question_id'], 'type': q['question_type'], 'abstention': q['question_id'].endswith('_abs'),
               'index': idx, 'ms': got['ms'], **({'context': got['context']} if ARGS.save_context else {}),
               **{leg: score(got[leg], gold, gold_turns) for leg in ('keyword', 'semantic', 'merged')}}
        results.append(row)
        print(f"[{n + 1}/{len(questions)}] {row['type']:28} kw={row['keyword']['session_any']!s:5} "
              f"sem={row['semantic']['session_any']!s:5} merged={row['merged']['session_any']!s:5} "
              f"{got['ms']:.0f}ms", flush=True)
        partial = Path(f'{ARGS.out}.tmp')  # Written whole, then swapped in: an interrupted save keeps the old file.
        with open(partial, 'w') as handle:
            json.dump({'args': vars(ARGS), 'results': results}, handle, indent=1)
        os.replace(partial, ARGS.out)
    shutil.rmtree(ROOT, ignore_errors=True)


if __name__ == '__main__':
    main()
