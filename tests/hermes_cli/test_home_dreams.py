"""Dream controls are usable without granting execution authority or starting a background job."""
import json

from hermes_cli.home import home_action
from hermes_state import SessionDB


def test_controls_enable_inspect_pause_and_clear(tmp_path, monkeypatch):
    with SessionDB(tmp_path / 'state.db') as db:
        home = home_action(db, '')['session_id']
        assert 'off' in home_action(db, home, 'dream')['output']
        assert 'Dreaming is on' in home_action(db, home, 'dream on')['output']
        db.create_session('travel', 'cli')
        db.append_message('travel', 'user', 'I prefer rail travel')

        def model(sources):
            row = sources[0]['messages'][0]
            return json.dumps({'notes': [{'kind': 'preference', 'text': row['text'],
                                        'sources': [{'id': row['id'], 'quote': row['text']}]}]})
        monkeypatch.setattr('agent.home_dream_model.reflect', model)
        assert '1 source-linked' in home_action(db, home, 'dream now')['output']
        notes = home_action(db, home, 'dream notes')['output']
        assert 'rail travel' in notes and '@session:' in notes
        assert 'paused' in home_action(db, home, 'dream off')['output']
        assert 'rail travel' in home_action(db, home, 'dream notes')['output']
        assert 'cleared' in home_action(db, home, 'dream clear')['output']
        assert 'No current' in home_action(db, home, 'dream notes')['output']


def test_pause_is_available_even_after_home_was_disabled(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        home = home_action(db, '')['session_id']
        home_action(db, home, 'dream on')
        home_action(db, home, 'off')
        assert 'paused' in home_action(db, home, 'dream off')['output']
