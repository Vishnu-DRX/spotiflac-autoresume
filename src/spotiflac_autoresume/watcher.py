"""SpotiFLAC auto-resume watcher.

When SpotiFLAC's queue stalls because a download server announced a scheduled
break ("...Please try again in about N minute(s)"), wait that long and press
Resume in the app. Nothing here talks to the download servers.

    python -m spotiflac_autoresume run          # the loop (what the scheduled task runs)
    python -m spotiflac_autoresume status       # read-only summary
    python -m spotiflac_autoresume watch        # same, live-refreshing
    python -m spotiflac_autoresume probe        # read-only: show break log lines + queue buttons
    python -m spotiflac_autoresume resume-now   # press Resume once, right now
"""
import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

from . import bbolt_read, ui

# Runtime files live in the project root (config.toml, state.json, PAUSE, watcher.log).
HERE = Path(os.environ.get("SPOTIFLAC_AUTORESUME_HOME") or Path(__file__).resolve().parents[2])
CFG_PATH, STATE_PATH, PAUSE_PATH = HERE / "config.toml", HERE / "state.json", HERE / "PAUSE"

PENDING = {"pending", "queued"}          # in the queue but NOT being processed until Start is pressed
ACTIVE = {"running", "downloading", "fetching"} | PENDING
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


def app_pid():
    """PID of the running SpotiFLAC.exe, or None."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SpotiFLAC.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    m = re.search(r'"SpotiFLAC\.exe","(\d+)"', out)
    return int(m.group(1)) if m else None


def app_running():
    return app_pid() is not None


def app_age_seconds(pid):
    """How long ago that process started (None if it can't be determined)."""
    ps = f"[int]((Get-Date)-(Get-Process -Id {int(pid)}).StartTime).TotalSeconds"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, creationflags=0x08000000, timeout=20).stdout.strip()
        return int(out)
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def note_app_restart(cfg, st):
    """Detect that SpotiFLAC was (re)started since the last tick and open a short window in which
    a stalled queue is resumed without needing a break message.

    A relaunched app always comes up with its queue paused and its logs empty, so without this a
    reboot or crash would leave the queue paused until someone pressed Resume.
    """
    pid = app_pid()
    prev = st.get("app_pid", "unset")        # "unset": this state file has never seen the app
    st["app_pid"] = pid
    if pid is None or pid == prev:
        return
    if prev == "unset":
        # no history to compare with: only a *fresh* process counts as a restart, otherwise a
        # pause you set in a long-running app would be overridden when the watcher (re)starts
        age = app_age_seconds(pid)
        if age is None or age > 600:
            return
    if cfg["watch"].get("resume_after_app_restart", True):
        st["restart_until"] = time.time() + 900
        log.info("SpotiFLAC was (re)started: will resume a stalled queue without waiting for a break message")


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


def press_start(cfg, why):
    if cfg["watch"]["dry_run"]:
        log.info("[dry_run] would press Start (%s)", why)
        return False
    with ui.Session() as s:
        pressed = s.click_queue_button("Start")
    log.info("%s: pressed %r", why, pressed)
    return bool(pressed)


def watch_active(cfg, st, items):
    """The queue claims to be active. Trust it only while counters move.

    'pending' means queued but not processing (the app needs Start, e.g. after a relaunch or a
    retry arrow); 'running' with no movement for a long time means something is wedged.
    """
    w = cfg["watch"]
    now = time.time()
    moved = sum(i["done"] + i["skipped"] + i["failed"] for i in items)
    if moved != st.get("moved") or st.get("moved_at") is None:
        st["moved"], st["moved_at"], st["stuck_warned"] = moved, now, False
        return
    idle_min = (now - st["moved_at"]) / 60
    pending = any(i["status"] in PENDING for i in items)
    if pending and idle_min >= w.get("pending_start_after_minutes", 2) and now - st.get("last_start", 0) > 300:
        st["last_start"] = now
        press_start(cfg, f"queue pending for {idle_min:.0f} min with no progress")
    elif not pending and idle_min >= w.get("stuck_minutes", 20) and not st.get("stuck_warned"):
        st["stuck_warned"] = True
        log.warning("queue says 'running' but nothing has moved for %.0f min", idle_min)
        notify(cfg, "SpotiFLAC auto-resume", f"Queue shows running but no progress for {idle_min:.0f} min.")


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
    note_app_restart(cfg, st)

    if any(i["status"] in ACTIVE for i in items):
        if not app_running():
            # queue.db still says active but the app is gone (shutdown, crash): bring it back;
            # the next tick sees the new process and resumes the (then paused) queue
            log.info("queue shows %s but SpotiFLAC is not running", [i["status"] for i in items])
            st["fp"] = None
            ensure_app(cfg)
            return
        st["resume_at"] = None
        st["fp"] = fp
        watch_active(cfg, st, items)
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

    # SpotiFLAC was just (re)started and left the queue paused: that is the restart's doing,
    # not a pause the user chose, so resume after a short settle time (no break message needed).
    if stalled and st.get("restart_until", 0) > time.time() and st.get("resume_at") is None:
        st["restart_until"] = 0
        settle = w.get("restart_settle_seconds", 45)
        st["resume_at"] = time.time() + settle
        st["fp"] = fp
        log.info("queue was left %s by the restart: resuming in %d s", [i["status"] for i in stalled], settle)
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
            running = lambda items: any(i["status"] in ACTIVE - PENDING for i in items)
            if not running(after) and any(i["status"] in PENDING for i in after):
                # the retry arrow / Resume only re-queued the work; the app still needs Start
                press_start(cfg, "resume left the queue pending")
                time.sleep(10)
                after = load_items(cfg)
            ok = running(after)
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
                    time.sleep(10)
                    ok = running(load_items(cfg))
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
        beat()
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
        beat()
        time.sleep(cfg["watch"]["poll_seconds"])


HEARTBEAT_PATH = HERE / "heartbeat"
ALIVE_WITHIN = 300      # a tick can take ~2 min (UI work + 40 s settle wait); 5 min of silence = dead


def beat():
    try:
        HEARTBEAT_PATH.write_text(str(time.time()))
    except OSError:
        pass


def heartbeat_age():
    try:
        return time.time() - float(HEARTBEAT_PATH.read_text())
    except (OSError, ValueError):
        return None


def _dur(sec):
    sec = int(max(sec, 0))
    h, m = sec // 3600, sec % 3600 // 60
    return f"{h}h {m:02d}m" if h else f"{m}m {sec % 60:02d}s"


def render_status(color=True):
    """Human-readable snapshot: a verdict line, what it is doing, the queue, recent log lines."""
    c = (lambda code, t: f"\x1b[{code}m{t}\x1b[0m") if color else (lambda code, t: t)
    cfg, st = load_cfg(), load_state()
    age = heartbeat_age()
    if age is None or age > ALIVE_WITHIN:
        verdict = c(31, "○ NOT RUNNING") + (f"  (no heartbeat for {_dur(age)})" if age else "  (never started)")
        verdict += "\n  start it with: scripts\\autoresume.ps1 start"
    elif PAUSE_PATH.exists():
        verdict = c(33, "◐ PAUSED") + "  watcher is up but taking no action (scripts\\autoresume.ps1 resume)"
    else:
        verdict = c(32, "● ACTIVE") + f"  watching, last check {_dur(age)} ago"

    lines = [verdict, ""]
    try:
        items = load_items(cfg)
    except (OSError, ValueError, KeyError) as e:
        items = []
        lines.append(c(31, f"cannot read queue.db: {e}"))
    now = time.time()
    active = [i for i in items if i["status"] in ACTIVE]
    stalled = [i for i in items if i["status"] not in ACTIVE | FINISHED]
    ra = st.get("resume_at")
    if active:
        doing = f"Downloading {active[0]['name']!r}"
    elif ra:
        doing = (f"Server on a scheduled break: will resume at {time.strftime('%H:%M', time.localtime(ra))} "
                 f"(in {_dur(ra - now)}), attempt {st.get('retries', 0) + 1}/{cfg['watch']['max_retries_per_batch']}")
    elif stalled:
        doing = "Queue stopped with no server break in the logs: leaving it alone"
    else:
        doing = "Idle: nothing to do"
    lines.append("Doing   : " + doing)
    sy = cfg.get("sync", {})
    if sy.get("enabled") and sy.get("playlists"):
        mode = sy.get("mode", "interval")
        wait = (sy.get("interval_hours", 6) * 3600 if mode == "interval"
                else sy.get("on_idle_cooldown_minutes", 30) * 60)
        nxt = st.get("last_sync", 0) + wait - now
        lines.append(f"Sync    : {mode}, {len(sy['playlists'])} playlist(s), "
                     + ("due now (when idle)" if nxt <= 0 else f"next in {_dur(nxt)}"))
    else:
        lines.append("Sync    : off")
    lines.append(f"SpotiFLAC: {'running' if app_running() else 'closed'}"
                 f"   |   breaks seen: {st.get('break_count', 0)}   |   retries: {st.get('retries', 0)}")
    for i in items:
        left = i["total"] - i["done"] - i["skipped"] - i["failed"]
        lines.append(f"Queue   : {i['name']!r} [{i['status']}] {i['done']} done, {i['skipped']} skipped, "
                     f"{i['failed']} failed, {left} to go of {i['total']}")
    try:
        tail = (HERE / "watcher.log").read_text(encoding="utf-8").splitlines()[-4:]
        lines += ["", "Recent  :"] + ["  " + t for t in tail]
    except OSError:
        pass
    return "\n".join(lines)


def status():
    print(render_status(color=sys.stdout.isatty()))


def show_config():
    """Print the settings the watcher is really using, flagging paths that don't exist."""
    cfg = load_cfg()
    print(f"Config file: {CFG_PATH}\n")
    for section, values in cfg.items():
        print(f"[{section}]")
        for key, val in values.items():
            note = ""
            if section == "paths":
                note = "" if Path(val).exists() else "   <-- NOT FOUND"
            if isinstance(val, list):
                print(f"  {key} = " + ("(none)" if not val else ""))
                for v in val:
                    print(f"      - {v}")
                continue
            print(f"  {key} = {val}{note}")
        print()


def watch(every=2):
    """Live view: redraw the status every few seconds until Ctrl+C."""
    try:
        while True:
            print("\x1b[2J\x1b[H" + render_status() + "\n\n" + "(refreshing every "
                  f"{every}s, Ctrl+C to exit)", flush=True)
            time.sleep(every)
    except KeyboardInterrupt:
        pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # legacy consoles are cp1252
    except (AttributeError, ValueError):
        pass                                                         # pythonw has no stdout
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "status":
        status()
    elif cmd == "watch":
        watch()
    elif cmd == "config":
        show_config()
    elif cmd == "probe":
        with ui.Session() as s:
            print("break events:", s.break_events())
            print("queue buttons:", s.queue_buttons())
    elif cmd == "sync-now":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        cfg = load_cfg()
        urls = cfg.get("sync", {}).get("playlists", [])
        if not urls:
            print("No playlists configured: add them under [sync] playlists in config.toml")
        elif any(i["status"] in ACTIVE for i in load_items(cfg)):
            print("Downloads are running: sync only starts when the queue is idle")
        elif ensure_app(cfg):
            readd(urls)
            st = load_state()
            st["last_sync"], st["fp"] = time.time(), None
            save_state(st)
            print("Done. The app skips files it already has; only new tracks download.")
    elif cmd == "resume-now":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        do_resume(load_cfg(), load_state())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
