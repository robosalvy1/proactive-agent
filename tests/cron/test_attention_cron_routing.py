"""Cron ↔ attention: recurring results go to the inbox instead of direct delivery when
``attention.route_cron`` is on; everything else keeps the existing delivery contract."""

from __future__ import annotations

import pytest

from cron import attention, attention_store, delivery_queue, executions, jobs, scheduler


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def enable(home, **extra):
    lines = "".join(f"  {key}: {value}\n" for key, value in extra.items())
    (home / "config.yaml").write_text(f"attention:\n  enabled: true\n  level: balanced\n{lines}")


def run(monkeypatch, job, response="the result", success=True):
    monkeypatch.setattr(scheduler, "run_job",
                        lambda job, **kw: (success, "raw", response, None if success else "boom"))
    scheduler.run_one_job(job)
    return executions.latest_execution(job["id"])


def items():
    if not attention_store.current_attention_file().exists():
        return []
    with attention_store.transaction() as conn:
        return attention_store.select_items(conn)


def test_recurring_result_goes_to_inbox_not_delivery(home, monkeypatch):
    enable(home)
    job = jobs.create_job(prompt="p", schedule="every 1h", deliver="telegram:fixture", name="News")
    execution = run(monkeypatch, job, "Headlines: a, b")
    assert delivery_queue.get_status(execution["id"]) is None
    assert execution["delivery_outcome"] == "inbox"
    assert jobs.get_job(job["id"])["last_status"] == "ok"
    [item] = items()
    assert (item["source"], item["kind"], item["deliver"]) == ("cron", "inform", "telegram:fixture")
    assert item["title"] == "News: Headlines: a, b" and item["category"] == "cron:News"


def test_unchanged_result_is_not_captured_twice(home, monkeypatch):
    enable(home)
    job = jobs.create_job(prompt="p", schedule="every 1h", deliver="telegram:fixture")
    run(monkeypatch, job, "same")
    second = run(monkeypatch, jobs.get_job(job["id"]), "same")
    assert len(items()) == 1 and second["delivery_outcome"] == "inbox"


def test_alert_marker_makes_an_alert(home, monkeypatch):
    enable(home)
    job = jobs.create_job(prompt="p", schedule="every 1h", deliver="telegram:fixture")
    run(monkeypatch, job, "[ALERT] Card charged twice\nCheck the bank app.")
    [item] = items()
    assert item["kind"] == "alert" and item["route"] == "now"
    assert item["body"].startswith("Card charged twice")


@pytest.mark.parametrize("schedule,response,success", [
    ("every 1h", "[SILENT]", True),            # silence stays silence
    ("every 1h", "result", False),             # failures keep their own alert path
    ("2099-01-01T09:00:00Z", "result", True),  # one-shot reminders deliver as timed
])
def test_not_routed(home, monkeypatch, schedule, response, success):
    enable(home)
    job = jobs.create_job(prompt="p", schedule=schedule, deliver="telegram:fixture")
    execution = run(monkeypatch, job, response, success)
    assert items() == []
    assert execution["delivery_outcome"] != "inbox"


def test_disabled_layer_keeps_direct_delivery(home, monkeypatch):
    job = jobs.create_job(prompt="p", schedule="every 1h", deliver="telegram:fixture")
    execution = run(monkeypatch, job, "the result")
    assert delivery_queue.get_status(execution["id"]) is not None
    assert not attention_store.current_attention_file().exists()


def test_route_cron_off_keeps_direct_delivery(home, monkeypatch):
    enable(home, route_cron="false")
    job = jobs.create_job(prompt="p", schedule="every 1h", deliver="telegram:fixture")
    execution = run(monkeypatch, job)
    assert delivery_queue.get_status(execution["id"]) is not None and items() == []


def test_alert_guidance_only_in_routed_prompts(home):
    from cron.scheduler_prompt import _build_job_prompt

    job = jobs.create_job(prompt="Check the bank", schedule="every 1h", deliver="telegram:fixture")
    plain = _build_job_prompt(job)
    enable(home)
    routed = _build_job_prompt(job)
    assert "[ALERT]" not in plain and "[ALERT]" in routed
    assert routed.replace(f"[{attention.CRON_ATTENTION_GUIDANCE}]\n\n", "") == plain


def test_idle_tick_flushes_due_alerts(home, monkeypatch):
    from cron import attention_flush
    from cron.scheduler_tick import tick

    enable(home, quiet_hours="''")  # wall-clock test: no quiet hours
    sent = []
    monkeypatch.setattr(attention_flush, "send_via_cron_delivery",
                        lambda deliver, origin, text, adapters, loop: sent.append((deliver, text)))
    attention.capture(kind="alert", title="Flight delayed", body="New departure 14:10", source="test",
                      category="test", urgency=9, dedup_key="flight", deliver="telegram")
    assert tick(verbose=False) == 0  # no cron jobs due
    assert sent == [("telegram", sent[0][1])] and sent[0][1].startswith("Flight delayed")


def test_attention_flush_runs_after_the_tick_lock_is_released(home, monkeypatch):
    """Slow attention deliveries must not hold the tick lock that due-job dispatch needs; a second
    flusher in the meantime is skipped by the attention lock instead."""
    from cron import attention_flush
    from cron.scheduler_tick import tick

    enable(home, quiet_hours="''")
    lock_dir, tick_lock = scheduler._get_lock_paths()
    observed = []

    def fake_flush(adapters=None, loop=None):
        tick_fd = scheduler._acquire_tick_lock(tick_lock)
        observed.append(tick_fd is not None)
        if tick_fd is not None:
            scheduler._release_tick_lock(tick_fd)
        observed.append(scheduler._acquire_tick_lock(lock_dir / ".attention.lock") is None)

    monkeypatch.setattr(attention_flush, "flush", fake_flush)
    tick(verbose=False)
    assert observed == [True, True]  # tick lock free; attention lock held by this flush
