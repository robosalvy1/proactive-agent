"""Bounded, revocable transcript snapshots for Home reflection."""
import hashlib
import json

from hermes_state_home import HomeStore

MAX_MESSAGES = 24
MAX_INPUT_CHARS = 16000


def snapshots_on(store: HomeStore, conn, state: dict, *, anchors=None) -> dict:
    """Fingerprint recent evidence, including message edits, rewinds and new corrections."""
    grouped = {}
    for meta in store._eligible_on(conn, state):
        anchor = meta['home_anchor']
        if anchors is not None and anchor not in anchors:
            continue
        rows = conn.execute(
            "SELECT id,session_id,message_uid,role,timestamp,substr(content,1,1600) AS text FROM messages "
            "WHERE session_id=? AND role IN ('user','assistant') AND (active=1 OR compacted=1) "
            "AND _compressed_summary=0 AND COALESCE(display_kind,'')='' ORDER BY id DESC LIMIT ?",
            (meta['id'], MAX_MESSAGES),
        ).fetchall()
        bucket = grouped.setdefault(anchor, {'anchor': anchor, 'title': meta['title'] or 'Untitled', 'rows': []})
        bucket['rows'].extend(dict(row) for row in rows)
    for bucket in grouped.values():
        # Compression copies keep message_uid; one copy is enough for reflection.
        seen, rows = set(), []
        for row in sorted(bucket['rows'], key=lambda row: row['id'], reverse=True):
            uid = row['message_uid'] or row['id']
            if uid not in seen:
                seen.add(uid)
                rows.append(row)
        bucket['rows'] = list(reversed(rows[:MAX_MESSAGES]))
        bucket['signature'] = hashlib.sha256(json.dumps(bucket['rows'], sort_keys=True).encode()).hexdigest()
    return {key: bucket for key, bucket in grouped.items() if bucket['rows']}


def make_batch(snapshots: dict, seen: dict) -> dict:
    """Oldest unprocessed chat first; send complete JSON of bounded recent evidence."""
    from agent.redact import redact_sensitive_text

    sources, used = [], 2
    pending = [s for key, s in snapshots.items() if seen.get(key) != s['signature']]
    if not pending:
        return {'sources': [], 'signatures': {}}
    # A previously reviewed chat can supply the other half of a useful connection.
    unchanged = [s for key, s in snapshots.items() if seen.get(key) == s['signature']]
    ordered = sorted(pending, key=lambda s: s['rows'][-1]['id']) + sorted(
        unchanged, key=lambda s: s['rows'][-1]['id'], reverse=True)
    for snapshot in ordered:
        messages = [{**row, 'text': redact_sensitive_text(row['text'] or '', force=True,
                                                        redact_url_credentials=True)} for row in snapshot['rows']]
        source = {'anchor': snapshot['anchor'], 'title': redact_sensitive_text(snapshot['title'][:100], force=True),
                  'messages': messages}
        size = len(json.dumps(source, ensure_ascii=True))
        if size > MAX_INPUT_CHARS:
            # Keep the newest complete rows of a long chat, not a partial source blob.
            while len(messages) > 1 and size > MAX_INPUT_CHARS:
                messages.pop(0)
                size = len(json.dumps(source, ensure_ascii=True))
        if used + size + 2 > MAX_INPUT_CHARS:
            continue
        sources.append(source)
        used += size + 2
        if len(sources) == 3:
            break
    return {'sources': sources, 'signatures': {s['anchor']: snapshots[s['anchor']]['signature'] for s in sources}}


def valid_notes(notes: list, snapshots: dict) -> list:
    return [note for note in notes if all(
        anchor in snapshots and snapshots[anchor]['signature'] == signature
        for anchor, signature in note['signatures'].items())]


def parse_notes(text: str, batch: dict, now: float) -> list:
    """Model summaries remain candidates; every citation must quote a real supplied message."""
    if len(text) > 14000:
        raise ValueError('reflection output too large')
    output = json.loads(text)
    if not isinstance(output, dict) or set(output) != {'notes'} or not isinstance(output['notes'], list):
        raise ValueError('expected notes JSON')
    if len(output['notes']) > 6:
        raise ValueError('too many notes')
    messages = {row['id']: (source, row) for source in batch['sources'] for row in source['messages']}
    notes = []
    for candidate in output['notes']:
        if (not isinstance(candidate, dict) or set(candidate) != {'kind', 'text', 'sources'}
                or candidate['kind'] not in {'decision', 'preference', 'open_item', 'connection'}
                or not isinstance(candidate['text'], str) or not 1 <= len(candidate['text']) <= 500
                or not isinstance(candidate['sources'], list) or not 1 <= len(candidate['sources']) <= 4):
            raise ValueError('invalid reflection note')
        refs, signatures = [], {}
        for citation in candidate['sources']:
            if not isinstance(citation, dict) or set(citation) != {'id', 'quote'} or type(citation['id']) is not int:
                raise ValueError('invalid citation')
            source, row = messages.get(citation['id'], (None, None))
            quote = citation['quote']
            if row is None or not isinstance(quote, str) or not 1 <= len(quote) <= 300 or quote not in row['text']:
                raise ValueError('citation does not match supplied evidence')
            # Decisions/preferences/open work must be grounded in user statements.
            if candidate['kind'] != 'connection' and row['role'] != 'user':
                raise ValueError('user evidence required')
            signatures[source['anchor']] = batch['signatures'][source['anchor']]
            refs.append({'id': row['id'], 'session_id': row['session_id'], 'role': row['role'],
                         'timestamp': row['timestamp'], 'quote': quote})
        if candidate['kind'] == 'connection' and (len(signatures) < 2 or not any(r['role'] == 'user' for r in refs)):
            raise ValueError('connections need evidence from separate chats')
        notes.append({'kind': candidate['kind'], 'text': candidate['text'], 'sources': refs,
                      'signatures': signatures, 'created_at': now})
    return notes
