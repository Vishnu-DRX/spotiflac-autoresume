# How it works

## Why UI automation

SpotiFLAC v7.2.2 is a Wails (Go + WebView2) desktop app. It has no CLI, headless mode or local
API (the README and changelog mention none), so the only way to press its **Resume** button is
through its window.

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
watcher.py   loop + decisions (the only module with policy)
ui.py        UI Automation: navigation, reading logs, pressing buttons, focus handling
bbolt_read.py  read-only reader for SpotiFLAC's queue.db
```

### Reading the queue (`bbolt_read.py`)

`~/.spotiflac/queue.db` is a [bbolt](https://github.com/etcd-io/bbolt) B+tree (Go), not SQLite.
The app keeps it open, but reading is allowed. bbolt is copy-on-write, so scanning the file for
JSON returns stale copies; the reader instead picks the meta page with the highest transaction
id and walks the tree from its root. The `DownloadQueueItems` bucket holds one JSON document per
queue item:

```json
{"name": "Vault_drx", "status": "paused", "trackCount": 777,
 "trackResults": {"<spotify id>": "done|skipped|failed", "...": "..."}}
```

Item `status` (`running`/`paused`/...) and the per-track result counts are all the watcher
needs from the database. The *error text* is **not** stored there, which is why the logs page
is consulted.

### Driving the app (`ui.py`)

- Page content is located relative to the web pane's own origin. A minimized window reports
  coordinates around `-32000`, so absolute positions would break.
- Sidebar buttons are identified by their vertical *slot* (first icon 56 px below the pane top,
  one every 48 px), because the button of the page you are on and the Queue button (which
  carries a count badge) aren't plain unnamed buttons.
- The last sidebar icon opens a GitHub-issues dialog and is never clicked.
- Every UI session remembers the page you were on and returns to it, keeps a minimized window
  minimized, and gives keyboard focus back to the window you were using. (WebView2 grabs focus
  when invoked; the hand-back uses the standard Alt-tap + `SetForegroundWindow`.)

## The decision loop (`watcher.tick`)

```
read queue.db
├─ any item running            → nothing to do (reset pending wait)
├─ nothing stalled             → nothing to do
└─ stalled (paused / failed)
   ├─ queue state changed since last look?
   │    open Debug Logs, count break messages
   │    ├─ more than last time → resume_at = now + (announced + margin) min
   │    ├─ none new, resume_unexplained_pauses → resume_at = now
   │    └─ none new → leave it alone (assume the user paused it)
   └─ resume_at reached?
        ├─ retries >= max → give up, notify
        └─ press "Resume All", wait 40 s, check queue.db shows it running
              (not running → forget fingerprint so the next tick re-reads the logs)
```

Retries reset whenever the done+skipped count grows, so a long job that hits many breaks is not
"given up on" while it makes progress. The UI is only touched when the queue is stalled *and*
changed, never while downloads run.

State between ticks (`state.json`): break count seen, pending `resume_at`, retries, a queue
fingerprint, and progress.

## Tests

`tests/` covers the break-message parser, the bbolt reader (against hand-built databases),
and the decision logic with fake queue/UI. `tools/focus_check.py` is a manual check that a UI
session leaves foreground focus and the minimized state untouched.
