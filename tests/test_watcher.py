"""Decision-logic tests: no real app, no clicks, throwaway state."""
import time

import pytest

from spotiflac_autoresume import ui, watcher


def item(status, done=10, failed=0, skipped=0):
    return {"name": "P", "status": status, "total": 100, "done": done, "skipped": skipped, "failed": failed}


@pytest.fixture
def env(monkeypatch):
    cfg = {
        "paths": {"app_exe": "x", "queue_db": "x"},
        "watch": {"poll_seconds": 1, "break_pattern": "scheduled short break", "safety_margin_minutes": 2,
                  "default_wait_minutes": 30, "max_retries_per_batch": 3,
                  "resume_unexplained_pauses": False, "dry_run": True},
        "autolaunch": {"enabled": False, "wait_seconds": 1},
        "notify": {"enabled": False},
    }
    state = {"items": [item("paused")], "events": [], "presses": 0}

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def break_events(self, pattern=None): return list(state["events"])

    monkeypatch.setattr(ui, "Session", FakeSession)
    monkeypatch.setattr(watcher, "load_items", lambda c: state["items"])
    monkeypatch.setattr(watcher, "app_running", lambda: True)
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "do_resume", lambda c, s: state.__setitem__("presses", state["presses"] + 1) or True)
    st = {"break_count": 0, "resume_at": None, "retries": 0, "fp": None, "progress": 0}
    return cfg, state, st


def test_paused_without_break_is_left_alone(env):
    cfg, state, st = env
    watcher.tick(cfg, st)
    assert st["resume_at"] is None and state["presses"] == 0


def test_break_schedules_wait_plus_margin(env):
    cfg, state, st = env
    state["events"] = [("x", 120)]
    watcher.tick(cfg, st)
    assert 121 < (st["resume_at"] - time.time()) / 60 < 123


def test_break_without_number_uses_default(env):
    cfg, state, st = env
    state["events"] = [("x", None)]
    watcher.tick(cfg, st)
    assert 31 < (st["resume_at"] - time.time()) / 60 < 33


def test_resume_pressed_once_wait_elapsed(env):
    cfg, state, st = env
    state["events"] = [("x", 5)]
    watcher.tick(cfg, st)
    st["resume_at"] = time.time() - 1
    watcher.tick(cfg, st)
    assert state["presses"] == 1 and st["retries"] == 1 and st["resume_at"] is None


def test_no_press_before_wait_elapsed(env):
    cfg, state, st = env
    state["events"] = [("x", 5)]
    watcher.tick(cfg, st)
    watcher.tick(cfg, st)
    assert state["presses"] == 0


def test_second_break_reschedules(env):
    cfg, state, st = env
    state["events"] = [("x", 120)]
    watcher.tick(cfg, st)
    st["resume_at"], st["fp"] = None, None
    state["events"].append(("y", 30))
    watcher.tick(cfg, st)
    assert 31 < (st["resume_at"] - time.time()) / 60 < 33


def test_gives_up_after_max_retries(env):
    cfg, state, st = env
    state["events"] = [("x", 1)]
    watcher.tick(cfg, st)
    st["resume_at"], st["retries"] = time.time() - 1, cfg["watch"]["max_retries_per_batch"]
    watcher.tick(cfg, st)
    assert state["presses"] == 0 and st["resume_at"] is None


def test_running_queue_is_never_touched(env):
    cfg, state, st = env
    state["items"] = [item("running")]
    state["events"] = [("x", 5)]
    watcher.tick(cfg, st)
    assert st["resume_at"] is None and state["presses"] == 0


def test_progress_resets_retry_counter(env):
    cfg, state, st = env
    st["retries"], st["progress"] = 4, 10
    state["items"] = [item("running", done=25)]
    watcher.tick(cfg, st)
    assert st["retries"] == 0


def sync_cfg(**kw):
    return {"sync": {"enabled": True, "mode": "interval", "interval_hours": 6,
                     "on_idle_cooldown_minutes": 30, "playlists": ["https://open.spotify.com/playlist/x"], **kw}}


def test_sync_off_by_default_or_without_playlists():
    assert not watcher.sync_due({}, {})
    assert not watcher.sync_due(sync_cfg(enabled=False), {})
    assert not watcher.sync_due(sync_cfg(playlists=[]), {})


def test_sync_interval_mode():
    now = 1_000_000
    assert watcher.sync_due(sync_cfg(), {"last_sync": 0}, now)
    assert not watcher.sync_due(sync_cfg(), {"last_sync": now - 5 * 3600}, now)
    assert watcher.sync_due(sync_cfg(), {"last_sync": now - 6 * 3600}, now)


def test_sync_on_idle_mode_uses_cooldown():
    now = 1_000_000
    cfg = sync_cfg(mode="on_idle")
    assert not watcher.sync_due(cfg, {"last_sync": now - 10 * 60}, now)
    assert watcher.sync_due(cfg, {"last_sync": now - 31 * 60}, now)


def test_idle_queue_triggers_sync_but_pending_break_does_not(env, monkeypatch):
    cfg, state, st = env
    cfg.update(sync_cfg(mode="on_idle"))
    cfg["watch"]["dry_run"] = False
    calls = []
    monkeypatch.setattr(watcher, "readd", lambda urls: calls.append(urls) or ["added"])
    state["items"] = [item("completed")]
    watcher.tick(cfg, st)
    assert len(calls) == 1 and st["last_sync"] > 0
    # a break wait is pending on a stalled item -> no sync, however overdue
    st["last_sync"], st["fp"] = 0, None
    state["items"], state["events"] = [item("partial", failed=2)], [("x", 60)]
    watcher.tick(cfg, st)
    watcher.tick(cfg, st)
    assert len(calls) == 1


def test_partial_item_after_break_is_scheduled_like_a_pause(env):
    """Real behaviour seen live: a break ends the item as 'partial' ('Completed with Issues')."""
    cfg, state, st = env
    state["items"] = [item("partial", done=0, skipped=392, failed=2)]
    state["events"] = [("x", 119)]
    watcher.tick(cfg, st)
    assert 120 < (st["resume_at"] - time.time()) / 60 < 122


def test_resume_unexplained_pauses_when_enabled(env):
    cfg, state, st = env
    cfg["watch"]["resume_unexplained_pauses"] = True
    watcher.tick(cfg, st)
    watcher.tick(cfg, st)
    assert state["presses"] == 1


def test_duration_formatting():
    assert watcher._dur(75) == "1m 15s"
    assert watcher._dur(2 * 3600 + 5 * 60) == "2h 05m"
    assert watcher._dur(-5) == "0m 00s"
