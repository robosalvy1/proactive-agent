"""Bounded recall for an assigned personal worker; no worker-side database access."""
from hermes_state_home import HomeStore
from hermes_state_home_context import home_context_on
from hermes_state_runtime import RuntimeStoreError


def worker_home_recall(db, conn, session_id, payload):
    if (set(payload) != {"query", "overview"} or not isinstance(payload["query"], str)
            or len(payload["query"]) > 2000 or type(payload["overview"]) is not bool):
        raise RuntimeStoreError("invalid_params")
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise RuntimeStoreError("not_found")
    store = HomeStore(db, principal_id=row["user_id"])
    # A worker assignment alone does not authorize personal cross-chat access. Require
    # the owner's existing native launch-policy receipt, same user, and a personal surface.
    from hermes_state_local import POLICY_PREFIX
    receipt = conn.execute("SELECT 1 FROM state_meta WHERE key=?",
                           (POLICY_PREFIX + (row["chat_id"] or ""),)).fetchone()
    if receipt is None or not store._personal_on(conn, row):
        return {"context": "", "count": 0}
    state = store._state_on(conn)
    anchor = store.anchor_on(conn, session_id)
    overview = payload["overview"] and anchor == state.get("anchor")
    return home_context_on(db, conn, row['user_id'], session_id, payload['query'], overview=overview)
