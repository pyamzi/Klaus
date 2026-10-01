"""Image Occlusion 1/3: IOE v1.4.0 is vendored verbatim and not yet wired.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_image_occlusion_vendor.py
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import check, section, report  # noqa: E402

PKG = os.path.join(ROOT, "klausmate", "image_occlusion")
SRC = os.path.expanduser("~/Library/Application Support/Anki2/addons21/1374772155")
PY = ["add", "config", "consts", "dialogs", "editor", "lang", "main", "nconvert",
      "ngen", "options", "qt", "template", "utils", "web", "_version"]


def read(p):
    with open(p, "rb") as f:
        return f.read()


def sha(p):
    return hashlib.sha256(read(p)).hexdigest()


section("package layout")
check("package exists", os.path.isdir(PKG))
check("__init__.py is empty", os.path.isfile(os.path.join(PKG, "__init__.py"))
      and read(os.path.join(PKG, "__init__.py")) == b"")
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
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        rel = os.path.relpath(os.path.join(base, f), PKG)
        if rel not in ("UPSTREAM.md", "__init__.py"):
            actual[rel] = os.path.join(base, f)
check("UPSTREAM.md hashes every vendored file", set(recorded) == set(actual),
      str(sorted(set(recorded) ^ set(actual))[:5]))
# The .py files get edited in later tasks (R1), so their recorded hash is
# provenance only; data files must still match it.
stale = [r for r, p in actual.items() if not r.endswith(".py") and recorded.get(r) != sha(p)]
check("non-.py files match recorded sha256", not stale, str(stale[:5]))

section("byte identity with installed IOE")
if not os.path.isdir(SRC):
    print("  NOTE: installed IOE add-on absent, byte-identity check skipped")
else:
    for n in PY:
        check(n + ".py identical to upstream",
              read(os.path.join(PKG, n + ".py")) == read(os.path.join(SRC, n + ".py")))
    bad = [r for r, p in actual.items() if not r.endswith(".py")
           and read(p) != read(os.path.join(SRC, r))]
    check("data files identical to upstream", not bad, str(bad[:5]))

section("not wired")
init = read(os.path.join(ROOT, "klausmate", "__init__.py")).decode()
check("klausmate/__init__.py does not import image_occlusion",
      "image_occlusion" not in init)

raise SystemExit(report())
