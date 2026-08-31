"""K-135 gate: the hex helper must SEE a literal, and the Library's
name column must survive the default splitter."""
import re, sys
src = open("tests/test_setup_crop_theme.py", encoding="utf-8").read()
ns = {}
exec(src.split("section(")[0], ns)
helper = ns["_hex_hits_outside_comments"]
sees_literal = bool(helper('BLUE = "#AABBCC"\n'))
drive = open("klausmate/pdf_drive.py", encoding="utf-8").read()
m = re.search(r"setSizes\(sane if sane is not None else \[(\d+), (\d+)\]\)", drive)
left = int(m.group(1)) if m else 0
numeric = sum(int(w) for w in re.findall(r"setColumnWidth\([123], (\d+)\)", drive))
name_px = left - numeric - 16
print(f"helper sees a literal: {sees_literal} | name column at default: {name_px}px")
sys.exit(0 if (sees_literal and name_px >= 200) else 1)
