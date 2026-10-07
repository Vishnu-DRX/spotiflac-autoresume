# Changelog

## Unreleased
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
