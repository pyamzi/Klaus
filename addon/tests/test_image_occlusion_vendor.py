"""Image Occlusion 1/3: IOE v1.4.0 is vendored (provenance in UPSTREAM.md) and wired once.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_image_occlusion_vendor.py
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import check, section, report  # noqa: E402

PKG = os.path.join(ROOT, "klaus_note", "image_occlusion")
SRC = os.path.expanduser("~/Library/Application Support/Anki2/addons21/1374772155")
PY = ["add", "config", "consts", "dialogs", "editor", "lang", "main", "nconvert",
      "ngen", "options", "qt", "template", "utils", "web", "_version"]
# Ruling R1: Task 2 ("the port follows Klaus rules") edits these; their
# as-vendored sha256 stays in UPSTREAM.md, and the rest stay byte-identical.
MODIFIED = ["add", "config", "consts", "dialogs", "editor", "main", "nconvert",
            "ngen", "options", "web"]


def read(p):
    with open(p, "rb") as f:
        return f.read()


def sha(p):
    return hashlib.sha256(read(p)).hexdigest()


section("package layout")
check("package exists", os.path.isdir(PKG))
# Task 3 wrote Klaus's own __init__.py (setup/occlude); IOE's bootstrap never came.
check("__init__.py is Klaus's setup, not IOE's bootstrap",
      os.path.isfile(os.path.join(PKG, "__init__.py"))
      and b"def setup()" in read(os.path.join(PKG, "__init__.py"))
      and b"setup_main(mw)" in read(os.path.join(PKG, "__init__.py")))
for d in ("_vendor", "icons", "svg-edit", "web"):
    check(d + "/ exists", os.path.isdir(os.path.join(PKG, d)))
for n in PY:
    check(n + ".py exists", os.path.isfile(os.path.join(PKG, n + ".py")))
for junk in ("meta.json", "manifest.json", "CHANGELOG.md", "__pycache__"):
    check("no " + junk, not os.path.exists(os.path.join(PKG, junk)))

section("licence and provenance")
lic = os.path.join(PKG, "LICENSE.txt")
check("LICENSE.txt is AGPL", os.path.isfile(lic)
      and b"GNU AFFERO GENERAL PUBLIC LICENSE" in read(lic))
up = os.path.join(PKG, "UPSTREAM.md")
text = read(up).decode() if os.path.isfile(up) else ""
check("UPSTREAM.md names v1.4.0", "v1.4.0" in text)
check("UPSTREAM.md names the GitHub URL",
      "https://github.com/glutanimate/image-occlusion-enhanced" in text)
check("UPSTREAM.md says __init__.py not copied", "__init__.py" in text)
recorded = dict((p, h) for h, p in re.findall(r"^([0-9a-f]{64})  (\S.*)$", text, re.M))
actual = {}
for base, dirs, files in os.walk(PKG):
    # excalidraw/ is Klaus's own page (Task 5), not part of IOE.
    dirs[:] = [d for d in dirs if d != "__pycache__" and not (base == PKG and d == "excalidraw")]
    for f in files:
        rel = os.path.relpath(os.path.join(base, f), PKG)
        # Klaus additions, not part of IOE (Ruling R9): excal_masks.py (Task 6),
        # excal_tab.py and svg-edit's owed MIT text (Task 7, R18).
        if rel not in ("UPSTREAM.md", "__init__.py", "excal_masks.py", "excal_tab.py",
                       os.path.join("svg-edit", "LICENSE-svg-edit.txt")):
            actual[rel] = os.path.join(base, f)
check("UPSTREAM.md hashes every vendored file", set(recorded) == set(actual),
      str(sorted(set(recorded) ^ set(actual))[:5]))
# The .py files get edited in later tasks (R1), so their recorded hash is
# provenance only; data files must still match it.
stale = [r for r, p in actual.items() if not r.endswith(".py") and recorded.get(r) != sha(p)]
check("non-.py files match recorded sha256", not stale, str(stale[:5]))
svg_lic = os.path.join(PKG, "svg-edit", "LICENSE-svg-edit.txt")
lic_text = read(svg_lic).decode() if os.path.isfile(svg_lic) else ""
check("R18: svg-edit's MIT licence text ships beside it",
      "Copyright (c) 2009-2012 by SVG-edit authors" in lic_text
      and "Permission is hereby granted, free of charge" in lic_text)
check("...and UPSTREAM.md names it with its upstream commit",
      "svg-edit/LICENSE-svg-edit.txt" in text
      and "92b9f6abeaca87aafa71aeba73658e7962896df9" in text)
check("UPSTREAM.md lists excal_tab.py as a Klaus addition", "`excal_tab.py`" in text)
t2 = [ln for ln in text.splitlines() if ln.startswith("Modified by Task 2")]
check("UPSTREAM.md has one line naming the files Task 2 modified",
      len(t2) == 1 and all("`%s.py`" % n in t2[0] for n in MODIFIED), str(t2))

section("byte identity with installed IOE")
if not os.path.isdir(SRC):
    print("  NOTE: installed IOE add-on absent, byte-identity check skipped")
else:
    for n in PY:
        ours, theirs = read(os.path.join(PKG, n + ".py")), read(os.path.join(SRC, n + ".py"))
        if n in MODIFIED:
            # AGPL: "Any modifications to this file must keep this entire header intact."
            end = theirs.find(b"# Any modifications to this file must keep this entire header intact.")
            check(n + ".py (modified) keeps upstream's copyright header intact",
                  end > 0 and ours[:end] == theirs[:end])
        else:
            check(n + ".py identical to upstream", ours == theirs)
    vendored = [r for r in actual if r.startswith("_vendor" + os.sep) and r.endswith(".py")]
    check("_vendor/ has its .py files", len(vendored) >= 3, str(vendored))
    for r in sorted(vendored):
        check(r + " identical to upstream",
              read(os.path.join(PKG, r)) == read(os.path.join(SRC, r)))
    bad = [r for r, p in actual.items() if not r.endswith(".py")
           and read(p) != read(os.path.join(SRC, r))]
    check("data files identical to upstream", not bad, str(bad[:5]))

section("wired once (Task 3)")
init = read(os.path.join(ROOT, "klaus_note", "__init__.py")).decode()
check("klaus_note/__init__.py calls image_occlusion's setup() exactly once",
      init.count("_image_occlusion.setup()") == 1)

raise SystemExit(report())
