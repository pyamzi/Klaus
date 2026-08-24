"""PDF study priorities — retention scoring of cards matched to each PDF.

Pipeline per PDF: embed its chunks persistently (pdf_index.py) → score every
indexed note against those chunks (max cosine, cached in matches.json) →
pull FSRS retrievability for the matched notes' cards → aggregate a
similarity-weighted retention score → rank PDFs by study priority.

Layout mirrors curation.py: pure math helpers up top (headlessly testable),
aqt glue below. Long work runs on QueryOp workers; embedding and matching
run ``without_collection()``.

Match cache invalidation: matches.json records the (provider, model, dims)
signature, the PDF's source signature, AND a digest of the card index's
(hashes, nids). The digest — not ``updated_at`` — is deliberate: Browse
previews bulk-tag notes, which bumps mods and resaves the card index
without changing any text; hashes+nids move only when content or
membership really changed.

Preview vehicle: the temp tag ``!Library::Matching`` (distinct from
curation's ``!Library::Curating`` so a priorities click never clobbers an
in-flight curation preview).
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import threading
import time
from typing import Any, Callable

import aqt
from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.utils import tooltip

from . import card_index, curation, embeddings, pdf_handler, pdf_index

USER_FILES = curation.USER_FILES
INDEX_DIR = curation.INDEX_DIR

RETENTION_TAG = "!Library::Matching"
MATCHES_FILE = "matches.json"
PREFS_FILE = "prefs.json"
MATCHES_VERSION = 1

# Cache floor for match scores — deliberately far below any usable
# threshold, so the panel's threshold slider is a pure re-filter of the
# cached list and never triggers a recompute.
MATCH_FLOOR = 0.15

DEFAULT_THRESHOLD = 0.55
_LEGACY_DEFAULT_THRESHOLD = 0.35  # the retired global default, one-time migrated up
DEFAULT_AGG = "max"
DEFAULT_MAX_CHUNKS = 1000

PDF_FLUSH_EVERY = 256  # vectors between partial saves while embedding a PDF

ProgressFn = Callable[[str, int, int], None]

try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))


def _migrate_default_threshold(cfg: dict) -> dict:
    """One-time bump of a stored 0.35 (the retired global default) up to
    0.55 (Pouya's chosen default) — guarded so it runs exactly once per
    profile and never touches a value someone set deliberately.

    Only the GLOBAL config's ``pdf_match_threshold`` is in scope here.
    Per-PDF prefs.json entries (set_threshold/get_threshold) are a user
    choice "saved forever" and this never reads or writes prefs.json.
    """
    if cfg.get("_threshold_default_migrated"):
        return cfg
    cfg = dict(cfg)
    try:
        current = float(cfg.get("pdf_match_threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        current = None
    if current == _LEGACY_DEFAULT_THRESHOLD:
        cfg["pdf_match_threshold"] = DEFAULT_THRESHOLD
    cfg["_threshold_default_migrated"] = True
    try:
        mw.taskman.run_on_main(lambda c=cfg: curation._pkg().write_config(c))
    except Exception as e:
        print(f"[klausmate] threshold default migration failed: {e}")
    return cfg


def _cfg() -> dict:
    """The global config, with the one-time threshold-default migration
    applied. This is the canonical config accessor for retention/curation's
    shared, threshold-scoped reads — curation._cfg() itself stays a plain
    pass-through so unrelated config reads (embedding signature, etc.)
    don't carry this side effect."""
    return _migrate_default_threshold(curation._cfg())


# ------------------------------------------------------------ pure helpers


def card_index_digest(cidx: card_index.CardIndex) -> str:
    """Content digest of the card index — moves only when note text or
    membership changes (mod-only resaves keep it stable)."""
    payload = ",".join(cidx.hashes) + ";" + ",".join(str(n) for n in cidx.nids)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


def match_scores(
    pdf_idx: pdf_index.PdfIndex,
    cidx: card_index.CardIndex,
    agg: str = DEFAULT_AGG,
    floor: float = MATCH_FLOOR,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[int, float]]:
    """Score every indexed note against the PDF's chunks → [(nid, score)].

    ``agg``: "max" (best single chunk) or "top3_mean" (mean of the 3 best —
    stricter, suppresses one-off spurious hits). Both indexes hold unit
    vectors, so similarity is a plain dot product.
    """
    if (pdf_idx.provider, pdf_idx.model) != (cidx.provider, cidx.model):
        raise ValueError(
            "Embedding spaces differ between the PDF index and the card index"
            " — re-embed the PDF."
        )
    if pdf_idx.dims != cidx.dims:
        raise ValueError("Embedding dimensions differ — re-embed the PDF.")
    d = cidx.dims
    n_chunks = pdf_idx.embedded_rows
    if not cidx.nids or not n_chunks or d <= 0:
        return []
    cmv = memoryview(cidx.vectors)
    pmv = memoryview(pdf_idx.vectors)
    chunk_rows = [pmv[j * d : (j + 1) * d] for j in range(n_chunks)]
    top3 = agg == "top3_mean"
    out: list[tuple[int, float]] = []
    total = len(cidx.nids)
    for i, nid in enumerate(cidx.nids):
        if cancel is not None and i % 512 == 0 and cancel.is_set():
            return out
        if on_progress and i % 512 == 0:
            on_progress(i, total)
        row = cmv[i * d : (i + 1) * d]
        if top3:
            best = heapq.nlargest(3, (_sumprod(row, c) for c in chunk_rows))
            score = sum(best) / len(best)
        else:
            score = max(_sumprod(row, c) for c in chunk_rows)
        if score >= floor:
            out.append((nid, score))
    return out


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


# ------------------------------------------------------- matches.json cache


def _matches_path(name: str) -> str:
    return os.path.join(pdf_index.index_dir(USER_FILES, name), MATCHES_FILE)


def load_matches(
    name: str,
    signature: tuple[str, str],
    dims: int,
    source_sig: tuple[int, int] | None,
    digest: str,
    agg: str,
) -> list[tuple[int, float]] | None:
    """Cached [(nid, score)] when every invalidation key matches, else None."""
    try:
        with open(_matches_path(name), encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version") != MATCHES_VERSION:
            return None
        if (str(m["provider"]), str(m["model"])) != signature:
            return None
        if int(m["dims"]) != dims:
            return None
        sig = m.get("pdf_source_sig") or [0, 0]
        if source_sig is None or (int(sig[0]), int(sig[1])) != source_sig:
            return None
        if str(m.get("card_index_digest")) != digest:
            return None
        if str(m.get("agg")) != agg:
            return None
        if float(m.get("floor", -1.0)) != MATCH_FLOOR:
            # MATCH_FLOOR changed since this cache was written — a cache
            # built with a different floor could be silently missing rows
            # that should now be included. Treat as cold, never stale-valid.
            return None
        return [(int(nid), float(score)) for nid, score in m["matches"]]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_matches(
    name: str,
    signature: tuple[str, str],
    dims: int,
    source_sig: tuple[int, int],
    digest: str,
    agg: str,
    matches: list[tuple[int, float]],
) -> None:
    payload = {
        "version": MATCHES_VERSION,
        "provider": signature[0],
        "model": signature[1],
        "dims": dims,
        "pdf_source_sig": list(source_sig),
        "card_index_digest": digest,
        "agg": agg,
        "floor": MATCH_FLOOR,
        "matches": [[nid, round(score, 6)] for nid, score in matches],
    }
    path = _matches_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)


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


def set_threshold(name: str, value: float) -> None:
    safe = pdf_handler._safe_basename(name)
    prefs = _load_prefs()
    prefs.setdefault(safe, {})["threshold"] = round(float(value), 3)
    path = _prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, separators=(",", ":"))
    os.replace(tmp, path)


# --------------------------------------------------- FSRS retrievability


def card_retrievability(col, nids: set[int]) -> dict[int, list[tuple[float, bool]]]:
    """nid → [(R, is_new)] per card, computed in bulk from raw SQL.

    FSRS state lives in ``cards.data`` JSON ({"s","d","dr","decay","lrt"}).
    New/unseen cards get R=0 (unlearned material — the strongest "study
    this" signal). Reviewed cards without FSRS state fall back to a crude
    interval-based estimate.
    """
    now = time.time()
    out: dict[int, list[tuple[float, bool]]] = {}
    rows = col.db.all("select id, nid, type, ivl, data from cards")
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
        if nid not in nids:
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
    """Bring one PDF's chunk index up to date. Callbacks fire on main.

    Never needs the collection — chunking reads files, embedding hits the
    provider — so the whole pipeline runs ``without_collection()``.
    Cancellation persists ``embedded_rows``; the next run resumes there.

    Guards ``curation._busy`` — the ONE re-entrancy token shared with the
    card-index sync and ensure_matches below, so a caller composing several
    phases (curation.run_curation) can hold it once across all of them.
    Pass ``_reentrant=True`` when the caller already holds it.
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
        try:
            max_chunks = int(cfg.get("pdf_index_max_chunks") or DEFAULT_MAX_CHUNKS)
        except (TypeError, ValueError):
            max_chunks = DEFAULT_MAX_CHUNKS
        src_sig = pdf_index.source_signature(USER_FILES, pdf_name)
        if src_sig is None:
            raise RuntimeError(f"No stored text for “{pdf_name}” — re-import the PDF.")
        dir_path = pdf_index.index_dir(USER_FILES, pdf_name)
        idx = pdf_index.load(dir_path)
        if pdf_index.is_fresh(idx, src_sig, sig):
            return idx

        pages = pdf_handler.load_pages(USER_FILES, pdf_name)
        if pages is None:
            # Legacy import without per-page JSON: treat the whole text as one page.
            base = pdf_handler._safe_basename(pdf_name)
            txt_path = os.path.join(USER_FILES, "contexts", base + ".txt")
            with open(txt_path, encoding="utf-8") as f:
                pages = [f.read()]
        chunked = pdf_index.chunk_pages(pages, max_chunks)
        if not chunked:
            raise RuntimeError(f"“{pdf_name}” has no extractable text to embed.")
        keys = [(p, s, ln) for p, s, ln, _t in chunked]
        texts = [t for _p, _s, _ln, t in chunked]

        resumable = (
            idx is not None
            and (idx.provider, idx.model) == sig
            and idx.source_sig == src_sig
            and idx.chunks == keys
            and 0 < idx.embedded_rows < len(keys)
        )
        if not resumable:
            safe = pdf_handler._safe_basename(pdf_name)
            idx = pdf_index.PdfIndex(
                provider=sig[0], model=sig[1], pdf_name=safe,
                source_sig=src_sig, chunks=keys,
            )
        start_row = idx.embedded_rows
        todo = texts[start_row:]
        total = len(texts)
        provider = embeddings.provider_from_config(_cfg)
        since_flush = 0
        for offset, vecs in embeddings.embed_batches(
            provider, todo, cancel=cancel, kind="document"
        ):
            for vec in vecs:
                if vec is None:
                    # Zero vector (empty-ish chunk) — keep row alignment with
                    # a null vector; it can't win a cosine match.
                    if idx.dims == 0:
                        raise RuntimeError("First PDF chunk produced no embedding.")
                    idx.vectors.extend([0.0] * idx.dims)
                else:
                    if idx.dims == 0:
                        idx.dims = len(vec)
                    elif len(vec) != idx.dims:
                        raise ValueError("Embedding dims changed mid-index")
                    idx.vectors.extend(vec)
                idx.embedded_rows += 1
            since_flush += len(vecs)
            if on_progress:
                done = idx.embedded_rows
                mw.taskman.run_on_main(
                    lambda d=done: on_progress("Embedding PDF…", d, total)
                )
            if since_flush >= PDF_FLUSH_EVERY:
                pdf_index.save(idx, dir_path)
                since_flush = 0
        pdf_index.save(idx, dir_path)
        return idx

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
    used to run entirely unguarded, letting its O(notes x chunks) match
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

    def do_match(_col=None) -> list[tuple[int, float]]:
        cfg = _cfg()
        sig = embeddings.index_signature(cfg)
        agg = str(cfg.get("pdf_match_agg") or DEFAULT_AGG)
        src_sig = pdf_index.source_signature(USER_FILES, pdf_name)
        pidx = pdf_index.load(pdf_index.index_dir(USER_FILES, pdf_name))
        if not pdf_index.is_fresh(pidx, src_sig, sig):
            raise RuntimeError(f"“{pdf_name}” isn't embedded yet.")
        cidx = card_index.load(INDEX_DIR)
        if cidx is None or not card_index.check_signature(cidx, sig):
            raise RuntimeError(
                "The card index needs a rebuild — run a search or re-index "
                "from Manage models first."
            )
        digest = card_index_digest(cidx)
        cached = load_matches(pdf_name, sig, cidx.dims, src_sig, digest, agg)
        if cached is not None:
            return cached

        def prog(done: int, total: int) -> None:
            if on_progress:
                mw.taskman.run_on_main(
                    lambda d=done, t=total: on_progress("Matching cards…", d, t)
                )

        matches = match_scores(
            pidx, cidx, agg=agg, cancel=cancel, on_progress=prog
        )
        if cancel is not None and cancel.is_set():
            return matches  # partial — do not cache
        matches.sort(key=lambda m: m[1], reverse=True)
        save_matches(pdf_name, sig, cidx.dims, src_sig, digest, agg, matches)
        return matches

    def done(matches: list[tuple[int, float]]) -> None:
        release()
        if on_done:
            on_done(matches)

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
    Returns {"rows": [...], "approx": bool, "card_r": {nid: [...]}} — card_r
    is handed back so threshold changes can re-aggregate without the col.
    """
    sig = embeddings.index_signature(cfg)
    agg = str(cfg.get("pdf_match_agg") or DEFAULT_AGG)
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
            (st["provider"], st["model"]) != sig
            or src_sig is None
        )
        matches = None
        if indexed and not stale and card_ok:
            matches = load_matches(name, sig, cidx.dims, src_sig, digest, agg)
            if matches is None:
                stale = True  # embedded but matches need a (re)compute
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
        }
        if matches is not None:
            all_matches[safe] = matches
            nid_pool.update(nid for nid, _ in matches)
        rows.append(row)

    card_r = card_retrievability(col, nid_pool) if nid_pool else {}
    for row in rows:
        matches = all_matches.get(row["name"])
        if matches is None:
            continue
        agg_out = pdf_retention(matches, row["threshold"], card_r)
        row.update(
            retention=agg_out["retention"],
            matched_cards=agg_out["matched_cards"],
            new_pct=agg_out["new_pct"],
            priority=agg_out["priority"],
        )
    rows.sort(key=lambda r: (r["retention"] is None, -r["priority"], r["label"]))
    return {
        "rows": rows,
        "approx": not fsrs_on,
        "card_r": card_r,
        "matches": all_matches,
        "card_index_ok": card_ok,
    }


# ------------------------------------------------------------- Browse hop


def preview_matches(parent, nids: list[int]) -> None:
    """Swap the pdfmatch tag onto the given notes, then open Browse on it."""

    def op(col):
        pos = col.add_custom_undo_entry("Klaus: preview PDF matches")
        stale = col.find_notes(f'tag:"{RETENTION_TAG}"')
        if stale:
            col.tags.bulk_remove(list(stale), RETENTION_TAG)
        col.tags.bulk_add(list(nids), RETENTION_TAG)
        return col.merge_undo_entries(pos)

    def done(_changes) -> None:
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(f'tag:"{RETENTION_TAG}"')

    CollectionOp(parent=parent, op=op).success(done).run_in_background()


def clear_pdfmatch_tag(parent=None, *, quiet: bool = False) -> None:
    """Tools-menu escape hatch: drop the pdfmatch tag from every note.

    ``quiet`` suppresses this function's own tooltip (both the "nothing to
    clear" early-out and the success summary) — for a caller that reports
    its own combined result instead. Default False keeps every existing
    caller's behavior unchanged.
    """
    parent = parent or mw
    nids = mw.col.find_notes(f'tag:"{RETENTION_TAG}"') if mw.col else []
    if not nids:
        if not quiet:
            tooltip("No notes carry the Klaus PDF-match tag.", parent=parent)
        return

    def op(col):
        pos = col.add_custom_undo_entry("Klaus: clear PDF-match tag")
        col.tags.bulk_remove(list(nids), RETENTION_TAG)
        return col.merge_undo_entries(pos)

    op_result = CollectionOp(parent=parent, op=op)
    if not quiet:
        op_result = op_result.success(
            lambda _c: tooltip(
                f"Cleared the PDF-match tag from {len(nids)} notes.", parent=parent
            )
        )
    op_result.run_in_background()
