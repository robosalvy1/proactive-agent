"""Semantic recall latency vs index size (synthetic vectors; measures the read path only).

    python bench_scoring.py --code-root . --sizes 4096,20000,40000 --dims 384
"""
import argparse
import math
import os
from pathlib import Path
import random
import statistics
import struct
import sys
import tempfile
import time

ap = argparse.ArgumentParser()
ap.add_argument('--code-root', required=True)
ap.add_argument('--sizes', default='4096,20000,40000')
ap.add_argument('--dims', type=int, default=384)
ap.add_argument('--queries', type=int, default=20)
ARGS = ap.parse_args()
ROOT = Path(tempfile.mkdtemp(prefix='bench-scoring-'))
os.environ['HERMES_HOME'] = str(ROOT / 'home')
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))

from hermes_state import SessionDB
from hermes_state_home import HomeStore
import hermes_state_home_semantic as hs


def unit(rng):
    v = [rng.gauss(0, 1) for _ in range(ARGS.dims)]
    n = math.hypot(*v)
    return [x / n for x in v]


DEFAULT_RESCORE_MIN = hs.RESCORE_MIN  # The product default, restored after every size.


def build(size, rng):
    profile = ROOT / f'p{size}'
    profile.mkdir()
    (profile / 'config.yaml').write_text('memory:\n  home_recall:\n    enabled: true\n'
                                         '    base_url: http://127.0.0.1:9/v1\n    model: bench\n    api_key_env: ""\n')
    db = SessionDB(profile / 'state.db')
    home = HomeStore(db).ensure_home()
    from agent.home_embeddings import load_embedding_config
    cfg = load_embedding_config(db)
    per = 50
    for s in range(-(-size // per)):  # Exactly ``size`` vectors: the last session takes the remainder.
        db.create_session(f's{s}', 'cli')
        db.append_messages_batch(f's{s}', [{'role': 'user', 'content': f'note {s}-{i}'}
                                            for i in range(min(per, size - s * per))])

    def fill(conn):
        hs._ensure_table_on(conn, cfg)
        rows = conn.execute("SELECT id,session_id,message_uid,role,timestamp,substr(content,1,900) AS content "
                            "FROM messages WHERE role='user'").fetchall()
        for row in rows:
            v = unit(rng)
            conn.execute(f'INSERT INTO {hs.TABLE} VALUES (?,?,?,?,?,?)', (
                cfg.identity, row['id'], hs._source_hash(row), len(v), struct.pack('<' + 'f' * len(v), *v), time.time()))
            conn.execute(f'INSERT INTO {hs.CODES} VALUES (?,?,?)', (cfg.identity, row['id'], hs._sign_code(v)))
        hs._bump_on(conn, hs.VECTORS_KEY)
    db._execute_write(fill)
    return db, home, cfg


def main():
    rng = random.Random(5)
    for size in map(int, ARGS.sizes.split(',')):
        db, home, cfg = build(size, rng)
        plans = [hs.SemanticQuery(cfg.identity, tuple(unit(rng)), 0.0) for _ in range(ARGS.queries)]
        for label, minimum in (('fast', DEFAULT_RESCORE_MIN), ('exact', 10 ** 9)):
            hs.RESCORE_MIN = minimum
            hs._CODE_CACHE.clear()
            with db._read_ctx() as conn:
                t0 = time.perf_counter()
                hs.semantic_rows_on(db, conn, None, home, plans[0])
                cold = (time.perf_counter() - t0) * 1000
                times = []
                for plan in plans[1:]:
                    t0 = time.perf_counter()
                    hs.semantic_rows_on(db, conn, None, home, plan)
                    times.append((time.perf_counter() - t0) * 1000)
            print(f'{size:6} vectors x {ARGS.dims}d  {label:5}  first query {cold:7.0f} ms   '
                  f'median {statistics.median(times):6.0f} ms   p90 {sorted(times)[int(len(times) * 0.9)]:6.0f} ms',
                  flush=True)
        hs.RESCORE_MIN = DEFAULT_RESCORE_MIN
        db.close()


if __name__ == '__main__':
    main()
