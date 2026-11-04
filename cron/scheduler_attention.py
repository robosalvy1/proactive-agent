"""Cron run → attention inbox handoff (``cron/attention.py``), called from
``scheduler._save_compose_deliver`` after silence and ownership checks."""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger("cron.scheduler")


def _capture_for(job: dict) -> tuple[Optional[Callable[[str], str]], bool]:
    """The capture step that owns ``job``'s result, or None to deliver directly. Watcher and
    discovery jobs (``cron/attention_watch.py``) are always owned: their output is structured data,
    never a message for the user, so a failed capture drops it rather than delivering raw JSON.
    Returns (capture, is_watch_job)."""
    from cron import attention, attention_policy, attention_watch

    role = attention_watch.job_role(job)
    if role is not None:
        if not attention_policy.load_settings().active:
            return (lambda content: "dropped (attention is off)"), True
        return (lambda content: (
            f"produced {attention_watch.capture_role_result(role, job, content)} inbox entries")), True
    if not attention.routes_cron_job(job):
        return None, False

    def capture_cron(content: str) -> str:
        item = attention.capture_cron_result(job, content)
        return (f"sent to the inbox (route={item['route']})" if item
                else "unchanged since its last capture; not re-sent")
    return capture_cron, False


def route_result_to_inbox(d, fence, deliver_content: str) -> bool:
    """Capture a successful recurring result instead of delivering it, when ``attention.route_cron``
    applies or the job is a watcher. True when the gate owns the result (captured, or unchanged
    since an earlier capture): the caller then skips direct delivery. Capture runs under the
    fire-claim fence like a send; any other failure falls back to normal delivery."""
    from cron.scheduler import _FireClaimLostDuringSideEffect

    watch_job = False
    try:
        capture, watch_job = _capture_for(d.job)
        if capture is None:
            return False
        with fence.side_effect_fence() as owns_capture:
            if not owns_capture:
                raise _FireClaimLostDuringSideEffect
            outcome = capture(deliver_content)
    except _FireClaimLostDuringSideEffect:
        raise
    except Exception:  # a broken inbox must never cost the user a normal job's result
        logger.warning("Job '%s': attention capture failed, %s", d.job["id"],
                       "dropping watcher output" if watch_job else "delivering directly", exc_info=True)
        if not watch_job:
            return False
        d.should_deliver = False
        return True
    d.should_deliver = False
    d.routed_to_inbox = True
    logger.info("Job '%s': result %s", d.job["id"], outcome)
    return True
