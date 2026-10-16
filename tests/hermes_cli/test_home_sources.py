"""Home source controls exercise the actual shared CLI/transport entrypoint."""
import pytest

from hermes_cli.home import home_action
from hermes_state import SessionDB
from hermes_state_home import HomeStore


@pytest.fixture
def state(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        home = home_action(db, '', '')['session_id']
        db.create_session('travel', 'cli')
        db.append_message('travel', 'user', 'Lisbon budget is 1200 euros')
        old = db._read_one('SELECT MAX(id) AS id FROM messages')['id']
        db.append_message('travel', 'user', 'Actually make it 1500 euros instead')
        new = db._read_one('SELECT MAX(id) AS id FROM messages')['id']
        yield db, home, old, new


def test_correction_and_forget_commands_take_effect_and_explain_scope(state):
    db, home, old, new = state
    assert f'message {old}' in home_action(db, home, 'overview')['output']
    result = home_action(db, home, f'supersede {old} {new}')
    assert 'Start a new chat' in result['output']
    rows = HomeStore(db).recall(home, 'Lisbon budget')
    assert any('1500' in r['content'] for r in rows)
    assert not any('1200' in r['content'] for r in rows)
    home_action(db, home, f'forget {new}')
    assert HomeStore(db).recall(home, 'Lisbon') == []
    assert 'forgotten' in home_action(db, home, 'sources')['output']


@pytest.mark.parametrize('action', ['forget', 'forget -1', 'forget x', 'supersede 1',
                                    'supersede 1 2 extra', 'index extra', 'sources extra'])
def test_malformed_source_commands_are_rejected(state, action):
    db, home, _, _ = state
    with pytest.raises(ValueError):
        home_action(db, home, action)


def test_index_requires_explicit_embedding_configuration(state):
    db, home, _, _ = state
    with pytest.raises(ValueError, match='embedding endpoint'):
        home_action(db, home, 'index')
    assert 'cleared' in home_action(db, home, 'index clear')['output']


def test_other_principal_cannot_control_sources(state):
    db, home, old, _ = state
    db._write_sql('UPDATE sessions SET user_id=? WHERE id=?', ('owner', home))
    with pytest.raises(ValueError, match='different local principal'):
        home_action(db, home, f'forget {old}', principal_id='stranger')
