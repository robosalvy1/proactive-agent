"""Derived notes cross the existing owner-mediated read with the same source/principal checks."""
import json

from agent.home_dreaming import dream_once
from agent.home_memory import HomeMemoryProvider
from hermes_state_dreams import DreamStore
from hermes_state_home import HomeStore
from hermes_state_local import POLICY_PREFIX
from tests.hermes_state.test_worker_home import native_chat


def test_worker_recalls_valid_dream_notes_then_loses_excluded_sources(worker):
    db, remote = worker
    HomeStore(db).ensure_home()
    db._write_sql("UPDATE sessions SET user_id='human',chat_id='owned',chat_type='dm' WHERE id='owned'")
    db._write_sql('INSERT INTO state_meta(key,value) VALUES(?,?)',
                  (POLICY_PREFIX + 'owned', json.dumps({'principal_id': 'human', 'session_id': 'owned',
                                                       'policy': {'source': 'cli'}})))
    HomeStore(db, principal_id='human').set_shared('owned', True)
    native_chat(db, 'travel', 'human', 'I prefer the overnight sleeper')
    native_chat(db, 'foreign', 'other', 'Foreign private itinerary')
    DreamStore(db, principal_id='human').configure(enabled=True)

    def model(sources):
        assert not any(source['anchor'] == 'foreign' for source in sources)
        row = sources[0]['messages'][0]
        return json.dumps({'notes': [{'kind': 'preference', 'text': 'Prefer rail travel',
                                     'sources': [{'id': row['id'], 'quote': row['text']}]}]})

    assert '1 source-linked' in dream_once(db, principal_id='human', manual=True, model=model)
    provider = HomeMemoryProvider(remote)
    assert 'Prefer rail travel' in provider.prefetch('rail travel', session_id='owned')
    HomeStore(db, principal_id='human').set_shared('travel', False)
    assert provider.prefetch('rail travel', session_id='owned') == ''
