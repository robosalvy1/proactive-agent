"""Explicit local-owner grants for one canonical private messaging conversation.

A grant never equates user IDs on different services. New conversations require a
new grant; compression alone may retain one while its exact identity stays stable.
"""
from __future__ import annotations

import json
import time

LINK_PREFIX = 'home.dm_link.v1:'
_BLOCKED_SOURCES = frozenset({'cli', 'tui', 'gui', 'desktop', 'dashboard', 'local',
                              'cron', 'subagent', 'tool', 'api', 'api_server',
                              'webhook', 'ntfy', 'raft', 'a2a'})


def private_platform(source: str) -> bool:
    from gateway.config import Platform

    if source in _BLOCKED_SOURCES:
        return False
    try:
        Platform(source)
        return True
    except ValueError:
        return False


def private_identity(row) -> dict | None:
    """Require a recognized adapter and matching canonical, persisted DM identity."""
    if row is None or row['hidden'] or not private_platform(row['source']):
        return None
    try:
        origin = json.loads(row['origin_json'] or '')
    except (ValueError, TypeError):
        return None
    if not isinstance(origin, dict) or row['chat_type'] != 'dm' or origin.get('chat_type') != 'dm':
        return None
    if not row['user_id'] or not row['chat_id'] or not row['session_key']:
        return None
    identity = {key: row[key] for key in ('source', 'user_id', 'chat_id', 'thread_id', 'transport_profile', 'session_key')}
    matches = {'platform': 'source', 'user_id': 'user_id', 'chat_id': 'chat_id', 'thread_id': 'thread_id'}
    if any((origin.get(origin_key) or None) != (identity[row_key] or None)
           for origin_key, row_key in matches.items()):
        return None
    identity['scope_id'] = origin.get('scope_id') or origin.get('guild_id') or None
    identity['profile'] = origin.get('profile') or None
    return identity


def _decode_grant(value) -> dict | None:
    """Corrupt persisted grants confer no authority and must not block other recall."""
    try:
        grant = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(grant, dict) or not isinstance(grant.get('anchor'), str) or not grant['anchor']:
        return None
    if 'principal_id' not in grant or not isinstance(grant['principal_id'], (str, type(None))):
        return None
    identity = grant.get('identity')
    if not isinstance(identity, dict) or not isinstance(identity.get('source'), str) or not identity['source']:
        return None
    return grant


def link_on(store, conn, session_id: str) -> dict | None:
    """Read and revalidate the grant and original source on every recall."""
    row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    identity = private_identity(row)
    if identity is None:
        return None
    anchor = store.anchor_on(conn, session_id)
    saved = conn.execute('SELECT value FROM state_meta WHERE key=?', (LINK_PREFIX + anchor,)).fetchone()
    root = conn.execute('SELECT * FROM sessions WHERE id=?', (anchor,)).fetchone()
    if not saved or private_identity(root) != identity:
        return None
    grant = _decode_grant(saved[0])
    if grant and grant['anchor'] == anchor and grant['identity'] == identity:
        return grant
    return None


def recall_principal_on(store, conn, session_id: str):
    """Resolve the local owner only through a valid grant, never a remote user ID."""
    grant = link_on(store, conn, session_id)
    row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    return grant['principal_id'] if grant else (row['user_id'] if row else None)


def require_local_owner(store, conn, caller_session_id: str = '') -> None:
    """Home mutation callers are authenticated native controls or the local CLI."""
    state = store._state_on(conn)
    if not state.get('anchor'):
        raise ValueError('Open Home before linking a private conversation.')
    owner = conn.execute('SELECT user_id FROM sessions WHERE id=?', (state['anchor'],)).fetchone()
    if owner is None or (owner['user_id'] and owner['user_id'] != store.principal_id):
        raise ValueError('Home belongs to a different local principal.')
    if caller_session_id:
        caller = conn.execute('SELECT * FROM sessions WHERE id=?', (caller_session_id,)).fetchone()
        from hermes_state_home import PERSONAL_SOURCES
        if caller is None or caller['source'] not in PERSONAL_SOURCES or not store._personal_on(conn, caller):
            raise ValueError('Link controls require a local personal session.')


def set_link(store, session_id: str, enabled: bool, *, caller_session_id: str = '') -> None:
    """Grant/revoke future Home recall; transcript and already-sent context remain."""
    def write(conn):
        require_local_owner(store, conn, caller_session_id)
        anchor = store.anchor_on(conn, session_id)
        key = LINK_PREFIX + anchor
        saved = conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
        grant = _decode_grant(saved[0]) if saved else None
        if grant and grant['principal_id'] != store.principal_id:
            raise ValueError('This conversation is linked by a different local principal.')
        if not enabled:
            conn.execute('DELETE FROM state_meta WHERE key=?', (key,))
            return
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        identity = private_identity(row)
        root = conn.execute('SELECT * FROM sessions WHERE id=?', (anchor,)).fetchone()
        if identity is None or private_identity(root) != identity:
            raise ValueError('Link requires an existing canonical private messaging session with a known sender and chat.')
        grant = {'anchor': anchor, 'principal_id': store.principal_id, 'identity': identity, 'linked_at': time.time()}
        conn.execute('INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(grant)))
        from hermes_state_home import SHARING_PREFIX
        conn.execute('INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (SHARING_PREFIX + anchor, 'shared'))
        from hermes_state_home_observations import reset_profiles_on
        from hermes_state_home_semantic import invalidate_coverage_on
        invalidate_coverage_on(conn)
        reset_profiles_on(conn)
    store.db._execute_write(write)


def linked_sources_on(store, conn) -> list[str]:
    """Candidate source expansion only; every hit still passes exact grant validation."""
    sources = set()
    for row in conn.execute('SELECT value FROM state_meta WHERE key GLOB ?', (LINK_PREFIX + '*',)):
        grant = _decode_grant(row[0])
        if grant and grant['principal_id'] == store.principal_id:
            sources.add(grant['identity']['source'])
    return sorted(sources)


def list_links(store, *, caller_session_id='') -> list[dict]:
    with store.db._read_ctx() as conn:
        require_local_owner(store, conn, caller_session_id)
        links = []
        for row in conn.execute('SELECT value FROM state_meta WHERE key GLOB ?', (LINK_PREFIX + '*',)):
            grant = _decode_grant(row[0])
            if grant and grant['principal_id'] == store.principal_id:
                links.append({'session_id': grant['anchor'], 'source': grant['identity']['source'],
                              'valid': link_on(store, conn, grant['anchor']) is not None})
        return links
