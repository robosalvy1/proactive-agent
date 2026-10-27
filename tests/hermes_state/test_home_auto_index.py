"""Automatic newest-first Home indexing: bounded, single-flight, recent history first."""
import pytest

from tests.waiting import wait_until

from hermes_state import SessionDB
from hermes_state_home import HomeStore
from hermes_state_home_controls import HomeSourceControls
import hermes_state_home_semantic as semantic_index
from hermes_state_home_semantic import HomeIndex, auto_index_step, prepare_semantic_query, semantic_rows_on


def make_db(tmp_path, endpoint, extra='', *, auto='true'):
    profile = tmp_path / 'owned'
    profile.mkdir(exist_ok=True)
    profile.joinpath('config.yaml').write_text(
        'memory:\n  home_recall:\n    enabled: true\n'
        f'    base_url: {endpoint[0]}\n    model: fixture-embeddings\n    api_key_env: ""\n'
        + (f'    auto_index: {auto}\n' if auto is not None else '') + extra)
    return SessionDB(profile / 'state.db')


@pytest.fixture
def db(tmp_path, endpoint):
    store = make_db(tmp_path, endpoint)
    yield store
    store.close()


def add(db, sid, text):
    db.create_session(sid, 'cli')
    db.append_message(sid, 'user', text)
    return db._read_one('SELECT id FROM messages WHERE session_id=?', (sid,))[0]


def indexed_ids(db):
    with db._read_ctx() as conn:
        if not semantic_index._table_exists(conn):
            return set()
        return {row[0] for row in conn.execute(f'SELECT message_id FROM {semantic_index.TABLE}')}


def semantic(db, home, query):
    plan = prepare_semantic_query(db, home, query)
    with db._read_ctx() as conn:
        return semantic_rows_on(db, conn, None, home, plan)


def test_recent_history_is_embedded_before_older_backfill(db, endpoint):
    home = HomeStore(db).ensure_home()
    for i in range(40):
        add(db, f'chat-{i:02}', f'fact {i:02}')
    index = HomeIndex(db)
    first = index.index(home)
    assert first['indexed'] == 32 and first['more']
    assert endpoint[1][0][2]['input'][0] == 'fact 39'
    assert 'fact 00' not in endpoint[1][0][2]['input']
    second = index.index(home)
    assert second['indexed'] == 8 and second['more'] is False
    assert endpoint[1][1][2]['input'][-1] == 'fact 00'


def test_full_index_keeps_newest_sources_instead_of_failing(db, endpoint, monkeypatch):
    """A long history no longer stops at 'index full' with recent chats missing."""
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'old-{i}', f'old fact {i}') for i in range(6)]
    result = HomeIndex(db).drain(home)
    assert result['capacity_reached'] and result['more'] is False
    assert indexed_ids(db) == set(ids[2:])
    newer = [add(db, f'new-{i}', f'new fact {i}') for i in range(2)]
    step = HomeIndex(db).index(home, refresh=False)
    assert step['evicted'] == 2
    assert indexed_ids(db) == set(ids[4:] + newer)


def test_completed_turns_index_new_messages_through_the_background_sync_worker(db, endpoint):
    """No /home index needed: the real sync_all path embeds the turn's new rows."""
    from agent.home_memory import IndexingHomeMemoryProvider
    from agent.memory_manager import MemoryManager

    home = HomeStore(db).ensure_home()
    mid = add(db, 'food', 'I avoid animal products in meals.')
    endpoint[2]['vectors'] = {'I avoid animal products in meals.': [1, 0, 0],
                              'What dietary restrictions do I have?': [1, 0.02, 0]}
    manager = MemoryManager()
    manager.add_provider(IndexingHomeMemoryProvider(db))
    manager.sync_all('A user turn', 'An assistant turn', session_id=home)
    assert manager.flush_pending(timeout=20)
    assert mid in indexed_ids(db)
    assert [r['source_session_id'] for r in semantic(db, home, 'What dietary restrictions do I have?')] == ['food']
    manager.shutdown_all()


@pytest.mark.parametrize('auto, expected', [('true', True), ('false', False), (None, False)])
def test_automatic_indexing_requires_its_own_explicit_opt_in(tmp_path, endpoint, auto, expected):
    """An existing ``enabled: true`` profile never starts uploading history after turns."""
    from agent.home_memory import _auto_indexing

    with make_db(tmp_path, endpoint, auto=auto) as store:
        assert _auto_indexing(store) is expected


def test_read_only_profile_does_not_select_the_indexing_provider(tmp_path):
    from agent.home_memory import _auto_indexing

    with SessionDB(tmp_path / 'state.db') as store:
        assert _auto_indexing(store) is False


@pytest.mark.parametrize('config', ['enabled: true\n    observe: true', 'observe: maybe\n    enabled: true\n    auto_index: true'])
def test_one_broken_opt_in_does_not_disable_the_other(tmp_path, config):
    """An embedding config missing its endpoint must not stop observation, and vice versa."""
    from agent.home_memory import _auto_indexing

    base = '' if 'observe: true' in config else "\n    base_url: http://127.0.0.1:9/v1\n    model: m"
    (tmp_path / 'config.yaml').write_text(f'memory:\n  home_recall:\n    {config}{base}\n')
    with SessionDB(tmp_path / 'state.db') as store:
        assert _auto_indexing(store) is True


def test_auto_step_is_single_flight_and_fails_open(db, endpoint):
    home = HomeStore(db).ensure_home()
    add(db, 'topic', 'A source.')
    semantic_index._ACTIVE.add(str(db.db_path))
    try:
        assert auto_index_step(db, home) is None
    finally:
        semantic_index._ACTIVE.discard(str(db.db_path))
    assert endpoint[1] == []
    endpoint[2]['status'] = 503
    assert auto_index_step(db, home) is None
    assert indexed_ids(db) == set()
    endpoint[2]['status'] = 200
    assert auto_index_step(db, home)['indexed'] == 1


def test_auto_step_does_not_index_when_disabled(tmp_path, endpoint):
    with make_db(tmp_path, endpoint, auto='false') as store:
        home = HomeStore(store).ensure_home()
        add(store, 'topic', 'A source.')
        assert auto_index_step(store, home) is None
        assert endpoint[1] == []


@pytest.mark.parametrize('revoke', ['exclude', 'forget'])
def test_sweep_removes_vectors_of_excluded_or_forgotten_sources(db, endpoint, revoke):
    home = HomeStore(db).ensure_home()
    mid = add(db, 'topic', 'Private source.')
    keep = add(db, 'other', 'Other source.')
    HomeIndex(db).index(home)
    assert indexed_ids(db) == {mid, keep}
    if revoke == 'exclude':
        HomeStore(db).set_shared('topic', False)
    else:
        HomeSourceControls(db).forget(mid)
    assert HomeIndex(db).index(home)['swept'] == 1
    assert indexed_ids(db) == {keep}


def test_a_reply_to_a_forgotten_message_is_never_embedded_or_kept(db, endpoint):
    """Forgetting a user message also covers the assistant's restatement, even one written later."""
    home = HomeStore(db).ensure_home()
    mid = add(db, 'door', 'My door code is 4417.')
    db.append_message('door', 'assistant', 'Noted: your door code is 4417.')
    echo = db._read_one("SELECT id FROM messages WHERE session_id='door' AND role='assistant'")[0]
    HomeIndex(db).index(home)
    assert {mid, echo} <= indexed_ids(db)
    HomeSourceControls(db).forget(mid)
    HomeIndex(db).index(home)
    assert not indexed_ids(db) & {mid, echo}  # The sweep drops the inherited echo too.
    sent = len(endpoint[1])
    db.append_message('door', 'assistant', 'Reminder saved: door code 4417.')
    HomeIndex(db).index(home)
    assert not any('4417' in str(request[2]) for request in endpoint[1][sent:])


def test_source_superseded_before_indexing_still_points_to_its_correction(db, endpoint):
    """Indexing order no longer decides whether a paraphrase reaches the correction."""
    home = HomeStore(db).ensure_home()
    old = add(db, 'budget', 'My annual holiday spending ceiling is 1200.')
    new = add(db, 'correction', 'Actually, make it 1500 instead.')
    HomeSourceControls(db).supersede(old, new)
    endpoint[2]['vectors'] = {'My annual holiday spending ceiling is 1200.': [1, 0, 0],
                              'What is my vacation budget?': [1, 0, 0]}
    HomeIndex(db).index(home)
    assert old in indexed_ids(db)
    assert [r['content'] for r in semantic(db, home, 'What is my vacation budget?')] == ['Actually, make it 1500 instead.']


def test_edited_source_is_reembedded_by_automatic_steps(db, endpoint):
    """An edit no longer silently drops a source from semantic recall until /home index."""
    home = HomeStore(db).ensure_home()
    mid = add(db, 'diet', 'I eat fish on Fridays.')
    endpoint[2]['vectors'] = {'I am fully vegan now.': [1, 0, 0], 'What do I eat?': [1, 0, 0]}
    auto_index_step(db, home)
    assert mid in indexed_ids(db)
    db._execute_write(lambda conn: conn.execute('UPDATE messages SET content=? WHERE id=?',
                                                ('I am fully vegan now.', mid)))
    step = auto_index_step(db, home)
    assert step['indexed'] == 1 and endpoint[1][-1][2]['input'] == ['I am fully vegan now.']
    assert [r['content'] for r in semantic(db, home, 'What do I eat?')] == ['I am fully vegan now.']


def test_hung_endpoint_backs_off_instead_of_stalling_every_turn(tmp_path, endpoint):
    import threading
    import time

    from agent.home_embeddings import EmbeddingUnavailable, embedding_health, load_embedding_config
    from hermes_cli.home_controls import source_action

    with make_db(tmp_path, endpoint, '    timeout_seconds: 2\n') as store:  # Room for a loaded runner.
        home = HomeStore(store).ensure_home()
        add(store, 'topic', 'A source.')
        HomeIndex(store).index(home)
        hung = threading.Event()
        endpoint[2]['callback'] = lambda: hung.wait(30)  # Outlasts the timeout; released below.
        assert prepare_semantic_query(store, home, 'recall') is None
        calls = len(endpoint[1])
        add(store, 'later', 'A newer source.')
        assert prepare_semantic_query(store, home, 'recall') is None
        assert auto_index_step(store, home) is None
        assert len(endpoint[1]) == calls  # Backoff: no further endpoint requests.
        assert embedding_health(load_embedding_config(store))['failures'] == 1
        assert 'Endpoint failing (TimeoutError, 1 in a row)' in source_action(store, home, 'index status')['output']
        with pytest.raises(EmbeddingUnavailable):
            HomeIndex(store).index(home)
        hung.set()
        endpoint[2]['callback'] = None
        assert source_action(store, home, 'index')['output'].startswith('Indexed 1 sources')
        assert 'Endpoint healthy' in source_action(store, home, 'index status')['output']


def test_source_edited_during_its_first_request_is_retried(db, endpoint):
    home = HomeStore(db).ensure_home()
    mid = add(db, 'source', 'first value')
    endpoint[2]['callback'] = lambda: db._execute_write(lambda conn: conn.execute(
        'UPDATE messages SET content=? WHERE id=?', ('edited value', mid)))
    assert auto_index_step(db, home)['indexed'] == 0
    endpoint[2]['callback'] = None
    assert auto_index_step(db, home)['indexed'] == 1
    assert endpoint[1][-1][2]['input'] == ['edited value'] and mid in indexed_ids(db)


def test_backfill_resumes_when_forgetting_frees_capacity(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'value {i}') for i in range(6)]
    auto_index_step(db, home)
    auto_index_step(db, home)
    assert indexed_ids(db) == set(ids[2:])
    HomeSourceControls(db).forget(ids[-1])
    for _ in range(3):
        auto_index_step(db, home)
    assert indexed_ids(db) == set(ids[1:-1])


def test_reembedding_edits_does_not_consume_new_capacity(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    monkeypatch.setattr(semantic_index, 'MAX_BATCH', 2)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'value {i}') for i in range(6)]
    auto_index_step(db, home)
    assert indexed_ids(db) == set(ids[-2:])
    monkeypatch.setattr(semantic_index, 'MAX_BATCH', 32)
    db._execute_write(lambda conn: conn.execute('UPDATE messages SET content=content || ? WHERE id>=?',
                                               (' edited', ids[-2])))
    auto_index_step(db, home)
    # Before the fix the two pending edits counted as new rows: only 2 of 4 slots were used.
    assert indexed_ids(db) == set(ids[2:])


def test_sharing_an_older_chat_reopens_completed_backfill(db, endpoint):
    old = add(db, 'pre-home', 'old fact')
    home = HomeStore(db).ensure_home()
    auto_index_step(db, home)
    assert old not in indexed_ids(db)
    HomeStore(db).set_shared('pre-home', True)
    auto_index_step(db, home)
    assert old in indexed_ids(db)


def test_drain_reembeds_every_edit_before_reporting_ready(db, endpoint):
    home = HomeStore(db).ensure_home()
    for i in range(40):
        add(db, f'source-{i}', f'value {i}')
    HomeIndex(db).drain(home)
    db._execute_write(lambda conn: conn.execute('UPDATE messages SET content=content || ?', (' edited',)))
    HomeIndex(db).drain(home)
    with db._read_ctx() as conn:
        stale = [r['message_id'] for r in conn.execute(f'SELECT * FROM {semantic_index.TABLE}')
                 if semantic_index._source_hash(semantic_index._source_on(conn, r['message_id'])) != r['source_hash']]
    assert stale == []


def test_sweep_keeps_another_principals_edited_source(db, endpoint):
    import json

    from hermes_state_home_links import set_link

    home = HomeStore(db).ensure_home()
    origin = {'platform': 'telegram', 'user_id': 'remote-b', 'chat_id': 'private-b', 'chat_type': 'dm', 'thread_id': None}
    key = 'agent:main:telegram:dm:private-b'
    db.create_session('dm-b', 'telegram', user_id='remote-b', chat_id='private-b', chat_type='dm',
                      session_key=key, origin_json=json.dumps(origin))
    db._write_sql("INSERT INTO gateway_routing(scope,session_key,entry_json,updated_at) VALUES('',?,?,0)",
                  (key, json.dumps({'session_id': 'dm-b', 'origin': origin, 'transport_profile': None})))
    db.append_message('dm-b', 'user', 'B private value')
    mid = db._read_one('SELECT id FROM messages WHERE session_id=?', ('dm-b',))[0]
    set_link(HomeStore(db, principal_id='B'), 'dm-b', True, caller_session_id=home)
    HomeIndex(db, principal_id='B').index(home, refresh=False)
    assert mid in indexed_ids(db)
    db._execute_write(lambda conn: conn.execute('UPDATE messages SET content=? WHERE id=?', ('B new value', mid)))
    HomeIndex(db, principal_id='A').index(home, refresh=False)
    assert mid in indexed_ids(db)


def test_indexing_is_single_flight_across_processes(db, endpoint):
    import subprocess
    import sys
    import threading
    from pathlib import Path

    home = HomeStore(db).ensure_home()
    add(db, 'source', 'private fact uploaded once')
    slow = threading.Event()
    endpoint[2]['callback'] = lambda: slow.wait(1)  # Holds the first request while the other process tries.
    code = ('import sys; sys.path.insert(0, sys.argv[3])\n'
            'from hermes_state import SessionDB\nfrom hermes_state_home_semantic import auto_index_step\n'
            'from pathlib import Path\nwith SessionDB(Path(sys.argv[1])) as db:\n'
            '    print(auto_index_step(db, sys.argv[2]))\n')
    root = str(Path(__file__).resolve().parents[2])
    procs = [subprocess.Popen([sys.executable, '-B', '-c', code, str(db.db_path), home, root],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
             for _ in range(2)]
    results = [proc.communicate(timeout=60) for proc in procs]
    assert all(proc.returncode == 0 for proc in procs), results
    assert len(endpoint[1]) == 1
    assert HomeIndex(db).index(home, refresh=False)['indexed'] == 0  # Lease released afterwards.


def test_explicit_indexing_reports_a_running_step(db, endpoint):
    home = HomeStore(db).ensure_home()
    add(db, 'source', 'value')
    db._execute_write(lambda conn: semantic_index._acquire_lease_on(conn, 'other', load_config(db)))
    with pytest.raises(semantic_index.IndexBusy):
        HomeIndex(db).index(home)
    assert auto_index_step(db, home) is None and endpoint[1] == []


def load_config(db):
    from agent.home_embeddings import load_embedding_config

    return load_embedding_config(db)


def test_endpoint_health_is_scoped_to_its_profile(tmp_path, monkeypatch):
    from agent import home_embeddings as he

    cfg_a = he.EmbeddingConfig('http://127.0.0.1:1/v1', 'same-model', '', str(tmp_path / 'a'))
    cfg_b = he.EmbeddingConfig('http://127.0.0.1:1/v1', 'same-model', '', str(tmp_path / 'b'))

    def request(config, texts):
        if config.profile_home == cfg_a.profile_home:
            raise TimeoutError('a timeout')
        return [(1.0, 0.0)]
    monkeypatch.setattr(he, '_request_embeddings', request)
    with pytest.raises(TimeoutError):
        he.embed(cfg_a, ['a'])
    assert he.embed(cfg_b, ['b']) == [(1.0, 0.0)]
    assert he.embedding_health(cfg_a)['failures'] == 1 and not he.embedding_health(cfg_b)['failures']


def test_only_one_probe_reaches_a_recovering_endpoint(tmp_path, monkeypatch):
    import threading

    from agent import home_embeddings as he

    cfg = he.EmbeddingConfig('http://127.0.0.1:9/v1', 'probe-model', '', str(tmp_path))
    he._HEALTH[he._health_key(cfg)] = {'failures': 1, 'retry_at': 0}
    calls, gate = [], threading.Event()

    def request(config, texts):
        calls.append(1)
        gate.wait(timeout=10)
        raise TimeoutError('timeout')
    monkeypatch.setattr(he, '_request_embeddings', request)

    def invoke():
        try:
            he.embed(cfg, ['probe'])
        except OSError:
            pass
    first = threading.Thread(target=invoke)
    first.start()
    wait_until(lambda: calls, what='the probe request')
    with pytest.raises(he.EmbeddingUnavailable):
        he.embed(cfg, ['probe'])
    gate.set()
    first.join(timeout=15)
    he.reset_embedding_health(cfg)
    assert len(calls) == 1


def test_managed_worker_turns_advance_the_owner_index(db, endpoint, monkeypatch):
    import threading

    home = HomeStore(db).ensure_home()
    mid = add(db, 'topic', 'Worker-era fact.')
    done = threading.Event()
    real = semantic_index.auto_index_step
    monkeypatch.setattr(semantic_index, 'auto_index_step', lambda *a, **k: (real(*a, **k), done.set()))
    assert semantic_index.schedule_auto_index_step(db, home)
    assert done.wait(20) and mid in indexed_ids(db)


def test_sharing_during_the_first_request_is_not_lost(db, endpoint):
    old = add(db, 'pre-home', 'newly shared old memory')
    home = HomeStore(db).ensure_home()
    add(db, 'recent', 'recent memory triggers the first request')
    endpoint[2]['callback'] = lambda: HomeStore(db).set_shared('pre-home', True)
    auto_index_step(db, home)
    endpoint[2]['callback'] = None
    for _ in range(3):
        auto_index_step(db, home)
    assert old in indexed_ids(db)


def test_linking_during_the_first_request_is_not_lost(db, endpoint):
    import json

    from hermes_state_home_links import set_link

    origin = {'platform': 'telegram', 'user_id': 'remote', 'chat_id': 'private', 'chat_type': 'dm', 'thread_id': None}
    key = 'agent:main:telegram:dm:private'
    db.create_session('dm', 'telegram', user_id='remote', chat_id='private', chat_type='dm',
                      session_key=key, origin_json=json.dumps(origin))
    db.append_message('dm', 'user', 'older private memory')
    mid = db._read_one('SELECT id FROM messages WHERE session_id=?', ('dm',))[0]
    home = HomeStore(db).ensure_home()
    add(db, 'recent', 'recent memory triggers the first request')
    endpoint[2]['callback'] = lambda: set_link(HomeStore(db), 'dm', True, caller_session_id=home)
    auto_index_step(db, home)
    endpoint[2]['callback'] = None
    for _ in range(3):
        auto_index_step(db, home)
    assert mid in indexed_ids(db)


def test_newly_shared_source_replaces_an_older_vector_when_full(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'memory {i}') for i in range(6)]
    HomeStore(db).set_shared('source-4', False)
    HomeIndex(db).drain(home)
    assert indexed_ids(db) == {ids[1], ids[2], ids[3], ids[5]}
    HomeStore(db).set_shared('source-4', True)
    HomeIndex(db).drain(home)
    assert indexed_ids(db) == set(ids[2:])


def test_space_freed_after_front_eviction_is_refilled(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'memory {i}') for i in range(4)]
    assert auto_index_step(db, home)['indexed'] == 4
    newer = [add(db, f'newer-{i}', f'new memory {i}') for i in range(2)]
    assert auto_index_step(db, home)['evicted'] == 2
    HomeSourceControls(db).forget(newer[-1])
    for _ in range(3):
        auto_index_step(db, home)
    assert indexed_ids(db) == set(ids[1:] + newer[:1])


def test_a_full_completed_index_stays_quiet(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'memory {i}') for i in range(6)]
    HomeIndex(db).drain(home)
    calls = len(endpoint[1])
    for _ in range(4):
        step = auto_index_step(db, home)
        assert not step['more'] and step['scanned'] == 0 and step['indexed'] == 0
    assert len(endpoint[1]) == calls and indexed_ids(db) == set(ids[2:])


def test_profile_scope_failure_releases_the_recovery_probe(db, endpoint, monkeypatch):
    from contextlib import contextmanager

    from agent import home_embeddings as he

    cfg = load_config(db)
    he._HEALTH[he._health_key(cfg)] = {'failures': 1, 'retry_at': 0}

    @contextmanager
    def broken(*_args):
        raise OSError('scope construction failed')
        yield
    original = he.embedding_profile_scope
    monkeypatch.setattr(he, 'embedding_profile_scope', broken)
    with pytest.raises(OSError):
        he.embed(cfg, ['probe'])
    assert not he.embedding_health(cfg)['probing']
    monkeypatch.setattr(he, 'embedding_profile_scope', original)
    he.reset_embedding_health(cfg)


def _linked_dm(db, sid, principal, home, count):
    import json

    from hermes_state_home_links import set_link

    origin = {'platform': 'telegram', 'user_id': 'remote-' + sid, 'chat_id': 'private-' + sid,
              'chat_type': 'dm', 'thread_id': None}
    key = 'agent:main:telegram:dm:private-' + sid
    db.create_session(sid, 'telegram', user_id=origin['user_id'], chat_id=origin['chat_id'],
                      chat_type='dm', session_key=key, origin_json=json.dumps(origin))
    ids = []
    for i in range(count):
        db.append_message(sid, 'user', f'{sid} fact {i}')
        ids.append(db._read_one('SELECT MAX(id) FROM messages WHERE session_id=?', (sid,))[0])
    set_link(HomeStore(db, principal_id=principal), sid, True, caller_session_id=home)
    return ids


def test_another_principals_eviction_is_refilled_when_space_frees(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    a = _linked_dm(db, 'dm-a', 'A', home, 4)
    b = _linked_dm(db, 'dm-b', 'B', home, 2)
    HomeIndex(db, principal_id='A').index(home, refresh=False)
    assert HomeIndex(db, principal_id='B').index(home, refresh=False)['evicted'] == 2
    for mid in b:
        HomeSourceControls(db, principal_id='B').forget(mid)
    for _ in range(3):
        HomeIndex(db, principal_id='A').index(home, refresh=False)
    assert indexed_ids(db) == set(a)


def test_switching_back_to_an_embedding_model_rebuilds_its_coverage(db, endpoint):
    from pathlib import Path

    home = HomeStore(db).ensure_home()
    mid = add(db, 'source', 'stable historical fact')
    assert auto_index_step(db, home)['indexed'] == 1
    path = Path(db.db_path).parent / 'config.yaml'
    original = path.read_text()
    path.write_text(original.replace('fixture-embeddings', 'fixture-other-model'))
    assert auto_index_step(db, home)['indexed'] == 1
    path.write_text(original)
    assert auto_index_step(db, home)['indexed'] == 1
    assert indexed_ids(db) == {mid}


def test_refill_settles_when_history_is_smaller_than_the_cap(db, endpoint, monkeypatch):
    monkeypatch.setattr(semantic_index, 'MAX_INDEX_ROWS', 4)
    home = HomeStore(db).ensure_home()
    ids = [add(db, f'source-{i}', f'fact {i}') for i in range(7)]
    HomeIndex(db).drain(home)
    for mid in ids[2:]:
        HomeSourceControls(db).forget(mid)
    for _ in range(4):
        auto_index_step(db, home)
    assert indexed_ids(db) == set(ids[:2])
    calls = len(endpoint[1])
    for _ in range(3):
        step = auto_index_step(db, home)
        assert step['scanned'] == step['indexed'] == 0 and not step['more']
    assert len(endpoint[1]) == calls


def _signed(pattern, scale=1.0):
    return [scale * (1 if bit == '1' else -1) for bit in pattern]


def test_large_indexes_rescore_only_the_closest_sign_codes(db, endpoint, monkeypatch):
    import random

    home = HomeStore(db).ensure_home()
    rng = random.Random(3)
    vectors = {}
    for i in range(30):
        text = f'unrelated note {i}'
        vectors[text] = _signed(''.join(rng.choice('01') for _ in range(8)))
        add(db, f'noise-{i}', text)
    target = add(db, 'target', 'I keep my passport in the blue drawer.')
    vectors['I keep my passport in the blue drawer.'] = _signed('11110000')
    vectors['Where is my passport?'] = _signed('11110000', 0.9)
    endpoint[2]['vectors'] = vectors
    HomeIndex(db).drain(home)
    monkeypatch.setattr(semantic_index, 'RESCORE_MIN', 4)
    scored = []
    real = semantic_index._dot
    monkeypatch.setattr(semantic_index, '_dot', lambda a, b: scored.append(1) or real(a, b))
    hits = semantic(db, home, 'Where is my passport?')
    assert hits[0]['id'] == target
    assert len(scored) == 4  # 31 vectors indexed; only the four closest sign codes were scored exactly.


def test_index_without_sign_codes_uses_the_exact_scan_until_backfilled(db, endpoint, monkeypatch):
    home = HomeStore(db).ensure_home()
    mid = add(db, 'fact', 'I keep my passport in the blue drawer.')
    endpoint[2]['vectors'] = {'I keep my passport in the blue drawer.': [1, 0, 0], 'Where is my passport?': [1, 0, 0]}
    HomeIndex(db).index(home)
    db._execute_write(lambda conn: conn.execute(f'DELETE FROM {semantic_index.CODES}'))  # A pre-upgrade index.
    semantic_index._CODE_CACHE.clear()
    monkeypatch.setattr(semantic_index, 'RESCORE_MIN', 1)  # Fast path once codes exist.
    assert [r['id'] for r in semantic(db, home, 'Where is my passport?')] == [mid]
    add(db, 'later', 'A later note.')
    auto_index_step(db, home)
    with db._read_ctx() as conn:
        assert conn.execute(f'SELECT COUNT(*) FROM {semantic_index.CODES}').fetchone()[0] == 2
    assert [r['id'] for r in semantic(db, home, 'Where is my passport?')] == [mid]
