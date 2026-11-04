"""Home reflection controls, shared by CLI and owner transports."""
from datetime import UTC, datetime

from hermes_state_dreams import DreamStore

USAGE = '/home dream [on | off | now | status | notes | clear]'


def dream_action(db, action, *, principal_id=None):
    store = DreamStore(db, principal_id=principal_id)
    command = action.partition(' ')[2] or 'status'
    if command in {'on', 'off', 'clear'}:
        store.configure(enabled=command == 'on' if command != 'clear' else None, clear=command == 'clear')
        outputs = {
            'on': 'Dreaming is on: quiet gateway idle reviews every six hours at most. Four calls/day including manual runs. No notifications or task execution.',
            'off': 'Dreaming is paused. In-flight results are revoked; existing source-checked notes remain available.',
            'clear': 'Dream notes cleared and in-flight results revoked. Unchanged chats will not regenerate them; new messages may be reviewed.',
        }
        return {'output': outputs[command]}
    if command == 'now':
        from agent.home_dreaming import dream_once
        return {'output': dream_once(db, principal_id=principal_id, manual=True)}
    if command not in {'status', 'notes'}:
        raise ValueError(USAGE)
    status = store.status()
    if command == 'notes':
        from agent.redact import redact_sensitive_text
        lines = ['Dream notes (fallible model candidates; check sources):']
        for note in status['notes']:
            when = datetime.fromtimestamp(note['created_at'], UTC).strftime('%b %d, %H:%M UTC')
            lines.append(f"\n{note['kind']} · {when}: {note['text']}")
            for source in note['sources']:
                profile = db._own_profile_name()
                sid = source['session_id']
                link = f'@session:{profile}/{sid}' if profile else f'@session:{sid}'
                observed = datetime.fromtimestamp(source['timestamp'], UTC).strftime('%b %d %Y, %H:%M UTC')
                lines.append(f"  {link} message {source['id']} · {observed}: {source['quote']}")
        return {'output': redact_sensitive_text('\n'.join(lines), force=True, redact_url_credentials=True)
                if status['notes'] else 'No current dream notes yet.'}
    mode = 'on' if status['enabled'] else 'off'
    running = ('running' if status['enabled'] else 'finishing a cancelled request') if status['running'] else status['last_status'] or 'not run'
    return {'output': f"Dreaming: {mode}; {running}; {len(status['notes'])} current notes. "
            'Limit: four calls per UTC day. Automatic runs need six hours between passes, five quiet minutes and a running gateway; now skips the idle/cadence wait.'}
