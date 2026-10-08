# Troubleshooting

Start with **`menu.bat`** (live status, recent log) or `scripts\autoresume.ps1 status` / `logs`.
Developer commands below need `PYTHONPATH=src` (set it with `$env:PYTHONPATH='src'` in PowerShell).

## The status says ○ NOT RUNNING
The watcher hasn't written a heartbeat for 5+ minutes: it isn't running, or it's hung.
`scripts\autoresume.ps1 restart` (menu: **R**). If it dies again, read `watcher.log`. Check the
scheduled task exists: `Get-ScheduledTask SpotiFLAC-AutoResume`; if not, re-run `scripts\install.ps1`.
Moved the project folder? Re-run `install.ps1` too (the task stores absolute paths).

## "queue stopped (['paused']) but no new server break in the logs; leaving it alone"
Working as intended: the queue is stopped but SpotiFLAC's logs show no break, so the watcher assumes
you paused it. Resume it yourself (menu **4**), or set `resume_unexplained_pauses = true` to let the
watcher resume any pause.

## After a reboot nothing resumed
1. Did you sign in? The watcher only runs after logon (no auto sign-in = nothing before the password).
2. `status` should say ● ACTIVE within a minute or two of signing in. If ○ NOT RUNNING, run
   `scriptsutoresume.ps1 start` and check the scheduled task.
3. The log should show `SpotiFLAC was (re)started` then `queue was left ['paused'] by the restart:
   resuming in 45 s`. Not there? Check `watch.resume_after_app_restart = true` and `autolaunch.enabled`.

## Downloads aren't progressing but the log says everything is fine
Open the app's **Debug Logs** page (menu **1**, or the app itself) and read the newest lines. The watcher
only acts on the *scheduled break* message. Other failures just fail tracks one by one:
- `Tidal ... 403 {"detail":"Upstream auth error"}`: Tidal's community API is rejecting requests. Nothing to
  wait out; try later, or update SpotiFLAC. Each track can take ~2 min to fail, so a big queue crawls.
- `Amazon API returned status 409` / `track not found`: that source can't serve the track.
Queue stuck at `pending`? The watcher presses **Start** after `pending_start_after_minutes`; if you see
`queue pending for N min ... pressed 'Start'` in the log, that's it working.

## A break happened but nothing resumed
1. `python -m spotiflac_autoresume probe` prints the break messages found on the Debug Logs page and
   the buttons visible on the Queue page.
2. No break events but the app shows one: the message wording may have changed. Adjust
   `watch.break_pattern`.
3. `Doing:` in `status` says "will resume at HH:MM" → it's simply waiting. The wait is the announced
   time + `safety_margin_minutes`.
4. Log says `pressed 'row retry arrow x1'` then `did not start the queue` and
   `falling back to re-adding`: the server was still down, or the retry only covers failed tracks.
   The fallback re-adds the playlist; if the break is still on it will simply stop again, and the
   watcher will read the new message and wait again.
5. `no resume/retry control found; queue page buttons: [...]`: the layout differs from v7.2.2.
   Open an issue with that list and your `watcher.log`.
6. `giving up after N resumes`: raise `max_retries_per_batch`, or the server is down for longer than a
   normal scheduled break.

## After a break the Queue shows "Completed with Issues" and no Resume All
Expected. That's how SpotiFLAC ends a batch at a break (see
[how-it-works](how-it-works.md#what-the-app-does-at-a-break-observed)). The watcher presses the row's
retry arrow instead of Resume All. If you do it by hand, use the arrow, not the red button.

## `sidebar button for 'X' not found` / `web content pane not found`
The app's layout differs from v7.2.2 or the window isn't reachable. Run `python tools\dump_ui.py`
to dump the UI Automation tree and compare. Keep the window in the taskbar (minimized is fine);
a window hidden in the tray may expose no tree.

## Playlist sync
- **Nothing happens:** `sync.enabled = true`, at least one URL under `sync.playlists`, and the watcher
  restarted? Menu **C** shows what's loaded; `status` shows `Sync: ...next in ...`. Sync waits for an
  idle queue and for any pending break wait.
- **Run it now:** menu **5**, or `python -m spotiflac_autoresume sync-now`.
- **Tracks downloaded twice (duplicates):** your filename template contains the playlist position
  (`{track}. {title}`) and a track was inserted mid-playlist or the playlist was re-ordered, so names
  no longer match. Use a title/artist-based template, or only append tracks at the end.
- **Removed tracks stay on disk:** by design, sync is add-only.
- **`fetch did not produce an 'Add to Queue' button`:** the URL is wrong/private, or Spotify metadata
  fetching failed in the app; try the same URL by hand on the Home page.

## Focus flickers
A UI session moves focus to SpotiFLAC and straight back. Sessions only happen when the queue stalls or
a sync is due, never while downloading. Verify with `python tools\focus_check.py`. If Windows blocks
the hand-back (some full-screen games), the app stays minimized but may hold focus until you click
elsewhere.

## Autolaunch opens SpotiFLAC in front
It starts minimized (`SW_SHOWMINNOACTIVE`) and is minimized again if it ignores the hint. If that
fails, set `autolaunch.enabled = false` and launch it yourself.

## Reset
Menu **9** (stop), delete `state.json`, menu **8** (start).
