"""Dev helper: does the watcher's UI automation work while the Windows session is locked?

Run it, then lock the PC (Win+L), wait a couple of minutes, and unlock. Every INTERVAL seconds it
records whether the session is locked, whether a real UI Automation session (navigate Debug Logs and
back) succeeded, and whether downloads are still progressing. Read-only apart from page navigation.

    set PYTHONPATH=src && python tools\\lock_test.py <logfile> [minutes]
"""
import ctypes
import sys
import time

from spotiflac_autoresume import ui
from spotiflac_autoresume.watcher import load_cfg, load_items

INTERVAL = 20
DESKTOP_SWITCHDESKTOP = 0x0100


def locked():
    """True while the secure (lock-screen) desktop has the input focus."""
    h = ctypes.windll.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True
    ctypes.windll.user32.CloseDesktop(h)
    return False


def done_count(cfg):
    it = load_items(cfg)
    return sum(i["done"] for i in it) if it else None


log, minutes = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10
cfg = load_cfg()
end = time.time() + minutes * 60
with open(log, "w", encoding="utf-8") as f:
    while time.time() < end:
        t0 = time.time()
        state = "LOCKED" if locked() else "unlocked"
        try:
            with ui.Session() as s:
                s.break_events()                      # navigates to Debug Logs and back
            result = "UI ok"
        except Exception as e:                        # noqa: BLE001 - we want to record anything
            result = f"UI FAILED: {type(e).__name__}: {str(e)[:80]}"
        f.write(f"{time.strftime('%H:%M:%S')}  {state:9} {result:60} done={done_count(cfg)}\n")
        f.flush()
        time.sleep(max(INTERVAL - (time.time() - t0), 1))
