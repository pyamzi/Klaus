"""PDF study priorities — retention scoring of cards matched to each PDF.

Pipeline per PDF: embed its pages persistently, one vector per page
(pdf_index.py, fed by page_store.py) → score every indexed note against
those pages (max cosine, cached in matches.json) → pull FSRS
retrievability for the matched notes' cards → aggregate a
similarity-weighted retention score → rank PDFs by study priority.

Layout mirrors curation.py: pure math helpers up top (headlessly testable),
aqt glue below. Long work runs on QueryOp workers; embedding and matching
run ``without_collection()``.

Match cache invalidation: matches.json records the (provider, model, dims)
signature, the PDF's source signature, AND a digest of the card index's
(hashes, nids). The digest — not ``updated_at`` — is deliberate: bulk
tag mutations bump mods and resave the card index without changing any
text; hashes+nids move only when content or membership really changed.

Browse hop: "Show matched cards in Browse" (pdf_drive._on_browse) no
longer mutates any note tags. Each PDF already owns a durable per-PDF
``!Library::...`` tag (tag_sync.py, K-053) holding exactly the matches
above its current sensitivity, so the hop just opens Browse on that
stored tag (tag_sync.get_stored_tag) — see K-055.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp

from . import card_index, curation, embeddings, page_store, pdf_handler, pdf_index

USER_FILES = curation.USER_FILES
INDEX_DIR = curation.INDEX_DIR

MATCHES_FILE = "matches.json"
PREFS_FILE = "prefs.json"
MATCHES_VERSION = 3  # 3: K-302 prefixed embeddings; old caches are a different space

# Cache floor for match scores — deliberately far below any usable
# threshold, so the panel's threshold slider is a pure re-filter of the
# cached list and never triggers a recompute.
MATCH_FLOOR = 0.15

# 0.45 on the centered scale (K-302), checked against AnKing's #Bootcamp
# tags: the Bootcamp Heme/Onc PDF matches 1,126 notes at precision 0.92,
# recall 0.49 (raw 0.75: 1,939 notes, 0.82 / 0.66), and the B12 lecture's
# wrong-lesson heme matches drop ~3x at equal recall. 0.50 was the first
# pick and caught only 30% of the tagged heme cards.
DEFAULT_THRESHOLD = 0.45
# Every global default this add-on has ever shipped, oldest first. A stored
# value equal to ANY of them was inherited, not chosen, so it follows the
# current default forward; anything else is a deliberate setting and is left
# alone. Keeping the whole history here (rather than one "previous default"
# constant) means a user who skipped a version still lands on the current
# default instead of being stranded on an intermediate one.
_SHIPPED_DEFAULTS = (0.35, 0.55, 0.75, 0.45)
# Records the default last applied, so changing DEFAULT_THRESHOLD is the only
# edit a future bump needs — no new boolean guard per change. Superseded the
# one-shot _threshold_default_migrated flag, which could not re-run.
_DEFAULT_APPLIED_KEY = "_threshold_default_applied"
# Set (only) by the Preferences dialog's default-sensitivity control
# (manage_models.py's save_threshold, K-052) the moment a human actually
# changes the slider — never by the dialog merely opening or repopulating.
# Before that control existed, a stored value equal to a _SHIPPED_DEFAULTS
# entry could only mean "inherited", so silently carrying it forward was
# safe. Once a user can deliberately pick 0.55 through the UI, that
# assumption breaks: a later default bump would look identical to an
# inherited value and overwrite a real choice. This flag is the
# distinguishing signal — once set, migration leaves the value alone
# forever, independent of _DEFAULT_APPLIED_KEY bookkeeping.
_THRESHOLD_USER_SET_KEY = "_threshold_user_set"
# IN-list chunk for the nid→queue batch (card_queues). SQLite's default
# host-parameter cap is 999; 900 leaves headroom without multiplying
# round-trips on a 30k-note pool.
CARD_QUEUE_CHUNK = 900

ProgressFn = Callable[[str, int, int], None]

try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))


def _migrate_default_threshold(cfg: dict) -> dict:
    """Carry a stored default forward when DEFAULT_THRESHOLD changes, and
    never touch a value someone set deliberately.

    Runs once per default value, not once per profile: it records which
    default it last applied, so a later bump re-runs for everyone instead
    of stranding whoever already migrated. That matters because the
    previous one-shot boolean had already fired for existing users at
    0.55; without this they would have kept 0.55 forever while new
    installs got 0.75.

    Only the GLOBAL config's ``pdf_match_threshold`` is in scope here.
    Per-PDF prefs.json entries (set_threshold/get_threshold) are a user
    choice "saved forever" and this never reads or writes prefs.json.

    A cfg with ``_threshold_user_set`` truthy is returned completely
    unchanged, before anything else runs: that flag means a human chose
    this value on purpose through the Preferences dialog, not that it
    happens to match an old shipped default.
    """
    if cfg.get(_THRESHOLD_USER_SET_KEY):
        return cfg
    if cfg.get(_DEFAULT_APPLIED_KEY) == DEFAULT_THRESHOLD:
        return cfg
    cfg = dict(cfg)
    try:
        current = float(cfg.get("pdf_match_threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        current = None
    # Tolerance rather than ==: these round-trip through JSON, and a stored
    # 0.5500000000000001 is still an inherited default, not a choice.
    if current is not None and any(
        abs(current - shipped) < 1e-9 for shipped in _SHIPPED_DEFAULTS
    ):
        cfg["pdf_match_threshold"] = DEFAULT_THRESHOLD
    cfg[_DEFAULT_APPLIED_KEY] = DEFAULT_THRESHOLD
    cfg.pop("_threshold_default_migrated", None)  # retired one-shot guard
    try:
        mw.taskman.run_on_main(lambda c=cfg: curation._pkg().write_config(c))
    except Exception as e:
        print(f"[klausmate] threshold default migration failed: {e}")
    return cfg


_SCALE_KEY = "_threshold_scale"
SCORE_SCALE = "centered"  # K-302


def _migrate_threshold_scale(cfg: dict) -> dict:
    """K-302 moved match scores from raw to centered cosine, where a raw
    0.75 matches almost nothing. A threshold set on the old scale means
    nothing on the new one, deliberately chosen or not, so ONCE: the
    global goes back to the default, the user-set mark goes (the value is
    the default again, and future default bumps should carry it), and
    every per-PDF override is cleared. The re-match that re-tags each PDF
    at the new threshold is setup_flow's (MATCHES_VERSION moved too)."""
    if cfg.get(_SCALE_KEY) == SCORE_SCALE:
        return cfg
    cfg = dict(cfg)
    cfg["pdf_match_threshold"] = DEFAULT_THRESHOLD
    cfg[_DEFAULT_APPLIED_KEY] = DEFAULT_THRESHOLD
    cfg[_SCALE_KEY] = SCORE_SCALE
    cfg.pop(_THRESHOLD_USER_SET_KEY, None)
    try:
        clear_threshold_overrides()
        mw.taskman.run_on_main(lambda c=cfg: curation._pkg().write_config(c))
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] threshold scale migration failed: {e}")
    return cfg


def _cfg() -> dict:
    """The global config, with the one-time threshold-default migration
    applied. This is the canonical config accessor for retention/curation's
    shared, threshold-scoped reads — curation._cfg() itself stays a plain
    pass-through so unrelated config reads (embedding signature, etc.)
    don't carry this side effect."""
    return _migrate_default_threshold(_migrate_threshold_scale(curation._cfg()))


# ------------------------------------------------------------ pure helpers


def card_index_digest(cidx: card_index.CardIndex) -> str:
    """Content digest of the card index — moves only when note text or
    membership changes (mod-only resaves keep it stable)."""
    payload = ",".join(cidx.hashes) + ";" + ",".join(str(n) for n in cidx.nids)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


def match_scores(
    pdf_idx: pdf_index.PdfIndex,
    cidx: card_index.CardIndex,
    floor: float = MATCH_FLOOR,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    mean=None,
) -> tuple[list[tuple[int, float]], dict[int, int]]:
    """Score every indexed note against the PDF's pages →
    ([(nid, score)], {nid: best page, 1-based}).

    One vector per page now (pdf_index v2), so a note's score is simply
    its best-matching page — the argmax that used to be discarded is the
    whole point now, since a note's best page is what the Lecture panel
    and the matches cache both need. Both indexes hold unit vectors, so
    similarity is a plain dot product.
    """
    if (pdf_idx.provider, pdf_idx.model) != (cidx.provider, cidx.model):
        raise ValueError(
            "Embedding spaces differ between the PDF index and the card index"
            " — re-embed the PDF."
        )
    if pdf_idx.dims != cidx.dims:
        raise ValueError("Embedding dimensions differ — re-embed the PDF.")
    d = cidx.dims
    n_pages = pdf_idx.embedded_rows
    if not cidx.nids or not n_pages or d <= 0:
        return [], {}
    cmv = memoryview(cidx.vectors)
    pmv = memoryview(pdf_idx.vectors)
    page_rows = [pmv[j * d : (j + 1) * d] for j in range(n_pages)]
    # K-302: centered on the card collection's mean when one is given
    # (card_index.Centered); raw cosine otherwise.
    cen = card_index.Centered(mean) if mean is not None and len(mean) == d else None
    page_terms = [cen.terms(r) for r in page_rows] if cen else []
    out: list[tuple[int, float]] = []
    pages: dict[int, int] = {}
    total = len(cidx.nids)
    for i, nid in enumerate(cidx.nids):
        if cancel is not None and i % 512 == 0 and cancel.is_set():
            return out, pages
        if on_progress and i % 512 == 0:
            on_progress(i, total)
        row = cmv[i * d : (i + 1) * d]
        scores = [_sumprod(row, c) for c in page_rows]
        if cen:
            ct = cen.terms(row)
            scores = [
                -1.0 if ct is None or pt is None else cen.score(x, ct, pt)
                for x, pt in zip(scores, page_terms)
            ]
        best = max(range(len(scores)), key=lambda k: scores[k])
        score = scores[best]
        if score >= floor:
            out.append((nid, score))
            pages[nid] = pdf_idx.pages[best][0]
    return out, pages


def fsrs_retrievability(
    s: float, decay: float, elapsed_days: float
) -> float:
    """FSRS forgetting curve: P(recall now) given stability and elapsed time.

    ``decay`` 0.5 reproduces the classic FSRS-4.5 curve (older card states
    lack the field); newer states carry their own per-card decay.
    """
    if s <= 0:
        return 0.0
    factor = 0.9 ** (-1.0 / decay) - 1.0
    r = (1.0 + factor * max(0.0, elapsed_days) / s) ** (-decay)
    return min(1.0, max(0.0, r))


def sm2_retrievability(ivl: int, elapsed_days: float) -> float:
    """Crude retention estimate for SM-2 cards (no FSRS state): treat the
    interval as stability under the classic curve."""
    return fsrs_retrievability(float(max(ivl, 1)), 0.5, elapsed_days)


def pdf_retention(
    matches: list[tuple[int, float]],
    threshold: float,
    card_r: dict[int, list[tuple[float, bool]]],
) -> dict:
    """Similarity-weighted retention over the matched notes' cards.

    ``card_r``: nid → [(R, is_new)] one entry per card of that note. Cards
    inherit their note's similarity, so multi-card notes weigh more (more
    study material) — intentional. Notes missing from ``card_r`` (deleted
    since indexing) are skipped.

    """
    weight_sum = 0.0
    weighted_r = 0.0
    matched_cards = 0
    new_cards = 0
    matched_notes = 0
    for nid, sim in matches:
        if sim < threshold:
            continue
        cards = card_r.get(nid)
        if not cards:
            continue
        matched_notes += 1
        for r, is_new in cards:
            weight_sum += sim
            weighted_r += sim * r
            matched_cards += 1
            if is_new:
                new_cards += 1
    retention = (weighted_r / weight_sum) if weight_sum > 0 else None
    priority = (
        (1.0 - retention) * math.log1p(matched_cards)
        if retention is not None
        else 0.0
    )
    return {
        "retention": retention,
        "matched_notes": matched_notes,
        "matched_cards": matched_cards,
        "new_pct": (new_cards / matched_cards) if matched_cards else 0.0,
        "priority": priority,
    }


def note_card_counts(
    matches: list[tuple[int, float]],
    threshold: float,
    queue_map: dict[int, list[int]],
) -> tuple[int, int, int]:
    """(note_count, card_count, suspended_count) over
    matches at/above ``threshold`` — the Library's Cards/Notes split
    (K-118).

    ``queue_map``: nid → [queue per card] (card_queues below). A note
    absent from the map (deleted since indexing) is skipped, mirroring
    pdf_retention's card_r rule, so note_count == pdf_retention's
    matched_notes for the same threshold. ``card_count`` is the VIEWABLE
    cards — queue != -1 — so buried cards (-2/-3, back on their own
    tomorrow) still count as viewable; only suspension (-1) moves a card
    to ``suspended_count``. card_count + suspended_count == pdf_retention's
    matched_cards by construction.
    """
    notes = 0
    viewable = 0
    suspended = 0
    for nid, sim in matches:
        if sim < threshold:
            continue
        queues = queue_map.get(nid)
        if not queues:
            continue
        notes += 1
        for q in queues:
            if q == -1:
                suspended += 1
            else:
                viewable += 1
    return notes, viewable, suspended


# ------------------------------------------------------- matches.json cache


def _matches_path(name: str) -> str:
    return os.path.join(pdf_index.index_dir(USER_FILES, name), MATCHES_FILE)


def pages_digest(name: str) -> str:
    """blake2b over this PDF index's page hashes, in order — the key that
    ties a cached ranking to the page TEXT it was actually computed from.

    None of the other keys can see a transcript (K-236): ``pdf_source_sig``
    stamps ``contexts/<safe>.json``, which ``page_store.append_segment``
    never touches, so a page whose said-text grew re-embeds (do_build's own
    ``idx.pages != keys`` check) while ``load_matches`` went on serving the
    old ranking against the new vectors.

    Manifest-only — never the vectors — and computed HERE rather than
    passed in, so all five callers (ensure_matches, priority_rows,
    pdf_graph, tag_sync) get the invalidation without a sixth signature to
    keep in step. "" when there is no readable index, which is what makes a
    pre-v2 profile's save/load pair agree with itself.
    """
    m = card_index.read_manifest(
        pdf_index.index_dir(USER_FILES, name),
        pdf_index.INDEX_VERSION,
        pdf_index.MANIFEST_FILE,
    )
    if not m:
        return ""
    try:
        h = hashlib.blake2b(digest_size=8)
        for row in m.get("pages") or []:
            h.update(str(row[1]).encode("utf-8"))
            h.update(b"\x1f")
        return h.hexdigest()
    except (KeyError, TypeError, IndexError):
        return ""


def load_matches(
    name: str,
    signature: tuple[str, str],
    dims: int,
    source_sig: tuple[int, int] | None,
    digest: str,
) -> tuple[list[tuple[int, float]], dict[int, int]] | None:
    """Cached ([(nid, score)], {nid: best page}) when every invalidation key
    matches, else None."""
    m = card_index.read_manifest(
        pdf_index.index_dir(USER_FILES, name), MATCHES_VERSION, MATCHES_FILE
    )
    if m is None:
        return None
    try:
        if not embeddings.signature_matches(
            str(m["provider"]), str(m["model"]), int(m["dims"]), signature
        ):
            return None
        if int(m["dims"]) != dims:
            return None
        sig = m.get("pdf_source_sig") or [0, 0]
        if source_sig is None or (int(sig[0]), int(sig[1])) != source_sig:
            return None
        if str(m.get("card_index_digest")) != digest:
            return None
        if str(m.get("pages_digest") or "") != pages_digest(name):
            # The pages themselves moved under this ranking (a re-embed, a
            # grown transcript, a pre-v2 payload with no digest at all).
            return None
        if float(m.get("floor", -1.0)) != MATCH_FLOOR:
            # MATCH_FLOOR changed since this cache was written — a cache
            # built with a different floor could be silently missing rows
            # that should now be included. Treat as cold, never stale-valid.
            return None
        matches = [(int(nid), float(score)) for nid, score in m["matches"]]
        pages = {int(k): int(v) for k, v in (m.get("pages") or {}).items()}
        return best_lecture_filter(matches, signature, dims, digest), pages
    except (ValueError, KeyError, TypeError):
        return None


def save_matches(
    name: str,
    signature: tuple[str, str],
    dims: int,
    source_sig: tuple[int, int],
    digest: str,
    matches: list[tuple[int, float]],
    pages: dict[int, int],
) -> None:
    payload = {
        "version": MATCHES_VERSION,
        "provider": signature[0],
        "model": signature[1],
        "dims": dims,
        "pdf_source_sig": list(source_sig),
        "pages_digest": pages_digest(name),
        "card_index_digest": digest,
        "floor": MATCH_FLOOR,
        "matches": [[nid, round(score, 6)] for nid, score in matches],
        "pages": {str(nid): p for nid, p in pages.items()},
    }
    pdf_handler._atomic_write_json(
        _matches_path(name), payload, separators=(",", ":")
    )


# ------------------------------------------ best-lecture assignment (K-302)
# Cosine answers "is this card about hematology", not "is it about THIS
# lecture": a generic card scores alike on every lecture of a subject and
# lands on all of them. So a match on lecture P counts only when P's score
# is within ``pdf_match_best_delta`` of the card's best score over every
# indexed lecture. Applied on READ (load_matches / ensure_matches) and never
# written into matches.json, because it depends on the OTHER PDFs' caches;
# tag_sync re-tags the other PDFs when one PDF's matches change.
# Off by default: on the eval it cut 3+-lecture cards 81 -> 11 but also
# pulled B12 cards onto the Bootcamp review lecture (recall 0.58 -> ~0.48),
# and keyword labels cannot tell a lost match from a correct reassignment.
DEFAULT_BEST_DELTA = -1.0
_best_memo: dict = {"key": None, "best": {}}


def best_delta(cfg: dict) -> float | None:
    """The tolerance, or None when the rule is off (a negative setting)."""
    try:
        value = float(cfg.get("pdf_match_best_delta", DEFAULT_BEST_DELTA))
    except (TypeError, ValueError):
        value = DEFAULT_BEST_DELTA
    return value if value >= 0 else None


def best_scores(signature: tuple, dims: int, digest: str) -> dict[int, float]:
    """{nid: best cached score across every PDF's matches.json} built from
    this card index (``digest``) in this embedding space. Memoised on every cache file's (mtime, size), so it
    re-reads only after some PDF was re-matched.

    ponytail: parses every matches.json whole (~0.3 s for 9 PDFs x 43k
    notes); keep a per-PDF best-score sidecar if libraries grow ~10x.
    """
    root = os.path.join(USER_FILES, pdf_index.SUBDIR)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return {}
    stamp = []
    for name in names:
        try:
            st = os.stat(os.path.join(root, name, MATCHES_FILE))
        except OSError:
            continue
        stamp.append((name, st.st_mtime_ns, st.st_size))
    key = (tuple(signature), dims, digest, tuple(stamp))
    if _best_memo["key"] == key:
        return _best_memo["best"]
    best: dict[int, float] = {}
    for name, _mtime, _size in stamp:
        m = card_index.read_manifest(os.path.join(root, name), MATCHES_VERSION, MATCHES_FILE)
        try:
            if m is None or int(m["dims"]) != dims or str(m.get("card_index_digest")) != digest or not embeddings.signature_matches(
                str(m["provider"]), str(m["model"]), int(m["dims"]), signature
            ):
                continue
            for nid, score in m["matches"]:
                nid, score = int(nid), float(score)
                if score > best.get(nid, -2.0):
                    best[nid] = score
        except (ValueError, KeyError, TypeError):
            continue
    _best_memo.update(key=key, best=best)
    return best


def best_lecture_filter(
    matches: list[tuple[int, float]], signature: tuple, dims: int, digest: str
) -> list[tuple[int, float]]:
    """Drop the matches that some other lecture fits clearly better."""
    try:
        cfg = curation._cfg()  # plain read: no threshold migration on a read path
    except Exception:  # noqa: BLE001 - unreadable config must not hide matches
        cfg = {}
    delta = best_delta(cfg)
    if delta is None or not matches:
        return matches
    best = best_scores(signature, dims, digest)
    return [(nid, s) for nid, s in matches if s >= best.get(nid, s) - delta]


# ------------------------------------------------------------- prefs.json


def _prefs_path() -> str:
    return os.path.join(USER_FILES, pdf_index.SUBDIR, PREFS_FILE)


def _load_prefs() -> dict:
    try:
        with open(_prefs_path(), encoding="utf-8") as f:
            prefs = json.load(f)
        return prefs if isinstance(prefs, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def get_threshold(name: str, cfg: dict) -> float:
    safe = pdf_handler._safe_basename(name)
    entry = _load_prefs().get(safe)
    if isinstance(entry, dict):
        try:
            t = float(entry.get("threshold"))
            if 0.0 < t < 1.0:
                return t
        except (TypeError, ValueError):
            pass
    try:
        return float(cfg.get("pdf_match_threshold") or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


# prefs.json is read-modify-written from the main thread (thresholds) and
# from tag_sync's CollectionOp worker (stored tags); unserialized, one
# writer's change silently erased the other's (K-305).
PREFS_LOCK = threading.RLock()


def set_threshold(name: str, value: float) -> None:
    safe = pdf_handler._safe_basename(name)
    with PREFS_LOCK:
        prefs = _load_prefs()
        prefs.setdefault(safe, {})["threshold"] = round(float(value), 3)
        pdf_handler._atomic_write_json(
            _prefs_path(), prefs, separators=(",", ":")
        )


def threshold_override_names() -> list[str]:
    """Safe basenames of every PDF carrying its own sensitivity override."""
    return sorted(
        safe
        for safe, entry in _load_prefs().items()
        if isinstance(entry, dict) and "threshold" in entry
    )


def clear_threshold_overrides() -> int:
    """Drop every per-PDF sensitivity so all PDFs follow the global default.

    Exists for the Preferences default-sensitivity slider (K-052 rework #2):
    Pouya moved the default and saw nothing change, because every one of his
    PDFs carried its own override and an override always wins — the default
    could not reach a single visible number. When the user says the new
    default should apply everywhere, this is the 'everywhere'.

    Only the ``threshold`` key is removed; any other key an entry carries
    (e.g. a future per-PDF tag) survives, and entries left empty are
    dropped entirely. Returns how many overrides were cleared.
    """
    with PREFS_LOCK:
        prefs = _load_prefs()
        cleared = 0
        for safe in list(prefs):
            entry = prefs[safe]
            if isinstance(entry, dict) and "threshold" in entry:
                del entry["threshold"]
                cleared += 1
                if not entry:
                    del prefs[safe]
        if cleared:
            pdf_handler._atomic_write_json(
                _prefs_path(), prefs, separators=(",", ":")
            )
    return cleared


def forget_prefs(name: str) -> None:
    """Drop ``name``'s entire prefs.json entry.

    Called from ``pdf_handler.delete_context`` when a PDF is deleted:
    prefs.json is a SIBLING of the per-PDF ``contexts``/``pdfs``/
    ``annotations`` directories, so nothing that rmtree's or unlinks
    those can reach it, and a stale entry (threshold, or any other
    per-PDF preference stored here later) would otherwise silently
    resurface if a PDF with the same safe basename is re-imported.
    """
    safe = pdf_handler._safe_basename(name)
    with PREFS_LOCK:
        prefs = _load_prefs()
        if safe in prefs:
            del prefs[safe]
            pdf_handler._atomic_write_json(
                _prefs_path(), prefs, separators=(",", ":")
            )


# --------------------------------------------------- FSRS retrievability


def card_retrievability(
    col, nids: set[int], skip_suspended: bool = False
) -> dict[int, list[tuple[float, bool]]]:
    """nid → [(R, is_new)] per card, computed in bulk from raw SQL.

    FSRS state lives in ``cards.data`` JSON ({"s","d","dr","decay","lrt"}).
    New/unseen cards get R=0 (unlearned material — the strongest "study
    this" signal). Reviewed cards without FSRS state fall back to a crude
    interval-based estimate.
    """
    now = time.time()
    out: dict[int, list[tuple[float, bool]]] = {}
    rows = col.db.all("select id, nid, type, ivl, data from cards")
    suspended = set(col.db.list("select id from cards where queue = -1")) if skip_suspended else set()
    # Lazy revlog fallback for FSRS states missing "lrt" (older versions).
    last_review: dict[int, int] | None = None

    def last_review_secs(cid: int) -> float | None:
        nonlocal last_review
        if last_review is None:
            last_review = {
                int(c): int(t)
                for c, t in col.db.all("select cid, max(id) from revlog group by cid")
            }
        ms = last_review.get(cid)
        return ms / 1000.0 if ms else None

    for cid, nid, ctype, ivl, data in rows:
        nid = int(nid)
        if nid not in nids or cid in suspended:
            continue
        entry: tuple[float, bool]
        state: dict | None = None
        if data:
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    state = parsed
            except (ValueError, TypeError):
                state = None
        s = None
        if state is not None:
            try:
                s = float(state.get("s")) if state.get("s") is not None else None
            except (TypeError, ValueError):
                s = None
        if int(ctype) == 0:
            entry = (0.0, True)  # new card: unlearned
        elif s is not None and s > 0:
            try:
                decay = float(state.get("decay") or 0.5)
            except (TypeError, ValueError):
                decay = 0.5
            lrt = state.get("lrt")
            try:
                lrt_s = float(lrt) if lrt else None
            except (TypeError, ValueError):
                lrt_s = None
            if lrt_s is None:
                lrt_s = last_review_secs(int(cid))
            elapsed = ((now - lrt_s) / 86400.0) if lrt_s else 0.0
            entry = (fsrs_retrievability(s, decay, elapsed), False)
        else:
            lrt_s = last_review_secs(int(cid))
            if lrt_s is None:
                entry = (0.0, True)  # never reviewed despite non-new type
            else:
                elapsed = (now - lrt_s) / 86400.0
                entry = (sm2_retrievability(int(ivl or 0), elapsed), False)
        out.setdefault(nid, []).append(entry)
    return out


def card_queues(col, nids: set[int]) -> dict[int, list[int]]:
    """nid → [queue value per card], from ONE batched query over the pool.

    ``queue == -1`` means suspended; everything else is viewable (new,
    learning, review, buried). Chunked at CARD_QUEUE_CHUNK because
    SQLite's default host-parameter cap is 999 — a 30k-note pool must
    not become 30k placeholders in one statement, and per-row queries
    are the other failure mode this exists to prevent. Sorted pool =
    deterministic chunks (and warmer index walks) for free.
    """
    out: dict[int, list[int]] = {}
    pool = sorted(nids)
    for i in range(0, len(pool), CARD_QUEUE_CHUNK):
        chunk = pool[i : i + CARD_QUEUE_CHUNK]
        marks = ",".join("?" * len(chunk))
        rows = col.db.all(
            f"select nid, queue from cards where nid in ({marks})", *chunk
        )
        for nid, queue in rows:
            out.setdefault(int(nid), []).append(int(queue))
    return out


# ------------------------------------------------------------ aqt pipeline


def _fail(on_error, exc: Exception) -> None:
    curation._fail(on_error, exc)


def ensure_pdf_index(
    parent,
    pdf_name: str,
    *,
    on_progress: ProgressFn | None = None,
    on_done: Callable[[pdf_index.PdfIndex], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    cancel: threading.Event | None = None,
    _reentrant: bool = False,
) -> None:
    """Bring one PDF's page index up to date. Callbacks fire on main.

    Never needs the collection — reading pages hits files, embedding hits
    the provider — so the whole pipeline runs ``without_collection()``.
    Cancellation persists ``embedded_rows``; the next run resumes there.

    Guards ``curation._busy`` — the ONE re-entrancy token shared with the
    card-index sync and ensure_matches below, so a caller composing
    several phases could hold it once across all of them. Pass
    ``_reentrant=True`` when the caller already holds it.

    No caller does. ``index_queue._run`` composes this with the two
    around it and lets each phase take the token in TURN, because its
    cancellation branches return without a release and a held token
    would leak (K-146's finding; the caller this parenthetical used to
    name, ``curation.run_curation``, was deleted by that same card).
    """
    if not _reentrant:
        if curation._busy:
            _fail(
                on_error,
                RuntimeError("Klaus is already indexing — try again in a moment."),
            )
            return
        curation._busy = True

    def release() -> None:
        if not _reentrant:
            curation._busy = False

    def finish_err(exc: Exception) -> None:
        release()
        _fail(on_error, exc)

    def do_build(_col=None) -> pdf_index.PdfIndex:
        cfg = _cfg()
        sig = embeddings.index_signature(cfg)
        src_sig = pdf_index.source_signature(USER_FILES, pdf_name)
        if src_sig is None:
            raise RuntimeError(f"No stored text for “{pdf_name}” — re-import the PDF.")
        dir_path = pdf_index.index_dir(USER_FILES, pdf_name)
        idx = pdf_index.load(dir_path)

        pages = pdf_handler.load_pages(USER_FILES, pdf_name)
        if pages is None:
            # Legacy import without per-page JSON: treat the whole text as one page.
            base = pdf_handler._safe_basename(pdf_name)
            with open(os.path.join(USER_FILES, "contexts", base + ".txt"), encoding="utf-8") as f:
                pages = [f.read()]
        safe = pdf_handler._safe_basename(pdf_name)
        path = pdf_handler.pdf_path_for(USER_FILES, safe) or ""
        page_store.ensure_records(USER_FILES, safe, path, pages)
        rows = page_store.page_texts(USER_FILES, safe, path, len(pages))   # (page, hash, text)
        keys = [(p, h) for p, h, _t in rows]
        # is_fresh() is NOT enough on its own (K-236): it stamps
        # contexts/<safe>.json, and page_store.append_segment writes a page
        # RECORD and never that file — so after a transcript lands the index
        # reads as current and the page's stale hash sits there forever,
        # which made D3's "a page whose transcript grew re-embeds alone"
        # untrue. ensure_records is idempotent, so reading the page keys
        # first costs one pass over the records and buys that sentence back.
        if pdf_index.is_fresh(idx, src_sig, sig) and idx.pages == keys:
            return idx
        if not any(t for _p, _h, t in rows):
            raise RuntimeError(f"“{pdf_name}” has no extractable text to embed.")
        # Keep every row whose hash is unchanged (same provider/model/dims);
        # embed only the rest. Rows are rebuilt in page order.
        old: dict[int, tuple[str, list[float]]] = {}
        if idx is not None and embeddings.signature_matches(idx.provider, idx.model, idx.dims, sig) and idx.dims > 0:
            mv = memoryview(idx.vectors)
            for i, (p, h) in enumerate(idx.pages[: idx.embedded_rows]):
                old[p] = (h, list(mv[i * idx.dims:(i + 1) * idx.dims]))
        new_idx = pdf_index.PdfIndex(provider=sig[0], model=sig[1], pdf_name=safe, source_sig=src_sig, pages=keys,
                                     dims=(idx.dims if idx is not None and old else 0))
        # Empty combined_text (a slide with no text layer and no transcript)
        # is kept out of the provider entirely — some providers reject ""
        # outright — and gets the spec's zero vector instead (seeded below,
        # once dims is known); best_page's plain dot product then scores it
        # 0.0 and it can never win over a real match.
        todo = [(i, t) for i, (p, h, t) in enumerate(rows) if t and not (p in old and old[p][0] == h)]
        vectors_by_row: dict[int, list[float]] = {i: old[p][1] for i, (p, h, _t) in enumerate(rows) if p in old and old[p][0] == h}
        total = len(rows)
        provider = embeddings.provider_from_config(_cfg)
        for offset, vecs in embeddings.embed_batches(provider, [t for _i, t in todo], cancel=cancel, kind="document"):
            for k, vec in enumerate(vecs):
                row_i = todo[offset + k][0]
                if vec is None:
                    if new_idx.dims == 0:
                        raise RuntimeError("First page produced no embedding.")
                    vectors_by_row[row_i] = [0.0] * new_idx.dims
                else:
                    if new_idx.dims == 0:
                        new_idx.dims = len(vec)
                    elif len(vec) != new_idx.dims:
                        raise ValueError("Embedding dims changed mid-index")
                    vectors_by_row[row_i] = vec
            if on_progress:
                mw.taskman.run_on_main(lambda d=len(vectors_by_row): on_progress("Embedding pages…", d, total))
        if new_idx.dims:
            # dims is resolvable here whenever any row was ever embedded —
            # either just now, or earlier (old carries idx.dims forward) —
            # and the any(t for ...) guard above guarantees at least one
            # non-empty row exists, so a first-ever build always sets it.
            for i, (_p, _h, t) in enumerate(rows):
                if not t and i not in vectors_by_row:
                    vectors_by_row[i] = [0.0] * new_idx.dims
        for i in range(total):
            vec = vectors_by_row.get(i)
            if vec is None:
                break  # never embedded (cancelled) — resume here next run
            new_idx.vectors.extend(vec)
            new_idx.embedded_rows += 1
        pdf_index.save(new_idx, dir_path)
        return new_idx

    def done(idx: pdf_index.PdfIndex) -> None:
        release()
        if on_done:
            on_done(idx)

    if on_progress:
        on_progress("Preparing PDF…", 0, 0)
    op = QueryOp(parent=parent, op=lambda col: do_build(), success=done)
    op.failure(finish_err)
    op.without_collection().run_in_background()


def ensure_matches(
    parent,
    pdf_name: str,
    *,
    on_progress: ProgressFn | None = None,
    on_done: Callable[[list[tuple[int, float]]], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    cancel: threading.Event | None = None,
    _reentrant: bool = False,
) -> None:
    """Return cached (or freshly computed) card↔PDF match scores.

    Guards ``curation._busy`` exactly like ensure_pdf_index above — this
    used to run entirely unguarded, letting its O(notes x pages) match
    pass start concurrently with an index build. Pass ``_reentrant=True``
    when a caller already holds the token.
    """
    if not _reentrant:
        if curation._busy:
            _fail(
                on_error,
                RuntimeError("Klaus is already indexing — try again in a moment."),
            )
            return
        curation._busy = True

    def release() -> None:
        if not _reentrant:
            curation._busy = False

    def do_match(_col=None) -> tuple[list[tuple[int, float]], dict[int, int]]:
        cfg = _cfg()
        sig = embeddings.index_signature(cfg)
        src_sig = pdf_index.source_signature(USER_FILES, pdf_name)
        pidx = pdf_index.load(pdf_index.index_dir(USER_FILES, pdf_name))
        if not pdf_index.is_fresh(pidx, src_sig, sig):
            raise RuntimeError(f"“{pdf_name}” isn't embedded yet.")
        cidx = card_index.load(INDEX_DIR)
        if cidx is None or not card_index.check_signature(cidx, sig):
            raise RuntimeError(
                "The card index needs a rebuild — press Index Now in "
                "KlausMate Preferences → Local models first."
            )
        digest = card_index_digest(cidx)
        cached = load_matches(pdf_name, sig, cidx.dims, src_sig, digest)
        if cached is not None:
            return cached

        def prog(done: int, total: int) -> None:
            if on_progress:
                mw.taskman.run_on_main(
                    lambda d=done, t=total: on_progress("Matching cards…", d, t)
                )

        matches, pages = match_scores(
            pidx, cidx, cancel=cancel, on_progress=prog,
            mean=card_index.mean_vector(INDEX_DIR),
        )
        if cancel is not None and cancel.is_set():
            return matches, pages  # partial — do not cache
        matches.sort(key=lambda m: m[1], reverse=True)
        save_matches(pdf_name, sig, cidx.dims, src_sig, digest, matches, pages)
        return best_lecture_filter(matches, sig, cidx.dims, digest), pages

    def done(result: tuple[list[tuple[int, float]], dict[int, int]]) -> None:
        release()
        if on_done:
            on_done(result[0])

    def fail(exc: Exception) -> None:
        release()
        _fail(on_error, exc)

    op = QueryOp(parent=parent, op=lambda col: do_match(), success=done)
    op.failure(fail)
    op.without_collection().run_in_background()


# ------------------------------------------------------------- panel data


def priority_rows(col, cfg: dict) -> dict:
    """Everything the priorities panel needs, in one collection-held pass.

    Uses only cached artifacts (pdf indexes, match caches) — never embeds.
    Freshness flags drive the panel's Embed/Refresh buttons instead.
    Returns {"rows": [...], "approx": bool, "card_r": {nid: [...]},
    "matches", "card_index_ok", "card_queues"} — card_r (and, same trick,
    card_queues) are handed back so threshold changes can re-aggregate
    without the col: pdf_retention and note_card_counts are both pure.

    Count keys per row (K-118, additive — the Library's Cards/Notes split
    and per-PDF suspend read them; every row carries them, unindexed rows
    at 0): ``note_count`` = matched notes at/above the row's threshold,
    ``card_count`` = those notes' cards with queue != -1 (viewable),
    ``suspended_count`` = cards with queue == -1. Aggregated from ONE
    batched nid→queue query (card_queues) over the whole match pool, as
    of each row's CONFIGURED threshold — a live threshold-slider preview
    that re-aggregates retention via card_r can re-derive counts the same
    way from card_queues, or simply show them as-of-configured.
    Right before returning, a retention snapshot per PDF is appended to
    retention_history.json (retention_history.record_rows) — guarded, so
    history can never break the Library.
    """
    sig = embeddings.index_signature(cfg)
    cidx = card_index.load(INDEX_DIR)
    digest = card_index_digest(cidx) if cidx is not None else ""
    card_ok = cidx is not None and card_index.check_signature(cidx, sig)

    fsrs_on = True
    try:
        fsrs_on = bool(col.get_config("fsrs"))
    except Exception:
        pass

    rows: list[dict] = []
    all_matches: dict[str, list[tuple[int, float]]] = {}
    nid_pool: set[int] = set()
    for fname in pdf_handler.list_contexts(USER_FILES):
        name = fname[:-4] if fname.endswith(".txt") else fname
        safe = pdf_handler._safe_basename(name)
        src_sig = pdf_index.source_signature(USER_FILES, name)
        st = pdf_index.stats_from_disk(pdf_index.index_dir(USER_FILES, name))
        indexed = st["exists"] and st["complete"]
        stale = indexed and (
            not embeddings.signature_matches(
                st["provider"], st["model"], st.get("dims", 0), sig
            )
            or src_sig is None
        )
        matches = None
        if indexed and not stale and card_ok:
            cached = load_matches(name, sig, cidx.dims, src_sig, digest)
            if cached is None:
                stale = True  # embedded but matches need a (re)compute
            else:
                matches, _pages = cached
        row = {
            "name": safe,
            "label": name,
            "indexed": bool(indexed),
            "stale": bool(stale),
            "threshold": get_threshold(name, cfg),
            "retention": None,
            "matched_cards": 0,
            "new_pct": 0.0,
            "priority": 0.0,
            "note_count": 0,
            "card_count": 0,
            "suspended_count": 0,
        }
        if matches is not None:
            all_matches[safe] = matches
            nid_pool.update(nid for nid, _ in matches)
        rows.append(row)

    card_r = card_retrievability(col, nid_pool) if nid_pool else {}
    queue_map = card_queues(col, nid_pool) if nid_pool else {}
    for row in rows:
        matches = all_matches.get(row["name"])
        if matches is None:
            continue
        agg_out = pdf_retention(matches, row["threshold"], card_r)
        n_notes, n_viewable, n_suspended = note_card_counts(
            matches, row["threshold"], queue_map
        )
        row.update(
            retention=agg_out["retention"],
            matched_cards=agg_out["matched_cards"],
            new_pct=agg_out["new_pct"],
            priority=agg_out["priority"],
            note_count=n_notes,
            card_count=n_viewable,
            suspended_count=n_suspended,
        )
    rows.sort(key=lambda r: (r["retention"] is None, -r["priority"], r["label"]))
    try:
        # Lazy import inside the guard: even an import-time failure in the
        # history module must degrade to a log line, never a dead Library.
        from . import retention_history

        retention_history.record_rows(USER_FILES, rows)
    except Exception as exc:
        print(f"[klausmate] retention history not recorded: {exc}")
    return {
        "rows": rows,
        "approx": not fsrs_on,
        "card_r": card_r,
        "matches": all_matches,
        "card_index_ok": card_ok,
        "card_queues": queue_map,
    }
