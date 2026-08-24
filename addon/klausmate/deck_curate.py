"""Curate Deck on Anki's deck screens — button, PDF drop, deck scoping.

Three surfaces, each installed independently so one failure never takes
down the others:

- **Deck browser bottom bar** — no hook exists, so the button is appended
  to the ``DeckBrowser.drawLinks`` class attribute (``_drawButtons``
  deepcopies it per render). Unknown link commands fall through Anki's
  ``_linkHandler`` silently, so the click arrives via
  ``webview_did_receive_js_message``, gated on the bottom bar's context.
- **Deck overview bottom bar** — a real filter hook,
  ``overview_will_render_bottom``.
- **PDF drop** — ``MainWebView.dropEvent`` consumes OS file drops on the
  deck browser and feeds them to Anki's importer, and ``AnkiWebView``
  disables HTML5 drops on every render, so a JS drop zone can never see
  the file. The only robust route is wrapping that method: peel off the
  PDFs, delegate everything else to the original.

Command namespace is ``klausmate_<action>`` (underscore) — deliberately
NOT the editor bridge's ``klausmate:<action>`` (colon), whose handler
claims and drops any message from a non-Editor context.

Dropping a PDF "arms" it: session-only state, shown on the deck browser,
consumed by the next Curate click and cleared afterwards.
"""

from __future__ import annotations

import os
from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QComboBox,
    QCursor,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QTimer,
    QVBoxLayout,
)
from aqt.utils import showWarning, tooltip

from . import curation, pdf_handler

CURATE_CMD = "klausmate_curate"
DISARM_CMD = "klausmate_disarm"
BROWSE_CMD = "klausmate_browse"
_CLAIMED = {CURATE_CMD, DISARM_CMD, BROWSE_CMD}

_armed_pdf: str | None = None


def _user_files() -> str:
    from . import USER_FILES

    return USER_FILES


def _display_name(safe: str) -> str:
    try:
        from . import drive_store

        return drive_store.display_name(_user_files(), safe)
    except Exception:
        return safe


# ------------------------------------------------------------ armed state


def armed() -> str | None:
    return _armed_pdf


def arm(safe: str | None) -> None:
    global _armed_pdf
    _armed_pdf = safe
    _refresh_current_screen()


def disarm_if(safe: str) -> None:
    """Clear the armed PDF when that PDF is deleted elsewhere."""
    if _armed_pdf == safe:
        arm(None)


def _refresh_current_screen() -> None:
    """Re-render whichever deck-scoped screen is currently showing, so the
    armed/idle drop square updates immediately after arm()/disarm() —
    needed on the overview now that Browse/disarm can be triggered there
    too, not just on the deck browser."""
    try:
        if mw is None:
            return
        state = getattr(mw, "state", "")
        if state == "deckBrowser":
            mw.deckBrowser.refresh()
        elif state == "overview":
            mw.overview.refresh()
    except Exception as e:
        print(f"[klausmate] deck/overview refresh failed: {e}")


# --------------------------------------------------------------- import


def _import_and_arm(paths: list[str], skipped: int = 0) -> None:
    from . import import_pdf_file

    last: str | None = None
    for path in paths:
        try:
            name = import_pdf_file(path)
        except Exception as e:
            print(f"[klausmate] deck-drop import failed for {path}: {e}")
            continue
        if name:
            last = name
    if skipped:
        tooltip(f"Klaus imported the PDF — ignored {skipped} other file(s).")
    if last:
        arm(last)
    else:
        _refresh_current_screen()


# ------------------------------------------------------------ deck scope


def choose_deck_scope(parent) -> tuple[bool, str | None]:
    """Ask which deck to curate against. Returns (accepted, deck_name)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Curate deck")
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("Search for matching cards in:"))
    combo = QComboBox()
    combo.addItem("All decks", None)
    try:
        if mw.col is not None:
            for entry in mw.col.decks.all_names_and_ids():
                combo.addItem(entry.name, entry.name)
    except Exception as e:
        print(f"[klausmate] deck list failed: {e}")
    layout.addWidget(combo)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False, None
    return True, combo.currentData()


# ------------------------------------------------------------- curation


def run_curation_flow(pdf_name: str, deck_scope: str | None, parent=None) -> None:
    """Run the shared curation pipeline with main-window progress."""
    parent = parent or mw
    started = False

    def on_progress(label: str, done: int, total: int) -> None:
        nonlocal started
        try:
            if not started:
                mw.progress.start(label=label, immediate=True)
                started = True
            if total > 0:
                mw.progress.update(label=f"{label} {done}/{total}")
            else:
                mw.progress.update(label=label)
        except Exception:
            pass

    def finish() -> None:
        nonlocal started
        if started:
            try:
                mw.progress.finish()
            except Exception:
                pass
            started = False

    def on_done(result: dict) -> None:
        finish()
        arm(None)
        count = len(result.get("nids") or [])
        if not count:
            tooltip("No matching cards — try a wider deck scope.")
        elif result.get("previewed"):
            tooltip(f"{count:,} matches tagged and opened in Browse.")
        else:
            tooltip(f"{count:,} matches found.")

    def on_error(exc: Exception) -> None:
        finish()
        from . import embeddings

        if isinstance(exc, embeddings.EmbeddingError):
            showWarning("Klaus curation failed.\n\n" + exc.user_message())
        else:
            showWarning(f"Klaus curation failed.\n\n{exc}")

    try:
        curation.run_curation(
            parent,
            pdf_name=pdf_name,
            deck_scope=deck_scope,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )
    except Exception as e:
        finish()
        showWarning(f"Klaus could not start curation.\n\n{e}")


def _pick_pdf_menu() -> None:
    """No PDF armed: offer the library, most recently used first."""
    user_files = _user_files()
    try:
        names = pdf_handler.list_by_recency(user_files)
    except Exception:
        names = [
            f[:-4] if f.endswith(".txt") else f
            for f in pdf_handler.list_contexts(user_files)
        ]
    if not names:
        tooltip("No PDFs imported yet — drop one on the deck list first.")
        return
    menu = QMenu(mw)
    # addAction(QAction) returns None in PyQt6 — build, configure, then add.
    header = QAction("Curate a deck from…", menu)
    header.setEnabled(False)
    menu.addAction(header)
    menu.addSeparator()
    for safe in names[:20]:
        act = QAction(_display_name(safe), menu)
        act.triggered.connect(lambda _c=False, s=safe: _curate_with(s))
        menu.addAction(act)
    menu.exec(QCursor.pos())


def _curate_with(safe: str) -> None:
    """A PDF is chosen — resolve the deck scope for the current screen."""
    scope_state = getattr(mw, "state", "")
    if scope_state == "overview":
        try:
            deck = mw.col.decks.current()["name"]
        except Exception as e:
            print(f"[klausmate] current deck lookup failed: {e}")
            deck = None
        if deck:
            run_curation_flow(safe, deck)
            return
    accepted, deck = choose_deck_scope(mw)
    if accepted:
        run_curation_flow(safe, deck)


def _on_curate_clicked() -> None:
    if mw is None or mw.col is None:
        return
    if _armed_pdf:
        _curate_with(_armed_pdf)
    else:
        _pick_pdf_menu()


def _browse_for_pdfs() -> None:
    """Open the file dialog and feed picks through the same path as a drop."""
    from aqt.qt import QFileDialog

    paths, _ = QFileDialog.getOpenFileNames(
        mw, "Import lecture PDF", "", "PDF files (*.pdf)"
    )
    if paths:
        _import_and_arm(list(paths))


def _on_browse_clicked() -> None:
    # Never open a modal QFileDialog synchronously inside the JS-message
    # callback — defer it exactly like the drop wrapper defers its import.
    QTimer.singleShot(0, _browse_for_pdfs)


# ------------------------------------------------------------- installs


def _install_deck_browser_button() -> None:
    from aqt.deckbrowser import DeckBrowser

    if not hasattr(DeckBrowser, "drawLinks"):
        print("[klausmate] DeckBrowser.drawLinks missing — button skipped")
        return
    if getattr(DeckBrowser, "_klausmate_curate_link", False):
        return
    DeckBrowser.drawLinks.append(["", CURATE_CMD, "Curate Deck"])
    DeckBrowser._klausmate_curate_link = True


def on_deck_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    """Claim the deck-surface link commands (underscore namespace)."""
    if message not in _CLAIMED:
        return handled
    try:
        from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar

        valid_contexts: tuple[type, ...] = (DeckBrowser, DeckBrowserBottomBar)
        # The overview's content webview (mw.web) passes the Overview
        # instance itself as bridge context (Overview._renderPage calls
        # stdHtml(..., context=self)) — imported defensively since aqt
        # isn't guaranteed importable in every host.
        try:
            from aqt.overview import Overview

            valid_contexts += (Overview,)
        except Exception:
            pass
        if not isinstance(context, valid_contexts):
            return handled
    except Exception:
        return handled
    if message == DISARM_CMD:
        arm(None)
    elif message == BROWSE_CMD:
        _on_browse_clicked()
    else:
        _on_curate_clicked()
    return (True, None)


def on_overview_bottom(link_handler, links):
    """Filter hook: add the button and intercept its command."""
    try:
        links.append(["", CURATE_CMD, "Curate Deck"])
    except Exception as e:
        print(f"[klausmate] overview button failed: {e}")
        return link_handler

    def wrapped(url: str = "", **kwargs):
        if url == CURATE_CMD:
            _on_curate_clicked()
            return None
        return link_handler(url=url, **kwargs)

    return wrapped


def _drop_square_html() -> str:
    """Render the drop-PDF square: idle body + Browse anchor, or the armed
    indicator + its × disarm link. Single source for every deck-scoped
    screen — deck browser, deck overview, and (K-043) the Library window —
    so they can never drift apart from each other.

    Fixed to the bottom of the CONTENT webview's own viewport rather than
    flowing in-place: on both the deck browser and the deck overview, the
    stats/table HTML this gets appended to renders in the main content
    webview (mw.web), while the button row (Get Shared / Curate Deck / …)
    lives in a SEPARATE webview (mw.bottomWeb, via aqt.toolbar.BottomBar)
    pinned below it — same split on both screens (both construct
    ``self.bottom = BottomBar(mw, mw.bottomWeb)`` in the real Anki source).
    There is no shared document to lay these two out against each other in
    normal flow, so `position: fixed; bottom` is what actually lands this
    directly above that button row on either screen — it stops exactly at
    the edge of the content webview, which is exactly where the separate
    bottom-bar webview begins.
    """
    if _armed_pdf:
        label = _display_name(_armed_pdf)
        safe_label = (
            label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        body = (
            f"<span style='flex:1;text-align:left;'>Armed: <b>{safe_label}</b>"
            " — press <b>Curate Deck</b> below.</span>"
            f"<a href=# onclick='pycmd(\"{DISARM_CMD}\"); return false;' "
            "style='flex:0 0 auto;color:inherit;text-decoration:none;'>"
            "&times;</a>"
        )
        border = "1px solid rgba(58,130,247,0.85)"
    else:
        body = (
            "<span style='flex:1;text-align:left;'>Drop a PDF to curate</span>"
            f"<a href=# onclick='pycmd(\"{BROWSE_CMD}\"); return false;' "
            "style='flex:0 0 auto;padding:3px 10px;"
            "border:1px solid rgba(128,128,128,0.55);border-radius:6px;"
            "font-size:12px;color:inherit;text-decoration:none;'>"
            "Browse&hellip;</a>"
        )
        border = "1px dashed rgba(128,128,128,0.55)"
    # One flex row, not a stacked block: the label takes the free space and
    # the action (Browse… / ×) sits hard right, matching the Qt surfaces in
    # pdf_drive._LibraryDropZone and __init__._PdfBar. Both states use the
    # same row so the square does not reflow when a PDF is armed.
    return (
        f"<div style='position:fixed;left:50%;bottom:10px;"
        f"transform:translateX(-50%);z-index:50;"
        f"display:flex;align-items:center;gap:10px;"
        f"margin:0;padding:8px 14px;max-width:420px;width:calc(100% - 40px);"
        f"box-sizing:border-box;background:var(--window-bg,transparent);"
        f"border:{border};border-radius:10px;"
        f"font-size:13px;opacity:0.95;color:inherit;'>{body}</div>"
    )


def on_deck_browser_content(deck_browser: Any, content: Any) -> None:
    """Inject the drop square / armed indicator above the deck list."""
    if not hasattr(content, "stats"):
        return
    try:
        content.stats += _drop_square_html()
    except Exception as e:
        print(f"[klausmate] deck browser content injection failed: {e}")


def on_overview_content(overview: Any, content: Any) -> None:
    """Inject the same drop square on the deck overview screen — 'just
    like it does for the main menu': opening a deck must not lose the
    affordance the deck-list screen has. Appended to content.table, the
    OverviewContent field that plays the same role content.stats does on
    the deck browser (both are the last piece rendered into the _body
    template before the closing </center>)."""
    if not hasattr(content, "table"):
        return
    try:
        content.table += _drop_square_html()
    except Exception as e:
        print(f"[klausmate] overview content injection failed: {e}")


def _install_drop_wrap() -> None:
    """Wrap MainWebView.dropEvent so PDFs never reach Anki's importer."""
    import aqt.main

    cls = getattr(aqt.main, "MainWebView", None)
    if cls is None or not hasattr(cls, "dropEvent"):
        print("[klausmate] MainWebView.dropEvent missing — PDF drop disabled")
        return
    if getattr(cls, "_klausmate_drop_wrapped", False):
        return
    original = cls.dropEvent

    def dropEvent(self, evt):  # noqa: N802 — Qt naming
        try:
            # Both screens that render the drop square (K-040), not just
            # the deck list. The square says "Drop a lecture PDF here" on
            # the overview too, and without this the drop falls through to
            # Anki's own importer, which chokes on a PDF — an invitation
            # the add-on then fails to honour.
            if getattr(mw, "state", "") in ("deckBrowser", "overview"):
                md = evt.mimeData()
                if md is not None and md.hasUrls():
                    pdfs, others = [], 0
                    for url in md.urls():
                        local = url.toLocalFile()
                        if local.lower().endswith(".pdf") and os.path.isfile(local):
                            pdfs.append(local)
                        elif local:
                            others += 1
                    if pdfs:
                        # Consume entirely: Anki's handler imports only the
                        # first url, so chaining would double-handle it.
                        evt.accept()
                        QTimer.singleShot(
                            0, lambda p=list(pdfs), s=others: _import_and_arm(p, s)
                        )
                        return
        except Exception as e:
            print(f"[klausmate] drop wrap failed, delegating: {e}")
        return original(self, evt)

    cls.dropEvent = dropEvent
    cls._klausmate_drop_orig = original
    cls._klausmate_drop_wrapped = True


def _on_profile_will_close() -> None:
    global _armed_pdf
    _armed_pdf = None


def setup() -> None:
    """Install every deck surface; each failure is isolated and logged."""
    for label, install in (
        ("deck browser button", _install_deck_browser_button),
        ("drop wrap", _install_drop_wrap),
    ):
        try:
            install()
        except Exception as e:
            print(f"[klausmate] {label} setup failed: {type(e).__name__}: {e}")

    try:
        gui_hooks.webview_did_receive_js_message.append(on_deck_js_message)
    except Exception as e:
        print(f"[klausmate] deck js hook failed: {e}")
    if hasattr(gui_hooks, "overview_will_render_bottom"):
        try:
            gui_hooks.overview_will_render_bottom.append(on_overview_bottom)
        except Exception as e:
            print(f"[klausmate] overview hook failed: {e}")
    if hasattr(gui_hooks, "deck_browser_will_render_content"):
        try:
            gui_hooks.deck_browser_will_render_content.append(on_deck_browser_content)
        except Exception as e:
            print(f"[klausmate] deck content hook failed: {e}")
    if hasattr(gui_hooks, "overview_will_render_content"):
        try:
            gui_hooks.overview_will_render_content.append(on_overview_content)
        except Exception as e:
            print(f"[klausmate] overview content hook failed: {e}")
    try:
        gui_hooks.profile_will_close.append(_on_profile_will_close)
    except Exception as e:
        print(f"[klausmate] deck curate profile hook failed: {e}")
