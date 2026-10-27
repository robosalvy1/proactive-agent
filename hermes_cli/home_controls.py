"""Local Home indexing and explicit source controls, shared by frontend transports."""
from __future__ import annotations

import time


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
    if verb == 'index' and args in ([], ['clear'], ['status']):
        from hermes_state_home_semantic import HomeIndex
        index = HomeIndex(db, principal_id=principal_id)
        if args == ['status']:
            return {'output': _index_status(index.status(session_id))}
        if args:
            index.clear(session_id)
            return {'output': 'Home semantic index cleared. Canonical history and source controls are retained.'}
        result = index.drain(session_id)
        if result['capacity_reached']:
            tail = ' The index is full and keeps the newest sources; older history stays keyword-searchable.'
        elif result['more']:
            tail = (f" About {result['remaining']} older messages remain; indexing continues after each turn"
                    ' (or run /home index again).')
        else:
            tail = ' Indexing is up to date.'
        if result['evicted']:
            tail += f" Replaced {result['evicted']} oldest sources with newer ones."
        if result['skipped']:
            tail += f" Skipped {result['skipped']} sources exceeding the redacted input budget."
        return {'output': f"Indexed {result['indexed']} sources; inspected {result['scanned']} messages." + tail}
    if verb == 'sources' and not args:
        rows = controls.list()
        return {'output': '\n'.join(f"{r['source_message_id']} · {r['source_session_id']} · {r['action']}"
                                   for r in rows) or 'No Home source controls.'}
    expected = 1 if verb == 'forget' else 2 if verb == 'supersede' else 0
    if not expected or len(args) != expected or any(not arg.isascii() or not arg.isdigit() for arg in args):
        raise ValueError('/home index [status|clear] | sources | forget <message-id> | supersede <old-id> <new-id>')
    if verb == 'forget':
        controls.forget(int(args[0]))
    else:
        controls.supersede(int(args[0]), int(args[1]))
    return _control_result(verb)


def _index_status(status):
    if status is None:
        return 'Semantic recall is off; keyword recall is active. Set memory.home_recall to enable it.'
    lines = [f"Semantic index ({status['model']}): {status['vectors']}/{status['capacity']} sources; "
             + ('full; the newest sources are kept and older history stays keyword-searchable.' if status['paused']
                else f"about {status['remaining']} older messages not yet indexed." if status['remaining']
                else 'backfill complete.'),
             'Automatic indexing after each turn is ' + ('on.' if status['auto_index'] else
                                                         'off (set memory.home_recall.auto_index: true to opt in).')]
    health = status['health']
    if health.get('failures'):
        wait = max(0, round(health['retry_at'] - time.time()))
        lines.append(f"Endpoint failing ({health['last_error']}, {health['failures']} in a row); "
                     f"keyword recall only, retrying in {wait}s or on /home index.")
    elif health.get('last_ok'):
        lines.append(f"Endpoint healthy; last success {round(time.time() - health['last_ok'])}s ago.")
    return '\n'.join(lines)


def _control_result(verb):
    return {'output': ('Source forgotten from future Home recall.' if verb == 'forget' else
                       'Source superseded for future Home recall.') +
            ' Start a new chat to remove previously loaded context. Raw history, native notes and external stores are separate.'}
