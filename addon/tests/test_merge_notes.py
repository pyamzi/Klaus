"""#12: minting a highlight never discards a note or its card offset.

merge_highlight_records cuts a new mark out of different-ink highlights
and unions same-ink ones. Pinned rule: a record that is fully recoloured
hands its note (and card) to the record that now covers its span; a
same-ink union joins every distinct note (blank line between, in list
order) and keeps the card of the first noted record.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_merge_notes.py
"""
import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
pv = importlib.import_module("klaus_note.pdfjs_viewer")

YEL, GRN = "#fadc50", "#7ed957"


section("different-ink recolour keeps the note")
out = pv.merge_highlight_records(
    [{"id": "a", "page": 0, "rects": [[100, 100, 200, 12]], "color": YEL,
      "note": "my note", "card": [30, -10]}],
    [{"id": "n", "page": 0, "rects": [[100, 100, 200, 12]], "color": GRN}],
)
check("one green record", len(out) == 1 and out[0]["color"] == GRN, repr(out))
check("...carrying the recoloured record's note",
      out[0].get("note") == "my note", repr(out))
check("...and its card offset", out[0].get("card") == [30, -10], repr(out))

out = pv.merge_highlight_records(
    [{"id": "a", "page": 0, "rects": [[100, 100, 90, 12]], "color": YEL,
      "note": "first"},
     {"id": "b", "page": 0, "rects": [[200, 100, 90, 12]], "color": YEL,
      "note": "second", "card": [5, 5]}],
    [{"id": "n", "page": 0, "rects": [[100, 100, 200, 12]], "color": GRN}],
)
check("two noted records recoloured by one drag keep both notes",
      len(out) == 1 and out[0].get("note") == "first\n\nsecond"
      and out[0].get("card") is None, repr(out))

out = pv.merge_highlight_records(
    [{"id": "a", "page": 0, "rects": [[100, 100, 200, 12]], "color": YEL,
      "note": "yellow note", "card": [1, 2]},
     {"id": "g", "page": 0, "rects": [[300, 100, 50, 12]], "color": GRN,
      "note": "green note", "card": [9, 9]}],
    [{"id": "n", "page": 0, "rects": [[100, 100, 210, 12]], "color": GRN}],
)
check("a recoloured note joining an existing same-ink record keeps both "
      "notes and the host's card",
      len(out) == 1 and out[0]["id"] == "g"
      and out[0].get("note") == "green note\n\nyellow note"
      and out[0].get("card") == [9, 9], repr(out))

section("same-ink union keeps card and every note")
out = pv.merge_highlight_records(
    [{"id": "h", "page": 0, "rects": [[10, 20, 40, 12]], "color": YEL,
      "note": ""},
     {"id": "a", "page": 0, "rects": [[100, 20, 40, 12]], "color": YEL,
      "note": "absorbed note", "card": [80, 40]}],
    [{"id": "n", "page": 0, "rects": [[30, 20, 90, 12]], "color": YEL}],
)
check("bridge collapses to one record", len(out) == 1, repr(out))
check("...with the absorbed note", out[0].get("note") == "absorbed note")
check("...and the absorbed note's card", out[0].get("card") == [80, 40],
      repr(out))

out = pv.merge_highlight_records(
    [{"id": "h", "page": 0, "rects": [[10, 20, 40, 12]], "color": YEL,
      "note": "left"},
     {"id": "a", "page": 0, "rects": [[100, 20, 40, 12]], "color": YEL,
      "note": "right", "card": [80, 40]}],
    [{"id": "n", "page": 0, "rects": [[30, 20, 90, 12]], "color": YEL}],
)
check("two noted records merged by one drag lose no note text",
      len(out) == 1 and out[0].get("note") == "left\n\nright", repr(out))
check("...and the card follows the first note (host has none: default spot)",
      out[0].get("card") is None, repr(out))

out = pv.merge_highlight_records(
    [{"id": "h", "page": 0, "rects": [[10, 20, 40, 12]], "color": YEL,
      "note": "same"},
     {"id": "a", "page": 0, "rects": [[100, 20, 40, 12]], "color": YEL,
      "note": "same"}],
    [{"id": "n", "page": 0, "rects": [[30, 20, 90, 12]], "color": YEL}],
)
check("identical notes are not doubled", out[0].get("note") == "same",
      repr(out))

section("unchanged behaviour")
base = [{"id": "a", "page": 0, "rects": [[10, 20, 100, 12]], "color": YEL,
         "note": "keep", "card": [1, 1]}]
mid = pv.merge_highlight_records(
    base, [{"id": "n", "page": 0, "rects": [[40, 20, 25, 12]], "color": GRN}])
check("a partial cut leaves the note on the surviving record only",
      len(mid) == 2 and mid[0].get("note") == "keep"
      and mid[0].get("card") == [1, 1] and not mid[1].get("note"), repr(mid))

raise SystemExit(report())
