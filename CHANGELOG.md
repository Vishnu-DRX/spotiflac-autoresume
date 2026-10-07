# Changelog

## 0.1.0 - 2026-10-08
Initial release.
- Watcher that detects SpotiFLAC "scheduled short break" errors and presses Resume All after the
  announced wait (+ safety margin), with retry cap and progress-based reset.
- Read-only bbolt reader for `queue.db`.
- UI Automation layer that works on a minimized window and restores focus afterwards.
- Autolaunch (minimized), tray notifications, `PAUSE` switch, dry-run mode.
- PowerShell install / uninstall / control scripts (per-user scheduled task, no admin).
