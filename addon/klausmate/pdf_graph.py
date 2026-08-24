"""Graph data for the future embedding map (K-058 Phase D) — headless data
assembly only, no window/canvas. That comes in the next card; this one
just produces the JSON-shaped dict a canvas will eventually render.

Layout: PDF nodes at the centroid of their matched notes' 2D positions,
note nodes at their own 2D position, edges PDF->nid for every match
at-or-above that PDF's sensitivity threshold. All positions come from
``projection.project`` over the card index's embedding vectors.

No Qt import anywhere at module top — ``card_index``, ``pdf_index``,
``pdf_handler``, ``drive_store`` and ``projection`` are all aqt-free, so
this module stays importable headless. ``retention`` is the one sibling
module this needs (for its ``matches.json`` cache reader and per-PDF
threshold) and it imports ``aqt`` at its own module top, so it is
imported lazily *inside* ``build_graph_data`` rather than at this
module's top level — matching the deferred-import convention
``retention.py``'s own docstring describes for its aqt-heavy half.

Vector access: both ``card_index.load`` and ``pdf_index.load`` are the
public loaders for their storage formats (see CLAUDE.md's module map) —
no loader is missing, so nothing was added to either module. This file
only ever reads the *card* index directly (for note positions); PDF-side
vectors are never read here at all — the PDF->note relationship comes
entirely from the already-computed ``matches.json`` cache via
``retention.load_matches``, never from re-scoring chunk vectors.

Match-cache semantics: ``retention.load_matches`` returns ``None`` when
the cache is missing OR any of its invalidation keys (signature, dims,
source signature, card-index digest, aggregation mode) don't match what
this call expects. Either way that means "unknown" — this module skips
that PDF entirely (no node, no edges) rather than inventing an empty or
stale match set for it.

Sampling tradeoff: ``projection.project`` caps how many notes get a 2D
position (``projection.DEFAULT_MAX_POINTS``, even-stride sampled). A
PDF's cached matches are computed against the FULL card index, so on a
large collection most of a PDF's real matches may fall outside the
sampled/positioned subset; only the intersection is used for that PDF's
centroid and edges. A PDF left with zero matches inside the sample is
skipped the same as a genuinely absent cache — there is no positioned
note to anchor it to. A future revision of the canvas card may widen the
sample for PDFs specifically, but that is out of scope here.
"""

from __future__ import annotations

import os

from . import card_index, drive_store, pdf_handler, pdf_index, projection

CARD_INDEX_SUBDIR = "card_index"


def build_graph_data(user_files: str, cfg: dict) -> dict:
    """Assemble the map's node/edge data from on-disk caches only.

    Never embeds, never re-scores, never touches the collection — every
    number here comes from a persisted index or cache. Returns
    ``{"pdfs": [...], "notes": [...], "edges": [...]}``:

    - ``notes``: ``{"nid": int, "xy": [x, y]}`` for every positioned note
      (a subset of the card index when it exceeds
      ``projection.DEFAULT_MAX_POINTS``).
    - ``pdfs``: ``{"safe", "display", "folder", "threshold", "retention",
      "xy", "match_count"}`` per PDF that has a valid match cache AND at
      least one matched, positioned note. ``retention`` is always
      ``None`` here — the FSRS-based score needs a live collection
      (``retention.card_retrievability``), which this headless function
      never has; a caller with a collection open can fill that in
      separately.
    - ``edges``: ``{"pdf": safe_name, "nid": int, "score": float}`` for
      every match at-or-above that PDF's threshold, restricted to
      positioned notes.
    """
    cidx = card_index.load(os.path.join(user_files, CARD_INDEX_SUBDIR))
    if cidx is None or not cidx.nids or cidx.dims <= 0:
        return {"pdfs": [], "notes": [], "edges": []}

    d = cidx.dims
    mv = memoryview(cidx.vectors)
    row_views = [mv[i * d:(i + 1) * d] for i in range(len(cidx.nids))]
    points, sampled = projection.project(row_views)
    note_xy: dict[int, tuple[float, float]] = {
        cidx.nids[row_idx]: pt for row_idx, pt in zip(sampled, points)
    }
    notes = [{"nid": nid, "xy": [xy[0], xy[1]]} for nid, xy in note_xy.items()]

    # Deferred: retention.py imports aqt at module top (see module
    # docstring above); importing it here keeps this module's own top
    # level Qt-free so it stays importable with no Anki present.
    from . import retention

    # retention.load_matches reads user_files/pdf_index/<safe>/matches.json
    # via a MODULE-GLOBAL path (retention.USER_FILES), not a parameter —
    # it has no per-call user_files argument to pass. Pointing that global
    # at THIS call's user_files is the same redirection
    # tests/test_klausmate.py already relies on to point retention at a
    # scratch dir; in production user_files is always curation.USER_FILES
    # already, so this is a no-op there.
    retention.USER_FILES = user_files

    sig = (cidx.provider, cidx.model)
    agg = str(cfg.get("pdf_match_agg") or retention.DEFAULT_AGG)
    digest = retention.card_index_digest(cidx)
    drive = drive_store.load(user_files)

    pdfs: list[dict] = []
    edges: list[dict] = []
    for fname in pdf_handler.list_contexts(user_files):
        name = fname[:-4] if fname.endswith(".txt") else fname
        safe = pdf_handler._safe_basename(name)
        src_sig = pdf_index.source_signature(user_files, name)
        matches = retention.load_matches(name, sig, cidx.dims, src_sig, digest, agg)
        if matches is None:
            continue  # unknown -- never invent an empty match set

        threshold = retention.get_threshold(name, cfg)
        hits = [
            (nid, score)
            for nid, score in matches
            if score >= threshold and nid in note_xy
        ]
        if not hits:
            continue

        xs = [note_xy[nid][0] for nid, _ in hits]
        ys = [note_xy[nid][1] for nid, _ in hits]
        centroid = (sum(xs) / len(xs), sum(ys) / len(ys))
        entry = drive["pdfs"].get(safe) or {}
        pdfs.append(
            {
                "safe": safe,
                "display": str(entry.get("display") or name),
                "folder": entry.get("folder"),
                "threshold": threshold,
                "retention": None,
                "xy": [centroid[0], centroid[1]],
                "match_count": len(hits),
            }
        )
        edges.extend({"pdf": safe, "nid": nid, "score": score} for nid, score in hits)

    return {"pdfs": pdfs, "notes": notes, "edges": edges}
