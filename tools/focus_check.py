"""Dev helper: verify that a watcher UI session never steals focus or un-minimizes SpotiFLAC.

Run with SpotiFLAC minimized and some other window in front, e.g.:
    set PYTHONPATH=src && python tools\\focus_check.py
"""
import ctypes
import time

from spotiflac_autoresume import ui

u32 = ctypes.windll.user32


def fg():
    h = u32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(h, buf, 256)
    return h, buf.value


win = ui._window()
before = (fg(), win.get_show_state())
print("before: foreground=%r  show_state=%s (2=minimized)" % (before[0][1], before[1]))

with ui.Session() as s:                      # same path the watcher takes
    events = s.break_events()                # navigates to Debug Logs
    buttons = s.queue_buttons()              # navigates to Queue
    print("  break events: %s | queue buttons: %s" % (events, buttons[:3]))
time.sleep(0.5)

after = (fg(), win.get_show_state())
print("after:  foreground=%r  show_state=%s" % (after[0][1], after[1]))
print("RESULT:", "FOCUS STOLEN" if before[0][0] != after[0][0] else "focus unchanged",
      "|", "window un-minimized" if before[1] == 2 and after[1] != 2 else "window state unchanged")
