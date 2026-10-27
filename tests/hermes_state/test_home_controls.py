"""Source revocation and explicit corrections affect every future Home read."""
import pytest

from hermes_state import SessionDB
from hermes_state_home import HomeStore, render_recall
from hermes_state_home_controls import HomeSourceControls


@pytest.fixture
def setup(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        home = HomeStore(db).ensure_home()
        db.create_session('travel', 'cli')
        db.append_message('travel', 'user', 'Lisbon budget is 1200 euros')
        old = db._read_one("SELECT id FROM messages WHERE session_id='travel'")['id']
        yield db, home, old


def test_forget_survives_restart_and_hides_keyword_overview_and_clones(setup):
    db, home, old = setup
    controls = HomeSourceControls(db)
    assert '1200' in render_recall(HomeStore(db).recall(home, 'Lisbon budget'))
    controls.forget(old)
    assert HomeStore(db).recall(home, 'Lisbon budget') == []
    assert HomeStore(db).recall(home, '', overview=True) == []
    # Compression keeps the message identity even when its physical row changes.
    uid = db._read_one('SELECT message_uid FROM messages WHERE id=?', (old,))['message_uid']
    db.create_session('copy', 'cli')
    db.append_message('copy', 'user', 'Lisbon budget is 1200 euros')
    db._write_sql("UPDATE messages SET message_uid=? WHERE session_id='copy'", (uid,))
    with SessionDB(db.db_path) as reopened:
        assert HomeStore(reopened).recall(home, 'Lisbon budget') == []
        assert HomeSourceControls(reopened).list()[0]['action'] == 'forgotten'


def test_explicit_distant_correction_replaces_old_evidence(setup):
    db, home, old = setup
    for n in range(8):
        db.append_message('travel', 'assistant', f'Unrelated discussion {n}')
    db.create_session('correction', 'cli')
    db.append_message('correction', 'user', 'Actually, make it 1500 euros instead.')
    new = db._read_one("SELECT id FROM messages WHERE session_id='correction'")['id']
    HomeSourceControls(db).supersede(old, new)
    packet = render_recall(HomeStore(db).recall(home, 'Lisbon budget'))
    assert '1500' in packet
    assert '1200' not in packet
    assert '"source_session_id": "correction"' in packet
    HomeStore(db).set_shared('correction', False)
    assert '1500' not in render_recall(HomeStore(db).recall(home, 'Lisbon budget'))


def test_forgetting_replacement_never_resurrects_original(setup):
    db, home, old = setup
    db.append_message('travel', 'user', 'Actually 1500 euros instead')
    new = db._read_one('SELECT MAX(id) AS id FROM messages')['id']
    controls = HomeSourceControls(db)
    controls.supersede(old, new)
    controls.forget(new)
    assert HomeStore(db).recall(home, 'Lisbon budget') == []


@pytest.mark.parametrize('kind', ['foreign', 'group', 'assistant', 'hidden'])
def test_correction_rejects_untrusted_replacement(setup, kind):
    db, _, old = setup
    db.create_session('other', 'telegram' if kind == 'group' else 'cli',
                      user_id='stranger' if kind == 'foreign' else None,
                      chat_type='group' if kind == 'group' else None)
    db.append_message('other', 'assistant' if kind == 'assistant' else 'user', 'Actually 9999')
    new = db._read_one('SELECT MAX(id) AS id FROM messages')['id']
    if kind == 'hidden':
        db._write_sql("UPDATE sessions SET hidden=1 WHERE id='other'")
    with pytest.raises(ValueError):
        HomeSourceControls(db).supersede(old, new)


def test_control_cannot_be_replaced_silently_or_target_unknown_source(setup):
    db, _, old = setup
    controls = HomeSourceControls(db)
    controls.forget(old)
    controls.forget(old)  # Idempotent explicit deletion.
    with pytest.raises(ValueError):
        controls.forget(999999)
    with pytest.raises(ValueError, match='positive message id'):
        controls.forget(2**63)


def test_forget_invalidates_dreams_and_prevents_reextraction(setup):
    import json
    from agent.home_dreaming import dream_once
    from hermes_state_dreams import DreamStore
    db, home, old = setup
    dreams = DreamStore(db)
    dreams.configure(enabled=True)
    def reflect(sources):
        row = sources[0]['messages'][0]
        return json.dumps({'notes': [{'kind': 'decision', 'text': 'Lisbon budget 1200',
                          'sources': [{'id': row['id'], 'quote': row['text']}]}]})
    assert '1 source-linked' in dream_once(db, manual=True, model=reflect)
    assert dreams.status()['notes']
    HomeSourceControls(db).forget(old)
    assert dreams.status()['notes'] == []
    assert dreams.reserve(manual=True) is None
    assert HomeStore(db).recall(home, 'Lisbon') == []


def test_forgetting_a_message_also_removes_the_assistants_echo(setup):
    db, home, old = setup
    db.append_message('travel', 'assistant', 'Noted: your Lisbon budget is 1200 euros.')
    db.append_message('travel', 'user', 'What museums are in Lisbon?')
    db.append_message('travel', 'assistant', 'The Gulbenkian and MAAT are popular in Lisbon.')
    HomeSourceControls(db).forget(old)
    packet = render_recall(HomeStore(db).recall(home, 'Lisbon budget euros'))
    assert '1200' not in packet
    assert 'Gulbenkian' in render_recall(HomeStore(db).recall(home, 'Lisbon museums'))  # Later exchange stays.


def test_a_correction_also_wins_over_the_assistants_restatement(setup):
    db, home, old = setup
    db.append_message('travel', 'assistant', 'Noted: your Lisbon budget is 1200 euros.')
    db.create_session('correction', 'cli')
    db.append_message('correction', 'user', 'Actually, make the Lisbon budget 1500 euros.')
    new = db._read_one("SELECT id FROM messages WHERE session_id='correction'")['id']
    HomeSourceControls(db).supersede(old, new)
    packet = render_recall(HomeStore(db).recall(home, 'Noted Lisbon budget euros'))
    assert '1500' in packet and '1200' not in packet
