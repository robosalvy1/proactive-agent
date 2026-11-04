"""One bounded reflection pass; no tools, notifications, task execution or transcript mutation."""
import logging
import time

from hermes_state_dreams import DreamStore
from hermes_state_dream_sources import parse_notes

logger = logging.getLogger(__name__)


def dream_once(db, *, principal_id=None, manual=False, cancelled=lambda: False, model=None, now=None):
    store = DreamStore(db, principal_id=principal_id)
    if cancelled():
        return 'Dreaming was cancelled.'
    batch = store.reserve(now=now, manual=manual)
    if batch is None:
        return 'No dream started: paused, busy, unchanged, or waiting for the idle/call budget.'
    try:
        from agent.home_dream_model import reflect

        if cancelled():
            store.finish(batch, [], cancelled=True)
            return 'Dreaming was cancelled.'
        notes = parse_notes((model or reflect)(batch['sources']), batch, time.time() if now is None else now)
        saved = store.finish(batch, notes, cancelled=cancelled())
        return (f'Dream finished: {len(notes)} source-linked candidate notes. /home dream notes to inspect.'
                if saved else 'Dream discarded: its sources or settings changed during reflection.')
    except Exception as exc:  # health: allow BLE001 -- provider errors can contain private transcripts/credentials; this fail-open auxiliary boundary logs only the error class
        # Provider failures may contain secrets or copied source text; persist a bounded
        # status only, and leave chat usable without a reflection result.
        logger.warning('Home reflection failed (%s)', type(exc).__name__)
        store.finish(batch, [], error=True)
        return 'Dreaming failed; no new notes saved. Check the auxiliary model configuration, then use /home dream now (daily limit still applies).'
