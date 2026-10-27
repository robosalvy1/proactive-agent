"""Opt-in derived Home vectors; canonical transcripts remain the only evidence store."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import http.client
import json
import logging
import math
import operator
import sqlite3
import struct
import threading
import time
import uuid

from agent.home_embeddings import (
    embed, embedding_health, embedding_input_sizes, load_embedding_config, reset_embedding_health,
    MAX_BATCH, MAX_DIMENSIONS, MAX_INPUT_CHARS)
from hermes_state_home import HomeStore, MAX_RESULTS

MAX_INDEX_ROWS = 50_000
MAX_INDEX_FLOATS = 16 * 1024 * 1024  # 64 MiB of float32 vectors per profile index.
RESCORE_MIN = 256  # Exact-rescored candidates per round (fraction grows with the index).
MAX_ROUNDS = 8  # Widening rounds when candidates are rejected (current chat, deleted, excluded).
MAX_CACHED_INDEXES = 8
MAX_SCAN_ROWS = 256
MAX_SWEEP_ROWS = 256
MAX_SOURCE_CHARS = 900
TABLE = 'home_recall_vectors'
CODES = 'home_recall_codes'  # One sign bit per dimension: fast candidate generation.
CURSOR_PREFIX = 'home.semantic.cursor.v2:'
CURSOR_GLOB = 'home.semantic.cursor.*'  # Also clears v1 explicit-pass cursors.
SWEEP_KEY = 'home.semantic.sweep.v1'
LEASE_KEY = 'home.semantic.lease.v1'
COVERAGE_KEY = 'home.semantic.coverage.v1'
EVICTION_KEY = 'home.semantic.evictions.v1'
VECTORS_KEY = 'home.semantic.vectors.v1'
GENERATION_KEY = 'home.semantic.generation.v1'
logger = logging.getLogger(__name__)
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
    for scored, lost in _candidate_rounds(db, conn, plan):
        # Highest scores first; stop once enough sources pass the per-row authorization checks,
        # keeping the whole tie group at the boundary so tie-breaking matches a full scan.
        boundary = None
        for score, indexed in sorted(scored, key=lambda hit: hit[0], reverse=True):
            if boundary is not None and score < boundary:
                break
            evidence = _indexed_evidence_on(store, conn, indexed, state)
            if evidence is None or evidence[1]['home_anchor'] == current['home_anchor']:
                lost += 1
                continue
            row, meta = evidence
            ranked.append((score, row, meta))
            if boundary is None and len(ranked) >= MAX_RESULTS:
                boundary = score
        if len(ranked) >= MAX_RESULTS or not lost:
            break  # Widen only when deleted, mismatched or rejected candidates could starve recall.
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


def _sign_code(vector):
    return int(''.join('1' if x > 0 else '0' for x in vector), 2).to_bytes((len(vector) + 7) // 8, 'big')


# Exact dot product: math.sumprod on Python 3.12+, the same sum in pure Python on 3.11.
_dot = getattr(math, 'sumprod', None) or (lambda a, b: sum(map(operator.mul, a, b)))

def _capacity_on(conn, model_key):
    """Row cap, bounded by vector bytes: about 43.7k sources at 384 dimensions, 5.4k at 3072."""
    row = conn.execute(f'SELECT dimensions FROM {TABLE} WHERE model_key=? LIMIT 1',
                       (model_key,)).fetchone() if _table_exists(conn) else None
    return min(MAX_INDEX_ROWS, MAX_INDEX_FLOATS // row[0]) if row and row[0] else MAX_INDEX_ROWS


_CODE_CACHE = {}
_CODE_LOCK = threading.Lock()


def _codes_on(db, conn, model_key):
    """Process cache of (ids, sign codes), reloaded when the index version or the code count
    changes (cascade deletes of messages bypass the version). None while an upgraded index still
    lacks codes for some vectors (exact scan until backfilled)."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (CODES,)).fetchone()
    if not exists:
        return None
    version = _meta_on(conn, VECTORS_KEY)
    count = conn.execute(f'SELECT COUNT(*) FROM {CODES} WHERE model_key=?', (model_key,)).fetchone()[0]
    key = (str(db.db_path), model_key)
    with _CODE_LOCK:
        hit = _CODE_CACHE.get(key)
    if hit and hit[0] == (version, count):
        return hit[1]
    vectors = conn.execute(f'SELECT COUNT(*) FROM {TABLE} WHERE model_key=?', (model_key,)).fetchone()[0]
    # Checked on reload only: every vector has a code (equal counts could hide an orphan).
    covered = conn.execute(f'SELECT COUNT(*) FROM {TABLE} v JOIN {CODES} c ON c.model_key=v.model_key '
                           'AND c.message_id=v.message_id WHERE v.model_key=?', (model_key,)).fetchone()[0]
    codes = None
    if covered >= vectors:
        rows = conn.execute(f'SELECT message_id,code FROM {CODES} WHERE model_key=?', (model_key,)).fetchall()
        codes = ([r[0] for r in rows], [int.from_bytes(r[1], 'big') for r in rows])
    with _CODE_LOCK:
        _CODE_CACHE.pop(key, None)
        _CODE_CACHE[key] = ((version, count), codes)
        for stale in [k for k in _CODE_CACHE if k[0] == key[0] and k[1] != model_key]:
            del _CODE_CACHE[stale]  # A retired embedding space of this profile.
        while len(_CODE_CACHE) > MAX_CACHED_INDEXES:
            del _CODE_CACHE[next(iter(_CODE_CACHE))]
    return codes


def _exact_on(conn, plan, rows, requested=None):
    """(above-threshold scored rows, candidates lost to deletion or dimension mismatch)."""
    scored, lost = [], 0 if requested is None else requested - len(rows)
    for indexed in rows:
        if indexed['dimensions'] != len(plan.vector) or not 1 <= indexed['dimensions'] <= MAX_DIMENSIONS:
            lost += 1
            continue
        blob = indexed['vector']
        if not isinstance(blob, bytes) or len(blob) != 4 * indexed['dimensions']:
            lost += 1
            continue
        score = _dot(plan.vector, struct.unpack('<' + 'f' * indexed['dimensions'], blob))
        if math.isfinite(score) and score >= plan.min_similarity:
            scored.append((score, indexed))
    return scored, lost


def _candidate_rounds(db, conn, plan):
    """Yield (exact-scored vectors at or above the threshold, lost candidates), closest first.
    Large indexes rank every sign code by Hamming distance and rescore one round of the closest
    candidates at a time; callers widen only when candidates were lost or rejected (up to 8 rounds)."""
    codes = _codes_on(db, conn, plan.model_key)
    reach = max(RESCORE_MIN, len(codes[0]) // 64) if codes else 0
    columns = f'SELECT message_id,source_hash,dimensions,vector FROM {TABLE} WHERE model_key=?'
    if codes is None or len(codes[0]) <= reach:
        yield _exact_on(conn, plan, conn.execute(columns + ' ORDER BY message_id DESC LIMIT ?',
                                                 (plan.model_key, _capacity_on(conn, plan.model_key))))
        return
    probe = int.from_bytes(_sign_code(plan.vector), 'big')
    ids, signs = codes
    distance = [(sign ^ probe).bit_count() for sign in signs]
    # The first round is ranked alone; the wider ordering is computed only if a caller widens.
    order = [ids[i] for i in heapq.nsmallest(reach, range(len(ids)), key=distance.__getitem__)]
    for start in range(0, min(len(ids), MAX_ROUNDS * reach), reach):
        if start == reach:
            order = [ids[i] for i in heapq.nsmallest(min(len(ids), MAX_ROUNDS * reach), range(len(ids)),
                                                     key=distance.__getitem__)]
        rows, chunk = [], order[start:start + reach]
        for part_start in range(0, len(chunk), 500):
            part = chunk[part_start:part_start + 500]
            rows += conn.execute(columns + f" AND message_id IN ({','.join('?' * len(part))})",
                                 (plan.model_key, *part)).fetchall()
        yield _exact_on(conn, plan, rows, len(chunk))


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



def _forgotten_on(conn, row):
    """Forgotten itself, or an assistant reply to a forgotten user message (never embedded or kept).
    Superseded rows stay indexable: recall resolves them to their correction."""
    from hermes_state_home_controls import _rule_on

    rule = _rule_on(conn, row)
    return rule is not None and rule['action'] == 'forgotten'


def _indexable_on(store, conn, row, state):
    """Superseded originals stay indexable: recall resolves them to their correction."""
    if row is None or not row['content'] or _forgotten_on(conn, row):
        return None
    session = conn.execute('SELECT * FROM sessions WHERE id=?', (row['session_id'],)).fetchone()
    return store._participating_on(conn, session, state)


def _owned_by_on(store, conn, session):
    """Only the indexing principal's own sources may be swept for exclusion."""
    from hermes_state_home import PERSONAL_SOURCES
    from hermes_state_home_links import link_on

    if session is None:
        return True
    if session['source'] in PERSONAL_SOURCES:
        return session['user_id'] in (None, store.principal_id)
    grant = link_on(store, conn, session['id'])
    return grant is None or grant['principal_id'] == store.principal_id


def _load_cursor(conn, key):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
    try:
        saved = json.loads(row[0]) if row else None
        return {'hi': int(saved['hi']), 'lo': int(saved['lo']), 'done': bool(saved['done']),
                'paused': bool(saved.get('paused')), 'lossy': bool(saved.get('lossy')),
                'generation': str(saved.get('generation', '')), 'evictions': str(saved.get('evictions', ''))}
    except (TypeError, ValueError, KeyError):
        # Missing or corrupt cursor: start a fresh newest-first pass over all history.
        top = conn.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
        return _fresh_cursor(conn, top)


def _coverage_generation_on(conn):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (COVERAGE_KEY,)).fetchone()
    return row[0] if row else '0'


def _meta_on(conn, key):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else '0'


def _fresh_cursor(conn, top):
    """A new pass from ``top`` downward under the current coverage generation and eviction epoch."""
    return {'hi': top, 'lo': top + 1, 'done': False, 'paused': False, 'lossy': False,
            'generation': _coverage_generation_on(conn), 'evictions': _meta_on(conn, EVICTION_KEY)}


_SOURCE_COLUMNS = ('SELECT id,session_id,message_uid,role,timestamp,substr(content,1,?) AS content FROM messages '
                   "WHERE {} AND role IN ('user','assistant') AND (active=1 OR compacted=1) "
                   "AND _compressed_summary=0 AND COALESCE(display_kind,'')!='hidden' ORDER BY id {} LIMIT ?")
_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


class HomeIndex:
    """Automatic newest-first indexing with a durable two-ended cursor.

    New messages (above ``hi``) are embedded first, then older history is backfilled
    downward from ``lo``. When the bounded index is full, new sources evict the oldest
    vectors and backfill stops: recent history always wins.
    """

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
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (CODES,)).fetchone():
                    conn.execute(f'DELETE FROM {CODES}')
                _bump_on(conn, VECTORS_KEY)
            conn.execute('DELETE FROM state_meta WHERE key GLOB ? OR key=?', (CURSOR_GLOB, SWEEP_KEY))
            conn.execute('INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) '
                         'DO UPDATE SET value=excluded.value', (GENERATION_KEY, str(time.time_ns())))
        self.db._execute_write(reset)

    def _cursor_key(self, cfg):
        principal = hashlib.sha256(str(self.principal_id).encode()).hexdigest()[:16]
        return CURSOR_PREFIX + cfg.identity + ':' + principal

    def _scan_on(self, conn, cursor):
        front = conn.execute(_SOURCE_COLUMNS.format('id>?', 'ASC'),
                             (MAX_SOURCE_CHARS, cursor['hi'], MAX_SCAN_ROWS)).fetchall()
        room = MAX_SCAN_ROWS - len(front)
        back = [] if cursor['done'] or room <= 0 else conn.execute(
            _SOURCE_COLUMNS.format('id<?', 'DESC'), (MAX_SOURCE_CHARS, cursor['lo'], room)).fetchall()
        return front, back, room

    def _edited_on(self, conn, cfg, state):
        """Sources in the next sweep slice whose content changed: re-embed rather than drop."""
        edited = []
        for indexed in _sweep_slice_on(conn, cfg):
            source = _source_on(conn, indexed['message_id'])
            if (source is not None and _source_hash(source) != indexed['source_hash']
                    and _indexable_on(self.home, conn, source, state) is not None):
                edited.append(source)
        return edited

    def _plan_on(self, conn, cfg, state, cursor):
        """Choose one bounded embedding batch; returns pending sources and the advanced cursor."""
        front, back, room = self._scan_on(conn, cursor)
        scanned_ids = {row['id'] for row in (*front, *back)}
        edited = [row for row in (self._edited_on(conn, cfg, state) if _table_exists(conn) else [])
                  if row['id'] not in scanned_ids]
        rows = ([(row, 'edit') for row in edited] + [(row, 'front') for row in front]
                + [(row, 'back') for row in back])
        cached = {}
        if rows and _table_exists(conn):
            ids = [row['id'] for row, _ in rows]
            cached = dict(conn.execute(
                f'SELECT message_id,source_hash FROM {TABLE} WHERE model_key=? '
                f'AND message_id IN ({",".join("?" * len(ids))})', (cfg.identity, *ids)).fetchall())
            stored = conn.execute(f'SELECT COUNT(*) FROM {TABLE} WHERE model_key=?', (cfg.identity,)).fetchone()[0]
        else:
            stored = 0
        capacity = _capacity_on(conn, cfg.identity)
        sizes = embedding_input_sizes(cfg, [row['content'] or '' for row, _ in rows])
        nxt = dict(cursor)
        pending, chars, done_rows, skipped, full, inserts = [], 0, 0, 0, False, 0
        victims = None  # Smallest retained ids, fetched only once the index is full.
        for (row, side), size in zip(rows, sizes):
            digest = _source_hash(row)
            admit = _indexable_on(self.home, conn, row, state) is not None and cached.get(row['id']) != digest
            if admit and size > MAX_INPUT_CHARS:
                admit, skipped = False, skipped + 1
            if admit and (len(pending) == MAX_BATCH or chars + size > MAX_INPUT_CHARS):
                break
            if admit and side == 'back' and row['id'] not in cached and stored + inserts >= capacity:
                # Full: an older source may still replace an even older vector (e.g. a newly shared
                # chat); otherwise pause backfill instead of evicting newer sources.
                if victims is None:
                    victims = [] if not _table_exists(conn) else [r[0] for r in conn.execute(
                        f'SELECT message_id FROM {TABLE} WHERE model_key=? ORDER BY message_id LIMIT ?',
                        (cfg.identity, MAX_BATCH + 1))]
                slot = stored + inserts - capacity
                if slot >= len(victims) or victims[slot] >= row['id']:
                    full = True
                    break
            if admit:
                pending.append((dict(row), digest, side))
                chars += size
                inserts += row['id'] not in cached
            if side == 'edit':
                continue
            nxt['hi' if side == 'front' else 'lo'] = row['id']
            done_rows += 1
        scanned = len(front) + len(back)
        backfill_finished = full or cursor['done'] or (
            room > 0 and done_rows == scanned and len(back) < room)
        nxt['done'] = backfill_finished
        nxt['paused'] = full or (cursor['paused'] and cursor['done'])
        nxt['lossy'] = cursor['lossy'] or full
        more = done_rows < scanned or len(front) == MAX_SCAN_ROWS or not backfill_finished
        return pending, nxt, {'scanned': done_rows, 'skipped': skipped, 'more': more, 'capacity_reached': full}

    def index(self, session_id, *, refresh=True):
        """One scan page and at most one 32-item/16k-character embedding batch per call.

        ``refresh`` (explicit calls) restarts a completed pass to re-verify sources, reusing
        unchanged vectors and re-embedding edits; automatic steps only extend the cursor.
        A database lease makes automatic and explicit indexing single-flight across processes.
        """
        cfg = load_embedding_config(self.db)
        if cfg is None:
            raise ValueError('Enable memory.home_recall and configure its embedding endpoint first.')
        key = self._cursor_key(cfg)
        owner = uuid.uuid4().hex
        self.db._execute_write(lambda conn: _acquire_lease_on(conn, owner, cfg))
        try:
            with self.db._read_ctx() as conn:
                state, current = _current_on(self.home, conn, session_id)
                if current is None:
                    raise ValueError('Open Home and participate in this conversation before indexing.')
                saved = conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
                cursor = _load_cursor(conn, key)
                stored = conn.execute(f'SELECT COUNT(*) FROM {TABLE} WHERE model_key=?',
                                      (cfg.identity,)).fetchone()[0] if _table_exists(conn) else 0
                stale = cursor['generation'] != _coverage_generation_on(conn)
                # Any principal's eviction may have dropped this pass's rows; refill once space frees.
                lossy = cursor['lossy'] or cursor['evictions'] != _meta_on(conn, EVICTION_KEY)
                if stale or (cursor['done'] and (refresh or (lossy and stored < _capacity_on(conn, cfg.identity)))):
                    # Re-verify; restart after sharing/linking made history newly eligible; or
                    # refill space freed after this pass evicted or paused at capacity.
                    cursor = _fresh_cursor(conn, cursor['hi'])
                pending, nxt, stats = self._plan_on(conn, cfg, state, cursor)
                generation = (state.get('anchor'), state.get('enabled_at'), _index_generation_on(conn))
            vectors = embed(cfg, [row['content'] for row, _, _ in pending]) if pending else []
            # Model/endpoint changes during HTTP revoke publication, never mix embedding spaces.
            latest = load_embedding_config(self.db)
            if latest is None or latest.identity != cfg.identity:
                raise ValueError('Embedding configuration changed; rerun /home index.')

            def publish(conn):
                state, current = _current_on(self.home, conn, session_id)
                if current is None or generation != (state.get('anchor'), state.get('enabled_at'), _index_generation_on(conn)):
                    raise ValueError('Home access changed while indexing.')
                if not _holds_lease_on(conn, owner) or conn.execute(
                        'SELECT value FROM state_meta WHERE key=?', (key,)).fetchone() != saved:
                    raise ValueError('Another indexing step advanced the index; retry shortly.')
                _ensure_table_on(conn, cfg)
                swept = self._sweep_on(conn, cfg, state)
                published, evicted, changed = self._publish_on(conn, cfg, state, pending, vectors)
                backfilled = _backfill_codes_on(conn, cfg)
                if swept or published or evicted or backfilled:
                    _bump_on(conn, VECTORS_KEY)
                final = dict(nxt, lossy=nxt['lossy'] or bool(evicted))
                if evicted:
                    conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) '
                                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (EVICTION_KEY, uuid.uuid4().hex))
                    final['evictions'] = _meta_on(conn, EVICTION_KEY)  # This pass already knows.
                # A source edited during the request is re-planned with its new content next step.
                front = [mid for mid, side in changed if side == 'front']
                back = [mid for mid, side in changed if side == 'back']
                if front:
                    final['hi'] = min(final['hi'], min(front) - 1)
                if back:
                    final.update(lo=max(final['lo'], max(back) + 1), done=False, paused=False)
                conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) '
                             'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(final)))
                conn.execute('DELETE FROM state_meta WHERE key=?', (LEASE_KEY,))
                more = stats['more'] or bool(changed)
                return {**stats, 'more': more, 'indexed': published, 'evicted': evicted, 'swept': swept,
                        'model': cfg.model, 'status': 'more' if more else 'ready'}
            return self.db._execute_write(publish)
        finally:
            self.db._execute_write(lambda conn: _release_lease_on(conn, owner))

    def _sweep_on(self, conn, cfg, state):
        """Rotate through stored vectors, dropping sources that are gone or forgotten, and this
        principal's own sources that are excluded from its Home. Other principals' sources are
        left alone. An edited source keeps its stale vector (never served: recall rechecks the
        hash) until ``_edited_on`` re-embeds it."""
        rows = _sweep_slice_on(conn, cfg)
        removed = 0
        for indexed in rows:
            source = _source_on(conn, indexed['message_id'])
            stale = source is None or _forgotten_on(conn, source)
            if not stale:
                session = conn.execute('SELECT * FROM sessions WHERE id=?', (source['session_id'],)).fetchone()
                stale = _owned_by_on(self.home, conn, session) and _indexable_on(self.home, conn, source, state) is None
            if stale:
                _delete_vector_on(conn, cfg.identity, indexed['message_id'])
                removed += 1
        position = rows[-1]['message_id'] if len(rows) == MAX_SWEEP_ROWS else 0
        conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (SWEEP_KEY, str(position)))
        return removed

    def _publish_on(self, conn, cfg, state, pending, vectors):
        published = evicted = 0
        changed = []
        if vectors:
            stored_dims = conn.execute(f'SELECT dimensions FROM {TABLE} WHERE model_key=? LIMIT 1',
                                       (cfg.identity,)).fetchone()
            if stored_dims and stored_dims[0] != len(vectors[0]):
                # The provider changed dimensions under the same model: rebuild this space.
                conn.execute(f'DELETE FROM {TABLE} WHERE model_key=?', (cfg.identity,))
                conn.execute(f'DELETE FROM {CODES} WHERE model_key=?', (cfg.identity,))
                _bump_on(conn, COVERAGE_KEY)
        count = conn.execute(f'SELECT COUNT(*) FROM {TABLE} WHERE model_key=?', (cfg.identity,)).fetchone()[0]
        capacity = min(MAX_INDEX_ROWS, MAX_INDEX_FLOATS // len(vectors[0])) if vectors else MAX_INDEX_ROWS
        for (source, digest, side), vector in zip(pending, vectors):
            row = _source_on(conn, source['id'])
            if row is None or _indexable_on(self.home, conn, row, state) is None:
                continue
            if _source_hash(row) != digest:
                changed.append((row['id'], side))
                continue
            exists = conn.execute(f'SELECT 1 FROM {TABLE} WHERE model_key=? AND message_id=?',
                                  (cfg.identity, row['id'])).fetchone()
            if exists is None and count >= capacity:
                oldest = conn.execute(f'SELECT MIN(message_id) FROM {TABLE} WHERE model_key=?',
                                      (cfg.identity,)).fetchone()[0]
                if oldest is None or oldest >= row['id']:
                    continue
                _delete_vector_on(conn, cfg.identity, oldest)
                evicted += 1
            elif exists is None:
                count += 1
            blob = struct.pack('<' + 'f' * len(vector), *vector)
            conn.execute(f'INSERT INTO {TABLE} VALUES (?,?,?,?,?,?) ON CONFLICT(model_key,message_id) '
                         'DO UPDATE SET source_hash=excluded.source_hash,dimensions=excluded.dimensions,'
                         'vector=excluded.vector,indexed_at=excluded.indexed_at',
                         (cfg.identity, row['id'], digest, len(vector), blob, time.time()))
            conn.execute(f'INSERT INTO {CODES} VALUES (?,?,?) ON CONFLICT(model_key,message_id) '
                         'DO UPDATE SET code=excluded.code', (cfg.identity, row['id'], _sign_code(vector)))
            published += 1
        return published, evicted, changed

    def remaining_on(self, conn, cfg):
        """Approximate count of older conversational rows not yet reached by backfill."""
        cursor = _load_cursor(conn, self._cursor_key(cfg))
        if cursor['done']:
            return 0
        return conn.execute("SELECT COUNT(*) FROM messages WHERE id<? AND role IN ('user','assistant')",
                            (cursor['lo'],)).fetchone()[0]

    def status(self, session_id):
        """Vector count, backfill progress and endpoint health for ``/home index status``."""
        cfg = load_embedding_config(self.db)
        if cfg is None:
            return None
        with self.db._read_ctx() as conn:
            _, current = _current_on(self.home, conn, session_id)
            if current is None:
                raise ValueError('Open Home and participate in this conversation first.')
            stored = conn.execute(f'SELECT COUNT(*) FROM {TABLE} WHERE model_key=?',
                                  (cfg.identity,)).fetchone()[0] if _table_exists(conn) else 0
            remaining = self.remaining_on(conn, cfg)
            paused = _load_cursor(conn, self._cursor_key(cfg))['paused']
            capacity = _capacity_on(conn, cfg.identity)
        return {'model': cfg.model, 'vectors': stored, 'capacity': capacity, 'remaining': remaining,
                'paused': paused, 'auto_index': cfg.auto_index, 'health': embedding_health(cfg)}

    def drain(self, session_id, *, budget_seconds=20.0):
        """Explicit ``/home index``: re-verify, then run bounded steps until done or out of time."""
        cfg = load_embedding_config(self.db)
        if cfg is not None:
            reset_embedding_health(cfg)
        deadline = time.monotonic() + budget_seconds
        total = {'indexed': 0, 'scanned': 0, 'skipped': 0, 'evicted': 0, 'capacity_reached': False}
        refresh = True
        while True:
            step = self.index(session_id, refresh=refresh)
            refresh = False
            for name in ('indexed', 'scanned', 'skipped', 'evicted'):
                total[name] += step[name]
            total['capacity_reached'] = total['capacity_reached'] or step['capacity_reached']
            if not step['more'] or deadline - time.monotonic() < cfg.timeout:
                break
        cfg = load_embedding_config(self.db)
        with self.db._read_ctx() as conn:
            remaining = self.remaining_on(conn, cfg) if cfg else 0
        return {**total, 'more': step['more'], 'remaining': remaining}


def _acquire_lease_on(conn, owner, cfg):
    now = time.time()
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (LEASE_KEY,)).fetchone()
    try:
        held = json.loads(row[0]) if row else None
        busy = held is not None and float(held['expires']) > now
    except (TypeError, ValueError, KeyError):
        busy = False
    if busy:
        raise IndexBusy('Home indexing is already running; try again shortly.')
    # Expiry covers one bounded request plus publication; a crashed holder never blocks for long.
    conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (LEASE_KEY, json.dumps({'owner': owner, 'expires': now + 2 * cfg.timeout + 30})))


def _holds_lease_on(conn, owner):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (LEASE_KEY,)).fetchone()
    try:
        return row is not None and json.loads(row[0])['owner'] == owner
    except (TypeError, ValueError, KeyError):
        return False


def _release_lease_on(conn, owner):
    if _holds_lease_on(conn, owner):
        conn.execute('DELETE FROM state_meta WHERE key=?', (LEASE_KEY,))


class IndexBusy(ValueError):
    """Another automatic or explicit indexing step holds the database lease."""


def invalidate_coverage_on(conn):
    """Newly eligible history (sharing an older chat, linking a conversation) needs a fresh
    pass. Bumping a durable generation restarts every cursor, including one an in-flight step
    is about to publish; unchanged vectors are reused."""
    conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (COVERAGE_KEY, uuid.uuid4().hex))


def _sweep_slice_on(conn, cfg):
    start = conn.execute('SELECT value FROM state_meta WHERE key=?', (SWEEP_KEY,)).fetchone()
    start = int(start[0]) if start and str(start[0]).isdigit() else 0
    return conn.execute(f'SELECT message_id,source_hash FROM {TABLE} WHERE model_key=? AND message_id>? '
                        'ORDER BY message_id LIMIT ?', (cfg.identity, start, MAX_SWEEP_ROWS)).fetchall()


def _ensure_table_on(conn, cfg):
    conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} ('
                 'model_key TEXT NOT NULL,message_id INTEGER NOT NULL,source_hash TEXT NOT NULL,'
                 'dimensions INTEGER NOT NULL,vector BLOB NOT NULL,indexed_at REAL NOT NULL,'
                 'PRIMARY KEY(model_key,message_id),FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)')
    conn.execute(f'CREATE TABLE IF NOT EXISTS {CODES} ('
                 'model_key TEXT NOT NULL,message_id INTEGER NOT NULL,code BLOB NOT NULL,'
                 'PRIMARY KEY(model_key,message_id),FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)')
    # Obsolete embedding spaces are derived state, not an ever-growing archive; their cursors
    # go with them so switching back to a model rebuilds its coverage.
    conn.execute(f'DELETE FROM {CODES} WHERE model_key!=?', (cfg.identity,))
    if conn.execute(f'DELETE FROM {TABLE} WHERE model_key!=?', (cfg.identity,)).rowcount:
        conn.execute('DELETE FROM state_meta WHERE key GLOB ? AND key NOT GLOB ?',
                     (CURSOR_GLOB, CURSOR_PREFIX + cfg.identity + ':*'))
        _bump_on(conn, VECTORS_KEY)


def _delete_vector_on(conn, model_key, message_id):
    conn.execute(f'DELETE FROM {TABLE} WHERE model_key=? AND message_id=?', (model_key, message_id))
    conn.execute(f'DELETE FROM {CODES} WHERE model_key=? AND message_id=?', (model_key, message_id))


def _bump_on(conn, key):
    conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, uuid.uuid4().hex))


def _backfill_codes_on(conn, cfg):
    """Indexes built before sign codes existed gain them a bounded slice per step."""
    rows = conn.execute(f'SELECT v.message_id,v.dimensions,v.vector FROM {TABLE} v LEFT JOIN {CODES} c '
                        'ON c.model_key=v.model_key AND c.message_id=v.message_id '
                        'WHERE v.model_key=? AND c.message_id IS NULL LIMIT ?', (cfg.identity, MAX_SWEEP_ROWS)).fetchall()
    for row in rows:
        vector = struct.unpack('<' + 'f' * row['dimensions'], row['vector'])
        conn.execute(f'INSERT OR REPLACE INTO {CODES} VALUES (?,?,?)', (cfg.identity, row['message_id'], _sign_code(vector)))
    # Codes whose vector is gone (e.g. written around by an older writer) would mask a missing code.
    orphans = conn.execute(f'DELETE FROM {CODES} WHERE rowid IN (SELECT c.rowid FROM {CODES} c LEFT JOIN {TABLE} v '
                           'ON v.model_key=c.model_key AND v.message_id=c.message_id '
                           'WHERE c.model_key=? AND v.message_id IS NULL LIMIT ?)', (cfg.identity, MAX_SWEEP_ROWS)).rowcount
    return len(rows) + orphans


def auto_index_step(db, session_id, *, principal_id=None):
    """Best-effort post-turn step: one batch, single-flight per database, never raises."""
    try:
        cfg = load_embedding_config(db)
    except _FAILURES:
        return None
    if cfg is None or not cfg.auto_index:
        return None
    key = str(db.db_path)
    with _ACTIVE_LOCK:
        if key in _ACTIVE:
            return None
        _ACTIVE.add(key)
    try:
        return HomeIndex(db, principal_id=principal_id).index(session_id, refresh=False)
    except _FAILURES as exc:
        # Not participating, provider down, busy, or access changed: keyword recall is unaffected.
        logger.debug('Home auto-index step skipped (%s)', type(exc).__name__)
        return None
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(key)


def schedule_auto_index_step(db, session_id, *, principal_id=None):
    """Owner-side step for managed-worker turns, which have no database access of their own.

    Runs one bounded step on a short-lived daemon thread; skipped when automatic indexing is
    off or a step is already running for this database.
    """
    try:
        cfg = load_embedding_config(db)
    except _FAILURES:
        return False
    if cfg is None or not cfg.auto_index:
        return False
    with _ACTIVE_LOCK:
        if str(db.db_path) in _ACTIVE:
            return False
    from agent.memory_provider import spawn_context_thread

    spawn_context_thread(auto_index_step, args=(db, session_id), kwargs={'principal_id': principal_id},
                         name='home-auto-index').start()
    return True
