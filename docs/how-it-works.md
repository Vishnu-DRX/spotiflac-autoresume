# How it works

## Why UI automation

SpotiFLAC v7.2.2 is a Wails (Go + WebView2) desktop app. It has no CLI, headless mode or local
API (the README and changelog mention none), so the only way to press its buttons is through its
window.

Two other routes were tried and rejected:

- **WebView2 remote debugging port** (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`). Wails sets its
  own WebView2 arguments and the environment variable had no effect. A registry policy could
  force it, but that means changing system-level browser settings and exposing a debug port.
- **Raw mouse clicks.** Fragile and intrusive.

Windows **UI Automation** (via [pywinauto](https://pywinauto.readthedocs.io/)) works because
WebView2 publishes its DOM as an accessibility tree: buttons and text have names such as
`Resume All` or `Debug Logs`. Actions use UIA *invoke*, so the mouse never moves.

## Components

```
watcher.py     loop, decisions, sync, status/watch/config rendering (the only module with policy)
ui.py          UI Automation: navigation, reading logs, pressing buttons, focus handling
bbolt_read.py  read-only reader for SpotiFLAC's queue.db
scripts/       install / uninstall / autoresume / menu (PowerShell);  menu.bat = double-click entry
```

### Reading the queue (`bbolt_read.py`)

`~/.spotiflac/queue.db` is a [bbolt](https://github.com/etcd-io/bbolt) B+tree (Go), not SQLite.
The app keeps it open, but reading is allowed. bbolt is copy-on-write, so scanning the file for
JSON returns stale copies; the reader instead picks the meta page with the highest transaction
id and walks the tree from its root. The `DownloadQueueItems` bucket holds one JSON document per
queue item:

```json
{"name": "Vault_drx", "status": "partial", "trackCount": 777,
 "trackResults": {"<spotify id>": "done|skipped|failed", "...": "..."}}
```

Item `status` values seen so far: `pending`, `running`, `paused`, `partial`. **`pending` means queued but not
being processed**: after a retry arrow or an app relaunch the app waits for **Start**. Treating `pending` as
"downloading" cost the first overnight run six hours (see below). Per-track results are
`done`, `skipped` (file already exists) and `failed`; tracks the app never reached have no entry.
The *error text* is **not** stored in the database, which is why the logs page is consulted.

### Driving the app (`ui.py`)

- Page content is located relative to the web pane's own origin. A minimized window reports
  coordinates around `-32000`, so absolute positions would break.
- Sidebar buttons are identified by their vertical *slot* (first icon 56 px below the pane top,
  one every 48 px), because the Queue button carries a count badge as its accessible name and
  the button of the page you are on is not a plain unnamed button either.
- The last sidebar icon opens a GitHub-issues dialog and is never clicked.
- Every UI session remembers the page you were on and returns to it, keeps a minimized window
  minimized, and gives keyboard focus back to the window you were using. (Invoking a WebView2
  control makes it grab focus; the hand-back uses the standard Alt-tap + `SetForegroundWindow`,
  and `tools/focus_check.py` verifies it.)

## What the app does at a break (observed)

On a real scheduled break the app does **not** pause the queue. It tries the first track that
needs a real download, gets

> `...The server is taking a scheduled short break. Please try again in about 120 minute(s).`

and ends the item as **"Completed with Issues"** (`status: partial`): tracks already on disk are
`skipped`, the failed ones are `failed`, and everything it never reached stays untouched. The
Queue page then shows no *Resume All*, only a **Start** button in the header and two icon buttons
in the row's ACTIONS column: a neutral **retry arrow** and a red **remove** button (class
`text-destructive`). The watcher presses only the neutral one.

When you pause a queue yourself the item is `paused` and the header shows **Resume All**.

### Recognising a break

Each Debug Logs row is `[HH:MM:SS] [level] message`. A break is identified by its **timestamp + text**, and
the watcher remembers the keys it has handled. (The first version *counted* matching lines; when the app
relaunched, its log restarted empty, one new break looked like "fewer lines than before", and a real break
went unnoticed for two hours.) The resume time is computed from the row's own timestamp, so a break
noticed late, or already over, resumes immediately instead of waiting a second full period.

## The decision loop (`watcher.tick`)

```
read queue.db
├─ any item running/pending                → trust it only while counters move (see below)
├─ nothing stalled                         → idle: maybe run a playlist sync (see below)
└─ stalled (paused / partial / failed)
   ├─ queue state changed since last look?
   │    open Debug Logs, count break messages
   │    ├─ a break message not seen before → resume_at = its log timestamp + (announced + margin) min
   │    ├─ none new, resume_unexplained_pauses → resume_at = now
   │    └─ none new → leave it alone (assume the user paused it)
   ├─ resume_at reached?
   │    ├─ retries >= max → give up, notify
   │    ├─ press "Resume All"; if absent, the row's retry arrow
   │    ├─ wait 40 s; item still `pending`? press "Start"
   │    ├─ check queue.db shows it `running`
   │    └─ not running → fall back: fetch the playlist URL again and press "Add to Queue"
   └─ otherwise, and no resume pending → maybe run a playlist sync
```

**Active-queue watchdog (`watch_active`).** Even a queue that claims to be active is checked: if the
`done+skipped+failed` counters haven't moved for `pending_start_after_minutes` (2) and the item is `pending`,
the watcher presses **Start** (at most once per 5 min); if it is `running` but frozen for `stuck_minutes` (20),
it logs a warning and notifies, because pressing Start can't fix that.

Retries reset whenever the done+skipped count grows, so a long job that hits many breaks is not
"given up on" while it makes progress. The UI is only touched when the queue is stalled *and*
changed (or a sync/resume is due), never while downloads run.

Why re-adding is a reasonable fallback: the app skips files it already has by filename, and at a
still-active break it stops at the first real download instead of hammering the server. On a
777-track playlist with 392 files on disk, a re-add skipped all 392 locally within a couple of minutes (not timed precisely) and
re-downloaded nothing.

## Restarts, reboots and crashes

A relaunched SpotiFLAC converts whatever was running to **paused** and empties its debug log, so the
usual rule ("paused with no break message → the user paused it, leave it alone") would strand the queue
after every reboot. Instead the watcher remembers the app's PID in `state.json`:

- PID changed, or the app was closed at the previous tick and is open now → a **restart** was seen.
- No PID on record (new state file): only a process younger than 10 minutes counts as a restart, so a
  pause you set in a long-running app survives the watcher itself being restarted.
- After a restart, a stalled queue is resumed after `restart_settle_seconds`, via the normal ladder
  (Resume All / retry arrow, then **Start** if the item is left `pending`, then re-add).
- If `queue.db` still says `running` but the app process is gone (shutdown mid-download), the watcher
  relaunches the app first (needs `autolaunch.enabled`).

The watcher itself is a per-user scheduled task that triggers **at logon**: it needs your desktop
session to drive the app, so nothing happens between boot and sign-in.

## Playlist sync

With `[sync]` enabled, the watcher periodically (`interval`) or whenever the queue is empty
(`on_idle`, rate-limited by a cooldown) does what you would by hand: paste the URL on the Home page,
**Fetch**, **Add to Queue**. If the app says **Already in Queue** (a finished item still sits there) it
clears the queue tab first (`Clear All` + confirm; files on disk are never touched) and adds again.

- Only runs when nothing is downloading and no break wait is pending.
- Add-only: it never deletes files.
- "Already have it" is decided by **filename**. With a template containing the playlist position
  (such as `{track}. {title}`), appended tracks are fine, but inserted or re-ordered tracks shift
  the numbers and are downloaded again as duplicates. Use a title/artist-based template if you
  reorder playlists often.

## "Is it on?" (`status`, `watch`, the menu)

The loop writes a `heartbeat` timestamp every cycle (before and after the work). `status` reads it:

| Heartbeat | Verdict |
|---|---|
| fresh, no `PAUSE` file | **● ACTIVE** |
| fresh, `PAUSE` file present | **◐ PAUSED** |
| older than 5 min, or missing | **○ NOT RUNNING** (a hung watcher counts) |

A tick can legitimately take ~2 minutes (UI work plus the 40 s settle wait), hence the 5-minute limit.
`status` also shows what the watcher is doing, the queue counts, when the next resume or sync is due,
and the last log lines. `watch` redraws it every 2 s; `menu.bat` wraps all of it.

State between ticks lives in `state.json` (keys of the break messages already handled, pending `resume_at`, retries, a queue
fingerprint, progress, last sync time). Files never committed: `config.toml`, `state.json`,
`heartbeat`, `watcher.log`, `PAUSE`.

## Tests

`tests/` covers the break-message parser, the bbolt reader (against hand-built databases), and the
decision logic with a fake queue and UI (including the `partial`-after-break case and sync
scheduling). `tools/focus_check.py` is a manual check that a UI session leaves foreground focus and
the minimized state untouched; `tools/dump_ui.py` and `tools/explore_fetch.py` are read-only helpers
for inspecting the app's UI after an update.
