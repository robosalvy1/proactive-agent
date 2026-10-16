"""Owner-side semantic recall preserves compute-worker fencing and profile authority."""
import json
from pathlib import Path

import pytest

from hermes_state_home import HomeStore
from hermes_state_home_semantic import HomeIndex
from hermes_state_local import POLICY_PREFIX
from hermes_state_runtime import RuntimeStoreError
from tests.hermes_state.test_worker_home import native_chat


def configure(db, endpoint):
    home = Path(db.db_path).parent
    home.joinpath('config.yaml').write_text(
        'memory:\n  home_recall:\n    enabled: true\n'
        f'    base_url: {endpoint[0]}\n    model: local-fixture\n    api_key_env: HOME_EMBEDDING_API_KEY\n')
    home.joinpath('.env').write_text('HOME_EMBEDDING_API_KEY=worker-profile-key\n')
    HomeStore(db).ensure_home()
    db._write_sql("UPDATE sessions SET user_id='human',chat_id='owned',chat_type='dm' WHERE id='owned'")
    db._write_sql('INSERT INTO state_meta(key,value) VALUES(?,?)',
                  (POLICY_PREFIX + 'owned', json.dumps({'principal_id': 'human', 'session_id': 'owned',
                                                       'policy': {'source': 'cli'}})))
    HomeStore(db, principal_id='human').set_shared('owned', True)
    native_chat(db, 'food', 'human', 'I avoid animal products in meals.')
    endpoint[2]['vectors'] = {'I avoid animal products in meals.': [1, 0, 0],
                              'What dietary restrictions do I have?': [1, 0.02, 0]}
    HomeIndex(db, principal_id='human').index('owned')


def test_worker_uses_the_same_owner_semantic_index(worker, endpoint):
    """A worker gets paraphrase evidence through its owner, with one query request."""
    db, remote = worker
    configure(db, endpoint)
    packet = remote.home_recall('owned', 'What dietary restrictions do I have?')
    assert 'avoid animal products' in packet['context']
    assert len(endpoint[1]) == 2
    assert endpoint[1][-1][1]['Authorization'] == 'Bearer worker-profile-key'


def test_worker_rechecks_assignment_after_embedding_http(worker, endpoint):
    """A stale epoch during HTTP is fenced again before any context is returned."""
    from hermes_state_runtime import begin_runtime_epoch

    db, remote = worker
    configure(db, endpoint)
    endpoint[2]['callback'] = lambda: begin_runtime_epoch(db, instance_id='replacement')
    with pytest.raises(RuntimeStoreError, match='stale_epoch'):
        remote.home_recall('owned', 'What dietary restrictions do I have?')
    assert len(endpoint[1]) == 2


def test_owner_can_revoke_sources_during_worker_query_without_database_lock(worker, endpoint):
    """No SQLite read transaction is held during HTTP; revocation affects that reply."""
    db, remote = worker
    configure(db, endpoint)
    endpoint[2]['callback'] = lambda: HomeStore(db, principal_id='human').set_shared('food', False)
    assert remote.home_recall('owned', 'What dietary restrictions do I have?') == {'context': '', 'count': 0}
    assert len(endpoint[1]) == 2
