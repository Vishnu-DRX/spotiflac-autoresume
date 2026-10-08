"""UI Automation helpers for the SpotiFLAC (Wails/WebView2) window.

All interaction uses UIA invoke(), so the real mouse is never moved and focus is
never stolen. The accessibility tree stays readable while the window is minimized
(Windows moves it ~-32000 px off-screen), so every position test below is relative
to the web pane's own origin, never absolute screen coordinates.
"""
import ctypes
import re
import time

from pywinauto import Desktop

# Sidebar order observed in v7.2.2. Index 6 opens a GitHub-issues dialog: never click it.
PAGES = {"SpotiFLAC": 0, "Queue": 1, "History": 2, "Settings": 3, "Debug Logs": 4, "Tools": 5}


class UiError(Exception):
    pass


DEFAULT_BREAK_PATTERN = "scheduled short break"


_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_LEVELS = {"debug", "info", "error", "success", "warning"}


def log_rows(texts):
    """Group the Debug Logs page's text nodes into (time, level, message) rows.

    The page renders each row as '[ HH:MM:SS ] [ level ] message', one text node per piece.
    """
    toks = [t for t in texts if t not in ("[", "]")]
    rows, i = [], 0
    while i < len(toks) - 2:
        if _TIME_RE.match(toks[i]) and toks[i + 1].lower() in _LEVELS:
            rows.append((toks[i], toks[i + 1], toks[i + 2]))
            i += 3
        else:
            i += 1
    return rows


def parse_break_rows(rows, pattern=DEFAULT_BREAK_PATTERN):
    events = []
    for stamp, _level, msg in rows:
        if pattern.lower() in msg.lower():
            m = re.search(r"(?:about|in)\s+(\d+)\s+minute", msg, re.I)
            events.append({"key": f"{stamp}|{msg[-70:]}", "time": stamp,
                           "minutes": int(m.group(1)) if m else None})
    return events


def parse_break_events(text, pattern=DEFAULT_BREAK_PATTERN):
    """Find every occurrence of `pattern` in `text` (one log line or a whole log block).

    Returns [(excerpt, minutes_or_None)]. The minutes come from the "about N minute(s)"
    that follows the occurrence, before the next occurrence of the pattern.
    """
    hits = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
    events = []
    for n, start in enumerate(hits):
        end = hits[n + 1] if n + 1 < len(hits) else len(text)
        chunk = text[start:end]
        m = re.search(r"(?:about|in)\s+(\d+)\s+minute", chunk, re.I)
        events.append((chunk[:120], int(m.group(1)) if m else None))
    return events


_u32 = ctypes.windll.user32
VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002


def _foreground():
    return _u32.GetForegroundWindow()


def _give_focus_back(hwnd):
    """Hand the foreground back to `hwnd`. Windows only allows this for a process that
    just had input, so tap Alt first (the standard workaround); the tap is invisible."""
    if not hwnd or not _u32.IsWindow(hwnd) or _foreground() == hwnd:
        return
    _u32.keybd_event(VK_MENU, 0, 0, 0)
    _u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    _u32.SetForegroundWindow(hwnd)


def _window():
    w = Desktop(backend="uia").window(title="SpotiFLAC", control_type="Window")
    if not w.exists(timeout=2):
        raise UiError("SpotiFLAC window not found")
    return w


def _doc(win):
    doc = win.child_window(title="SpotiFLAC - Web content")
    if not doc.exists(timeout=2):
        raise UiError("web content pane not found")
    return doc


# Sidebar slots: first icon sits 56 px below the pane top, then one every 48 px.
# The button of the page currently shown is NOT an unnamed button, so counting
# buttons is unreliable; the vertical slot is not.
NAV_FIRST_DY, NAV_PITCH = 56, 48


def _nav_buttons(doc):
    """Return {slot: button} for the unnamed sidebar icon buttons that are present."""
    origin = doc.rectangle()
    out = {}
    for b in doc.descendants(control_type="Button"):
        r = b.element_info.rectangle
        name = b.element_info.name
        # icon-only buttons are unnamed, except Queue whose name is its count badge ("1", "12", ...)
        if (name and not name.isdigit()) or r.width() >= 60 or r.left > origin.left + 40:
            continue
        out[round((r.top - origin.top - NAV_FIRST_DY) / NAV_PITCH)] = b
    return out


# Page content starts right of the sidebar and below the title bar (offsets from the pane origin).
CONTENT_DX, CONTENT_DY = 62, 44


def _content_elements(doc):
    """Named Text/Button/DataItem wrappers inside the page area (not sidebar/title bar)."""
    origin = doc.rectangle()
    out = []
    for d in doc.descendants():
        i = d.element_info
        if i.name and i.control_type in ("Text", "Button", "DataItem"):
            r = i.rectangle
            if r.left > origin.left + CONTENT_DX and r.top > origin.top + CONTENT_DY:
                out.append(d)
    return out


def _content_texts(doc):
    return [(d.element_info.control_type, d.element_info.name) for d in _content_elements(doc)]


def current_page(doc):
    for kind, name in _content_texts(doc):
        if kind == "Text" and name in PAGES:
            return name
    return None


def goto(doc, page):
    if current_page(doc) == page:
        return
    navs = _nav_buttons(doc)
    btn = navs.get(PAGES[page])
    if btn is None:
        raise UiError(f"sidebar button for {page!r} not found (slots present: {sorted(navs)})")
    btn.invoke()
    for _ in range(20):
        time.sleep(0.25)
        if current_page(doc) == page:
            return
    raise UiError(f"navigation to {page!r} did not land")


class Session:
    """Context manager: works on the window as-is (minimized is fine) and puts the
    user back on the page they were viewing afterwards."""

    def __enter__(self):
        self.prev_fg = _foreground()
        self.win = _window()
        self.doc = _doc(self.win)
        self.start_state = self.win.get_show_state()
        self.start_page = current_page(self.doc)
        if self.start_page is None:
            # Never seen a readable tree (e.g. started minimized): restore once, then re-minimize.
            self.was_min = self.win.get_show_state() == 2
            if self.was_min:
                self.win.restore()
                time.sleep(1.5)
                self.start_page = current_page(self.doc)
        else:
            self.was_min = False
        return self

    def __exit__(self, *exc):
        try:
            if self.start_page:
                goto(self.doc, self.start_page)
        except Exception:
            pass
        try:
            if self.start_state == 2 and self.win.get_show_state() != 2:
                self.win.minimize()          # never leave it un-minimized
            _give_focus_back(self.prev_fg)   # clicks make WebView2 grab focus
        except Exception:
            pass
        return False

    def break_events(self, pattern=DEFAULT_BREAK_PATTERN):
        """Break messages on the Debug Logs page: [{'key', 'time', 'minutes'}], oldest first.

        `key` identifies one log row (its timestamp + text), so a break is recognised as new even
        if the log was cleared or the app was relaunched in between (counting lines is not safe).
        """
        goto(self.doc, "Debug Logs")
        time.sleep(0.5)
        texts = [name for kind, name in _content_texts(self.doc) if kind == "Text"]
        return parse_break_rows(log_rows(texts), pattern)

    def queue_buttons(self):
        goto(self.doc, "Queue")
        time.sleep(0.5)
        return [n for k, n in _content_texts(self.doc) if k == "Button"]

    def add_to_queue(self, url, timeout=40):
        """Fetch a Spotify URL on the Home page and press 'Add to Queue'.

        Returns 'added', or 'already' when the app says it is already queued
        (the caller can clear the finished item and try again).
        """
        goto(self.doc, "SpotiFLAC")
        edit = next(iter(self.doc.descendants(control_type="Edit")), None)
        if edit is None:
            raise UiError("Home page URL box not found")
        edit.set_edit_text(url)                        # UIA ValuePattern: no typing, no focus
        fetch = next(d for d in _content_elements(self.doc) if d.element_info.name == "Fetch")
        fetch.invoke()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1.5)
            for d in _content_elements(self.doc):
                if d.element_info.control_type == "Button":
                    if d.element_info.name == "Add to Queue":
                        d.invoke()
                        return "added"
                    if d.element_info.name == "Already in Queue":
                        return "already"
        raise UiError("fetch did not produce an 'Add to Queue' button in time")

    def clear_queue(self, tab="Playlists"):
        """Remove every queued item on one Queue tab (files already on disk are unaffected).

        'Clear All' only affects the tab being shown, so the tab is selected explicitly first.
        """
        goto(self.doc, "Queue")
        time.sleep(0.5)
        tab_btn = next((d for d in _content_elements(self.doc)
                        if d.element_info.control_type == "Button"
                        and re.match(rf"{tab}(\s+\d+)?$", d.element_info.name)), None)
        if tab_btn is None:
            return False
        tab_btn.invoke()
        time.sleep(1.0)
        if not self.click_queue_button("Clear All"):
            return False
        time.sleep(1.0)
        buttons = [d for d in self.doc.descendants(control_type="Button")
                   if d.element_info.name in ("Cancel", "Clear All")]
        cancel = next((b for b in buttons if b.element_info.name == "Cancel"), None)
        if cancel is None:
            return False                              # no confirmation dialog appeared
        ct = cancel.element_info.rectangle.top
        confirm = [b for b in buttons if b.element_info.name == "Clear All"
                   and abs(b.element_info.rectangle.top - ct) < 8]
        if len(confirm) != 1:
            cancel.invoke()                           # unsure which is which: back out safely
            return False
        confirm[0].invoke()
        time.sleep(1.0)
        return True

    def click_row_retry(self):
        """Press the retry arrow on every queue row that has one; returns how many were pressed.

        After a server break the app ends the item as "Completed with Issues" and offers no
        Resume All; the row's ACTIONS column then holds two unnamed icon buttons: retry (neutral)
        and remove (class contains "text-destructive"). Only the neutral one is ever pressed.
        """
        goto(self.doc, "Queue")
        time.sleep(0.5)
        pressed = 0
        tabs = [d for d in _content_elements(self.doc)
                if d.element_info.control_type == "Button"
                and re.match(r"(Tracks|Albums|Playlists|Artists)\s+\d+$", d.element_info.name)]
        for tab in tabs:                      # only tabs that show an item count have rows
            tab.invoke()
            time.sleep(1.0)
            pressed += self._press_row_retries()
        return pressed

    def _press_row_retries(self):
        header = next((d for d in self.doc.descendants(control_type="DataItem")
                       if d.element_info.name.upper() == "ACTIONS"), None)
        if header is None:
            return 0
        hr = header.element_info.rectangle
        rows = {}
        for b in self.doc.descendants(control_type="Button"):
            r = b.element_info.rectangle
            if b.element_info.name or r.top <= hr.bottom or not (hr.left - 5 <= r.left <= hr.right):
                continue
            try:
                cls = b.element_info.element.GetCurrentPropertyValue(30012) or ""
            except Exception:
                continue
            if "text-destructive" in cls:
                continue                      # remove button: never touch
            rows.setdefault(round(r.top / 10), []).append((r.left, b))
        pressed = 0
        for _top, buttons in sorted(rows.items()):
            buttons.sort(key=lambda t: t[0])
            buttons[0][1].invoke()            # leftmost neutral icon = retry arrow
            pressed += 1
            time.sleep(0.5)
        return pressed

    def click_queue_button(self, *names):
        """Click the first queue-page button whose name matches one of `names`, in priority order."""
        goto(self.doc, "Queue")
        time.sleep(0.5)
        buttons = [d for d in _content_elements(self.doc) if d.element_info.control_type == "Button"]
        for want in names:
            for b in buttons:
                if b.element_info.name == want:
                    b.invoke()
                    return want
        return None
