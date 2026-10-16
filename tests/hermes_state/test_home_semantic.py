"""Semantic Home retrieval uses real bounded HTTP, synthetic vectors and canonical evidence."""
import json

import pytest

from agent.home_embeddings import embed, load_embedding_config, normalized_vector
from hermes_state import SessionDB
from hermes_state_home import HomeStore
from hermes_state_home_controls import HomeSourceControls
from hermes_state_home_semantic import (
    HomeIndex, merge_recall, prepare_semantic_query, semantic_rows_on,
)


@pytest.fixture
def db(tmp_path, endpoint):
    profile = tmp_path / 'owned'
    profile.mkdir()
    profile.joinpath('config.yaml').write_text(
        'memory:\n  home_recall:\n    enabled: true\n'
        f'    base_url: {endpoint[0]}\n    model: fixture-embeddings\n'
        '    api_key_env: HOME_EMBEDDING_API_KEY\n')
    profile.joinpath('.env').write_text('HOME_EMBEDDING_API_KEY=profile-only-secret-token\n')
    store = SessionDB(profile / 'state.db')
    yield store
    store.close()


def add(db, sid, text):
    db.create_session(sid, 'cli')
    db.append_message(sid, 'user', text)
    return db._read_one('SELECT id FROM messages WHERE session_id=?', (sid,))[0]


def semantic(db, home, query):
    plan = prepare_semantic_query(db, home, query)
    with db._read_ctx() as conn:
        return semantic_rows_on(db, conn, None, home, plan)


def test_real_http_paraphrase_recall_and_distractor_ranking(db, endpoint):
    """Distinct lexical wording recalls the synthetic matching vector, not a distractor."""
    home = HomeStore(db).ensure_home()
    add(db, 'food', 'I avoid animal products in meals.')
    add(db, 'travel', 'I fly to Lisbon on Friday.')
    endpoint[2]['vectors'] = {'I avoid animal products in meals.': [1, 0, 0],
                              'What dietary restrictions do I have?': [1, 0.02, 0],
                              'I fly to Lisbon on Friday.': [0, 1, 0]}
    assert HomeStore(db).recall(home, 'What dietary restrictions do I have?') == []
    result = HomeIndex(db).index(home)
    assert result['indexed'] == 2
    hits = semantic(db, home, 'What dietary restrictions do I have?')
    assert [r['source_session_id'] for r in hits] == ['food']
    assert len(endpoint[1]) == 2
    assert all(request[0] == '/v1/embeddings' for request in endpoint[1])
    assert endpoint[1][0][1]['Authorization'] == 'Bearer profile-only-secret-token'


def test_unchanged_index_reuses_vectors_and_source_edits_invalidate(db, endpoint):
    """Repeated explicit indexing is cached; edited text cannot reuse stale derived vectors."""
    home = HomeStore(db).ensure_home()
    mid = add(db, 'topic', 'Old source fact.')
    HomeIndex(db).index(home)
    assert HomeIndex(db).index(home)['indexed'] == 0
    assert len(endpoint[1]) == 1
    db._execute_write(lambda conn: conn.execute('UPDATE messages SET content=? WHERE id=?', ('New fact.', mid)))
    assert semantic(db, home, 'recall') == []
    assert HomeIndex(db).index(home)['indexed'] == 1
    assert semantic(db, home, 'recall')[0]['content'] == 'New fact.'


@pytest.mark.parametrize('revoke', ['exclude', 'delete', 'forget', 'disable'])
def test_canonical_revocations_hide_already_indexed_sources(db, revoke):
    """Derived vectors cannot restore excluded, deleted, forgotten or disabled evidence."""
    store = HomeStore(db)
    home = store.ensure_home()
    mid = add(db, 'topic', 'Old source fact.')
    HomeIndex(db).index(home)
    plan = prepare_semantic_query(db, home, 'recall')
    if revoke == 'exclude':
        store.set_shared('topic', False)
    elif revoke == 'delete':
        db.clear_messages('topic')
    elif revoke == 'forget':
        HomeSourceControls(db).forget(mid)
    else:
        store.set_enabled(False)
    with db._read_ctx() as conn:
        assert semantic_rows_on(db, conn, None, home, plan) == []


def test_exclusion_during_embedding_never_publishes(db, endpoint):
    """A source revoked during HTTP is revalidated before derived state is published."""
    store = HomeStore(db)
    home = store.ensure_home()
    add(db, 'topic', 'Source that is revoked in flight.')
    endpoint[2]['callback'] = lambda: store.set_shared('topic', False)
    assert HomeIndex(db).index(home)['indexed'] == 0
    assert semantic(db, home, 'recall') == []


def test_provider_failure_preserves_keyword_recall(db, endpoint):
    """Index/query HTTP errors do not remove the canonical lexical retrieval path."""
    store = HomeStore(db)
    home = store.ensure_home()
    add(db, 'topic', 'Lisbon budget is 1500 euros.')
    HomeIndex(db).index(home)
    endpoint[2]['status'] = 503
    assert prepare_semantic_query(db, home, 'Lisbon') is None
    assert '1500' in merge_recall(store.recall(home, 'Lisbon'), [])[0]['content']
    assert len(endpoint[1]) == 2


def test_own_lineage_and_unshared_sources_are_never_indexed_or_recalled(db, endpoint):
    """Only participating sources reach embeddings, and own-context hits are excluded."""
    old = add(db, 'old', 'Never shared old secret context.')
    home = HomeStore(db).ensure_home()
    add(db, 'topic', 'My own session context.')
    HomeIndex(db).index(home)
    assert endpoint[1][0][2]['input'] == ['My own session context.']
    assert semantic(db, 'topic', 'recall') == []
    assert old > 0


def test_input_is_redacted_in_owning_profile_and_decoy_profile_is_ignored(db, endpoint, monkeypatch, tmp_path):
    """Credentials and exact known profile secrets are redacted before network egress."""
    decoy = tmp_path / 'decoy'
    decoy.mkdir()
    decoy.joinpath('.env').write_text('HOME_EMBEDDING_API_KEY=wrong-profile-secret-token\n')
    monkeypatch.setenv('HERMES_HOME', str(decoy))
    home = HomeStore(db).ensure_home()
    add(db, 'topic', 'My token is profile-only-secret-token and https://user:password@example.com/private')
    HomeIndex(db).index(home)
    sent = endpoint[1][0]
    assert sent[1]['Authorization'] == 'Bearer profile-only-secret-token'
    assert 'profile-only-secret-token' not in sent[2]['input'][0]
    assert 'user:password@' not in sent[2]['input'][0]


def test_index_batches_are_bounded_and_cursor_reaches_later_sources(db, endpoint):
    """A bounded page can continue across calls without repeatedly embedding earlier rows."""
    home = HomeStore(db).ensure_home()
    for i in range(70):
        add(db, f'topic-{i}', f'Useful fact number {i}.')
    counts = [HomeIndex(db).index(home) for _ in range(3)]
    assert [row['indexed'] for row in counts] == [32, 32, 6]
    assert counts[-1]['more'] is False
    assert all(len(call[2]['input']) <= 32 for call in endpoint[1])
    assert sum(len(call[2]['input']) for call in endpoint[1]) == 70


def test_embedding_dimension_change_and_bad_results_fail_closed(db, endpoint):
    """Malformed/different vector spaces never reach cosine ranking or corrupt cache."""
    home = HomeStore(db).ensure_home()
    add(db, 'topic', 'A source.')
    HomeIndex(db).index(home)
    endpoint[2]['response'] = {'data': [{'index': 0, 'embedding': [1, 0]}]}
    assert semantic(db, home, 'recall') == []
    endpoint[2]['response'] = {'data': [{'index': 0, 'embedding': [float('nan'), 1]}]}
    assert prepare_semantic_query(db, home, 'recall') is None
    endpoint[2]['response'] = {'data': [{'index': 1, 'embedding': [1, 0]}]}
    with pytest.raises(ValueError, match='indexes'):
        embed(load_embedding_config(db), ['query'])


@pytest.mark.parametrize('value', [[], [0, 0], [True, 1], [float('inf')], [1] * 3073])
def test_invalid_vectors_are_rejected(value):
    """Bound dimensions and reject zero, nonfinite and boolean vectors."""
    with pytest.raises(ValueError):
        normalized_vector(value)


def test_redaction_expansion_cannot_exceed_the_egress_budget(db, endpoint):
    from pathlib import Path
    profile = Path(db.db_path).parent
    with profile.joinpath('.env').open('a') as stream:
        stream.write('SHORT_SECRET=abc12345\n')
    with pytest.raises(ValueError, match='Redacted embedding input'):
        embed(load_embedding_config(db), ['abc12345' * 2000])
    assert endpoint[1] == []


def test_redaction_expansion_batches_keep_advancing_to_later_sources(db, endpoint):
    """Near-limit raw batches split before HTTP using the owning profile's redacted size."""
    from pathlib import Path

    with Path(db.db_path).parent.joinpath('.env').open('a') as stream:
        stream.write('SHORT_SECRET=abc12345\n')
    home = HomeStore(db).ensure_home()
    for i in range(20):
        add(db, f'topic-{i}', f'{i:02} ' + 'abc12345' * 110)
    index = HomeIndex(db)
    first = index.index(home)
    assert first['more']
    final = index.index(home)
    assert final['more'] is False
    assert first['indexed'] + final['indexed'] == 20
    assert len(endpoint[1]) == 2
    for _, _, payload in endpoint[1]:
        assert sum(map(len, payload['input'])) <= 16000
        assert all('abc12345' not in text for text in payload['input'])
    assert endpoint[1][-1][2]['input'][-1].startswith('19 ')


def test_unindexable_redacted_source_does_not_block_later_rows(db, endpoint, monkeypatch):
    """A single over-budget source is reported and skipped without retrying HTTP."""
    from agent import home_embeddings

    original = home_embeddings._redact_inputs

    def redact(config, texts):
        return ['[REDACTED]' * 2000 if text == 'expanding' else text
                for text in original(config, texts)]

    monkeypatch.setattr(home_embeddings, '_redact_inputs', redact)
    home = HomeStore(db).ensure_home()
    add(db, 'too-large', 'expanding')
    add(db, 'later', 'Useful later fact.')
    result = HomeIndex(db).index(home)
    assert result['indexed'] == 1
    assert result['skipped'] == 1
    assert result['more'] is False
    assert endpoint[1][0][2]['input'] == ['Useful later fact.']


def test_clear_is_available_offline_and_revokes_inflight_index(db, endpoint):
    home = HomeStore(db).ensure_home()
    add(db, 'topic', 'Private source.')
    index = HomeIndex(db)
    index.index(home)
    endpoint[2]['callback'] = lambda: index.clear(home)
    add(db, 'later', 'New source.')
    with pytest.raises(ValueError, match='access changed'):
        index.index(home)
    assert semantic(db, home, 'recall') == []
    assert len(endpoint[1]) == 2  # No query request against the cleared index.
    assert HomeStore(db).recall(home, 'Private source')


def test_supersession_keeps_semantic_pointer_after_reindex_and_respects_exclusion(db, endpoint):
    home = HomeStore(db).ensure_home()
    old = add(db, 'food', 'I avoid animal products in meals.')
    endpoint[2]['vectors'] = {'I avoid animal products in meals.': [1, 0, 0],
                              'What dietary restrictions do I have?': [1, 0.02, 0]}
    index = HomeIndex(db)
    index.index(home)
    new = add(db, 'correction', 'Actually, I eat those now.')
    HomeSourceControls(db).supersede(old, new)
    index.index(home)
    hits = semantic(db, home, 'What dietary restrictions do I have?')
    assert [r['content'] for r in hits] == ['Actually, I eat those now.']
    HomeStore(db).set_shared('food', False)
    assert semantic(db, home, 'What dietary restrictions do I have?') == []


def test_semantic_pointer_resolves_distant_correction_without_old_content(db, endpoint):
    """An indexed original can locate its explicit correction without resurfacing stale prose."""
    home = HomeStore(db).ensure_home()
    old = add(db, 'topic', 'My annual holiday spending ceiling is 1200.')
    endpoint[2]['vectors'] = {'My annual holiday spending ceiling is 1200.': [1, 0, 0],
                              'What is my vacation budget?': [1, 0, 0]}
    HomeIndex(db).index(home)
    new = add(db, 'correction', 'Actually, make it 1500 instead.')
    HomeSourceControls(db).supersede(old, new)
    hits = semantic(db, home, 'What is my vacation budget?')
    assert [row['content'] for row in hits] == ['Actually, make it 1500 instead.']
    HomeSourceControls(db).forget(new)
    assert semantic(db, home, 'What is my vacation budget?') == []


def test_rank_fusion_keeps_exact_and_semantic_answers_and_deduplicates_identity():
    """Fusion handles incomparable retrieval scores and compression clones by identity."""
    exact = {'id': 1, 'message_uid': 'exact'}
    shared = {'id': 2, 'message_uid': 'same'}
    clone = {'id': 20, 'message_uid': 'same'}
    paraphrase = {'id': 3, 'message_uid': 'meaning'}
    rows = merge_recall([exact, shared], [clone, paraphrase])
    assert len(rows) == 3
    assert rows[0]['message_uid'] == 'same'
    assert {row['message_uid'] for row in rows} == {'exact', 'same', 'meaning'}
