"""Local Home indexing and explicit source controls, shared by frontend transports."""
from __future__ import annotations


def source_action(db, session_id, action, *, principal_id=None):
    verb, *args = action.split()
    verb = verb.lower()
    if verb not in {'index', 'forget', 'supersede', 'sources'}:
        return None
    from hermes_state_home import HomeStore
    from hermes_state_home_links import require_local_owner
    from hermes_state_home_controls import HomeSourceControls

    store = HomeStore(db, principal_id=principal_id)
    with db._read_ctx() as conn:
        require_local_owner(store, conn, session_id)
    controls = HomeSourceControls(db, principal_id=principal_id)
    if verb == 'index' and args in ([], ['clear']):
        from hermes_state_home_semantic import HomeIndex
        index = HomeIndex(db, principal_id=principal_id)
        if args:
            index.clear(session_id)
            return {'output': 'Home semantic index cleared. Canonical history and source controls are retained.'}
        result = index.index(session_id)
        tail = ' Run /home index again for the next batch.' if result['more'] else ' Indexing pass complete.'
        if result['skipped']:
            tail += f" Skipped {result['skipped']} sources exceeding the redacted input budget."
        return {'output': f"Indexed {result['indexed']} sources; inspected {result['scanned']} messages." + tail}
    if verb == 'sources' and not args:
        rows = controls.list()
        return {'output': '\n'.join(f"{r['source_message_id']} · {r['source_session_id']} · {r['action']}"
                                   for r in rows) or 'No Home source controls.'}
    expected = 1 if verb == 'forget' else 2 if verb == 'supersede' else 0
    if not expected or len(args) != expected or any(not arg.isascii() or not arg.isdigit() for arg in args):
        raise ValueError('/home index | sources | forget <message-id> | supersede <old-id> <new-id>')
    if verb == 'forget':
        controls.forget(int(args[0]))
    else:
        controls.supersede(int(args[0]), int(args[1]))
    return {'output': ('Source forgotten from future Home recall.' if verb == 'forget' else
                       'Source superseded for future Home recall.') +
            ' Start a new chat to remove previously loaded context. Raw history, native notes and external stores are separate.'}
