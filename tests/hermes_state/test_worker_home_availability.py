"""Optional recall failures must never contaminate the worker's durable write journal."""
import pytest

from agent.home_memory import HomeMemoryProvider
from agent.runtime_session_store import WorkerPersistenceError


@pytest.mark.parametrize('error', [WorkerPersistenceError('owner_unavailable'), TimeoutError('lost acknowledgement')])
def test_recall_failure_warns_once_and_does_not_block_later_transcript_writes(worker, error):
    db, remote = worker
    original = remote.rpc
    journal = remote.path.read_bytes()
    warnings = []

    def rpc(method, **params):
        if method == 'worker.home.recall':
            # A lost response after the owner read is equally harmless: no sequence was consumed.
            original(method, **params)
            raise error
        return original(method, **params)

    remote.rpc = rpc
    provider = HomeMemoryProvider(remote, warning_callback=warnings.append)
    assert provider.prefetch('Lisbon', session_id='owned') == ''
    assert provider.prefetch('Lisbon', session_id='owned') == ''
    assert len(warnings) == 1
    assert remote.failure is None
    assert remote.path.read_bytes() == journal
    assert db._read_one("SELECT last_sequence FROM worker_executions WHERE execution_id='worker'")[0] == 0
    remote.append_messages_batch('owned', [{'role': 'user', 'content': 'Conversation still works'}])
    assert db.get_messages('owned')[-1]['content'] == 'Conversation still works'


@pytest.mark.parametrize('change', ['epoch', 'generation', 'terminal'])
def test_nonjournaled_read_still_fences_assignment_lifecycle(worker, change):
    db, remote = worker
    updates = {
        'epoch': "UPDATE runtime_epoch SET epoch=epoch+1",
        'generation': "UPDATE worker_executions SET generation=generation+1 WHERE execution_id='worker'",
        'terminal': "UPDATE worker_executions SET status='terminal' WHERE execution_id='worker'",
    }
    db._write_sql(updates[change])
    with pytest.raises(ValueError, match='stale_'):
        remote.home_recall('owned', 'Lisbon')
    assert remote.failure is None
    assert remote.journal['pending'] == []
