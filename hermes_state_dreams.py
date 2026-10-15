"""Durable opt-in reflection, reservations, budgets and source-linked candidate notes."""
import json
import time
import uuid

from hermes_state_home import HomeStore, query_terms
from hermes_state_dream_sources import make_batch, snapshots_on, valid_notes

KEY = 'home.dream.v1'
DAILY_CALLS = 4
INTERVAL = 6 * 3600
MIN_IDLE = 300
LEASE_SECONDS = 600
MAX_NOTES = 32


class DreamStore:
    def __init__(self, db, *, principal_id=None):
        self.db = db
        self.home = HomeStore(db, principal_id=principal_id)
        self.principal_id = principal_id

    @staticmethod
    def load_on(conn):
        row = conn.execute('SELECT value FROM state_meta WHERE key=?', (KEY,)).fetchone()
        return json.loads(row[0]) if row else {'enabled': False, 'notes': [], 'seen': {}, 'revision': 0}

    @staticmethod
    def save_on(conn, state):
        conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (KEY, json.dumps(state)))

    def _authorize(self, state):
        if 'principal_id' in state and state['principal_id'] != self.principal_id:
            raise ValueError('Dreaming belongs to another principal in this profile.')

    def configure(self, *, enabled=None, clear=False):
        def update(conn):
            home = self.home._state_on(conn)
            state = self.load_on(conn)
            if 'principal_id' in state:
                self._authorize(state)
            if not home.get('enabled') and enabled is not False and not clear:
                raise ValueError('Open /home first; Home recall must be on.')
            state['principal_id'] = self.principal_id
            state['revision'] += 1
            # Keep the physical reservation until its caller exits/lease expires.
            # The revision revokes its result without allowing overlapping requests.
            if enabled is not None:
                state['enabled'] = enabled
                if not enabled or state.get('last_status') == 'running':
                    state['last_status'] = 'paused' if not enabled else 'revoked'
            if clear:
                state['notes'] = []
                snapshots = snapshots_on(self.home, conn, home) if home.get('anchor') else {}
                state['seen'] = {key: s['signature'] for key, s in snapshots.items()}
                state['last_status'] = 'cleared'
            self.save_on(conn, state)
        self.db._execute_write(update)

    def status(self):
        with self.db._read_ctx() as conn:
            state = self.load_on(conn)
            self._authorize(state)
            home = self.home._state_on(conn)
            snapshots = snapshots_on(self.home, conn, home) if home.get('enabled') else {}
            notes = valid_notes(state['notes'], snapshots)
            return {**{k: state.get(k) for k in ('enabled', 'last_at', 'last_status', 'next_at', 'attempts')},
                    'notes': notes, 'running': bool(state.get('lease', {}).get('until', 0) > time.time())}

    def reserve(self, *, now=None, manual=False):
        now = time.time() if now is None else now
        def claim(conn):
            home, state = self.home._state_on(conn), self.load_on(conn)
            self._authorize(state)
            if not home.get('enabled') or (not manual and not state['enabled']):
                return None
            if state.get('lease', {}).get('until', 0) > now or (not manual and state.get('next_at', 0) > now):
                return None
            # Persistent turn leases cover classic CLI as well as managed workers.
            if conn.execute('SELECT 1 FROM session_turn_leases WHERE expires_at>? LIMIT 1', (now,)).fetchone():
                return None
            last = conn.execute("SELECT MAX(COALESCE(last_activity_at,started_at)) FROM sessions").fetchone()[0] or 0
            if not manual and now - last < MIN_IDLE:
                return None
            day = int(now // 86400)
            attempts = state.get('attempts', 0) if state.get('day') == day else 0
            if attempts >= DAILY_CALLS:
                return None
            snapshots = snapshots_on(self.home, conn, home)
            batch = make_batch(snapshots, state['seen'])
            if not batch['sources']:
                return None
            token = uuid.uuid4().hex
            state.update(lease={'token': token, 'until': now + LEASE_SECONDS}, day=day, attempts=attempts + 1,
                         next_at=now + INTERVAL, last_at=now, last_status='running', principal_id=self.principal_id)
            self.save_on(conn, state)
            return {**batch, 'token': token, 'revision': state['revision']}
        return self.db._execute_write(claim)

    def finish(self, batch, notes, *, error=False, cancelled=False):
        def commit(conn):
            home, state = self.home._state_on(conn), self.load_on(conn)
            if state.get('lease', {}).get('token') != batch['token']:
                return False
            lease = state.pop('lease')
            if state['revision'] != batch['revision']:
                self.save_on(conn, state)
                return False
            snapshots = snapshots_on(self.home, conn, home) if home.get('enabled') else {}
            fresh = all(key in snapshots and snapshots[key]['signature'] == signature
                        for key, signature in batch['signatures'].items())
            state['notes'] = valid_notes(state['notes'], snapshots)
            if error or cancelled or not fresh or lease['until'] <= time.time():
                state['last_status'] = 'failed' if error else 'discarded'
                # Failed/cancelled work remains eligible after the durable cooldown.
            else:
                state['notes'] = [n for n in state['notes'] if not set(n['signatures']) & set(batch['signatures'])]
                state['notes'] = (state['notes'] + notes)[-MAX_NOTES:]
                state['seen'].update(batch['signatures'])
                state['seen'] = {key: value for key, value in state['seen'].items() if key in snapshots}
                state['last_status'] = 'saved' if notes else 'nothing useful'
            self.save_on(conn, state)
            return state['last_status'] in {'saved', 'nothing useful'}
        return self.db._execute_write(commit)

    def recall_on(self, conn, session_id, query, *, overview=False):
        home, state = self.home._state_on(conn), self.load_on(conn)
        if not home.get('enabled') or not state['notes'] or state.get('principal_id') != self.principal_id:
            return []
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        current = self.home._participating_on(conn, row, home)
        if current is None:
            return []
        terms = query_terms(query)
        candidates = [note for note in reversed(state['notes']) if (
            set(note['signatures']) != {current['home_anchor']}
            and (overview or any(term in note['text'].casefold() for term in terms)))]
        if not candidates:
            return []
        anchors = {anchor for note in candidates for anchor in note['signatures']}
        snapshots = snapshots_on(self.home, conn, home, anchors=anchors)
        return valid_notes(candidates, snapshots)[:4]
