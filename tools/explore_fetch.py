"""Dev helper (read-only): fetch a playlist URL on SpotiFLAC's Home page and list the controls
that appear afterwards. Never clicks anything that downloads.

    set PYTHONPATH=src && python tools\\explore_fetch.py <spotify-playlist-url>
"""
import sys
import time

from spotiflac_autoresume import ui

url = sys.argv[1]
with ui.Session() as s:
    ui.goto(s.doc, "SpotiFLAC")
    edit = [d for d in s.doc.descendants(control_type="Edit")][0]
    edit.set_edit_text(url)                       # UIA ValuePattern: no focus, no typing
    fetch = [d for d in ui._content_elements(s.doc)
             if d.element_info.control_type == "Button" and d.element_info.name == "Fetch"][0]
    fetch.invoke()
    for i in range(12):
        time.sleep(2)
        names = [(k, n) for k, n in ui._content_texts(s.doc)]
        if any("Download" in n for k, n in names):
            break
    print("--- controls after Fetch (first 60):")
    for k, n in names[:60]:
        print(f"{k:9} {n[:70]!r}")
