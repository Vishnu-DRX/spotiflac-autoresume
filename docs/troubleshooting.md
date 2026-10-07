# Troubleshooting

Start with `scripts\autoresume.ps1 status` and `scripts\autoresume.ps1 logs`.

## "queue stopped (['paused']) but no new server break in the logs; leaving it alone"
Working as intended: the queue is paused but SpotiFLAC's logs show no break, so the watcher
assumes you paused it. Resume it yourself (`scripts\autoresume.ps1 resume-now`), or set
`resume_unexplained_pauses = true` to let the watcher resume any pause.

## The break happened but nothing resumed
1. `python -m spotiflac_autoresume probe` (with `PYTHONPATH=src`). It prints the break messages
   found on the Debug Logs page and the buttons visible on the Queue page.
2. No break events but the app shows one: the message wording may have changed. Adjust
   `watch.break_pattern`.
3. Log says `pressed 'Resume All'` then `did not start the queue`: the server was still down, or
   the app finished the item with failed tracks rather than pausing it, and Resume All doesn't
   retry them. Open an issue with `watcher.log` and the queue buttons from `probe`.
4. `giving up after N resumes`: raise `max_retries_per_batch`, or the server is down for longer
   than a normal scheduled break.

## `sidebar button for 'X' not found` / `web content pane not found`
The app's layout differs from v7.2.2 or the window isn't reachable. Run
`python tools\dump_ui.py` (with `PYTHONPATH=src`) to dump the UI Automation tree and compare.
Only fully minimized-to-tray states hide the pane; keep the window in the taskbar.

## Focus flickers
A UI session moves focus to SpotiFLAC and straight back. Sessions only happen when the queue
stalls, not while downloading. Verify with `tools\focus_check.py`. If Windows blocks the focus
hand-back (some full-screen games), the app window stays minimized but may hold focus until
you click elsewhere.

## Autolaunch opens SpotiFLAC in front
It starts minimized (`SW_SHOWMINNOACTIVE`) and is minimized again if it ignores the hint. If
that fails, set `autolaunch.enabled = false` and launch it yourself.

## The task isn't running after reboot
`Get-ScheduledTask SpotiFLAC-AutoResume`. It triggers at logon of the installing user. Re-run
`scripts\install.ps1`. If you moved the project folder, re-run it too (the task stores paths).

## Reset
`scripts\autoresume.ps1 stop`, delete `state.json`, `scripts\autoresume.ps1 start`.
