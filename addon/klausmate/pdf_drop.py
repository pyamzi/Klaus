"""Import a lecture PDF from Anki's deck screens — drop square and drop wrap.

**K-146 removed the curate-a-deck ceremony this file was built around;
K-151 renamed the file and retired the last of its vocabulary.** The
button never created a deck: it searched, tagged, and opened Browse on
the per-PDF ``!Library`` tag — the same tag indexing already writes
(``tag_sync.sync_after_matches``) and the same view the Library's "Show
Matched Cards in Browse" opens. What it did do, invisibly, was refresh
the CARD index; that job moved to ``pdf_drive._on_embed``, which is now
the only user-facing path that reaches ``curation.ensure_index``.

What remains is the import surface, on two screens:

- **PDF drop** — ``MainWebView.dropEvent`` consumes OS file drops on the
  deck browser and feeds them to Anki's importer, and ``AnkiWebView``
  disables HTML5 drops on every render, so a JS drop zone can never see
  the file. The only robust route is wrapping that method: peel off the
  PDFs, delegate everything else to the original. **This wrapper is the
  only thing standing between a dropped PDF and Anki's own importer
  choking on it** — it outlives the button by a wide margin.
- **The drop square** — rendered into the deck browser's and the
  overview's content webviews, with a Browse… file picker for people who
  would rather not drag. Its ``pycmd`` clicks arrive over
  ``webview_did_receive_js_message`` gated on those screens' contexts.

Command namespace is ``klausmate_<action>`` (underscore) — deliberately
NOT the editor bridge's ``klausmate:<action>`` (colon), whose handler
claims and drops any message from a non-Editor context.

**The square has ONE state.** Importing used to "arm" the PDF: session
state (``_armed_pdf``/``arm``/``disarm_if``), a ``klausmate_disarm``
bridge command, and a second rendering of the square that named the
file and offered a × to dismiss it. That existed to stage a PDF for the
curate button; with the button gone there was nothing left to arm FOR,
and a square naming a file with no action attached is a confirmation
Anki already gives — ``import_pdf_file`` tooltips "Klaus: loaded '<name>'"
on every import surface. K-151 removed the armed half whole rather than
leaving a vestige: state, command, handler branch, HTML, the deck/overview
re-render it needed, and ``pdf_drive``'s ``disarm_if`` call on delete.
"""

from __future__ import annotations

import os
from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QTimer
from aqt.utils import tooltip

BROWSE_CMD = "klausmate_browse"


# --------------------------------------------------------------- import


def _import_pdfs(paths: list[str], skipped: int = 0) -> None:
    """Feed dropped/picked paths through the shared import.

    No return value and no screen refresh: ``import_pdf_file`` already
    tooltips each successful load and warns on each failure, and since
    K-151 the square renders the same either way, so there is nothing
    here to tell the deck screen about.
    """
    from . import import_pdf_file

    for path in paths:
        try:
            import_pdf_file(path)
        except Exception as e:
            print(f"[klausmate] deck-drop import failed for {path}: {e}")
    if skipped:
        tooltip(f"Klaus imported the PDF — ignored {skipped} other file(s).")


def _browse_for_pdfs() -> None:
    """Open the file dialog and feed picks through the same path as a drop."""
    from aqt.qt import QFileDialog

    paths, _ = QFileDialog.getOpenFileNames(
        mw, "Import lecture PDF", "", "PDF files (*.pdf)"
    )
    if paths:
        _import_pdfs(list(paths))


def _on_browse_clicked() -> None:
    # Never open a modal QFileDialog synchronously inside the JS-message
    # callback — defer it exactly like the drop wrapper defers its import.
    QTimer.singleShot(0, _browse_for_pdfs)


# ------------------------------------------------------------- installs


def on_deck_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    """Claim the deck-surface link command (underscore namespace).

    One command since K-151 retired ``klausmate_disarm`` with the armed
    square. The handler stays registered for it: a js-message handler
    leaving the roster is as deliberate a change as one arriving
    (tests/test_bridge_reentrancy.py).
    """
    if message != BROWSE_CMD:
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
    _on_browse_clicked()
    return (True, None)


def _drop_square_html() -> str:
    """Render the drop-PDF square: the invitation plus its Browse anchor.

    Single source for every deck-scoped screen — deck browser and deck
    overview — so they can never drift apart from each other. ONE state
    since K-151: there is no armed variant to reflow into.

    Fixed to the bottom of the CONTENT webview's own viewport rather than
    flowing in-place: on both the deck browser and the deck overview, the
    stats/table HTML this gets appended to renders in the main content
    webview (mw.web), while Anki's own button row (Get Shared / Create
    Deck / Import File — K-146 took Klaus's button out of it)
    lives in a SEPARATE webview (mw.bottomWeb, via aqt.toolbar.BottomBar)
    pinned below it — same split on both screens (both construct
    ``self.bottom = BottomBar(mw, mw.bottomWeb)`` in the real Anki source).
    There is no shared document to lay these two out against each other in
    normal flow, so `position: fixed; bottom` is what actually lands this
    directly above that button row on either screen — it stops exactly at
    the edge of the content webview, which is exactly where the separate
    bottom-bar webview begins.
    """
    # Colours from the shared theme tokens (theme.drop_zone_qss renders
    # the same values as QSS for the Library's Qt drop zone).
    try:
        from . import theme as _theme

        _c = _theme.palette(_theme.night_mode())
        _idle_border = f"1px dashed {_c['grey_mid']}"
        _btn_border = f"1px solid {_c['grey_mid']}"
    except Exception:
        _idle_border = "1px dashed rgba(128,128,128,0.55)"
        _btn_border = "1px solid rgba(128,128,128,0.55)"
    # One flex row, not a stacked block: the label takes the free space and
    # Browse… sits hard right, matching the Qt surfaces in
    # pdf_drive._LibraryDropZone and __init__._PdfBar.
    body = (
        "<span style='flex:1;text-align:left;'>"
        "Drop a lecture PDF to add it to your Library</span>"
        f"<a href=# onclick='pycmd(\"{BROWSE_CMD}\"); return false;' "
        "style='flex:0 0 auto;padding:3px 10px;"
        f"border:{_btn_border};border-radius:6px;"
        "font-size:12px;color:inherit;text-decoration:none;'>"
        "Browse&hellip;</a>"
    )
    return (
        f"<div style='position:fixed;left:50%;bottom:10px;"
        f"transform:translateX(-50%);z-index:50;"
        f"display:flex;align-items:center;gap:10px;"
        f"margin:0;padding:8px 14px;max-width:420px;width:calc(100% - 40px);"
        f"box-sizing:border-box;background:var(--window-bg,transparent);"
        f"border:{_idle_border};border-radius:12px;"
        f"font-size:13px;opacity:0.95;color:inherit;'>{body}</div>"
    )


def on_deck_browser_content(deck_browser: Any, content: Any) -> None:
    """Inject the drop square above the deck list."""
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
                            0, lambda p=list(pdfs), s=others: _import_pdfs(p, s)
                        )
                        return
        except Exception as e:
            print(f"[klausmate] drop wrap failed, delegating: {e}")
        return original(self, evt)

    cls.dropEvent = dropEvent
    cls._klausmate_drop_orig = original
    cls._klausmate_drop_wrapped = True


def setup() -> None:
    """Install every deck surface; each failure is isolated and logged.

    K-146 dropped two installs with the button they existed for: the
    ``DeckBrowser.drawLinks`` append and the ``overview_will_render_bottom``
    filter. Klaus adds nothing to either bottom bar now. K-151 dropped a
    third — the ``profile_will_close`` handler that reset the armed PDF —
    because there is no session state left in this module to reset.
    """
    try:
        _install_drop_wrap()
    except Exception as e:
        print(f"[klausmate] drop wrap setup failed: {type(e).__name__}: {e}")

    try:
        gui_hooks.webview_did_receive_js_message.append(on_deck_js_message)
    except Exception as e:
        print(f"[klausmate] deck js hook failed: {e}")
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
