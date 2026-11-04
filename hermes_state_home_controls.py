"""Explicit source-level Home revocation; raw transcripts remain independently searchable."""
from __future__ import annotations

import time

MAX_CONTROLS = 10000
MAX_CHAIN = 16


def _origin_uid_on(conn, row):
    """An assistant message answers the latest user message before it in its chat. Compaction can
    copy a reply into another chat, so the answer is resolved from the ORIGINAL row of that message
    identity (its earliest copy), never from wherever a copy landed."""
    if row['role'] != 'assistant':  # Callers must select role: a missing column fails closed.
        return None
    reference = None
    if row['message_uid']:
        reference = conn.execute('SELECT id,session_id FROM messages WHERE message_uid=? ORDER BY id LIMIT 1',
                                 (row['message_uid'],)).fetchone()
    if reference is None:
        reference = conn.execute('SELECT id,session_id FROM messages WHERE id=?', (row['id'],)).fetchone()
    if reference is None:
        return None
    origin = conn.execute("SELECT message_uid FROM messages WHERE session_id=? AND id<? AND role='user' "
                          'ORDER BY id DESC LIMIT 1', (reference['session_id'], reference['id'])).fetchone()
    return origin[0] if origin else None


def _rule_on(conn, row):
    """The control that governs ``row``: its own, else (for an assistant reply) the control of the
    user message it answers. Enforced on every read, so the assistant's restatement of a forgotten
    or corrected message is covered however long the tool loop was and even when written later."""
    for uid in (row['message_uid'], _origin_uid_on(conn, row)):
        if uid:
            rule = conn.execute('SELECT * FROM home_source_controls WHERE message_uid=?', (uid,)).fetchone()
            if rule is not None:
                return rule
    return None


def source_allowed_on(conn, row) -> bool:
    """Suppressed source identities, and replies to them, must not be indexed, injected or reflected on."""
    return _rule_on(conn, row) is None


def resolve_source_on(db, conn, row, principal_id):
    """Resolve only explicit corrections, validating canonical replacement evidence each read."""
    from hermes_state_home import HomeStore

    store = HomeStore(db, principal_id=principal_id)
    state = store._state_on(conn)
    seen = set()
    for _ in range(MAX_CHAIN):
        uid = row['message_uid']
        if not uid:
            return row
        if uid in seen:
            return None
        seen.add(uid)
        rule = _rule_on(conn, row)
        if rule is None:
            return row
        # Any owner's revocation suppresses the source. A different owner cannot
        # redirect another principal's context to a replacement of their choice.
        if rule['action'] == 'forgotten' or rule['principal_id'] != principal_id:
            return None
        row = conn.execute(
            "SELECT id,session_id,message_uid,role,timestamp,substr(content,1,900) AS content FROM messages "
            "WHERE message_uid=? AND role='user' AND (active=1 OR compacted=1) "
            "AND _compressed_summary=0 AND COALESCE(display_kind,'')!='hidden' ORDER BY id DESC LIMIT 1",
            (rule['replacement_uid'],)).fetchone()
        if row is None:
            return None
        session = conn.execute('SELECT * FROM sessions WHERE id=?', (row['session_id'],)).fetchone()
        if store._participating_on(conn, session, state) is None:
            return None
    return None


class HomeSourceControls:
    """Local controls authorize sources through the existing Home participation boundary."""

    def __init__(self, db, *, principal_id=None):
        self.db, self.principal_id = db, principal_id

    def _source_on(self, conn, message_id):
        from hermes_state_home import HomeStore

        if type(message_id) is not int or not 1 <= message_id <= 2**63 - 1:
            raise ValueError('Use the positive message id shown in Home evidence.')
        row = conn.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        store = HomeStore(self.db, principal_id=self.principal_id)
        session = conn.execute('SELECT * FROM sessions WHERE id=?', (row['session_id'],)).fetchone() if row else None
        if (row is None or not row['message_uid'] or not store._personal_on(conn, session)
                or row['role'] not in {'user', 'assistant'} or row['_compressed_summary']
                or row['display_kind'] == 'hidden' or not (row['active'] or row['compacted'])):
            raise ValueError('Source is unavailable or is not an owned personal message.')
        return row

    def forget(self, message_id: int) -> None:
        self._write(message_id)

    def supersede(self, message_id: int, replacement_id: int) -> None:
        self._write(message_id, replacement_id)

    def _write(self, message_id, replacement_id=None):
        def update(conn):
            old = self._source_on(conn, message_id)
            existing = conn.execute('SELECT * FROM home_source_controls WHERE message_uid=?',
                                    (old['message_uid'],)).fetchone()
            if existing:
                if replacement_id is None and existing['action'] == 'forgotten':
                    return
                if replacement_id is not None:
                    raise ValueError('This source already has a control; correct the latest replacement instead.')
            replacement = self._source_on(conn, replacement_id) if replacement_id is not None else None
            if replacement is not None:
                if (replacement['role'] != 'user' or replacement['id'] <= old['id']
                        or replacement['message_uid'] == old['message_uid']
                        or not source_allowed_on(conn, replacement)):
                    raise ValueError('Replacement must be a newer, unsuppressed user message.')
            if not existing and conn.execute('SELECT COUNT(*) FROM home_source_controls').fetchone()[0] >= MAX_CONTROLS:
                raise ValueError('Home source-control limit reached; existing revocations are retained.')
            now = time.time()
            conn.execute(
                'INSERT INTO home_source_controls VALUES(?,?,?,?,?,?,?) ON CONFLICT(message_uid) DO UPDATE SET '
                'action=excluded.action,replacement_uid=excluded.replacement_uid,created_at=excluded.created_at',
                (old['message_uid'], old['session_id'], old['id'], self.principal_id,
                 'superseded' if replacement is not None else 'forgotten',
                 replacement['message_uid'] if replacement is not None else None, now))
            # Observations citing the source are stale (forgotten) or outdated (corrected). Those citing
            # the assistant's replies to it fail revalidation through the same inherited control.
            from hermes_state_home_observations import Observations
            Observations(self.db, principal_id=self.principal_id).invalidate_sources_on(
                conn, [old['message_uid']], now)
        self.db._execute_write(update)

    def list(self) -> list[dict]:
        with self.db._read_ctx() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT source_session_id,source_message_id,action,created_at FROM home_source_controls '
                'WHERE principal_id IS ? ORDER BY created_at DESC LIMIT 128', (self.principal_id,))]
