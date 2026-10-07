"""SpotiFLAC auto-resume watcher.

When SpotiFLAC's queue stalls because a download server announced a scheduled
break ("...Please try again in about N minute(s)"), wait that long and press
Resume in the app. Nothing here talks to the download servers.

    python -m spotiflac_autoresume run          # the loop (what the scheduled task runs)
    python -m spotiflac_autoresume status       # read-only summary
    python -m spotiflac_autoresume probe        # read-only: show break log lines + queue buttons
    python -m spotiflac_autoresume resume-now   # press Resume once, right now
"""
import json
import logging
import logging.handlers
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

import os

from . import bbolt_read, ui

# Runtime files live in the project root (config.toml, state.json, PAUSE, watcher.log).
HERE = Path(os.environ.get("SPOTIFLAC_AUTORESUME_HOME") or Path(__file__).resolve().parents[2])
CFG_PATH, STATE_PATH, PAUSE_PATH = HERE / "config.toml", HERE / "state.json", HERE / "PAUSE"

ACTIVE = {"running", "queued", "pending", "downloading", "fetching"}
FINISHED = {"completed", "complete", "done", "finished", "cancelled", "canceled"}

log = logging.getLogger("autoresume")


def load_cfg():
    with open(CFG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    for key in ("app_exe", "queue_db"):   # allow ~ and %VARS% in paths
        cfg["paths"][key] = os.path.expandvars(os.path.expanduser(cfg["paths"][key]))
    return cfg


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {"break_count": 0, "resume_at": None, "retries": 0, "fp": None, "progress": 0}


def save_state(st):
    STATE_PATH.write_text(json.dumps(st))


def load_items(cfg):
    raw = bbolt_read.read_bucket(cfg["paths"]["queue_db"], "DownloadQueueItems")
    items = []
    for v in raw.values():
        d = json.loads(v)
        res = Counter(d.get("trackResults", {}).values())
        items.append({"name": d.get("name"), "status": d.get("status", ""), "total": d.get("trackCount", 0),
                      "done": res.get("done", 0), "skipped": res.get("skipped", 0),
                      "failed": res.get("failed", 0)})
    return items


def fingerprint(items):
    return json.dumps([(i["name"], i["status"], i["done"], i["skipped"], i["failed"]) for i in items])


def app_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SpotiFLAC.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "SpotiFLAC.exe" in out


def notify(cfg, title, text):
    if not cfg["notify"]["enabled"]:
        return
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;"
          f"$n.Visible=$true;$n.ShowBalloonTip(8000,'{title}','{text}','Info');Start-Sleep 9;$n.Dispose()")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                     creationflags=0x08000000)


def ensure_app(cfg):
    if app_running():
        return True
    if not cfg["autolaunch"]["enabled"]:
        log.info("SpotiFLAC is closed and autolaunch is off")
        return False
    log.info("SpotiFLAC closed with unfinished queue items: launching it minimized")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7                      # SW_SHOWMINNOACTIVE: minimized, no focus
    subprocess.Popen([cfg["paths"]["app_exe"]], cwd=str(Path(cfg["paths"]["app_exe"]).parent),
                     startupinfo=si)
    deadline = time.time() + cfg["autolaunch"]["wait_seconds"]
    while time.time() < deadline:
        time.sleep(3)
        try:
            with ui.Session() as s:
                if s.win.get_show_state() != 2:   # the app may ignore the hint
                    s.win.minimize()
                return True
        except ui.UiError:
            continue
    log.warning("launched SpotiFLAC but its window never became readable")
    return False


def do_resume(cfg, st):
    if cfg["watch"]["dry_run"]:
        log.info("[dry_run] would press Resume All")
        return True
    with ui.Session() as s:
        clicked = s.click_queue_button("Resume All", "Retry All", "Resume", "Retry")
        if not clicked:
            # a break ends the item as "Completed with Issues": no Resume All, only the row's retry arrow
            n = s.click_row_retry()
            if n:
                clicked = f"row retry arrow x{n}"
        if not clicked:
            log.warning("no resume/retry control found; queue page buttons: %s", s.queue_buttons())
            return False
    log.info("pressed %r", clicked)
    return True


def recent_url(name):
    """URL SpotiFLAC remembers for a fetched item name (its recent_fetches.json)."""
    path = Path(os.path.expanduser("~/.spotiflac/recent_fetches.json"))
    try:
        for r in json.loads(path.read_text(encoding="utf-8")):
            if r.get("name") == name and r.get("url"):
                return r["url"]
    except (OSError, ValueError):
        pass
    return None


def readd(urls):
    """Fetch each URL again and add it to the queue (existing files are skipped by the app)."""
    done = []
    for url in urls:
        with ui.Session() as s:
            res = s.add_to_queue(url)
            if res == "already":
                if not s.clear_queue():
                    log.warning("could not clear the finished queue item for %s", url)
                    continue
                res = s.add_to_queue(url)
        log.info("re-add %s -> %s", url, res)
        done.append(res)
    return done


def sync_due(cfg, st, now=None):
    sy = cfg.get("sync", {})
    if not sy.get("enabled") or not sy.get("playlists"):
        return False
    now = now or time.time()
    wait = (sy.get("interval_hours", 6) * 3600 if sy.get("mode", "interval") == "interval"
            else sy.get("on_idle_cooldown_minutes", 30) * 60)
    return now - st.get("last_sync", 0) >= wait


def maybe_sync(cfg, st):
    """Re-add the configured playlists when due. Callers guarantee no download is running
    and no break wait is pending."""
    if cfg["watch"]["dry_run"] or not sync_due(cfg, st):
        return
    st["last_sync"] = time.time()           # set first: a failure must not retry every tick
    if not ensure_app(cfg):
        return
    log.info("playlist sync: %d playlist(s)", len(cfg["sync"]["playlists"]))
    readd(cfg["sync"]["playlists"])
    st["fp"] = None                          # new queue state -> re-read the logs if it stops


def tick(cfg, st):
    w = cfg["watch"]
    items = load_items(cfg)
    if not items:
        return
    fp = fingerprint(items)
    progress = sum(i["done"] + i["skipped"] for i in items)
    if progress > st.get("progress", 0):
        st["retries"] = 0
    st["progress"] = progress

    if any(i["status"] in ACTIVE for i in items):
        st["resume_at"] = None
        st["fp"] = fp
        return

    stalled = [i for i in items if i["status"] not in FINISHED]
    failed_done = [i for i in items if i["status"] in FINISHED and i["failed"] > 0]
    unknown = {i["status"] for i in stalled} - {"paused", "failed", "error", "partial"}
    if unknown:
        log.info("unrecognised item status values: %s", sorted(unknown))
    if not stalled and not failed_done:
        st["resume_at"] = None
        st["retries"] = 0
        st["fp"] = fp
        maybe_sync(cfg, st)
        return

    # Queue changed since last look (or a resume is pending): decide why it stopped.
    if fp != st.get("fp") and st.get("resume_at") is None:
        if stalled and not ensure_app(cfg):
            return
        if not app_running():
            return
        with ui.Session() as s:
            events = s.break_events(w["break_pattern"])
        n = len(events)
        if n < st["break_count"]:
            st["break_count"] = n           # logs were cleared / app restarted
        if n > st["break_count"]:
            mins = events[-1][1] or w["default_wait_minutes"]
            st["break_count"] = n
            st["resume_at"] = time.time() + (mins + w["safety_margin_minutes"]) * 60
            log.info("server break announced (%s min); will resume at %s", mins,
                     time.strftime("%H:%M", time.localtime(st["resume_at"])))
        elif stalled and w["resume_unexplained_pauses"]:
            st["resume_at"] = time.time()
        else:
            log.info("queue stopped (%s) but no new server break in the logs; leaving it alone",
                     [i["status"] for i in items])
        st["fp"] = fp
        return

    if st.get("resume_at") and time.time() >= st["resume_at"]:
        if st["retries"] >= w["max_retries_per_batch"]:
            log.warning("giving up after %d resumes without progress", st["retries"])
            notify(cfg, "SpotiFLAC auto-resume", "Gave up: server still failing after repeated resumes.")
            st["resume_at"] = None
            return
        if not ensure_app(cfg):
            return
        st["retries"] += 1
        st["resume_at"] = None
        if do_resume(cfg, st):
            time.sleep(40)
            after = load_items(cfg)
            ok = any(i["status"] in ACTIVE for i in after)
            log.info("resume %s (attempt %d)", "took effect" if ok else "did not start the queue",
                     st["retries"])
            if ok:
                notify(cfg, "SpotiFLAC auto-resume", "Server break over: downloads resumed.")
            if not ok:
                # Retry/Resume did nothing: fetch the playlist(s) again; the app skips files it
                # already has, and a still-active break just stops the batch at the first real download.
                urls = {recent_url(i["name"]) for i in after if i["status"] not in FINISHED} - {None}
                if urls:
                    log.info("falling back to re-adding %d playlist(s)", len(urls))
                    readd(sorted(urls))
                    ok = any(i["status"] in ACTIVE for i in load_items(cfg))
            # not started -> forget the fingerprint so the next tick re-reads the logs for a new break
            st["fp"] = fingerprint(load_items(cfg)) if ok else None
        return

    if st.get("resume_at") is None:
        maybe_sync(cfg, st)


def run():
    handler = logging.handlers.RotatingFileHandler(HERE / "watcher.log", maxBytes=512_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    log.info("watcher started")
    paused_logged = False
    while True:
        cfg = load_cfg()
        try:
            if PAUSE_PATH.exists():
                if not paused_logged:
                    log.info("PAUSE file present: idle")
                    paused_logged = True
            else:
                paused_logged = False
                st = load_state()
                tick(cfg, st)
                save_state(st)
        except (ui.UiError, OSError, ValueError, KeyError) as e:
            log.warning("tick failed: %s: %s", type(e).__name__, e)
        except Exception:
            log.exception("unexpected error")
        time.sleep(cfg["watch"]["poll_seconds"])


def status():
    cfg, st = load_cfg(), load_state()
    print("watcher paused (PAUSE file):", PAUSE_PATH.exists())
    print("SpotiFLAC running:", app_running())
    for i in load_items(cfg):
        print(f"queue item {i['name']!r}: status={i['status']} total={i['total']} "
              f"done={i['done']} skipped={i['skipped']} failed={i['failed']} "
              f"untouched={i['total'] - i['done'] - i['skipped'] - i['failed']}")
    ra = st.get("resume_at")
    print("pending resume at:", time.strftime("%H:%M:%S", time.localtime(ra)) if ra else "none",
          "| retries:", st.get("retries"), "| breaks seen:", st.get("break_count"))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "status":
        status()
    elif cmd == "probe":
        with ui.Session() as s:
            print("break events:", s.break_events())
            print("queue buttons:", s.queue_buttons())
    elif cmd == "resume-now":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        do_resume(load_cfg(), load_state())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
