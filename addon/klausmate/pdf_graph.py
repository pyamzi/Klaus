"""Graph data for the future embedding map (K-058 Phase D) — headless data
assembly only, no window/canvas. That comes in the next card; this one
just produces the JSON-shaped dict a canvas will eventually render.

Layout: PDF nodes at the centroid of their matched notes' 3D positions,
note nodes at their own 3D position, edges PDF->nid for every match
at-or-above that PDF's sensitivity threshold. All positions come from
``projection.project`` over the card index's embedding vectors — three
principal components since K-148, so the map has a real depth axis to
rotate around rather than a decorative one. The key is ``xyz``; it held
two numbers under the key ``xy`` until then, and ``pdf_map`` still reads
a two-component row as a point on the z=0 plane.

No Qt import anywhere at module top — ``card_index``, ``pdf_index``,
``pdf_handler``, ``drive_store`` and ``projection`` are all aqt-free, so
this module stays importable headless. ``retention`` is the one sibling
module this needs (for its ``matches.json`` cache reader and per-PDF
threshold) and it imports ``aqt`` at its own module top, so it is
imported lazily *inside* ``build_graph_data`` rather than at this
module's top level — matching the deferred-import convention
``retention.py``'s own docstring describes for its aqt-heavy half.

Cached (K-167): the positions are a pure function of the card index, so
they are persisted to ``user_files/map_layout/layout.bin`` and read back
on a repeat open — 29.5 s becomes 0.04 s. The key is the card index and
nothing else, so a sensitivity edit, a re-tagged PDF or a new match
cache still land on the very next open; only a changed, re-embedded or
re-widened index pays for a projection. See the LAYOUT CACHE block below
for the invalidation keys and for the measurement that ruled out also
caching the fit.

Vector access: both ``card_index.load`` and ``pdf_index.load`` are the
public loaders for their storage formats (see CLAUDE.md's module map) —
no loader is missing, so nothing was added to either module. This file
only ever reads the *card* index directly (for note positions); PDF-side
vectors are never read here at all — the PDF->note relationship comes
entirely from the already-computed ``matches.json`` cache via
``retention.load_matches``, never from re-scoring page vectors.

Match-cache semantics: ``retention.load_matches`` returns ``None`` when
the cache is missing OR any of its invalidation keys (signature, dims,
source signature, card-index digest) don't match what
this call expects. Either way that means "unknown" — this module skips
that PDF entirely (no node, no edges) rather than inventing an empty or
stale match set for it.

No sampling tradeoff any more (K-138): ``projection.project`` fits its
components on an even-stride sample (``DEFAULT_FIT_ROWS``) but
positions EVERY row, so a PDF's centroid and edges are computed over
all of its cached matches rather than over whichever ones happened to
land in a sample. The paragraph that used to sit here described the
opposite — most of a large collection's matches falling outside the
positioned subset, and PDFs skipped for having none inside it — and was
the reason Pouya asked for "all of the notes to show up".

**K-158 samples for DISPLAY, and deliberately not here.** The map now
draws a few hundred dots instead of 28,668, but that sample is taken by
``pdf_map.split_cloud`` at paint time, off a graph that still holds
every note. Thinning the graph instead would be wrong twice over: a
PDF's centroid and its edge set are statistics over the whole match
set, so computing them from a sample would move the nodes and change
which notes a PDF is said to reach; and ``map_canvas(parent, graph)``
is a public seam whose sampling policy belongs to the renderer, not to
the data. This function stays the complete, honest answer — the caption
can only say "28,670 notes, showing 643" because that is true.
"""

from __future__ import annotations

import json
import os
import uuid
from array import array

from . import (
    card_index,
    drive_store,
    embeddings,
    pdf_handler,
    pdf_index,
    projection,
)
from . import settings

CARD_INDEX_SUBDIR = "card_index"

# --------------------------------------------------------- layout cache
#
# K-167. Measured on Pouya's real 28,670-note index: build_graph_data took
# 29.5 s, of which projection.project was 29.47 s and the FIT inside it
# 29.29 s. Everything else this function does — the card index off disk,
# every match cache, the drive store — is 0.07 s put together. So the map's
# whole wait was one PCA recomputed from scratch on every open, of a layout
# that is a pure function of the card index (projection.project is seeded
# and deterministic by its own contract). It is cached here instead:
# ~0.04 s to reopen, all of it the 88 MB vector read the digest needs.
#
# POSITIONS ONLY — the fit is deliberately NOT cached, and this is the one
# decision in the file worth defending, because caching it looks free.
# The idea was that a mean plus three 768-d component vectors is 25 KB and
# statistically stable, so a changed index could re-score in 2 s off an old
# fit instead of refitting for 29 s. Measured against the real index rather
# than assumed, and it is false:
#
#     perturbation of the index      median note moves   worst note
#     50 of 28,670 notes deleted      0.073  (~24 px)     ~70 px
#     50 notes added                  0.241  (~80 px)    ~197 px
#     same data, resampled            0.449 (~150 px)    ~391 px
#
#   (normalized [-1, 1] units, where 0.003 is about a pixel on a 700 px
#    canvas; the add/resample rows are after optimally aligning axis SIGNS,
#    which are arbitrary in PCA and would otherwise flatter nothing.)
#
# The last row is the diagnosis and it has nothing to do with caching: the
# SAME 28,670 vectors, fitted from a different even-stride 4,000, move the
# median note 150 px. The cloud is nearly isotropic — the three principal
# axes have standard deviations 0.1332, 0.1236, 0.1190, i.e. no eigengap
# worth the name — so components 2 and 3 are not determined by a 4,000-row
# sample at all: under a resample they SWAP (|<v2, v3'>| = 0.86 against a
# diagonal of 0.45). Only the three-dimensional SUBSPACE is stable, to
# 6-18 degrees. That also retro-explains K-148's non-monotone iteration
# table: power iteration separates two components at a rate set by their
# variance ratio, and 0.93^40 is 0.05, so the third axis was never going to
# converge in 40 passes no matter how many it got.
#
# Two consequences. Fit reuse would show a picture that depends on when the
# cache last went cold — hidden state, and visibly the wrong map by the only
# criterion that matters here, which is Pouya looking at his own collection.
# And separately: this layout is intrinsically unstable under index growth,
# today, cache or no cache. Fixing THAT means fitting on more rows (or
# on a stable basis), not caching harder, and it is not this card.
LAYOUT_SUBDIR = "map_layout"
LAYOUT_FILE = "layout.bin"
LAYOUT_VERSION = 1
# The seed build_graph_data projects with. Named rather than left to
# project()'s default because the cache KEYS on it: a value that can move
# without the key noticing is how a cache serves the wrong picture.
PROJECTION_SEED = 0


def _layout_params() -> dict:
    """Everything about the projection that moves where a point lands.

    Named values rather than a version bump, so a reader who retunes
    MAX_ITERATIONS invalidates the cache without having to know one exists.
    """
    return {
        "components": int(projection.COMPONENTS),
        "iterations": int(projection.MAX_ITERATIONS),
        "fit_rows": int(projection.DEFAULT_FIT_ROWS),
        "seed": int(PROJECTION_SEED),
    }


def _signature_ok(header: dict, signature: tuple) -> bool:
    """True when a stored layout's embedding space is the one we want.

    The digest alone cannot answer this: it is built from note TEXT hashes
    and nids, so re-embedding the whole collection on a new provider, model
    or width leaves it bit-identical while every vector — and therefore
    every position — changes underneath. Delegated to
    ``embeddings.signature_matches`` and never spelled here: a hand-written
    tuple comparison is what read every cache as stale and silently
    re-embedded a paid collection when the signature grew a third element.
    """
    return embeddings.signature_matches(
        str(header["provider"]),
        str(header["model"]),
        int(header["dims"]),
        signature,
    )


def _read_prior_layout(
    user_files: str, signature: tuple
) -> tuple[list[tuple[float, ...]], list[int]] | None:
    """Whatever positions are on disk for THIS embedding space, regardless
    of whether the card index has since changed — the alignment anchor
    K-171 rotates a fresh layout onto (see ``projection.align_to`` and the
    module docstring's isotropy finding: a resample or an add/delete can
    swap PC2/PC3 outright, and this is the previous picture to stay
    continuous with).

    Deliberately looser than ``_read_layout``: it ignores the digest and
    row count entirely, because those are exactly what a note add/delete/
    edit changes, and an anchor that required them unchanged would never
    fire for the case this exists to fix. A different embedding space
    (provider/model/dims) is still refused — those coordinates mean
    nothing here — and so is anything that cannot name its own rows'
    identities (an older-format cache with no ``nids``, or a corrupt one),
    since alignment cannot pair points it cannot identify. None always
    means "nothing to align to", never a partial answer.
    """
    blob = _read_blob(os.path.join(user_files, LAYOUT_SUBDIR, LAYOUT_FILE))
    if blob is None:
        return None
    header, values = blob
    try:
        if header.get("version") != LAYOUT_VERSION:
            return None
        if not _signature_ok(header, signature):
            return None
        comps = int(header["params"]["components"])
        if comps != projection.COMPONENTS or comps <= 0:
            return None
        nids = header.get("nids")
        stored = int(header["rows"])
        if (
            not isinstance(nids, list)
            or len(nids) != stored
            or len(values) != stored * comps
        ):
            return None
        nids = [int(n) for n in nids]
    except (KeyError, TypeError, ValueError):
        return None
    points = list(zip(*(values[k::comps] for k in range(comps))))
    return points, nids


def _write_blob(path: str, header: dict, values: array) -> None:
    """One self-describing artifact: a JSON header line, then packed
    float64. Atomic tmp + ``os.replace``, retention_history's shape.

    Header and body live in ONE file on purpose. Split across two, a
    concurrent writer (both map hosts build this off the UI thread) could
    pair a fresh header with a stale body — both the right SIZE, so no
    length check would catch it, and the map would be drawn from another
    index's coordinates without a word.
    """
    dest = os.path.dirname(path) or "."
    os.makedirs(dest, exist_ok=True)
    tmp = os.path.join(dest, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(json.dumps(header, separators=(",", ":")).encode("utf-8"))
            f.write(b"\n")
            f.write(values.tobytes())
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_blob(path: str) -> tuple[dict, array] | None:
    """``(header, values)``, or None for anything at all wrong with the
    file — missing, empty, truncated, hand-edited, half-written."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        cut = raw.find(b"\n")
        if cut < 0:
            return None
        header = json.loads(raw[:cut].decode("utf-8"))
        if not isinstance(header, dict):
            return None
        values = array("d")
        body = raw[cut + 1:]
        if len(body) % values.itemsize:
            return None
        values.frombytes(body)
        return header, values
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _read_layout(
    user_files: str, signature: tuple, digest: str, rows: int
) -> list | None:
    """Cached positions when EVERY invalidation key matches, else None.

    None always means "unknown, recompute" — never a partial or
    best-effort answer. A corrupt file reads exactly like an absent one.
    """
    blob = _read_blob(os.path.join(user_files, LAYOUT_SUBDIR, LAYOUT_FILE))
    if blob is None:
        return None
    header, values = blob
    params = _layout_params()
    try:
        if header.get("version") != LAYOUT_VERSION:
            return None
        if not _signature_ok(header, signature):
            return None
        if header.get("params") != params:
            return None
        if str(header.get("digest")) != digest:
            return None
        comps = int(params["components"])
        stored = int(header["rows"])
        if stored != rows or comps <= 0 or len(values) != stored * comps:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return list(zip(*(values[k::comps] for k in range(comps))))


def _write_layout(
    user_files: str, signature: tuple, digest: str, points: list, nids: list
) -> None:
    """Persist positions AND the note ids they belong to. A cache that
    cannot be written is not an error — it costs the next open a refit,
    which is exactly the status quo.

    ``nids`` is new for K-171: the exact-match read below never needed it
    (a matching digest already guarantees the same nids in the same
    order), but ``_read_prior_layout`` does — it is read back precisely
    when the digest DOESN'T match, to pair up whichever notes the old and
    new layouts still share.
    """
    params = _layout_params()
    comps = int(params["components"])
    flat = array("d")
    for p in points:
        flat.extend(p)
    if comps <= 0 or len(flat) != len(points) * comps or len(nids) != len(points):
        return  # a point of unexpected width would never read back
    header = {
        "version": LAYOUT_VERSION,
        "provider": str(signature[0]),
        "model": str(signature[1]),
        "dims": int(signature[2]) if len(signature) > 2 else 0,
        "digest": str(digest),
        "rows": len(points),
        "params": params,
        "nids": [int(n) for n in nids],
    }
    try:
        _write_blob(
            os.path.join(user_files, LAYOUT_SUBDIR, LAYOUT_FILE), header, flat
        )
    except OSError:
        pass


def build_graph_data(user_files: str, cfg: dict) -> dict:
    """Assemble the map's node/edge data from on-disk caches only.

    Never embeds, never re-scores, never touches the collection — every
    number here comes from a persisted index or cache. Returns
    ``{"pdfs": [...], "notes": [...], "edges": [...]}``:

    - ``notes``: ``{"nid": int, "xyz": [x, y, z]}`` for EVERY note in
      the card index — ``DEFAULT_FIT_ROWS`` bounds what the PCA is
      fitted on, not what comes back.
    - ``pdfs``: ``{"safe", "display", "folder", "threshold", "retention",
      "xyz", "match_count"}`` per PDF that has a valid match cache AND at
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

    # Deferred: retention.py imports aqt at module top (see module
    # docstring above); importing it here keeps this module's own top
    # level Qt-free so it stays importable with no Anki present. It sits
    # ahead of the projection because card_index_digest — retention's,
    # already the invalidation key for matches.json — is the layout
    # cache's key too.
    from . import retention

    # retention.load_matches reads user_files/pdf_index/<safe>/matches.json
    # via settings.user_files(), not a parameter — it has no per-call
    # user_files argument to pass. Pointing settings at THIS call's
    # user_files is the same redirection tests already rely on; in
    # production user_files is always settings.user_files() already, so
    # this is a no-op there.
    settings.user_files_dir = user_files

    # Three-element signature: load_matches already enforces the width
    # through its own `dims` argument, so the third element is a no-op
    # there — it is load-bearing for the layout cache, whose digest is
    # blind to a re-embed at a different width (_signature_ok).
    sig = (cidx.provider, cidx.model, cidx.dims)
    digest = retention.card_index_digest(cidx)

    # K-167: the whole 29.5 s was this. Positions are a pure function of
    # the card index, so a repeat open reads them back instead.
    cached = _read_layout(user_files, sig, digest, len(cidx.nids))
    if cached is not None:
        note_xyz: dict[int, tuple[float, ...]] = dict(zip(cidx.nids, cached))
    else:
        # Built here and not above: on a cache hit the vectors are never
        # looked at, and 28,670 memoryview slices cost 3 ms of an open
        # that is now only 110 ms all told.
        d = cidx.dims
        mv = memoryview(cidx.vectors)
        row_views = [mv[i * d:(i + 1) * d] for i in range(len(cidx.nids))]
        # normalize=False: K-171's alignment has to rotate the RAW cloud
        # onto whatever the previous layout was BEFORE the [-1, 1] squash,
        # or the squash's own per-axis noise defeats most of the fix (see
        # projection.normalize_points's docstring for the measurement).
        raw_points, sampled = projection.project(
            row_views, seed=PROJECTION_SEED, normalize=False
        )
        full = sampled == list(range(len(cidx.nids)))
        if full:
            # K-138 made every row a point, so `sampled` is range(n) and a
            # point's ROW is its identity — which is what lets the fresh
            # layout align directly against cidx.nids with no lookup of
            # its own. A reduced sample (should that ever come back) skips
            # alignment along with the cache write below, for the same
            # reason it always skipped caching: the subset would later
            # read back onto the wrong notes.
            prior = _read_prior_layout(user_files, sig)
            if prior is not None:
                raw_points, _aligned = projection.align_to(
                    raw_points, cidx.nids, prior[0], prior[1]
                )
        points = projection.normalize_points(raw_points)
        note_xyz = {
            cidx.nids[row_idx]: pt for row_idx, pt in zip(sampled, points)
        }
        if full:
            _write_layout(user_files, sig, digest, points, cidx.nids)
    notes = [{"nid": nid, "xyz": list(p)} for nid, p in note_xyz.items()]

    drive = drive_store.load(user_files)

    pdfs: list[dict] = []
    edges: list[dict] = []
    for fname in pdf_handler.list_contexts(user_files):
        name = fname[:-4] if fname.endswith(".txt") else fname
        safe = pdf_handler._safe_basename(name)
        src_sig = pdf_index.source_signature(user_files, name)
        cached = retention.load_matches(name, sig, cidx.dims, src_sig, digest)
        if cached is None:
            continue  # unknown -- never invent an empty match set
        matches, _pages = cached

        threshold = retention.get_threshold(name, cfg)
        hits = [
            (nid, score)
            for nid, score in matches
            if score >= threshold and nid in note_xyz
        ]
        if not hits:
            continue

        # Centroid on every axis, depth included — a PDF node that kept
        # a 2D centroid would float on the z=0 plane while its own notes
        # sat in front of and behind it.
        cols = list(zip(*(note_xyz[nid] for nid, _ in hits)))
        centroid = [sum(c) / len(hits) for c in cols]
        entry = drive["pdfs"].get(safe) or {}
        pdfs.append(
            {
                "safe": safe,
                "display": str(entry.get("display") or name),
                "folder": entry.get("folder"),
                "threshold": threshold,
                "retention": None,
                "xyz": centroid,
                "match_count": len(hits),
            }
        )
        edges.extend({"pdf": safe, "nid": nid, "score": score} for nid, score in hits)

    return {"pdfs": pdfs, "notes": notes, "edges": edges}
