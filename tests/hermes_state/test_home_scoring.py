"""Two-stage Home semantic scoring: sign-code candidates, widening, cache coherence, dimensions.

Several cases were contributed as reproductions by a GPT-6.1 Sol peer review.
"""
import sqlite3
import struct

import pytest

from agent.home_embeddings import load_embedding_config, normalized_vector
from hermes_state_home import HomeStore
import hermes_state_home_semantic as hs
from tests.hermes_state.test_home_auto_index import add, make_db


@pytest.fixture
def db(tmp_path, endpoint):
    store = make_db(tmp_path, endpoint)
    hs._CODE_CACHE.clear()
    yield store
    store.close()


def setup_index(db, monkeypatch, vectors):
    monkeypatch.setattr(hs, 'embed', lambda cfg, texts: [normalized_vector(vectors[t]) for t in texts])
    monkeypatch.setattr(hs, 'RESCORE_MIN', 4)
    home = HomeStore(db).ensure_home()
    return home


def hits(db, home, vector):
    plan = hs.SemanticQuery(load_embedding_config(db).identity, normalized_vector(vector), 0.5)
    with db._read_ctx() as conn:
        return hs.semantic_rows_on(db, conn, None, home, plan)


def test_cascade_delete_invalidates_warmed_candidates(db, monkeypatch):
    vectors = {f'ghost{i}': [1, 0, 0] for i in range(6)}
    vectors['target'] = [1, .1, 0]
    home = setup_index(db, monkeypatch, vectors)
    for text in vectors:
        add(db, text, text)
    hs.HomeIndex(db).drain(home)
    hits(db, home, [1, 0, 0])  # Warm this process's code cache.
    before = db._read_one('SELECT value FROM state_meta WHERE key=?', (hs.VECTORS_KEY,))[0]
    for i in range(6):
        db.delete_session(f'ghost{i}')
    assert db._read_one(f'SELECT COUNT(*) FROM {hs.TABLE}')[0] == 1
    assert db._read_one(f'SELECT COUNT(*) FROM {hs.CODES}')[0] == 1
    assert db._read_one('SELECT value FROM state_meta WHERE key=?', (hs.VECTORS_KEY,))[0] == before
    cached = hits(db, home, [1, 0, 0])
    hs._CODE_CACHE.clear()
    fresh = hits(db, home, [1, 0, 0])
    assert [r['content'] for r in fresh] == ['target']
    assert [r['content'] for r in cached] == ['target'], 'cascade left ghost candidates in process cache'


def test_current_home_cannot_exhaust_authorized_candidate_budget(db, monkeypatch):
    vectors = {f'own{i}': [1, 0, 0] for i in range(6)}
    vectors['target'] = [1, .1, 0]
    home = setup_index(db, monkeypatch, vectors)
    db.append_messages_batch(home, [{'role': 'user', 'content': f'own{i}'} for i in range(6)])
    add(db, 'source', 'target')
    hs.HomeIndex(db).drain(home)
    fast = hits(db, home, [1, 0, 0])
    monkeypatch.setattr(hs, 'RESCORE_MIN', 100)
    exact = hits(db, home, [1, 0, 0])
    assert [r['content'] for r in exact] == ['target']
    assert [r['content'] for r in fast] == ['target'], 'own-lineage hits consumed the entire candidate budget'


def test_dimension_change_cannot_exhaust_rescore_candidates(db, monkeypatch):
    vectors = {f'old{i}': [0, 0, 1] for i in range(6)}
    vectors['target'] = [0, 0, .1, 1]
    home = setup_index(db, monkeypatch, vectors)
    for i in range(6):
        add(db, f'old{i}', f'old{i}')
    hs.HomeIndex(db).drain(home)
    add(db, 'new', 'target')
    hs.HomeIndex(db).index(home)
    fast = hits(db, home, [0, 0, 0, 1])
    monkeypatch.setattr(hs, 'RESCORE_MIN', 100)
    exact = hits(db, home, [0, 0, 0, 1])
    assert [r['content'] for r in exact] == ['target']
    assert [r['content'] for r in fast] == ['target'], 'incompatible dimensions consumed candidates'


def test_capacity_is_a_bound_after_endpoint_dimension_change(db, monkeypatch):
    # Scale only the float budget; ratio and batch dimension changes match production.
    monkeypatch.setattr(hs, 'MAX_INDEX_FLOATS', 24)
    vectors = {f'old{i}': [1] for i in range(12)}
    vectors.update({f'new{i}': [1, 0, 0] for i in range(8)})
    home = setup_index(db, monkeypatch, vectors)
    for i in range(12):
        add(db, f'old{i}', f'old{i}')
    hs.HomeIndex(db).drain(home)
    for i in range(8):
        add(db, f'new{i}', f'new{i}')
    hs.HomeIndex(db).index(home)
    floats = db._read_one(f'SELECT SUM(dimensions) FROM {hs.TABLE}')[0]
    assert floats <= hs.MAX_INDEX_FLOATS, f'{floats} floats exceeds {hs.MAX_INDEX_FLOATS}'


def test_exact_ties_keep_newest_resolved_correction(db, monkeypatch):
    # Resolved correction recency differs from original message ID order.
    vectors = {f'old{i}': [1, 0, 0] for i in range(10)}
    vectors.update({f'fix{i}': [0, 0, 1] for i in range(10)})
    home = setup_index(db, monkeypatch, vectors)
    originals = [add(db, f'old{i}', f'old{i}') for i in range(10)]
    hs.HomeIndex(db).drain(home)
    # Reverse correction publication order so resolved recency differs from original IDs.
    from hermes_state_home_controls import HomeSourceControls
    corrections = {}
    for i in reversed(range(10)):
        corrections[i] = add(db, f'fix{i}', f'fix{i}')
        HomeSourceControls(db).supersede(originals[i], corrections[i])
    monkeypatch.setattr(hs, 'RESCORE_MIN', 100)
    actual = hits(db, home, [1, 0, 0])
    expected = [f'fix{i}' for i in range(8)]
    assert [r['content'] for r in actual] == expected


def test_missing_codes_table_migrates_and_clear_is_safe(db, monkeypatch):
    vectors = {'target': [1, 0, 0]}
    home = setup_index(db, monkeypatch, vectors)
    add(db, 'source', 'target')
    hs.HomeIndex(db).index(home)
    db._execute_write(lambda conn: conn.execute(f'DROP TABLE {hs.CODES}'))
    hs._CODE_CACHE.clear()
    assert [r['content'] for r in hits(db, home, [1, 0, 0])] == ['target']
    hs.HomeIndex(db).status(home)
    hs.HomeIndex(db).index(home, refresh=False)
    assert db._read_one(f'SELECT COUNT(*) FROM {hs.CODES}')[0] == 1
    db._execute_write(lambda conn: conn.execute(f'DROP TABLE {hs.CODES}'))
    hs.HomeIndex(db).clear(home)
    assert db._read_one(f'SELECT COUNT(*) FROM {hs.TABLE}')[0] == 0


def test_separate_connection_publish_invalidates_cache(db, monkeypatch):
    vectors = {f'noise{i}': [1, 0, 0] for i in range(6)}
    vectors['target'] = [0, 0, 1]
    home = setup_index(db, monkeypatch, vectors)
    ids = {t: add(db, t, t) for t in vectors}
    hs.HomeIndex(db).drain(home)
    hits(db, home, [1, 0, 0])
    with sqlite3.connect(str(db.db_path)) as conn:
        vector = normalized_vector([-1, 0, 0])
        conn.executemany(f'UPDATE {hs.TABLE} SET vector=? WHERE message_id=?',
                         [(struct.pack('<3f', *vector), ids[f'noise{i}']) for i in range(6)])
        conn.executemany(f'UPDATE {hs.CODES} SET code=? WHERE message_id=?',
                         [(hs._sign_code(vector), ids[f'noise{i}']) for i in range(6)])
        hs._bump_on(conn, hs.VECTORS_KEY)
    assert [r['content'] for r in hits(db, home, [0, 0, 1])] == ['target']


def test_cardinality_does_not_imply_vector_code_coverage(db, monkeypatch):
    vectors = {f'noise{i}': [0, 0, 1] for i in range(6)}
    vectors['target'] = [1, 0, 0]
    vectors['orphan'] = [0, 0, 1]
    home = setup_index(db, monkeypatch, vectors)
    ids = {t: add(db, t, t) for t in vectors}
    hs.HomeIndex(db).drain(home)
    # Old process/direct derived-state maintenance can remove vectors without codes.
    def diverge(conn):
        conn.execute(f'DELETE FROM {hs.TABLE} WHERE message_id=?', (ids['orphan'],))
        conn.execute(f'DELETE FROM {hs.CODES} WHERE message_id=?', (ids['target'],))
        hs._bump_on(conn, hs.VECTORS_KEY)
    db._execute_write(diverge)
    with db._read_ctx() as conn:
        cfg = load_embedding_config(db)
        assert hs._codes_on(db, conn, cfg.identity) is None, 'equal counts hide a vector without a code'


def test_interleaved_old_reader_does_not_poison_future_cache_versions(db, monkeypatch):
    vectors = {'target': [1, 0, 0]}
    home = setup_index(db, monkeypatch, vectors)
    mid = add(db, 'source', 'target')
    hs.HomeIndex(db).index(home)
    cfg = load_embedding_config(db)
    old = sqlite3.connect(f'file:{db.db_path}?mode=ro', uri=True, isolation_level=None)
    old.row_factory = sqlite3.Row
    try:
        old.execute('BEGIN')
        assert hs._codes_on(db, old, cfg.identity)[1] == [4]
        def update(conn):
            conn.execute(f'UPDATE {hs.TABLE} SET vector=? WHERE message_id=?',
                         (struct.pack('<3f', 0, 0, 1), mid))
            conn.execute(f'UPDATE {hs.CODES} SET code=? WHERE message_id=?', (b'\x01', mid))
            hs._bump_on(conn, hs.VECTORS_KEY)
        db._execute_write(update)
        with db._read_ctx() as current:
            assert hs._codes_on(db, current, cfg.identity)[1] == [1]
        # A late reader can replace the global entry with its older snapshot.
        assert hs._codes_on(db, old, cfg.identity)[1] == [4]
        with db._read_ctx() as current:
            assert hs._codes_on(db, current, cfg.identity)[1] == [1]
    finally:
        old.close()


def test_current_home_candidate_starvation_at_production_reach(db, monkeypatch):
    vectors = {f'own{i}': [1, 0, 0] for i in range(256)}
    vectors['target'] = [1, .1, 0]
    home = setup_index(db, monkeypatch, vectors)
    monkeypatch.setattr(hs, 'RESCORE_MIN', 256)
    db.append_messages_batch(home, [{'role': 'user', 'content': f'own{i}'} for i in range(256)])
    add(db, 'source', 'target')
    hs.HomeIndex(db).drain(home)
    assert db._read_one(f'SELECT COUNT(*) FROM {hs.TABLE}')[0] == 257
    fast = hits(db, home, [1, 0, 0])
    monkeypatch.setattr(hs, 'RESCORE_MIN', 1000)
    assert [r['content'] for r in hits(db, home, [1, 0, 0])] == ['target']
    assert [r['content'] for r in fast] == ['target']
