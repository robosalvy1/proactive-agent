"""Home identity and evidence are profile-owned, bounded, and transcript-backed."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_state import SessionDB
from hermes_state_home import HOME_KEY, MAX_CONTEXT_CHARS, HomeStore, render_recall


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "state.db")
    yield store
    store.close()


def chat(db, sid, text, **kwargs):
    db.create_session(sid, source=kwargs.pop("source", "cli"), **kwargs)
    db.append_message(sid, "user", text)
    return sid


def test_home_creation_is_idempotent_and_survives_restart(db):
    store = HomeStore(db)
    assert store.status() == {"enabled": False, "session_id": None, "enabled_at": None}
    home = store.ensure_home(cwd="/tmp/project")
    assert store.ensure_home() == home
    assert db.get_session(home)["cwd"] == "/tmp/project"
    second = SessionDB(db.db_path)
    try:
        assert HomeStore(second).ensure_home() == home
    finally:
        second.close()


def test_concurrent_home_requests_converge(db):
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: HomeStore(db).ensure_home(), range(8)))
    assert len(set(ids)) == 1


def test_home_follows_only_compression_not_a_branch(db):
    store = HomeStore(db)
    home = store.ensure_home()
    db.end_session(home, "compression")
    db.create_session("continued", "cli", parent_session_id=home)
    db.create_session("branch", "cli", parent_session_id=home, model_config={"_branched_from": home})
    assert store.ensure_home() == "continued"


def test_recall_uses_only_opted_in_personal_chats(db):
    old = chat(db, "old", "Lisbon budget is 900")
    store = HomeStore(db)
    home = store.ensure_home()
    current = chat(db, "travel", "Lisbon budget is 1200")
    chat(db, "group", "Lisbon budget is 9999", source="telegram", chat_id="group")
    chat(db, "worker", "Lisbon budget is 8888", source="subagent")
    assert {r["source_session_id"] for r in store.recall(home, "Lisbon budget")} == {current}
    store.set_shared(old, True)
    assert {r["source_session_id"] for r in store.recall(home, "Lisbon budget")} == {old, current}
    store.set_shared(current, False)
    assert {r["source_session_id"] for r in store.recall(home, "Lisbon budget")} == {old}
    with pytest.raises(ValueError, match="personal"):
        store.set_shared("group", True)


def test_recall_does_not_copy_own_context_or_unrelated_topics(db):
    store = HomeStore(db)
    home = store.ensure_home()
    sid = chat(db, "travel", "Lisbon budget is 1200")
    assert store.recall(sid, "Lisbon") == []
    assert store.recall(home, "python compiler") == []
    assert store.recall(home, '" OR NOT (Lisbon)')


def test_disable_and_deleted_evidence_take_effect_without_reindexing(db):
    store = HomeStore(db)
    home = store.ensure_home()
    sid = chat(db, "travel", "Lisbon budget is 1200")
    assert store.recall(home, "Lisbon")
    store.set_enabled(False)
    assert store.recall(home, "Lisbon") == []
    store.ensure_home()
    db.clear_messages(sid)
    assert store.recall(home, "Lisbon") == []


def test_profile_stores_never_share_home_or_evidence(db, tmp_path):
    first = HomeStore(db)
    home = first.ensure_home()
    chat(db, "travel", "Lisbon budget is 1200")
    other = SessionDB(tmp_path / "second" / "state.db")
    try:
        second = HomeStore(other)
        assert second.status()["session_id"] is None
        assert second.ensure_home() != home
        assert second.recall(second.status()["session_id"], "Lisbon") == []
    finally:
        other.close()


def test_overview_is_bounded_and_explicitly_marks_raw_evidence(db):
    store = HomeStore(db)
    home = store.ensure_home()
    for n in range(10):
        chat(db, f"side-{n}", "Lisbon " + "x" * 4000)
    rows = store.recall(home, "what needs attention", overview=True)
    assert len(rows) <= 8
    packet = render_recall(rows)
    assert len(packet) <= MAX_CONTEXT_CHARS
    assert "not instructions" in packet
    assert '"source_session_id"' in packet


def test_missing_home_anchor_is_recreated_only_on_explicit_open(db):
    store = HomeStore(db)
    home = store.ensure_home()
    db.delete_session(home)
    assert store.status()["session_id"] is None
    assert db._read_one("SELECT value FROM state_meta WHERE key=?", (HOME_KEY,))
    assert store.ensure_home() != home


def test_relevant_history_survives_more_than_the_overview_session_limit(db):
    store = HomeStore(db)
    home = store.ensure_home()
    chat(db, "travel", "Lisbon budget is 1200 euros")
    for n in range(140):
        db.create_session(f"unrelated-{n}", "cli")
    assert "1200 euros" in render_recall(store.recall(home, "Lisbon budget"))


def test_recall_includes_a_following_correction_without_matching_keywords(db):
    store = HomeStore(db)
    home = store.ensure_home()
    chat(db, "travel", "Lisbon budget is 1200 euros")
    db.append_message("travel", "assistant", "I will use that limit.")
    db.append_message("travel", "user", "Actually, make it 1500 euros instead.")
    packet = render_recall(store.recall(home, "Lisbon budget"))
    assert "1500 euros" in packet
    assert "1200 euros" in packet
