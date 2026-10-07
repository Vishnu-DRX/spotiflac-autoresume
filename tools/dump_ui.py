"""Dev helper: dump the UI Automation tree of the SpotiFLAC window."""
import sys
from pywinauto import Desktop

win = Desktop(backend="uia").window(title="SpotiFLAC", control_type="Window")
win.wait("exists", timeout=15)
depth = int(sys.argv[1]) if len(sys.argv) > 1 else 12

def walk(el, d=0):
    if d > depth:
        return
    try:
        info = el.element_info
        name = (info.name or "").replace("\n", " ")[:80]
        print("  " * d + f"{info.control_type} | {name!r} | id={info.automation_id!r}")
        for c in el.children():
            walk(c, d + 1)
    except Exception as e:
        print("  " * d + f"<err {e}>")

walk(win)
