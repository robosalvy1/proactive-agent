"""Opt-in derived Home vectors; canonical transcripts remain the only evidence store."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import json
import math
import sqlite3
import struct
import time

from agent.home_embeddings import embed, embedding_input_sizes, load_embedding_config, MAX_DIMENSIONS, MAX_INPUT_CHARS
from hermes_state_home import HomeStore, MAX_RESULTS

MAX_INDEX_ROWS = 4096
MAX_SCAN_ROWS = 256
MAX_SOURCE_CHARS = 900
TABLE = 'home_recall_vectors'
CURSOR_PREFIX = 'home.semantic.cursor.v1:'
GENERATION_KEY = 'home.semantic.generation.v1'
_FAILURES = (OSError, ValueError, TypeError, KeyError, sqlite3.Error, http.client.HTTPException)


@dataclass(frozen=True)
class SemanticQuery:
    model_key: str
    vector: tuple[float, ...]
    min_similarity: float


def _table_exists(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone())


def _source_hash(row):
    return hashlib.sha256(json.dumps([row['session_id'], row['message_uid'], row['role'],
                                     row['timestamp'], row['content']], ensure_ascii=True).encode()).hexdigest()


def _source_on(conn, message_id):
    return conn.execute(
        'SELECT id,session_id,message_uid,role,timestamp,substr(content,1,?) AS content '
        "FROM messages WHERE id=? AND role IN ('user','assistant') AND (active=1 OR compacted=1) "
        "AND _compressed_summary=0 AND COALESCE(display_kind,'')!='hidden'",
        (MAX_SOURCE_CHARS, message_id),
    ).fetchone()


def _current_on(store, conn, session_id):
    state = store._state_on(conn)
    if not state.get('enabled'):
        return state, None
    row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    return state, store._participating_on(conn, row, state)


def _source_allowed_on(store, conn, row, state):
    from hermes_state_home_controls import source_allowed_on

    if row is None or not source_allowed_on(conn, row):
        return None
    session = conn.execute('SELECT * FROM sessions WHERE id=?', (row['session_id'],)).fetchone()
    return store._participating_on(conn, session, state)


def _indexed_evidence_on(store, conn, indexed, state):
    """An unchanged authorized vector can point to an explicit newer correction."""
    from hermes_state_home_controls import resolve_source_on

    source = _source_on(conn, indexed['message_id'])
    if source is None or _source_hash(source) != indexed['source_hash']:
        return None
    session = conn.execute('SELECT * FROM sessions WHERE id=?', (source['session_id'],)).fetchone()
    if store._participating_on(conn, session, state) is None:
        return None
    resolved = resolve_source_on(store.db, conn, source, store.principal_id)
    meta = _source_allowed_on(store, conn, resolved, state)
    return (resolved, meta) if meta is not None else None


def _index_generation_on(conn):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (GENERATION_KEY,)).fetchone()
    return row[0] if row else '0'


def prepare_semantic_query(db, session_id, query, *, principal_id=None):
    """At most one query call, only after current access and an existing index are checked.

    Call outside SQLite transactions. Optional provider failure retains keyword recall.
    """
    if not isinstance(query, str) or not query.strip():
        return None
    try:
        cfg = load_embedding_config(db)
        if cfg is None:
            return None
        store = HomeStore(db, principal_id=principal_id)
        with db._read_ctx() as conn:
            _, current = _current_on(store, conn, session_id)
            if current is None or not _table_exists(conn):
                return None
            if not conn.execute(f'SELECT 1 FROM {TABLE} WHERE model_key=? LIMIT 1', (cfg.identity,)).fetchone():
                return None
        vector = embed(cfg, [query[:2000]])[0]
        latest = load_embedding_config(db)
        if latest is None or latest.identity != cfg.identity:
            return None
        return SemanticQuery(cfg.identity, vector, cfg.min_similarity)
    except _FAILURES:
        # Optional retrieval is best-effort. Return no copied snippets or provider error
        # body; existing lexical evidence remains available to the caller.
        return None


def semantic_rows_on(db, conn, principal_id, session_id, plan):
    """Score derived vectors but publish only fresh, currently authorized source rows."""
    if plan is None or not _table_exists(conn):
        return []
    store = HomeStore(db, principal_id=principal_id)
    state, current = _current_on(store, conn, session_id)
    if current is None:
        return []
    ranked = []
    rows = conn.execute(f'SELECT message_id,source_hash,dimensions,vector FROM {TABLE} '
                        'WHERE model_key=? ORDER BY message_id DESC LIMIT ?', (plan.model_key, MAX_INDEX_ROWS))
    for indexed in rows:
        if indexed['dimensions'] != len(plan.vector) or not 1 <= indexed['dimensions'] <= MAX_DIMENSIONS:
            continue
        blob = indexed['vector']
        if not isinstance(blob, bytes) or len(blob) != 4 * indexed['dimensions']:
            continue
        vector = struct.unpack('<' + 'f' * indexed['dimensions'], blob)
        score = math.fsum(a * b for a, b in zip(plan.vector, vector))
        if not math.isfinite(score) or score < plan.min_similarity:
            continue
        evidence = _indexed_evidence_on(store, conn, indexed, state)
        if evidence is None:
            continue
        row, meta = evidence
        if meta['home_anchor'] == current['home_anchor']:
            continue
        ranked.append((score, row, meta))
    ranked.sort(key=lambda hit: (hit[0], hit[1]['timestamp'], hit[1]['id']), reverse=True)
    result, seen = [], set()
    for _, row, meta in ranked[:MAX_RESULTS]:
        # Include immediate corrections under the same source-admission rules.
        for item in [row, *store._following_on(conn, row)]:
            identity = item['message_uid'] or item['id']
            if identity in seen or _source_allowed_on(store, conn, item, state) is None:
                continue
            seen.add(identity)
            profile = db._own_profile_name()
            sid = item['session_id']
            result.append({**dict(item), 'title': meta['title'] or 'Untitled',
                           'source_session_id': sid,
                           'link': f'@session:{profile}/{sid}' if profile else f'@session:{sid}'})
            if len(result) == MAX_RESULTS:
                return result
    return result


def merge_recall(keyword, semantic):
    """Reciprocal-rank fusion preserves exact matches while admitting paraphrase hits."""
    if not semantic:
        return keyword
    rows, scores = {}, {}
    for leg in (keyword, semantic):
        for rank, row in enumerate(leg):
            key = row.get('message_uid') or row['id']
            rows[key] = row
            scores[key] = scores.get(key, 0) + 1 / (60 + rank + 1)
    return [rows[key] for key in sorted(scores, key=lambda key: -scores[key])[:MAX_RESULTS]]


class HomeIndex:
    """Explicit bounded indexing, with a durable cursor and reuse of unchanged vectors."""

    def __init__(self, db, *, principal_id=None):
        self.db = db
        self.home = HomeStore(db, principal_id=principal_id)
        self.principal_id = principal_id

    def clear(self, session_id):
        """Clear derived vectors/cursors and revoke an already-dispatched indexing pass."""
        from hermes_state_home_links import require_local_owner

        def reset(conn):
            require_local_owner(self.home, conn, session_id)
            if _table_exists(conn):
                conn.execute(f'DELETE FROM {TABLE}')
            conn.execute('DELETE FROM state_meta WHERE key GLOB ?', (CURSOR_PREFIX + '*',))
            conn.execute('INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) '
                         'DO UPDATE SET value=excluded.value', (GENERATION_KEY, str(time.time_ns())))
        self.db._execute_write(reset)

    def index(self, session_id):
        """One scan page and at most one 32-item/16k-character embedding batch per call."""
        cfg = load_embedding_config(self.db)
        if cfg is None:
            raise ValueError('Enable memory.home_recall and configure its embedding endpoint first.')
        principal = hashlib.sha256(str(self.principal_id).encode()).hexdigest()[:16]
        cursor_key = CURSOR_PREFIX + cfg.identity + ':' + principal
        with self.db._read_ctx() as conn:
            state, current = _current_on(self.home, conn, session_id)
            if current is None:
                raise ValueError('Open Home and participate in this conversation before indexing.')
            saved = conn.execute('SELECT value FROM state_meta WHERE key=?', (cursor_key,)).fetchone()
            cursor = int(saved[0]) if saved else 0
            rows = conn.execute(
                'SELECT id,session_id,message_uid,role,timestamp,substr(content,1,?) AS content '
                "FROM messages WHERE id>? AND role IN ('user','assistant') AND (active=1 OR compacted=1) "
                "AND _compressed_summary=0 AND COALESCE(display_kind,'')!='hidden' ORDER BY id LIMIT ?",
                (MAX_SOURCE_CHARS, cursor, MAX_SCAN_ROWS),
            ).fetchall()
            cached, obsolete = {}, []
            if _table_exists(conn):
                for indexed in conn.execute(f'SELECT message_id,source_hash FROM {TABLE} WHERE model_key=?',
                                            (cfg.identity,)):
                    if _indexed_evidence_on(self.home, conn, indexed, state) is not None:
                        cached[indexed['message_id']] = indexed['source_hash']
                    else:
                        obsolete.append(indexed['message_id'])
            pending, chars, scanned, skipped = [], 0, 0, 0
            sizes = embedding_input_sizes(cfg, [row['content'] for row in rows])
            for row, input_size in zip(rows, sizes):
                if _source_allowed_on(self.home, conn, row, state) is None or not row['content']:
                    cursor, scanned = row['id'], scanned + 1
                    continue
                digest = _source_hash(row)
                if cached.get(row['id']) == digest:
                    cursor, scanned = row['id'], scanned + 1
                    continue
                if input_size > MAX_INPUT_CHARS:
                    cursor, scanned, skipped = row['id'], scanned + 1, skipped + 1
                    continue
                if len(pending) == 32 or chars + input_size > MAX_INPUT_CHARS:
                    break
                if len(cached) + len(pending) >= MAX_INDEX_ROWS and row['id'] not in cached:
                    raise ValueError('Home semantic index is full (4096 sources); clear or exclude older sources.')
                pending.append((dict(row), digest))
                chars += input_size
                cursor, scanned = row['id'], scanned + 1
            more = len(rows) == MAX_SCAN_ROWS or scanned < len(rows)
            generation = (state.get('anchor'), state.get('enabled_at'), _index_generation_on(conn))
        vectors = embed(cfg, [row['content'] for row, _ in pending]) if pending else []
        # Model/endpoint changes during HTTP revoke publication, never mix embedding spaces.
        latest = load_embedding_config(self.db)
        if latest is None or latest.identity != cfg.identity:
            raise ValueError('Embedding configuration changed; rerun /home index.')

        def publish(conn):
            state, current = _current_on(self.home, conn, session_id)
            if current is None or generation != (state.get('anchor'), state.get('enabled_at'), _index_generation_on(conn)):
                raise ValueError('Home access changed while indexing.')
            conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} ('
                         'model_key TEXT NOT NULL,message_id INTEGER NOT NULL,source_hash TEXT NOT NULL,'
                         'dimensions INTEGER NOT NULL,vector BLOB NOT NULL,indexed_at REAL NOT NULL,'
                         'PRIMARY KEY(model_key,message_id),FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)')
            # Obsolete embedding spaces are derived state, not an ever-growing archive.
            conn.execute(f'DELETE FROM {TABLE} WHERE model_key!=?', (cfg.identity,))
            for message_id in obsolete:
                indexed = conn.execute(f'SELECT message_id,source_hash FROM {TABLE} '
                                       'WHERE model_key=? AND message_id=?', (cfg.identity, message_id)).fetchone()
                if indexed and _indexed_evidence_on(self.home, conn, indexed, state) is None:
                    conn.execute(f'DELETE FROM {TABLE} WHERE model_key=? AND message_id=?',
                                 (cfg.identity, message_id))
            published = 0
            count = conn.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0]
            for (source, digest), vector in zip(pending, vectors):
                row = _source_on(conn, source['id'])
                if _source_allowed_on(self.home, conn, row, state) is None or _source_hash(row) != digest:
                    continue
                existing = conn.execute(f'SELECT 1 FROM {TABLE} WHERE model_key=? AND message_id=?',
                                        (cfg.identity, row['id'])).fetchone()
                if existing is None:
                    if count >= MAX_INDEX_ROWS:
                        raise ValueError('Home semantic index reached its bounded source limit.')
                    count += 1
                blob = struct.pack('<' + 'f' * len(vector), *vector)
                conn.execute(f'INSERT INTO {TABLE} VALUES (?,?,?,?,?,?) ON CONFLICT(model_key,message_id) '
                             'DO UPDATE SET source_hash=excluded.source_hash,dimensions=excluded.dimensions,'
                             'vector=excluded.vector,indexed_at=excluded.indexed_at',
                             (cfg.identity, row['id'], digest, len(vector), blob, time.time()))
                published += 1
            conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) '
                         'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         (cursor_key, str(cursor if more else 0)))
            return {'indexed': published, 'scanned': scanned, 'skipped': skipped,
                    'more': more, 'cursor': cursor if more else 0,
                    'model': cfg.model, 'status': 'ready' if not more else 'more'}
        return self.db._execute_write(publish)
