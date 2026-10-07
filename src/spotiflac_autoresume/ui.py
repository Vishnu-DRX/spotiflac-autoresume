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
        """Return [(excerpt, minutes_or_None)] for every break message on the Debug Logs page."""
        goto(self.doc, "Debug Logs")
        time.sleep(0.5)
        events = []
        for _kind, name in _content_texts(self.doc):
            events.extend(parse_break_events(name, pattern))
        return events

    def queue_buttons(self):
        goto(self.doc, "Queue")
        time.sleep(0.5)
        return [n for k, n in _content_texts(self.doc) if k == "Button"]

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
