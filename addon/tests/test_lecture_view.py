"""K-119 lecture view: resolution core, targeted vector access, glue pins.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_lecture_view.py
"""

import importlib
import json
import os
import re
import shutil
import sys
import tempfile
from array import array

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install, check, section, report  # noqa: E402

install()

card_index = importlib.import_module("klausmate.card_index")
pdf_index = importlib.import_module("klausmate.pdf_index")
lecture_view = importlib.import_module("klausmate.lecture_view")

LectureMatch = lecture_view.LectureMatch
NoLecture = lecture_view.NoLecture


def unit(vals):
    n = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / n for v in vals]


def flat(rows):
    a = array("f")
    for r in rows:
        a.extend(r)
    return a


def write_prefs(ufd, prefs):
    d = os.path.join(ufd, pdf_index.SUBDIR)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "prefs.json"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def write_ctx_json(ufd, safe, pages):
    d = os.path.join(ufd, "contexts")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, safe + ".json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "page_count": len(pages)}, f)


def write_ctx_txt(ufd, safe, text):
    d = os.path.join(ufd, "contexts")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, safe + ".txt"), "w", encoding="utf-8") as f:
        f.write(text)


def make_pdf_index(ufd, safe, chunks, rows, provider="p", model="m", dims=4):
    idx = pdf_index.PdfIndex(
        provider=provider,
        model=model,
        pdf_name=safe,
        dims=dims,
        source_sig=pdf_index.source_signature(ufd, safe) or (0, 0),
        chunks=list(chunks),
        embedded_rows=len(chunks),
        vectors=flat(rows),
    )
    pdf_index.save(idx, pdf_index.index_dir(ufd, safe))
    return idx


def make_card_index(ufd, nids, rows, skipped=None, provider="p", model="m", dims=4):
    ci = card_index.CardIndex(
        provider=provider,
        model=model,
        dims=dims,
        nids=list(nids),
        mods=[1] * len(nids),
        hashes=["h%d" % n for n in nids],
        skipped=dict(skipped or {}),
        vectors=flat(rows),
    )
    card_index.save(ci, os.path.join(ufd, lecture_view.CARD_INDEX_SUBDIR))
    return ci


# ---------------------------------------------------------------- fixtures

TMP = tempfile.mkdtemp(prefix="klaus_lecture_")


def fresh_ufd():
    d = tempfile.mkdtemp(dir=TMP)
    return d


# ------------------------------------------------------------ pure helpers

section("tag inversion + candidates")

prefs = {
    "PDF_A": {"tag": "!Library::Anatomy::A", "threshold": 0.7},
    "PDF_B": {"tag": "!Library::B"},
    "NoTag": {"threshold": 0.5},
    "Junk": "not-a-dict",
}
inv = lecture_view.tag_to_safe(prefs)
check("two tagged entries invert", len(inv) == 2)
check("keys are casefolded", "!library::anatomy::a" in inv)
check("threshold-only entry skipped", "NoTag" not in inv.values())
check(
    "exact tag resolves",
    lecture_view.candidates_for_tags(["!Library::B"], inv) == ["PDF_B"],
)
check(
    "case-insensitive hit",
    lecture_view.candidates_for_tags(["!LIBRARY::b"], inv) == ["PDF_B"],
)
check(
    "unrelated + marked tags ignored",
    lecture_view.candidates_for_tags(
        ["marked", "!Library::Other::Leaf"], inv
    )
    == [],
)
check(
    "order preserved, deduped",
    lecture_view.candidates_for_tags(
        ["!Library::B", "!Library::Anatomy::A", "!library::b"], inv
    )
    == ["PDF_B", "PDF_A"],
)

section("best_chunk argmax")

ufd = fresh_ufd()
write_ctx_json(ufd, "B", ["p1", "p2", "p3"])
idx_b = make_pdf_index(
    ufd,
    "B",
    chunks=[(1, 0, 2), (2, 0, 2), (7, 0, 2)],
    rows=[unit([0, 1, 0, 0]), unit([0.6, 0.8, 0, 0]), unit([1, 0, 0, 0])],
)
j, s = pdf_index.best_chunk(idx_b, unit([1, 0, 0, 0]))
check("argmax row found", j == 2)
check("argmax score is the dot", abs(s - 1.0) < 1e-6)
j2, s2 = pdf_index.best_chunk(idx_b, unit([0, 1, 0, 0]))
check("different query, different row", j2 == 0 and abs(s2 - 1.0) < 1e-6)
check(
    "empty index unusable",
    pdf_index.best_chunk(
        pdf_index.PdfIndex(provider="p", model="m", pdf_name="x", dims=4),
        unit([1, 0, 0, 0]),
    )
    == (-1, 0.0),
)
check(
    "dims mismatch unusable",
    pdf_index.best_chunk(idx_b, [1.0, 0.0]) == (-1, 0.0),
)

section("row map + targeted vector read")

ufd2 = fresh_ufd()
make_card_index(
    ufd2,
    nids=[10, 20, 30],
    rows=[unit([1, 0, 0, 0]), unit([0, 1, 0, 0]), unit([0, 0, 1, 0])],
    skipped={99: (1, "h99")},
)
cdir = os.path.join(ufd2, lecture_view.CARD_INDEX_SUBDIR)
rm = card_index.load_row_map(cdir)
check("row map loads", rm is not None)
check("every nid mapped", rm.rows == {10: 0, 20: 1, 30: 2})
check("skipped carried as set", rm.skipped == {99})
check("provider/model/dims carried", (rm.provider, rm.model, rm.dims) == ("p", "m", 4))
v2 = card_index.read_vector(cdir, 2, 4)
check("row 2 read exactly", v2 is not None and abs(v2[2] - 1.0) < 1e-6 and abs(v2[0]) < 1e-9)
check("past-end row is None", card_index.read_vector(cdir, 3, 4) is None)
check("negative row is None", card_index.read_vector(cdir, -1, 4) is None)
vec_path = os.path.join(cdir, card_index.VECTORS_FILE)
with open(vec_path, "r+b") as f:
    f.truncate(4 * 4 * 3 - 6)  # chop mid-row
check("truncated file is None", card_index.read_vector(cdir, 2, 4) is None)
bad = card_index.load_row_map(fresh_ufd())
check("missing manifest -> None", bad is None)
os.makedirs(os.path.join(TMP, "corrupt"), exist_ok=True)
with open(os.path.join(TMP, "corrupt", "manifest.json"), "w") as f:
    f.write("{nope")
check(
    "corrupt manifest -> None",
    card_index.load_row_map(os.path.join(TMP, "corrupt")) is None,
)

# ------------------------------------------------------- end-to-end resolve

section("resolve: end to end")

ufd3 = fresh_ufd()
write_prefs(
    ufd3,
    {
        "PDF_A": {"tag": "!Library::A"},
        "PDF_B": {"tag": "!Library::B"},
    },
)
write_ctx_json(ufd3, "PDF_A", ["a1", "a2"])
write_ctx_json(ufd3, "PDF_B", ["b"] * 8)
make_pdf_index(
    ufd3,
    "PDF_A",
    chunks=[(1, 0, 2)],
    rows=[unit([0.8, 0.6, 0, 0])],
)
make_pdf_index(
    ufd3,
    "PDF_B",
    chunks=[(1, 0, 2), (2, 0, 2), (7, 0, 2)],
    rows=[unit([0, 1, 0, 0]), unit([0.6, 0.8, 0, 0]), unit([1, 0, 0, 0])],
)
make_card_index(
    ufd3,
    nids=[100, 200, 300],
    rows=[unit([1, 0, 0, 0]), unit([0, 0, 0, 1]), unit([0, 1, 0, 0])],
    skipped={400: (1, "h")},
)
resolver = lecture_view.LectureResolver(ufd3)
both = ["!Library::A", "!Library::B"]
out = resolver.resolve(100, both)
check("match wins over both candidates", isinstance(out, LectureMatch))
check("winner is the closer PDF", out.safe == "PDF_B")
check("page is the argmax chunk's stored page", out.page == 7)
check("pages are known (json context)", out.pages_known is True)
check("fresh index is not stale", out.stale is False)
check("score carried", abs(out.score - 1.0) < 1e-6)

out_a = resolver.resolve(300, ["!Library::A"])
check(
    "single-candidate resolve hits it",
    isinstance(out_a, LectureMatch) and out_a.safe == "PDF_A" and out_a.page == 1,
)

section("resolve: every no-lecture reason")

check(
    "no tags",
    resolver.resolve(100, ["marked"]) == NoLecture(lecture_view.R_NO_TAGS),
)
check(
    "skipped nid = no vector",
    resolver.resolve(400, both) == NoLecture(lecture_view.R_NO_VECTOR),
)
check(
    "unknown nid = no vector",
    resolver.resolve(555, both) == NoLecture(lecture_view.R_NO_VECTOR),
)
check(
    "orthogonal vector = below floor",
    resolver.resolve(200, both) == NoLecture(lecture_view.R_BELOW_FLOOR),
)

ufd4 = fresh_ufd()
write_prefs(ufd4, {"PDF_A": {"tag": "!Library::A"}})
r4 = lecture_view.LectureResolver(ufd4)
check(
    "card manifest missing = no card index",
    r4.resolve(1, ["!Library::A"]) == NoLecture(lecture_view.R_NO_CARD_INDEX),
)
make_card_index(ufd4, nids=[1], rows=[unit([1, 0, 0, 0])])
r4.invalidate()
check(
    "candidate index dir missing = index unavailable",
    r4.resolve(1, ["!Library::A"])
    == NoLecture(lecture_view.R_INDEX_UNAVAILABLE),
)
write_ctx_json(ufd4, "PDF_A", ["x"])
make_pdf_index(
    ufd4, "PDF_A", chunks=[(1, 0, 1)], rows=[unit([1, 0, 0, 0])],
    provider="OTHER",
)
r4.invalidate()
check(
    "provider mismatch = index unavailable",
    r4.resolve(1, ["!Library::A"])
    == NoLecture(lecture_view.R_INDEX_UNAVAILABLE),
)

section("resolve: legacy pages + stale")

ufd5 = fresh_ufd()
write_prefs(ufd5, {"PDF_L": {"tag": "!Library::L"}})
write_ctx_txt(ufd5, "PDF_L", "one big blob")  # legacy: .txt only, no .json
make_pdf_index(ufd5, "PDF_L", chunks=[(1, 0, 4)], rows=[unit([1, 0, 0, 0])])
make_card_index(ufd5, nids=[1], rows=[unit([1, 0, 0, 0])])
r5 = lecture_view.LectureResolver(ufd5)
out5 = r5.resolve(1, ["!Library::L"])
check("legacy still matches", isinstance(out5, LectureMatch))
check("legacy pages unknown", out5.pages_known is False and out5.page == 0)

ufd6 = fresh_ufd()
write_prefs(ufd6, {"PDF_S": {"tag": "!Library::S"}})
write_ctx_json(ufd6, "PDF_S", ["p"])
make_pdf_index(ufd6, "PDF_S", chunks=[(1, 0, 1)], rows=[unit([1, 0, 0, 0])])
make_card_index(ufd6, nids=[1], rows=[unit([1, 0, 0, 0])])
r6 = lecture_view.LectureResolver(ufd6)
first = r6.resolve(1, ["!Library::S"])
check("pre-rewrite not stale", isinstance(first, LectureMatch) and first.stale is False)
write_ctx_json(ufd6, "PDF_S", ["p", "q", "r", "s"])  # size changes -> new sig
out6 = r6.resolve(1, ["!Library::S"])
check("context rewrite flips stale", isinstance(out6, LectureMatch) and out6.stale is True)

section("resolve: stamp-validated caching")

calls = {"n": 0}
orig_load = pdf_index.load


def counting_load(d):
    calls["n"] += 1
    return orig_load(d)


pdf_index.load = counting_load
try:
    r7 = lecture_view.LectureResolver(ufd3)
    a = r7.resolve(100, both)
    loads_first = calls["n"]
    b = r7.resolve(100, both)
    check("cache hit returns equal outcome", a == b)
    check("cache hit re-loads nothing", calls["n"] == loads_first)
    # Rewrite PDF_B's index so a different chunk (page 3) wins, and
    # bump its manifest stamp — the cached result must be recomputed.
    make_pdf_index(
        ufd3,
        "PDF_B",
        chunks=[(3, 0, 2)],
        rows=[unit([1, 0, 0, 0])],
    )
    man = os.path.join(pdf_index.index_dir(ufd3, "PDF_B"), pdf_index.MANIFEST_FILE)
    os.utime(man, (os.path.getmtime(man) + 5, os.path.getmtime(man) + 5))
    c = r7.resolve(100, both)
    check(
        "manifest drift recomputes",
        isinstance(c, LectureMatch) and c.page == 3,
    )
    # prefs drift: dropping PDF_B's tag removes the candidate.
    write_prefs(ufd3, {"PDF_A": {"tag": "!Library::A"}})
    d = r7.resolve(100, both)
    check(
        "prefs drift re-picks candidates",
        isinstance(d, LectureMatch) and d.safe == "PDF_A",
    )
finally:
    pdf_index.load = orig_load

# ------------------------------------------------------------- glue pins

section("glue pins (source)")

SRC_PATH = "klausmate/lecture_view.py"
with open(SRC_PATH, encoding="utf-8") as f:
    SRC = f.read()


def code_only(text):
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        out.append(stripped)
    return "\n".join(out)


CODE = code_only(SRC)

for hook in (
    "webview_will_set_content.append",
    "webview_did_receive_js_message.append",
    "reviewer_did_show_question.append",
    "state_did_change.append",
    "state_shortcuts_will_change.append",
    "reviewer_will_show_context_menu.append",
    "profile_will_close.append",
    "aboutToQuit.connect",
):
    check("registers %s" % hook, hook in CODE)

check("bottom bar name-matched", '"ReviewerBottomBar"' in SRC)
check("button posts klausmate:lecture", 'pycmd("klausmate:lecture")' in SRC)
check("button id present", "klaus-lecture-btn" in SRC)
check("button sits beside More", "insertBefore(b, more)" in SRC)
check("bridge matches the exact message", '"klausmate:lecture"' in CODE)
check("toggle deferred out of the bridge", "QTimer.singleShot(0, toggle_lecture_view)" in CODE)
check("no app-modal exec anywhere", ".exec()" not in CODE)
check("sidebar cleanup on the close path", "self.sidebar.cleanup()" in CODE)
check("jump defer idiom present", "QTimer.singleShot" in CODE)
check("shortcut only in review state", 'state != "review"' in CODE)
check("shortcut collision scan present", '"l" in taken' in CODE)
check("never activateWindow (focus stays on reviewer)", "activateWindow" not in CODE)
check(
    "no literal hex colours in code",
    re.search(r"#[0-9a-fA-F]{6}\b", CODE) is None,
)
check(
    "empty-state sentence is Pouya's, verbatim",
    lecture_view.NO_LECTURE_TEXT == "No lecture page available for this card.",
)
check("dock is right-area", "RightDockWidgetArea" in CODE)
check("state change hides outside review", "_dock.hide()" in CODE)

section("wiring pins")

with open("klausmate/__init__.py", encoding="utf-8") as f:
    INIT = f.read()
check(
    "setup wired in __init__ (guarded)",
    "from . import lecture_view as _lecture_view" in INIT
    and "_lecture_view.setup()" in INIT,
)
with open("klausmate/config.json", encoding="utf-8") as f:
    CONF = json.load(f)
check("config default present and true", CONF.get("lecture_view_reopen") is True)
with open("klausmate/config.md", encoding="utf-8") as f:
    check("config.md documents the key", "lecture_view_reopen" in f.read())

check("module has aqt-free/glue divider", "aqt glue" in SRC)
check("public toggle exists", callable(lecture_view.toggle_lecture_view))
check("public open exists", callable(lecture_view.open_lecture_view))
check("setup exists", callable(lecture_view.setup))

shutil.rmtree(TMP, ignore_errors=True)
raise SystemExit(report())
