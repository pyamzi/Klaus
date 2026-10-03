"""K-302: card<->lecture match precision.

Centered cosine (scores after subtracting the card collection's mean
vector), the one-time threshold-scale migration, the re-match of stale
caches, and the opt-in best-lecture assignment.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_match_precision.py
"""
from __future__ import annotations

import importlib
import json
import math
import os
import sys
import tempfile
import time
from array import array

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import LiveStore, check, install, report, section  # noqa: E402

install()

import klaus_note.settings as _settings  # noqa: E402

card_index = importlib.import_module("klaus_note.card_index")
pdf_index = importlib.import_module("klaus_note.pdf_index")
curation = importlib.import_module("klaus_note.curation")
retention = importlib.import_module("klaus_note.retention")
tag_sync = importlib.import_module("klaus_note.tag_sync")
index_queue = importlib.import_module("klaus_note.index_queue")

cfg: dict = {"embedding_model": "nomic-embed-text"}
_settings.store = LiveStore(cfg)
retention.mw = type("MW", (), {"taskman": type("T", (), {"run_on_main": staticmethod(lambda fn: fn())})()})()


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def centered_cos(a, b, m):
    a2 = [x - y for x, y in zip(a, m)]
    b2 = [x - y for x, y in zip(b, m)]
    return sum(x * y for x, y in zip(a2, b2)) / (
        math.sqrt(sum(x * x for x in a2)) * math.sqrt(sum(x * x for x in b2)))


section("centered cosine")
m = [0.5, 0.4, 0.1]
a, b = unit([0.9, 0.3, 0.1]), unit([0.6, 0.7, 0.2])
cen = card_index.Centered(array("f", m))
got = cen.score(sum(x * y for x, y in zip(a, b)), cen.terms(a), cen.terms(b))
check("expanded form equals the explicit centered cosine", abs(got - centered_cos(a, b, m)) < 1e-5)
check("a zero row has no terms (never a match)", cen.terms([0.0, 0.0, 0.0]) is None)

section("card mean vector, cached beside the index")
root = tempfile.mkdtemp(prefix="klaus-k302-")
cdir = os.path.join(root, "card_index")
rows = [unit([1, 0, 0]), unit([0.8, 0.6, 0]), unit([0.9, 0, 0.4])]
cidx = card_index.CardIndex(provider="ollama", model="nomic-embed-text", dims=3, nids=[1, 2, 3],
                            mods=[1, 1, 1], hashes=["a", "b", "c"], vectors=array("f", sum(rows, [])))
card_index.save(cidx, cdir)
check("too few notes -> no centering", card_index.mean_vector(cdir) is None)
card_index.MIN_ROWS_FOR_MEAN = 1
card_index._mean_memo.clear()
time.sleep(0.01)
card_index.save(cidx, cdir)
mean = card_index.mean_vector(cdir)
want = [sum(r[j] for r in rows) / 3 for j in range(3)]
check("mean of every row", mean is not None and all(abs(x - y) < 1e-5 for x, y in zip(mean, want)))
check("sidecar written", os.path.exists(os.path.join(cdir, card_index.MEAN_FILE)))
card_index._mean_memo.clear()
check("sidecar read back", list(card_index.mean_vector(cdir)) == list(mean))
time.sleep(0.01)
cidx.vectors = array("f", sum([unit([0, 1, 0])] * 3, []))
card_index.save(cidx, cdir)
check("a rebuilt index recomputes", abs(card_index.mean_vector(cdir)[1] - 1.0) < 1e-5)
check("no index -> None", card_index.mean_vector(os.path.join(root, "nope")) is None)

section("match_scores and the Lecture panel center alike")
cidx.vectors = array("f", sum(rows, []))
pages = [unit([1, 0.1, 0]), unit([0.7, 0.7, 0.1]), [0.0, 0.0, 0.0]]
pidx = pdf_index.PdfIndex(provider="ollama", model="nomic-embed-text", pdf_name="L", dims=3,
                          pages=[(1, "x"), (2, "y"), (3, "z")], embedded_rows=3,
                          vectors=array("f", sum(pages, [])))
mv = array("f", want)
raw, _ = retention.match_scores(pidx, cidx, floor=-2)
centered, best_pages = retention.match_scores(pidx, cidx, floor=-2, mean=mv)
check("no mean -> raw cosine, unchanged",
      abs(dict(raw)[2] - max(sum(x * y for x, y in zip(rows[1], p)) for p in pages[:2])) < 1e-5)
check("with mean -> centered cosine",
      abs(dict(centered)[2] - max(centered_cos(rows[1], p, want) for p in pages[:2])) < 1e-4)
for nid, row in zip([1, 2, 3], rows):
    page, score = pdf_index.best_page(pidx, array("f", row), mv)
    check(f"note {nid}: Lecture panel picks the cached best page", page == best_pages[nid]
          and abs(score - dict(centered)[nid]) < 1e-5)
check("a zero page never wins", 3 not in best_pages.values())

section("threshold scale migration (once, user-set or not)")
_settings.user_files_dir = root
retention.set_threshold("Heme", 0.75)
out = retention._migrate_threshold_scale({"pdf_match_threshold": 0.75, "_threshold_user_set": True})
check("global reset to the centered default", out["pdf_match_threshold"] == retention.DEFAULT_THRESHOLD == 0.45)
check("user-set mark dropped", "_threshold_user_set" not in out)
check("per-PDF override cleared", "Heme" not in retention.threshold_override_names())
check("written back", out.get("_threshold_scale") == retention.SCORE_SCALE)
retention.set_threshold("Heme", 0.42)
again = retention._migrate_threshold_scale({**out, "pdf_match_threshold": 0.61})
check("second run is a no-op", again["pdf_match_threshold"] == 0.61
      and retention.get_threshold("Heme", again) == 0.42)

section("stale match caches are re-matched on profile open")
index_queue._manifest_paths = lambda: [
    (n, os.path.join(_settings.user_files(), "pdf_index", n, "manifest.json")) for n in ("Old", "New", "Never")]
sig = ("ollama", "nomic-embed-text")
retention.save_matches("New", sig, 3, (1, 1), "d", [(1, 0.5)], {})
retention.save_matches("Old", sig, 3, (1, 1), "d", [(1, 0.5)], {})
p = retention._matches_path("Old")
with open(p, encoding="utf-8") as f:
    payload = json.load(f)
payload["version"] = 2
with open(p, "w", encoding="utf-8") as f:
    json.dump(payload, f)
check("old-version cache is stale, current and absent ones are not",
      index_queue.stale_match_names() == ["Old"])

section("best-lecture assignment (opt-in, read-time, across PDFs)")
check("off by default", retention.best_delta({}) is None)
cfg["pdf_match_best_delta"] = 0.03
retention.save_matches("Anemia", sig, 2, (1, 1), "d", [(1, 0.80), (2, 0.76), (3, 0.70)], {1: 1, 2: 1, 3: 2})
retention.save_matches("B12", sig, 2, (2, 2), "d", [(1, 0.70), (2, 0.80), (3, 0.69)], {1: 1, 2: 1, 3: 1})
got = dict(retention.load_matches("Anemia", sig, 2, (1, 1), "d")[0])
check("card clearly better on another lecture is dropped", 2 not in got)
check("card best here is kept", got.get(1) == 0.80)
check("near-tie within delta stays on both lectures", 3 in got
      and 3 in dict(retention.load_matches("B12", sig, 2, (2, 2), "d")[0]))
retention.save_matches("B12", sig, 2, (2, 2), "d", [(1, 0.70), (2, 0.60), (3, 0.69)], {1: 1, 2: 1, 3: 1})
check("re-matching another PDF refreshes the baseline",
      2 in dict(retention.load_matches("Anemia", sig, 2, (1, 1), "d")[0]))
retention.save_matches("B12", sig, 2, (2, 2), "stale", [(1, 0.99), (2, 0.99), (3, 0.99)], {})
check("a cache from another card index never sets the baseline",
      len(retention.load_matches("Anemia", sig, 2, (1, 1), "d")[0]) == 3)
check("a different embedding space never sets the baseline",
      retention.best_scores(("ollama", "other-model"), 2, "d") == {})

section("re-matching one PDF re-tags the others from cache")
curation.index_dir = lambda: os.path.join(root, "card_index2")
cidx2 = card_index.CardIndex(provider="ollama", model="nomic-embed-text", dims=2, nids=[1, 2, 3],
                             mods=[1, 1, 1], hashes=["a", "b", "c"], vectors=array("f", [1, 0] * 3))
card_index.save(cidx2, curation.index_dir())
digest = retention.card_index_digest(cidx2)
for name, rows_ in (("Anemia", [(1, 0.80), (2, 0.76), (3, 0.70)]),
                    ("B12", [(1, 0.70), (2, 0.80), (3, 0.69)]),
                    ("Cold", [(1, 0.99)])):
    retention.save_matches(name, sig, 2, (0, 0), digest if name != "Cold" else "stale", rows_, {})
retention.pdf_index.source_signature = lambda uf, n: (0, 0)
retention.get_threshold = lambda name, c: 0.65
for name in ("Anemia", "B12", "Cold"):
    tag_sync.set_stored_tag(name, "!Library::" + name)
synced: dict = {}
tag_sync._do_sync_one = lambda col, safe, tag, nids: synced.__setitem__(safe, nids)
tag_sync._folder_and_display = lambda safe: (None, safe)
tag_sync._retag_others(object(), "B12", cfg)
check("the other PDF is re-tagged with its filtered set", synced.get("Anemia") == {1, 3})
check("the PDF just synced is skipped", "B12" not in synced)
check("a cold cache is never re-tagged (no stripping on missing data)", "Cold" not in synced)
synced.clear()
tag_sync._retag_others(object(), "B12", {**cfg, "pdf_match_best_delta": -1})
check("rule off -> no cross-PDF re-tag", synced == {})

raise SystemExit(report())
