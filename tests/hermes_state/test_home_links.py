"""Explicit DM grants preserve local authority, exact identity and restart boundaries."""
import json

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore
from hermes_cli.home import home_action
from hermes_state import SessionDB
from hermes_state_home import HomeStore, render_recall
from hermes_state_home_links import link_on, set_link


def messaging_chat(db, sid='dm', *, source='telegram', user='remote-user', chat='private-chat',
                   chat_type='dm', transport=None):
    """Synthetic canonical gateway row and routing record, without a connected adapter."""
    origin = {'platform': source, 'user_id': user, 'chat_id': chat, 'chat_type': chat_type,
              'thread_id': None}
    key = f'agent:main:{source}:{chat_type}:{chat}'
    db.create_session(sid, source, user_id=user, chat_id=chat, chat_type=chat_type,
                      session_key=key, origin_json=json.dumps(origin), transport_profile=transport)
    # The worker fixture already has an assigned row; create_session intentionally
    # never overwrites existing identity. Model the gateway's canonical row update.
    db._write_sql('UPDATE sessions SET source=?,user_id=?,chat_id=?,chat_type=?,session_key=?,origin_json=?, '
                  'transport_profile=? WHERE id=?',
                  (source, user, chat, chat_type, key, json.dumps(origin), transport, sid))
    entry = {'session_id': sid, 'origin': origin, 'transport_profile': transport}
    db._write_sql("INSERT OR REPLACE INTO gateway_routing(scope,session_key,entry_json,updated_at) VALUES('',?,?,0)",
                  (key, json.dumps(entry)))
    db.append_message(sid, 'user', 'Lisbon budget is 1700 euros')
    return sid


@pytest.fixture
def chats(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        local = HomeStore(db)
        home = local.ensure_home()
        db.append_message(home, 'user', 'My Lisbon hotel is the Azul.')
        yield db, local, home


def test_real_gateway_route_requires_explicit_link_and_survives_restart(tmp_path):
    sessions = SessionStore(tmp_path / 'sessions', GatewayConfig())
    db = sessions._db
    try:
        home = HomeStore(db).ensure_home()
        db.append_message(home, 'user', 'My Lisbon hotel is Azul.')
        source = SessionSource(Platform.TELEGRAM, 'private', user_id='remote-human')
        entry = sessions.get_or_create_session(source)
        db.append_message(entry.session_id, 'user', 'Lisbon budget is 1700 euros')
        assert HomeStore(db).recall(home, 'Lisbon') == []
        home_action(db, home, f'link {entry.session_id}')
        second = SessionDB(db.db_path)
        try:
            assert '1700 euros' in render_recall(HomeStore(second).recall(home, 'Lisbon'))
            assert HomeStore(second).recall(entry.session_id, 'Lisbon')
        finally:
            second.close()
    finally:
        db.close()


def test_linked_dm_recall_is_bidirectional_and_revoke_is_immediate(chats):
    db, store, home = chats
    sid = messaging_chat(db)
    set_link(store, sid, True, caller_session_id=home)
    assert '1700 euros' in render_recall(store.recall(home, 'Lisbon'))
    assert 'Azul' in render_recall(store.recall(sid, 'Lisbon'))
    store.set_shared(sid, False)
    assert not store.recall(sid, 'Lisbon')
    assert not store.recall(home, 'Lisbon')
    set_link(store, sid, True, caller_session_id=home)
    set_link(store, sid, False, caller_session_id=home)
    assert not store.recall(sid, 'Lisbon')
    assert not store.recall(home, 'Lisbon')
    assert db.message_count(sid) == 1


@pytest.mark.parametrize('source,chat_type,user,chat', [
    ('telegram', 'group', 'remote-user', 'group'), ('telegram', 'channel', 'remote-user', 'channel'),
    ('telegram', 'dm', None, 'private'), ('telegram', 'dm', 'remote-user', None),
    ('ntfy', 'dm', 'remote-user', 'broadcast'), ('raft', 'dm', 'remote-user', 'peer'),
    ('a2a', 'dm', 'remote-user', 'peer'), ('cron', 'dm', 'remote-user', 'job'),
    ('subagent', 'dm', 'remote-user', 'worker'), ('unknown-platform', 'dm', 'remote-user', 'private'),
    ('api_server', 'dm', 'remote-user', 'api'),
])
def test_nonprivate_and_unknown_identities_cannot_be_linked(chats, source, chat_type, user, chat):
    db, store, home = chats
    sid = messaging_chat(db, source=source, chat_type=chat_type, user=user, chat=chat)
    with pytest.raises(ValueError, match='private messaging'):
        set_link(store, sid, True, caller_session_id=home)
    assert not store.recall(home, 'Lisbon')


@pytest.mark.parametrize('column,value', [('source', 'discord'), ('user_id', 'different-user'),
    ('chat_id', 'different-chat'), ('chat_type', 'group'), ('transport_profile', 'other-bot'),
    ('thread_id', 'different-thread'), ('origin_json', '{}')])
def test_source_identity_drift_invalidates_grant(chats, column, value):
    db, store, home = chats
    sid = messaging_chat(db, transport='receiving-bot')
    set_link(store, sid, True, caller_session_id=home)
    assert store.recall(home, 'Lisbon')
    db._write_sql(f'UPDATE sessions SET {column}=? WHERE id=?', (value, sid))
    assert not store.recall(home, 'Lisbon')
    assert not store.recall(sid, 'Lisbon')


def test_same_ids_on_different_provider_and_new_session_never_inherit_grants(chats):
    db, store, home = chats
    original = messaging_chat(db)
    set_link(store, original, True, caller_session_id=home)
    other = messaging_chat(db, 'other', source='discord')
    assert not store.recall(other, 'Lisbon')
    db.end_session(original, 'new_session')
    newer = messaging_chat(db, 'newer')
    assert not store.recall(newer, 'Lisbon')
    assert {r['source_session_id'] for r in store.recall(home, 'Lisbon')} == {original}


def test_compression_keeps_grant_only_with_same_identity(chats):
    db, store, home = chats
    original = messaging_chat(db)
    set_link(store, original, True, caller_session_id=home)
    db.end_session(original, 'compression')
    db.create_session('continued', 'telegram', parent_session_id=original)
    assert store.recall('continued', 'Lisbon')
    db._write_sql("UPDATE sessions SET user_id='different' WHERE id='continued'")
    assert not store.recall('continued', 'Lisbon')


def test_remote_caller_and_other_local_principal_cannot_control_grant(chats):
    db, store, home = chats
    sid = messaging_chat(db)
    with pytest.raises(ValueError, match='local personal'):
        home_action(db, sid, 'link dm', principal_id='remote-user')
    set_link(store, sid, True, caller_session_id=home)
    for enabled in (True, False):
        with pytest.raises(ValueError, match='different local principal'):
            set_link(HomeStore(db, principal_id='other'), sid, enabled, caller_session_id=home)
    with db._read_ctx() as conn:
        assert link_on(store, conn, sid)


def test_missing_canonical_origin_is_refused(chats):
    db, store, home = chats
    sid = messaging_chat(db)
    db._write_sql("UPDATE sessions SET origin_json=NULL WHERE id='dm'")
    with pytest.raises(ValueError, match='canonical private messaging'):
        set_link(store, sid, True, caller_session_id=home)
    assert not store.recall(sid, 'Lisbon')


def test_cli_link_listing_and_unlink_do_not_lowercase_session_ids(chats):
    db, _, home = chats
    sid = messaging_chat(db, 'CaseSensitive-ID')
    assert 'linked to Home' in home_action(db, home, f'link {sid}')['output']
    assert sid in home_action(db, home, 'links')['output']
    assert 'unlinked' in home_action(db, home, f'unlink {sid}')['output']
    assert 'No private' in home_action(db, home, 'links')['output']


def test_same_platform_other_sender_and_chat_cannot_recall_or_contribute(chats):
    db, store, home = chats
    linked = messaging_chat(db)
    set_link(store, linked, True, caller_session_id=home)
    stranger = messaging_chat(db, 'stranger', user='stranger', chat='other-private-chat')
    assert not store.recall(stranger, 'Lisbon')
    assert {row['source_session_id'] for row in store.recall(home, 'Lisbon')} == {linked}


def test_profile_database_does_not_inherit_private_grants(chats, tmp_path):
    db, store, home = chats
    sid = messaging_chat(db)
    set_link(store, sid, True, caller_session_id=home)
    with SessionDB(tmp_path / 'other' / 'state.db') as other:
        other_store = HomeStore(other)
        other_home = other_store.ensure_home()
        messaging_chat(other)
        assert other_store.recall(other_home, 'Lisbon') == []
        assert other_store.recall(sid, 'Lisbon') == []


def test_assigned_messaging_worker_requires_current_explicit_grant(worker):
    db, remote = worker
    store = HomeStore(db)
    home = store.ensure_home()
    db.append_message(home, 'user', 'Lisbon hotel is Azul')
    messaging_chat(db, 'owned')
    assert remote.home_recall('owned', 'Lisbon') == {'context': '', 'count': 0}
    set_link(store, 'owned', True, caller_session_id=home)
    assert 'Azul' in remote.home_recall('owned', 'Lisbon')['context']
    set_link(store, 'owned', False, caller_session_id=home)
    assert remote.home_recall('owned', 'Lisbon') == {'context': '', 'count': 0}


def test_messaging_worker_does_not_reuse_a_replaced_grant(worker, monkeypatch):
    db, remote = worker
    store = HomeStore(db)
    home = store.ensure_home()
    db.append_message(home, 'user', 'Lisbon hotel is Azul')
    messaging_chat(db, 'owned')
    set_link(store, 'owned', True, caller_session_id=home)
    def regrant(*_args, **_kwargs):
        set_link(store, 'owned', False, caller_session_id=home)
        set_link(store, 'owned', True, caller_session_id=home)
    monkeypatch.setattr('hermes_state_home_semantic.prepare_semantic_query', regrant)
    assert remote.home_recall('owned', 'Lisbon') == {'context': '', 'count': 0}
