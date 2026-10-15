"""Idle reflection rides existing owner housekeeping and tracked shutdown/drain work."""
import asyncio
from functools import partial
import time


def home_dream_chore(runner, loop, stop_event):
    """Build a profile-scoped chore; enqueue at most one pass per owning authority."""
    def tick():
        from gateway.session_authorities import active_authority
        from hermes_state_dreams import DreamStore

        authority = active_authority(runner)
        if authority is None or loop is None or stop_event.is_set():
            return
        with authority.db._read_ctx() as conn:
            state = DreamStore.load_on(conn)
        if not state['enabled'] or state.get('next_at', 0) > time.time():
            return

        def start():
            from agent.home_dreaming import dream_once
            from gateway.session_runtime_workers import executing_sessions, mutation_tasks, track_mutation

            def cancelled():
                return (stop_event.is_set() or getattr(runner, '_draining', False)
                        or getattr(authority, 'retiring', False))

            task = getattr(authority, '_home_dream_task', None)
            if cancelled() or (task is not None and not task.done()) or mutation_tasks(authority):
                return
            if list(executing_sessions(authority)) or any(
                    not worker.closed.is_set() for worker in getattr(authority, '_managed_workers', {}).values()):
                return
            operation = partial(dream_once, authority.db, principal_id=state.get('principal_id'), cancelled=cancelled)
            authority._home_dream_task = track_mutation(authority, asyncio.to_thread(operation))
        # call_soon_threadsafe preserves the chore's owning profile/secret context.
        loop.call_soon_threadsafe(start)
    return tick
