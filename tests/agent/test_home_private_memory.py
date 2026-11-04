"""Messaging recall uses exact local grants and the authenticated current source."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.home_memory import HomeMemoryProvider, attach_home_memory, bind_home_source
from agent.turn_context import compose_user_api_content
from gateway.config import Platform
from gateway.session import SessionSource
from hermes_state import SessionDB
from hermes_state_home import HomeStore
from hermes_state_home_links import set_link
from tests.hermes_state.test_home_links import messaging_chat


@pytest.fixture
def private_chat(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        store = HomeStore(db)
        home = store.ensure_home()
        db.append_message(home, 'user', 'Lisbon hotel is Azul')
        sid = messaging_chat(db)
        source = SessionSource(Platform.TELEGRAM, 'private-chat', user_id='remote-user')
        row = db.get_session(sid)
        agent = SimpleNamespace(_session_db=db, _memory_manager=None, _emit_warning=Mock(),
                                _user_id=source.user_id, _chat_id=source.chat_id, _thread_id=None,
                                _chat_type='dm', _gateway_session_key=row['session_key'])
        attach_home_memory(agent, skip_memory=False, platform='telegram')
        yield db, store, home, sid, source, agent


def test_existing_dm_agent_starts_recalling_next_turn_after_local_link(private_chat):
    db, store, home, sid, source, agent = private_chat
    provider = agent._memory_manager.get_provider('builtin')
    bind_home_source(agent, source, db.get_session(sid)['session_key'])
    assert provider.prefetch('Lisbon', session_id=sid) == ''
    set_link(store, sid, True, caller_session_id=home)
    recalled = provider.prefetch('Lisbon', session_id=sid)
    assert 'Azul' in recalled
    sent = compose_user_api_content('Lisbon?', recalled, '')
    set_link(store, sid, False, caller_session_id=home)
    assert provider.prefetch('Lisbon', session_id=sid) == ''
    assert 'Azul' in sent  # Revocation cannot erase bytes already sent to a model.


def test_ambient_database_access_cannot_substitute_for_current_gateway_identity(private_chat):
    db, store, home, sid, _, _ = private_chat
    set_link(store, sid, True, caller_session_id=home)
    assert HomeMemoryProvider(db).prefetch('Lisbon', session_id=sid) == ''


def test_attached_dm_requires_authenticated_turn_binding_before_recall(private_chat):
    db, store, home, sid, source, agent = private_chat
    set_link(store, sid, True, caller_session_id=home)
    provider = agent._memory_manager.get_provider('builtin')
    assert provider.runtime_identity is None
    assert provider.prefetch('Lisbon', session_id=sid) == ''
    bind_home_source(agent, source, db.get_session(sid)['session_key'])
    assert 'Azul' in provider.prefetch('Lisbon', session_id=sid)


@pytest.mark.parametrize('change', ['user', 'chat', 'group', 'bot', 'profile', 'source', 'transport'])
def test_gateway_source_mismatch_never_reuses_granted_identity(private_chat, monkeypatch, change):
    db, store, home, sid, source, agent = private_chat
    set_link(store, sid, True, caller_session_id=home)
    provider = agent._memory_manager.get_provider('builtin')
    changes = {'user': ('user_id', 'stranger'), 'chat': ('chat_id', 'another-chat'),
               'group': ('chat_type', 'group'), 'bot': ('is_bot', True),
               'profile': ('profile', 'other-profile'), 'source': ('platform', Platform.DISCORD)}
    if change == 'transport':
        monkeypatch.setattr('gateway.session_identity.transport_profile_of', lambda _: 'other-bot')
    else:
        field, value = changes[change]
        setattr(source, field, value)
    bind_home_source(agent, source, db.get_session(sid)['session_key'])
    assert provider.prefetch('Lisbon', session_id=sid) == ''


def test_new_turn_author_cannot_borrow_the_conversation_opener_grant(private_chat):
    db, store, home, sid, source, agent = private_chat
    set_link(store, sid, True, caller_session_id=home)
    bind_home_source(agent, source, db.get_session(sid)['session_key'])
    provider = agent._memory_manager.get_provider('builtin')
    provider.on_turn_start(2, 'Lisbon', author_id='other-sender')
    assert provider.prefetch('Lisbon', session_id=sid) == ''
    provider.on_turn_start(3, 'Lisbon', author_id=source.user_id)
    assert 'Azul' in provider.prefetch('Lisbon', session_id=sid)
    provider.on_turn_start(4, 'Lisbon', author_id=source.user_id, author_is_bot=True)
    assert provider.prefetch('Lisbon', session_id=sid) == ''


def test_unlink_during_embedding_query_is_rechecked_before_context_egress(private_chat, monkeypatch):
    db, store, home, sid, source, agent = private_chat
    set_link(store, sid, True, caller_session_id=home)
    bind_home_source(agent, source, db.get_session(sid)['session_key'])
    def query(*args, **kwargs):
        set_link(store, sid, False, caller_session_id=home)
    monkeypatch.setattr('hermes_state_home_semantic.prepare_semantic_query', query)
    provider = agent._memory_manager.get_provider('builtin')
    assert provider.prefetch('Lisbon', session_id=sid) == ''
