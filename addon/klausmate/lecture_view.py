"""Lecture view (K-119): while reviewing, show the lecture page the
current card belongs to.

A "Library" button on the reviewer's bottom bar (next to More) toggles a
right-docked side panel on the main window hosting a standalone
:class:`~.pdf_viewer.PdfSidebar`. Once open it follows every card:
note tags → `!Library::*` candidates (inverted from pdf_index/prefs.json
— the tag IS the membership verdict, so there is deliberately NO
threshold re-gating here; only MATCH_FLOOR rejects absurd tag/vector
disagreement) → the note's one embedding row (card_index.read_vector,
never the full ~90MB load) → pdf_index.best_page argmax → its own
1-based page number, straight off the index (one vector per page now).
All vectors are already on disk; a resolve is a few
stats + one 3KB seek + ≤1000 dot products. When nothing matches, the
panel says exactly NO_LECTURE_TEXT — Pouya's wording.

Everything above the aqt-glue divider is pure and testable headless.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from . import card_index, pdf_handler, pdf_index

# Mirrors retention.MATCH_FLOOR — sanity only, far below any usable
# threshold (see retention.py's rationale for the constant).
MATCH_FLOOR = 0.15
# Mirrors retention.PREFS_FILE / the card_index storage dir; retention
# itself is not importable here (its module top pulls curation → aqt).
PREFS_FILE = "prefs.json"
CARD_INDEX_SUBDIR = "card_index"

R_NO_TAGS = "no-tags"
R_NO_VECTOR = "no-vector"
R_NO_CARD_INDEX = "no-card-index"
R_INDEX_UNAVAILABLE = "index-unavailable"
R_BELOW_FLOOR = "below-floor"

# Pouya's exact sentence — pinned by test, do not reword casually.
NO_LECTURE_TEXT = "No lecture page available for this card."

_STATUS_HINTS = {
    R_NO_TAGS: "",
    R_NO_VECTOR: "This note isn't in the search index yet.",
    R_NO_CARD_INDEX: "Lecture index is updating…",
    R_INDEX_UNAVAILABLE: "Lecture index is updating…",
    R_BELOW_FLOOR: "",
}


@dataclass(frozen=True)
class LectureMatch:
    safe: str
    page: int  # 1-based; 0 when pages_known is False
    score: float
    pages_known: bool
    stale: bool


@dataclass(frozen=True)
class NoLecture:
    reason: str


def prefs_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, pdf_index.SUBDIR, PREFS_FILE)


def load_prefs(user_files_dir: str) -> dict:
    """Tolerant read of pdf_index/prefs.json (retention._load_prefs,
    path-parameterized so tests can point it at a temp dir)."""
    try:
        with open(prefs_path(user_files_dir), encoding="utf-8") as f:
            prefs = json.load(f)
        return prefs if isinstance(prefs, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def tag_to_safe(prefs: dict) -> dict[str, str]:
    """Invert the safe→tag map (tag_sync.reconcile_from_tags' inversion
    — exact and lossless, unlike _tag_to_folder_display). Keys are
    casefolded because Anki tags compare case-insensitively."""
    inv: dict[str, str] = {}
    for safe, entry in prefs.items():
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag")
        if isinstance(tag, str) and tag:
            inv[tag.casefold()] = str(safe)
    return inv


def candidates_for_tags(tags: list, inv: dict[str, str]) -> list[str]:
    """The note's `!Library` PDFs, in tag order, deduped."""
    out: list[str] = []
    for t in tags or []:
        safe = inv.get(str(t).casefold())
        if safe is not None and safe not in out:
            out.append(safe)
    return out


def _stamp(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
        return (int(st.st_mtime), int(st.st_size))
    except OSError:
        return None


class LectureResolver:
    """card → (PDF, page) with stamp-validated caches. Cheap enough for
    the per-card hook once warm; the RowMap parse (the one slow-ish
    step) happens on the user-initiated open, not per card."""

    def __init__(self, user_files_dir: str) -> None:
        self._ufd = user_files_dir
        self._card_dir = os.path.join(user_files_dir, CARD_INDEX_SUBDIR)
        self._prefs_stamp: Any = ()
        self._inv: dict[str, str] = {}
        self._rowmap_stamp: Any = ()
        self._rowmap: Any = None
        self._idx_cache: dict[str, tuple[Any, Any]] = {}  # safe -> (stamp, idx)
        self._results: dict[int, tuple[Any, list]] = {}

    def invalidate(self) -> None:
        self._prefs_stamp = ()
        self._rowmap_stamp = ()
        self._rowmap = None
        self._idx_cache.clear()
        self._results.clear()

    # -- stamped sub-caches ------------------------------------------------

    def _inverse(self) -> dict[str, str]:
        s = _stamp(prefs_path(self._ufd))
        if s != self._prefs_stamp:
            self._inv = tag_to_safe(load_prefs(self._ufd))
            self._prefs_stamp = s
        return self._inv

    def _row_map(self):
        s = _stamp(os.path.join(self._card_dir, card_index.MANIFEST_FILE))
        if s != self._rowmap_stamp:
            self._rowmap = card_index.load_row_map(self._card_dir)
            self._rowmap_stamp = s
        return self._rowmap

    def _pdf_idx(self, safe: str):
        manifest = os.path.join(
            pdf_index.index_dir(self._ufd, safe), pdf_index.MANIFEST_FILE
        )
        s = _stamp(manifest)
        cached = self._idx_cache.get(safe)
        if cached is not None and cached[0] == s:
            return cached[1]
        idx = pdf_index.load(pdf_index.index_dir(self._ufd, safe))
        self._idx_cache[safe] = (s, idx)
        while len(self._idx_cache) > 4:  # tiny LRU — ~3MB per entry max
            self._idx_cache.pop(next(iter(self._idx_cache)))
        return idx

    # -- resolution --------------------------------------------------------

    def resolve(self, nid: int, tags: list):
        # Keyed on the tags too: a cached hit for the nid must not
        # survive the note gaining/losing a Library tag mid-session.
        tag_key = tuple(sorted({str(t).casefold() for t in tags or []}))
        cached = self._results.get(nid)
        if (
            cached is not None
            and cached[2] == tag_key
            and all(_stamp(path) == stamp for path, stamp in cached[1])
        ):
            return cached[0]
        outcome, consulted = self._resolve_fresh(int(nid), tags)
        if len(self._results) > 512:
            self._results.clear()
        self._results[nid] = (outcome, consulted, tag_key)
        return outcome

    def _resolve_fresh(self, nid: int, tags: list):
        consulted: list = []

        def note(path: str) -> None:
            consulted.append((path, _stamp(path)))

        note(prefs_path(self._ufd))
        note(os.path.join(self._card_dir, card_index.MANIFEST_FILE))
        note(os.path.join(self._card_dir, card_index.MEAN_FILE))  # K-302 centering

        cands = candidates_for_tags(tags, self._inverse())
        if not cands:
            return NoLecture(R_NO_TAGS), consulted

        rm = self._row_map()
        if rm is None:
            return NoLecture(R_NO_CARD_INDEX), consulted
        if nid in rm.skipped or nid not in rm.rows:
            return NoLecture(R_NO_VECTOR), consulted
        vec = card_index.read_vector(self._card_dir, rm.rows[nid], rm.dims)
        if vec is None:
            return NoLecture(R_NO_CARD_INDEX), consulted

        mean = card_index.mean_vector(self._card_dir)  # K-302 centering
        best: tuple[float, str, int, Any] | None = None
        for safe in cands:
            note(
                os.path.join(
                    pdf_index.index_dir(self._ufd, safe),
                    pdf_index.MANIFEST_FILE,
                )
            )
            idx = self._pdf_idx(safe)
            if idx is None:
                continue
            if (idx.provider, idx.model) != (rm.provider, rm.model):
                continue
            if idx.dims != rm.dims:
                continue
            page_1based, score = pdf_index.best_page(idx, vec, mean)
            if page_1based < 0:
                continue
            # Deterministic winner: highest score, then lexical safe.
            if best is None or score > best[0] or (
                score == best[0] and safe < best[1]
            ):
                best = (score, safe, page_1based, idx)
        if best is None:
            return NoLecture(R_INDEX_UNAVAILABLE), consulted
        score, safe, page_1based, idx = best
        if score < MATCH_FLOOR:
            return NoLecture(R_BELOW_FLOOR), consulted

        ctx_json = os.path.join(self._ufd, "contexts", safe + ".json")
        note(ctx_json)
        pages_known = pdf_handler.load_pages(self._ufd, safe) is not None
        stale = pdf_index.source_signature(self._ufd, safe) != idx.source_sig
        page = page_1based if pages_known else 0
        return (
            LectureMatch(
                safe=safe,
                page=page,
                score=float(score),
                pages_known=pages_known,
                stale=stale,
            ),
            consulted,
        )


# ── aqt glue ─────────────────────────────────────────────────────────────

try:
    from aqt import gui_hooks, mw
    from aqt.qt import (
        QDockWidget,
        QLabel,
        QStackedWidget,
        Qt,
        QTimer,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # headless tests / partial environments
    gui_hooks = mw = None  # type: ignore[assignment]
    QDockWidget = QLabel = QStackedWidget = Qt = QTimer = QVBoxLayout = QWidget = None  # type: ignore[assignment]

from .slot_guard import guarded as _guarded
from . import settings


# ``class LectureDock(None)`` is a hard TypeError at IMPORT time, so a
# partial Qt surface would cost the RESOLVER, the config keys and every
# hook as well — not just the panel that could not have been drawn. The
# None fallback is the house convention and is right for names used as
# values; it is a trap for names used as BASE CLASSES. Only the dock needs
# Qt, so only the dock degrades: the base falls back to ``object`` and
# ``_ensure_dock`` keeps the real gate. Same shape as
# ``index_queue._DockBase`` (K-152), which is where this was found first.
_DockBase: Any = QDockWidget if QDockWidget is not None else object

_dock: Any = None
_resolver: LectureResolver | None = None
_setup_done = False
_JUMP_DELAYS_MS = (0, 120, 250, 500, 1000, 2000)

# Injected into the ReviewerBottomBar page (set once per Reviewer._initWeb;
# only #middle is rewritten per question/answer, so a sibling of the More
# button survives). FUNCTIONAL injection — never gated on klausbook_design.
_BUTTON_JS = """
<script>
(function () {
  try {
    if (document.getElementById("klaus-lecture-btn")) { return; }
    var btns = document.getElementsByTagName("button");
    var more = null;
    for (var i = 0; i < btns.length; i++) {
      var oc = btns[i].getAttribute("onclick") || "";
      if (oc.indexOf("'more'") !== -1) { more = btns[i]; break; }
    }
    if (!more) { return; }
    var b = more.cloneNode(false);
    b.id = "klaus-lecture-btn";
    b.textContent = "Library";
    b.title = "Show the lecture page for this card";
    b.removeAttribute("onclick");
    b.onclick = function () { pycmd("klausmate:lecture"); };
    more.parentNode.insertBefore(b, more);

    // Anki centres the ease buttons inside the MIDDLE cell, not the window —
    // that cell only lands window-centred while the two side cells happen to
    // be equal (one button each). Adding ours to the right cell drags the
    // whole answer row ~half our width to the LEFT, into whatever the left
    // cell holds: AnkiHub parks its "View on AnkiHub" button there as
    // position:absolute, so it sits at its static position and cannot be
    // pushed out of the way — the rows collide (Pouya's screenshot).
    // Pad the left CELL by exactly our own width instead. Padding widens the
    // column while leaving the cell's own content — and that absolute
    // button's static position — exactly where they were; a spacer ELEMENT
    // would shift both and end up worse than doing nothing.
    var left = document.querySelector("#innertable > tbody > tr > td.stat:first-child");
    var edit = left ? left.querySelector("button") : null;
    if (!edit || left === b.parentNode) { return; }
    var outer = function (el) {
      var cs = window.getComputedStyle(el);
      return el.offsetWidth + parseFloat(cs.marginLeft) + parseFloat(cs.marginRight);
    };
    var pad = outer(b);
    // Never buy centring at the cost of wrapping the answer row onto a second
    // line — the bar's height is fixed and the second line is clipped. Below
    // this width the padding is simply not applied (bar behaves as it does
    // today). Anki's four ease buttons are cut from the same CSS as ours, so
    // 4 * pad bounds their row; + edit + more + our own pad = the whole bar.
    var minw = Math.ceil(outer(edit) + outer(more) + pad * 6);
    var st = document.createElement("style");
    st.textContent = "@media (min-width: " + minw + "px) {"
      + " #innertable > tbody > tr > td.stat:first-child {"
      + " padding-right: " + pad + "px; } }";
    document.head.appendChild(st);
  } catch (e) {}
})();
</script>
"""




def _saved_state() -> dict:
    try:
        state = pdf_handler._load_tabs_file(settings.user_files()).get("lecture_view")
        return dict(state) if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(**updates: Any) -> None:
    try:
        state = _saved_state()
        state.update(updates)
        pdf_handler._save_tabs_file(settings.user_files(), {"lecture_view": state})
    except Exception as e:
        print(f"[klausmate] lecture state save failed: {e}")


class LectureDock(_DockBase):  # type: ignore[misc]
    """Right-docked lecture panel on mw. Frameless: an empty title bar (no drag/
    float/close chrome) — the bottom-bar button, the L shortcut, and the
    reviewer menu are its only toggles."""

    def __init__(self) -> None:
        super().__init__(mw)
        from . import theme
        from .pdf_viewer import PdfSidebar

        self.setObjectName("KlausLectureDock")
        try:
            self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
            self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            self.setTitleBarWidget(QWidget(self))
        except Exception as e:
            print(f"[klausmate] lecture dock chrome failed: {e}")

        body = QWidget(self)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.stack = QStackedWidget(body)
        self.empty_label = QLabel(NO_LECTURE_TEXT, body)
        try:
            self.empty_label.setWordWrap(True)
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_label.setStyleSheet(
                theme.muted_label_qss(theme.night_mode(), 13)
            )
            self.empty_label.setMargin(24)
        except Exception:
            pass
        self.sidebar = PdfSidebar(None, parent=body, host_key="lecture")
        # The reader clears itself when its last tab closes; show the
        # panel's empty state then, not a blank reader.
        self.sidebar.tabs.closed.connect(self._on_tab_closed)
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.sidebar)
        lay.addWidget(self.stack, 1)

        self.status = QLabel("", body)
        try:
            self.status.setStyleSheet(theme.muted_label_qss(theme.night_mode()))
            self.status.setContentsMargins(8, 3, 8, 3)
        except Exception:
            pass
        lay.addWidget(self.status, 0)
        self.setWidget(body)

        self._jump_gen = 0
        self._last_target: tuple[str, int] | None = None

    # -- follow ------------------------------------------------------------

    def follow_card(self, card: Any) -> None:
        global _resolver
        try:
            nid = int(card.nid)
            tags = list(getattr(card.note(), "tags", None) or [])
        except Exception as e:
            print(f"[klausmate] lecture: card read failed: {e}")
            return
        if _resolver is None:
            _resolver = LectureResolver(settings.user_files())
        try:
            outcome = _resolver.resolve(nid, tags)
        except Exception as e:
            print(f"[klausmate] lecture: resolve failed for nid={nid}: {e}")
            return
        if isinstance(outcome, LectureMatch):
            self._show_match(outcome)
        else:
            print(
                f"[klausmate] lecture: no match for nid={nid} ({outcome.reason})"
            )
            self._show_empty(outcome.reason)

    def _show_match(self, m: LectureMatch) -> None:
        try:
            if getattr(self.sidebar, "_name", None) != m.safe:
                # A tab per lecture (PDF reader 3/5): opening B while A is
                # open adds B beside A and loads it, instead of replacing A.
                self.sidebar.tabs.open(m.safe)
                self._last_target = None
                # The webview grabbing focus on load would eat the answer
                # keys — hand focus straight back to the reviewer.
                QTimer.singleShot(0, _refocus_reviewer)
            self.stack.setCurrentWidget(self.sidebar)
        except Exception as e:
            print(f"[klausmate] lecture: load failed for {m.safe}: {e}")
            return

        display = m.safe
        try:
            from . import drive_store

            display = drive_store.display_name(settings.user_files(), m.safe) or m.safe
        except Exception:
            pass
        if m.pages_known and m.page > 0:
            text = f"{display} — p. {m.page}"
            if m.stale:
                text += " · index older than PDF"
            target = (m.safe, m.page)
            if target != self._last_target:
                # A new target always jumps; the SAME target never
                # re-jumps (sibling cards of one note share a page and a
                # re-center would fight the user's own scrolling).
                self._last_target = target
                self._arm_jump(m.page - 1)
        else:
            text = (
                f"{display} — page unknown · re-import this PDF to enable"
                " page tracking"
            )
            self._jump_gen += 1
            self._last_target = None
        self._set_status(text)

    def _show_empty(self, reason: str) -> None:
        self._jump_gen += 1
        self._last_target = None
        try:
            self.stack.setCurrentWidget(self.empty_label)
        except Exception:
            pass
        self._set_status(_STATUS_HINTS.get(reason, ""))

    @_guarded
    def _on_tab_closed(self, *_args) -> None:
        if not self.sidebar.tabs.names():
            self._show_empty("")

    def _set_status(self, text: str) -> None:
        try:
            self.status.setText(text)
            self.status.setVisible(bool(text))
        except Exception:
            pass

    def _arm_jump(self, page0: int) -> None:
        """Generation-stamped retry ladder. pdf.js posts its page count
        before the page divs exist, so one deferred jump can be
        swallowed; jump_to_page is idempotent (scrollIntoView), the
        ladder stops as soon as the sidebar's page tracker reports the
        target, and any newer card/close bumps the generation."""
        self._jump_gen += 1
        gen = self._jump_gen

        def attempt(i: int) -> None:
            if gen != self._jump_gen or not self.isVisible():
                return
            if getattr(self.sidebar, "_current_page", None) == page0 and i > 0:
                return
            try:
                self.sidebar.jump_to_page(page0)
            except Exception as e:
                print(f"[klausmate] lecture: jump failed: {e}")
                return
            # A jump can move focus into the reader; the answer keys must
            # keep reaching the reviewer.
            QTimer.singleShot(0, _refocus_reviewer)
            if i + 1 < len(_JUMP_DELAYS_MS):
                QTimer.singleShot(
                    _JUMP_DELAYS_MS[i + 1], lambda: attempt(i + 1)
                )

        QTimer.singleShot(_JUMP_DELAYS_MS[0], lambda: attempt(0))

    # -- lifecycle ---------------------------------------------------------

    def save_width(self) -> None:
        try:
            if self.isVisible() and self.width() > 80:
                _save_state(width=int(self.width()))
        except Exception:
            pass

    def shutdown(self) -> None:
        """Sever the webview from Anki's global hooks BEFORE the C++
        object dies (K-095: a PdfJsViewer destroyed without cleanup()
        crashes the user's next theme switch)."""
        self._jump_gen += 1
        try:
            self.sidebar.clear()
        except Exception:
            pass
        try:
            self.sidebar.cleanup()
        except Exception as e:
            print(f"[klausmate] lecture sidebar cleanup failed: {e}")

    def closeEvent(self, evt: Any) -> None:  # noqa: N802 — Qt naming
        # No close chrome exists, but Qt can still close docks (e.g.
        # parent teardown). Treat it as a user close unless the module
        # teardown flagged otherwise.
        try:
            self.save_width()
            if not getattr(self, "_closing_for_shutdown", False):
                _save_state(open=False)
        except Exception:
            pass
        try:
            super().closeEvent(evt)
        except Exception:
            pass


def _refocus_reviewer() -> None:
    try:
        if getattr(mw, "state", None) == "review":
            mw.web.setFocus()
    except Exception:
        pass


def _ensure_dock() -> Any:
    global _dock, _resolver
    if _dock is not None:
        return _dock
    if mw is None or QDockWidget is None:
        return None  # the gate _DockBase's fallback moved down to here
    _dock = LectureDock()
    if _resolver is None:
        _resolver = LectureResolver(settings.user_files())
    try:
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _dock)
        width = int(_saved_state().get("width") or 420)
        QTimer.singleShot(
            0,
            lambda: mw.resizeDocks(
                [_dock], [max(240, width)], Qt.Orientation.Horizontal
            ),
        )
    except Exception as e:
        print(f"[klausmate] lecture dock install failed: {e}")
    return _dock


def open_lecture_view() -> None:
    if mw is None or getattr(mw, "state", None) != "review":
        return
    dock = _ensure_dock()
    if dock is None:
        return
    try:
        if _resolver is not None:
            _resolver.invalidate()  # fresh stamps on a user-initiated open
        dock.show()
        dock.raise_()  # never activateWindow(): answer keys stay put
    except Exception as e:
        print(f"[klausmate] lecture open failed: {e}")
        return
    _save_state(open=True)
    card = getattr(getattr(mw, "reviewer", None), "card", None)
    if card is not None:
        QTimer.singleShot(0, lambda: dock.follow_card(card))


def toggle_lecture_view() -> None:
    if _dock is not None and _dock.isVisible():
        try:
            _dock.save_width()
            _dock.hide()
        except Exception:
            pass
        _save_state(open=False)
    else:
        open_lecture_view()


# -- hooks -----------------------------------------------------------------


def _on_bottom_bar_content(web_content: Any, context: Any) -> None:
    try:
        if type(context).__name__ == "ReviewerBottomBar":
            web_content.body += _BUTTON_JS
    except Exception as e:
        print(f"[klausmate] lecture button inject failed: {e}")


def _on_js_message(
    handled: tuple, message: str, context: Any
) -> tuple:
    # __init__.on_js_message (registered earlier) blanket-swallows
    # non-Editor "klausmate:" messages — but the hook is a CHAIN and the
    # final return wins, so matching on the exact message here works
    # regardless of what earlier handlers said.
    if message != "klausmate:lecture":
        return handled
    try:
        # Deferred: never open/close UI inside a webchannel dispatch
        # (the bridge-reentrancy rule).
        QTimer.singleShot(0, toggle_lecture_view)
    except Exception as e:
        print(f"[klausmate] lecture toggle failed: {e}")
    return (True, None)


def _on_show_question(card: Any) -> None:
    dock = _dock
    if dock is None or not dock.isVisible():
        return
    try:
        QTimer.singleShot(0, lambda: dock.follow_card(card))
    except Exception:
        pass


def _on_state_change(new_state: str, old_state: str) -> None:
    try:
        if new_state == "review":
            if bool(settings.read().get("lecture_view_reopen", True)) and bool(
                _saved_state().get("open")
            ):
                open_lecture_view()
        elif _dock is not None and _dock.isVisible():
            _dock.save_width()
            _dock.hide()  # the deck browser shares mw — never show there
    except Exception as e:
        print(f"[klausmate] lecture state change failed: {e}")


def _on_state_shortcuts(state: str, shortcuts: list) -> None:
    if state != "review":
        return
    try:
        taken = {str(k).lower() for k, _ in shortcuts}
        if "l" in taken:
            # A duplicate key would go ambiguous-dead (the documented
            # QShortcut hazard) — the menu stays the access path.
            print("[klausmate] lecture: 'l' already bound; shortcut skipped")
            return
        shortcuts.append(("l", toggle_lecture_view))
    except Exception:
        pass


def _on_reviewer_menu(reviewer: Any, menu: Any) -> None:
    try:
        act = menu.addAction("Lecture View")
        act.setCheckable(True)
        act.setChecked(_dock is not None and _dock.isVisible())
        act.triggered.connect(lambda _=False: toggle_lecture_view())
    except Exception:
        pass


def _teardown() -> None:
    global _dock, _resolver
    dock, _dock = _dock, None
    _resolver = None
    if dock is None:
        return
    try:
        dock._closing_for_shutdown = True
        dock.save_width()
        dock.shutdown()
        try:
            mw.removeDockWidget(dock)
        except Exception:
            pass
        dock.deleteLater()
    except RuntimeError:
        pass  # C++ side already gone
    except Exception as e:
        print(f"[klausmate] lecture teardown failed: {e}")


def setup() -> None:
    global _setup_done
    if _setup_done or gui_hooks is None or mw is None:
        return
    _setup_done = True
    for register in (
        lambda: gui_hooks.webview_will_set_content.append(_on_bottom_bar_content),
        lambda: gui_hooks.webview_did_receive_js_message.append(_on_js_message),
        lambda: gui_hooks.reviewer_did_show_question.append(_on_show_question),
        lambda: gui_hooks.state_did_change.append(_on_state_change),
        lambda: gui_hooks.state_shortcuts_will_change.append(_on_state_shortcuts),
        lambda: gui_hooks.reviewer_will_show_context_menu.append(_on_reviewer_menu),
        lambda: gui_hooks.profile_will_close.append(_teardown),
        lambda: mw.app.aboutToQuit.connect(_teardown),
    ):
        try:
            register()
        except Exception as e:
            print(f"[klausmate] lecture hook failed: {type(e).__name__}: {e}")
