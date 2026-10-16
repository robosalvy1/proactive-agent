"""Overview and dreaming select participating rows before applying their session budget."""
import time

import pytest

from hermes_state import SessionDB
from hermes_state_dreams import DreamStore
from hermes_state_home import HomeStore, MAX_SESSIONS


@pytest.mark.parametrize('noise', ['excluded', 'predates_enablement', 'tied_excluded', 'fallback_excluded'])
def test_overview_and_dreaming_page_past_newer_nonparticipating_chats(tmp_path, noise):
    with SessionDB(tmp_path / 'state.db') as db:
        store = HomeStore(db)
        home = store.ensure_home()
        db.create_session('travel', 'cli')
        db.append_message('travel', 'user', 'Lisbon budget is 1200 euros')
        recent = time.time() + 100
        if noise in {'tied_excluded', 'fallback_excluded'}:
            db._write_sql('UPDATE sessions SET started_at=?,last_activity_at=NULL WHERE id=?', (recent, 'travel'))
        for index in range(MAX_SESSIONS + 3):
            sid = f'z-noise-{index}'
            db.create_session(sid, 'cli')
            db.append_message(sid, 'user', 'Excluded evidence')
            db._write_sql('UPDATE sessions SET started_at=?,last_activity_at=? WHERE id=?',
                          (0 if noise == 'predates_enablement' else recent,
                           None if noise == 'fallback_excluded' else recent, sid))
            if noise != 'predates_enablement':
                store.set_shared(sid, False)
        assert {row['id'] for row in store.conversations()} == {home, 'travel'}
        overview = store.recall(home, '', overview=True)
        assert {row['source_session_id'] for row in overview} == {'travel'}
        assert '1200 euros' in overview[0]['content']
        dreams = DreamStore(db)
        dreams.configure(enabled=True)
        batch = dreams.reserve(now=recent + 1000, manual=True)
        assert {source['anchor'] for source in batch['sources']} == {'travel'}


def test_overview_session_budget_keeps_newest_participating_rows(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        store = HomeStore(db)
        store.ensure_home()
        for index in range(MAX_SESSIONS + 3):
            sid = f'chat-{index:03}'
            db.create_session(sid, 'cli')
            db._write_sql('UPDATE sessions SET last_activity_at=? WHERE id=?', (time.time() + index + 1, sid))
        rows = store.conversations()
        assert len(rows) == MAX_SESSIONS
        assert rows[0]['id'] == f'chat-{MAX_SESSIONS + 2:03}'
        assert rows[-1]['id'] == 'chat-003'
