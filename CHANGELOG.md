# Changelog

## Unreleased
- **Reboot / crash recovery:** the watcher now notices SpotiFLAC was (re)started (PID tracking), resumes the
  queue the relaunch leaves paused, and relaunches the app when `queue.db` still claims activity but the
  process is gone. New keys `resume_after_app_restart`, `restart_settle_seconds`. Tests: 36.
- **Fix (found in the first overnight run):** after a break the retry arrow leaves the item `pending`, and the app
  needs **Start**. The watcher had counted `pending` as "downloading", logged a false "resume took effect" and
  idled for six hours. Now `pending` is verified with a progress watchdog and **Start** is pressed; a frozen
  `running` queue triggers a warning. Regression tests added (30 total).
- Docs: README, how-it-works and troubleshooting brought in line with the post-break behaviour, sync,
  heartbeat status and menu.
- `menu.bat`: interactive text menu (status, pause/resume, resume now, sync now, view/edit config, logs,
  start/stop/restart, uninstall); new `config` and `sync-now` commands.
- `status` now leads with a clear ACTIVE / PAUSED / NOT RUNNING verdict (heartbeat-based), says what the
  watcher is doing and when the next resume or sync is due; new live `watch` view.
- Optional playlist sync (`[sync]`: `interval` or `on_idle` mode); add-only.
- Handles what the app actually does at a break: the item ends as *Completed with Issues*
  (status `partial`) with no Resume All, so the watcher presses the row's retry arrow and,
  failing that, re-adds the playlist. Only the neutral retry button is ever pressed, never remove.
- Verified against a live scheduled break: detected, wait parsed (119 min), resume scheduled.

## 0.1.0 - 2026-10-08
Initial release.
- Watcher that detects SpotiFLAC "scheduled short break" errors and presses Resume All after the
  announced wait (+ safety margin), with retry cap and progress-based reset.
- Read-only bbolt reader for `queue.db`.
- UI Automation layer that works on a minimized window and restores focus afterwards.
- Autolaunch (minimized), tray notifications, `PAUSE` switch, dry-run mode.
- PowerShell install / uninstall / control scripts (per-user scheduled task, no admin).
