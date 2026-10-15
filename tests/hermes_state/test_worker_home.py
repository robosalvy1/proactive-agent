"""Managed workers recall through the owner and retain their assignment fences."""
import json

import pytest

from agent.home_memory import HomeMemoryProvider
from agent.runtime_session_store import WorkerPersistenceError
from hermes_state_home import HomeStore
from hermes_state_local import POLICY_PREFIX


def native_chat(db, sid, user, content):
    db.create_session(sid, "cli", user_id=user, chat_id=sid, chat_type="dm")
    db.append_message(sid, "user", content)
    db._write_sql("INSERT INTO state_meta(key,value) VALUES(?,?)",
                  (POLICY_PREFIX + sid, json.dumps({"principal_id": user, "session_id": sid,
                                                   "policy": {"source": "cli"}})))


def test_assigned_worker_reads_only_same_principal_participating_chats(worker):
    db, remote = worker
    home = HomeStore(db).ensure_home()
    db._write_sql("UPDATE sessions SET user_id='human',chat_id='owned',chat_type='dm' WHERE id='owned'")
    db._write_sql("INSERT INTO state_meta(key,value) VALUES(?,?)",
                  (POLICY_PREFIX + "owned", json.dumps({"principal_id": "human", "session_id": "owned",
                                                         "policy": {"source": "cli"}})))
    HomeStore(db, principal_id="human").set_shared("owned", True)
    native_chat(db, "travel", "human", "Lisbon budget is 1200 euros")
    native_chat(db, "stranger", "other", "Lisbon secret is 9999 euros")
    provider = HomeMemoryProvider(remote)
    context = provider.prefetch("Lisbon budget", session_id="owned")
    assert "1200 euros" in context
    assert "9999" not in context
    assert '"source_session_id": "travel"' in context
    HomeStore(db, principal_id="human").set_shared("travel", False)
    assert provider.prefetch("Lisbon budget", session_id="owned") == ""
    with pytest.raises(WorkerPersistenceError, match="permission_denied"):
        remote.home_recall(home, "Lisbon")


def test_worker_without_personal_launch_receipt_gets_no_cross_chat_context(worker):
    db, remote = worker
    HomeStore(db).ensure_home()
    db.create_session("travel", "cli")
    db.append_message("travel", "user", "Lisbon budget is 1200 euros")
    assert remote.home_recall("owned", "Lisbon") == {"context": "", "count": 0}
