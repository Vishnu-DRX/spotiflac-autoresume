# spotiflac-autoresume

Keeps your [SpotiFLAC](https://github.com/spotbye/SpotiFLAC) download queue moving on its own.

SpotiFLAC's free-tier download servers take announced, scheduled breaks, and the app reports
them as an error like:

> `The server is taking a scheduled short break. Please try again in about 120 minute(s).`

Normally you have to notice, wait, and press **Resume** by hand. This small background
watcher does that for you: it detects the break, waits for the time the server itself
announced, then presses **Resume All** in the app. It runs whenever your PC is on and
SpotiFLAC has unfinished queue items.

> **Unofficial.** Not affiliated with or endorsed by SpotiFLAC or any music service. It
> only operates the app's own window on your PC; it never contacts a download server, and it
> waits exactly as long as the service asks. You are responsible for using SpotiFLAC and the
> services behind it in line with their terms and the law where you live.

## How it works (short version)

1. Every 60 s it reads SpotiFLAC's `queue.db` (read-only, no UI touched). While downloads are
   running it does nothing.
2. If the queue stops, it opens the app's **Debug Logs** page and looks for a break message.
   Break found → it schedules a resume for *announced minutes + 2 min safety margin*.
3. When that time arrives it presses **Resume All** on the **Queue** page, then checks that
   the queue actually started. Still on break → it reads the new message and waits again.
4. It never touches a queue you paused yourself (no break message in the logs → hands off).

It drives the app with Windows UI Automation (invoke calls, no simulated mouse), keeps the
window **minimized**, and hands focus straight back to whatever you were using.
Details: [docs/how-it-works.md](docs/how-it-works.md).

## Requirements

- Windows 10/11
- Python 3.11+ on `PATH`
- SpotiFLAC **v7.x** (developed and tested against v7.2.2)

## Install

```powershell
git clone https://github.com/<you>/spotiflac-autoresume.git
cd spotiflac-autoresume
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

`install.ps1` installs `pywinauto` (user scope), creates `config.toml` from
[`config.example.toml`](config.example.toml) if missing, and registers a per-user scheduled
task that starts the watcher at every logon, hidden. No admin rights needed. Safe to re-run.

Then open `config.toml` and check `[paths] app_exe` points at your `SpotiFLAC.exe`
(only needed for autolaunch).

## Everyday use

```powershell
scripts\autoresume.ps1 status       # task, watcher, queue counts, pending resume time
scripts\autoresume.ps1 pause        # watcher stays up but takes no action
scripts\autoresume.ps1 resume       # un-pause the watcher
scripts\autoresume.ps1 logs         # last 40 lines of watcher.log
scripts\autoresume.ps1 resume-now   # press Resume All once, right now
scripts\autoresume.ps1 stop|start|restart
```

**Keep SpotiFLAC open (minimized) during a break.** The watcher needs the app running to
press Resume. If you close it, autolaunch starts it again (minimized) when the queue still has
unfinished items, but a relaunch comes up with the queue *paused*, so keeping the app open is
smoother.

## Configuration

All options live in `config.toml`; restart the watcher after editing
(`scripts\autoresume.ps1 restart`).

| Key | Default | Meaning |
|---|---|---|
| `paths.app_exe` | `~\Downloads\SpotiFLAC.exe` | Used by autolaunch |
| `paths.queue_db` | `~\.spotiflac\queue.db` | SpotiFLAC's queue database |
| `watch.poll_seconds` | `60` | Queue check interval |
| `watch.break_pattern` | `scheduled short break` | Text that identifies a break message |
| `watch.safety_margin_minutes` | `2` | Added to the announced wait |
| `watch.default_wait_minutes` | `30` | Used when a message has no number |
| `watch.max_retries_per_batch` | `6` | Give up after this many resumes with no progress |
| `watch.resume_unexplained_pauses` | `false` | Also resume pauses with no break in the logs |
| `watch.dry_run` | `false` | Log what would be clicked, click nothing |
| `autolaunch.enabled` | `true` | Start SpotiFLAC (minimized) if it is closed and work remains |
| `notify.enabled` | `true` | Tray balloon on resume / give-up |

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1          # remove task, keep folder
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -Purge   # also delete the folder
```

SpotiFLAC, its queue and your music are never touched.

## Known limitations

- **Real-break behaviour is the least-tested part.** The Resume click is verified on a paused
  queue, and the decision logic is covered by tests, but this project's author had not yet
  seen a live "scheduled break" end to end when v0.1.0 was cut. If the app finishes the item
  with failed tracks instead of pausing it, **Resume All** may not retry them; see
  [docs/troubleshooting.md](docs/troubleshooting.md) and please open an issue with your
  `watcher.log`.
- Depends on SpotiFLAC's UI layout (sidebar order, button names such as *Resume All*). A big
  redesign can break it; `python -m spotiflac_autoresume probe` shows what it can see.
- A resume briefly flips Windows focus to the app and back (well under a second). If you are
  typing at that exact moment a keystroke can land in the wrong window.
- Windows only.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest
set PYTHONPATH=src && python tools\focus_check.py   # verifies no focus theft (needs the app minimized)
```

Layout: `src/spotiflac_autoresume/` (`watcher.py` loop and decisions, `ui.py` UI Automation,
`bbolt_read.py` queue-database reader), `scripts/` (PowerShell install/control), `tests/`,
`docs/`, `tools/` (dev helpers).

## License

[MIT](LICENSE)
