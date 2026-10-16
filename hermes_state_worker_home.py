"""Bounded recall for an assigned personal worker; no worker-side database access."""
import json

from hermes_state_home import HomeStore
from hermes_state_home_context import home_context_on
from hermes_state_runtime import RuntimeStoreError


def read_worker_home(db, *, epoch, execution_id, session_id, generation, query, overview):
    """Fresh assignment-fenced read: no receipt, journal sequence or copied recall cache."""
    from hermes_state_runtime import _epoch, _worker_assignment

    payload = {'query': query, 'overview': overview}
    _validate_payload(payload)

    def authorize(conn):
        _epoch(conn, epoch)
        assignment = _worker_assignment(conn, execution_id, session_id, generation)
        if assignment['owner_epoch'] != epoch:
            raise RuntimeStoreError('stale_epoch')
        if assignment['status'] not in {'registered', 'running'}:
            raise RuntimeStoreError('stale_generation')
        return worker_home_principal_on(db, conn, session_id)

    with db._read_ctx() as conn:
        access = authorize(conn)
    if access is None:
        return {'context': '', 'count': 0}
    from hermes_state_home_semantic import prepare_semantic_query
    plan = None if overview else prepare_semantic_query(db, session_id, query, principal_id=access[0])
    # Network never holds a read transaction, and a revoked worker/grant cannot use
    # a result prepared under its former authority.
    with db._read_ctx() as conn:
        final_access = authorize(conn)
        if final_access is None or final_access != access:
            return {'context': '', 'count': 0}
        return worker_home_recall(db, conn, session_id, payload, semantic_plan=plan)


def _validate_payload(payload):
    if (set(payload) != {"query", "overview"} or not isinstance(payload["query"], str)
            or len(payload["query"]) > 2000 or type(payload["overview"]) is not bool):
        raise RuntimeStoreError("invalid_params")


def worker_home_principal_on(db, conn, session_id):
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise RuntimeStoreError("not_found")
    from hermes_state_home import PERSONAL_SOURCES
    from hermes_state_home_links import link_on
    initial = HomeStore(db)
    grant = link_on(initial, conn, session_id)
    principal = grant['principal_id'] if grant else row['user_id']
    store = HomeStore(db, principal_id=principal)
    # A worker assignment alone is insufficient. Local sessions need their native
    # launch receipt; messaging sessions need an explicit exact-identity Home grant.
    if row['source'] in PERSONAL_SOURCES:
        from hermes_state_local import POLICY_PREFIX
        receipt = conn.execute('SELECT 1 FROM state_meta WHERE key=?',
                               (POLICY_PREFIX + (row['chat_id'] or ''),)).fetchone()
        if receipt is None or not store._personal_on(conn, row):
            return None
    elif grant is None:
        return None
    state = store._state_on(conn)
    anchor = store.anchor_on(conn, session_id)
    grant_revision = json.dumps(grant, sort_keys=True) if grant else None
    return principal, anchor == state.get('anchor'), grant_revision


def worker_home_recall(db, conn, session_id, payload, *, semantic_plan=None):
    _validate_payload(payload)
    access = worker_home_principal_on(db, conn, session_id)
    if access is None:
        return {'context': '', 'count': 0}
    principal, is_home, _grant_revision = access
    return home_context_on(db, conn, principal, session_id, payload['query'],
                           overview=payload['overview'] and is_home, semantic_plan=semantic_plan)
