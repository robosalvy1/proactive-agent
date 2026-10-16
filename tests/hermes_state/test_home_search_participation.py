"""High-ranked non-participating messages must not exhaust Home's first search page."""
import pytest

from hermes_state import SessionDB
from hermes_state_home import HomeStore


@pytest.mark.parametrize('noise', ['old', 'excluded', 'own_lineage'])
def test_participating_evidence_survives_high_ranked_nonparticipating_hits(tmp_path, noise):
    with SessionDB(tmp_path / 'state.db') as db:
        store = HomeStore(db)
        if noise == 'old':
            db.create_session('noise', 'cli')
            for _ in range(260):
                db.append_message('noise', 'user', 'Lisbon')
        home = store.ensure_home()
        if noise == 'excluded':
            db.create_session('noise', 'cli')
            for _ in range(260):
                db.append_message('noise', 'user', 'Lisbon')
            store.set_shared('noise', False)
        if noise == 'own_lineage':
            for _ in range(260):
                db.append_message(home, 'user', 'Lisbon')
            db.end_session(home, 'compression')
            db.create_session('continued', 'cli', parent_session_id=home)
            home = 'continued'
        db.create_session('shared', 'cli')
        db.append_message('shared', 'user', 'Lisbon trip budget is 1700 euros with a hotel booking pending.')
        rows = store.recall(home, 'Lisbon')
        assert rows
        assert {row['source_session_id'] for row in rows} == {'shared'}
        assert '1700 euros' in rows[0]['content']
