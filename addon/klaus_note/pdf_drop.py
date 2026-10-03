"""Import a lecture PDF from Anki's deck screens — Add to Library and drop wrap.

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
- **Add to Library** — a button in the deck list's and the overview's
  bottom rows (``DeckBrowser.drawLinks``, ``overview_will_render_bottom``),
  beside Anki's own buttons there; it opens the file picker. Its
  ``pycmd`` click arrives over ``webview_did_receive_js_message`` gated on
  those screens' contexts. It replaced the dashed drop square that sat
  in the content webviews (removed on request); a drop still imports.

Command namespace is ``klaus_note_<action>`` (underscore) — deliberately
NOT the editor bridge's ``klaus_note:<action>`` (colon), whose handler
claims and drops any message from a non-Editor context.

**The square has ONE state.** Importing used to "arm" the PDF: session
state (``_armed_pdf``/``arm``/``disarm_if``), a ``klaus_note_disarm``
bridge command, and a second rendering of the square that named the
file and offered a × to dismiss it. That existed to stage a PDF for the
curate button; with the button gone there was nothing left to arm FOR,
and a square naming a file with no action attached is a confirmation
Anki already gives — ``import_pdf_file`` tooltips "KlausNote: loaded '<name>'"
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

BROWSE_CMD = "klaus_note_browse"
ADD_LABEL = "Add to Library"


# --------------------------------------------------------------- import


REPLACE, KEEP_BOTH = "replace", "keep"


def _import_pdfs(paths: list[str], skipped: int = 0, ask=None) -> None:
    """Feed dropped/picked paths through the shared import.

    A PDF whose name is already in the Library is asked about first
    (#10): Replace, Keep Both or Cancel, one window-modal prompt per
    clashing file, in order — the next file waits for this one's answer,
    and Cancel skips only this one. ``ask`` is the prompt (tests pass a
    fake). No return value and no screen refresh: ``import_pdf_file``
    already tooltips each successful load and warns on each failure.
    """
    ask = ask or _ask_clash
    queue = list(paths)

    def resume(path: str, choice: str | None) -> None:
        if getattr(mw, "col", None) is None:
            return  # the profile closed while the prompt was up
        _import_one(path, choice)
        run()

    def run() -> None:
        while queue:
            path = queue.pop(0)
            shown = _clash_name(path)
            if shown:
                def answered(choice: str | None, p: str = path) -> None:
                    # A tick later, so the box has closed before the next
                    # one opens (bridge_reentrancy's deferral rule).
                    QTimer.singleShot(0, lambda: resume(p, choice))

                ask(path, shown, answered)
                return
            _import_one(path, KEEP_BOTH)
        if skipped:
            tooltip(f"KlausNote imported the PDF and ignored {skipped} other file(s).")

    run()


def _import_one(path: str, choice: str | None) -> None:
    if choice is None:
        return  # Cancel
    from . import import_pdf_file

    try:
        import_pdf_file(path, replace=choice == REPLACE)
    except Exception as e:
        print(f"[klaus_note] deck-drop import failed for {path}: {e}")


def _clash_name(path: str) -> str | None:
    """The Library name an import of *path* would clash with, as the
    Library shows it; None when the name is free (or unknowable — the
    import then keeps both, which never overwrites)."""
    try:
        from . import drive_store, pdf_handler, settings

        uf = settings.user_files()
        safe = pdf_handler.name_in_library(uf, os.path.splitext(os.path.basename(path))[0])
        if safe is None:
            return None
        shown = drive_store.display_name(uf, safe)
        return shown if shown != safe else os.path.basename(path)
    except Exception as e:
        print(f"[klaus_note] import clash check failed for {path}: {e}")
        return None


def _ask_clash(path: str, shown: str, answer, parent: Any = mw) -> Any:
    """Replace / Keep Both / Cancel for one clashing PDF. Window-modal
    open(), never exec() (K-114); ``answer`` gets REPLACE, KEEP_BOTH or
    None (Cancel, Escape, closed)."""
    from aqt.qt import QMessageBox, Qt

    box = QMessageBox(parent)
    box.setWindowTitle("Add to Library")
    box.setText(f"“{shown}” is already in your Library.")
    box.setInformativeText("Replace moves the old file to the Trash.")
    replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep Both", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(keep)
    box.setEscapeButton(cancel)
    box.setWindowModality(Qt.WindowModality.WindowModal)

    def done(_result: int) -> None:
        try:
            hit = box.clickedButton()
            answer(REPLACE if hit is replace else KEEP_BOTH if hit is keep else None)
        finally:
            box.deleteLater()

    box.finished.connect(done)
    box.open()
    return box


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

    One command since K-151 retired ``klaus_note_disarm`` with the armed
    square. The handler stays registered for it: a js-message handler
    leaving the roster is as deliberate a change as one arriving
    (tests/test_bridge_reentrancy.py).
    """
    if message != BROWSE_CMD:
        return handled
    try:
        from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar

        valid_contexts: tuple[type, ...] = (DeckBrowser, DeckBrowserBottomBar)
        try:
            from aqt.overview import OverviewBottomBar

            valid_contexts += (OverviewBottomBar,)
        except Exception:
            pass
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


def add_library_link(links: list) -> None:
    """Append Add to Library to a bottom-row link list, once, so the
    button sits in Anki's own row beside Get Shared / Create Deck."""
    link = ["", BROWSE_CMD, ADD_LABEL]
    if link not in links:
        links.append(link)


def on_overview_will_render_bottom(link_handler: Any, links: list) -> Any:
    """``overview_will_render_bottom`` filter: the same button on the
    deck overview's row. Returns Anki's link handler untouched."""
    add_library_link(links)
    return link_handler


def _install_drop_wrap() -> None:
    """Wrap MainWebView.dropEvent so PDFs never reach Anki's importer."""
    import aqt.main

    cls = getattr(aqt.main, "MainWebView", None)
    if cls is None or not hasattr(cls, "dropEvent"):
        print("[klaus_note] MainWebView.dropEvent missing — PDF drop disabled")
        return
    if getattr(cls, "_klaus_note_drop_wrapped", False):
        return
    original = cls.dropEvent

    def dropEvent(self, evt):  # noqa: N802 — Qt naming
        try:
            # Both deck screens (K-040), not just the deck list: without
            # this a PDF dropped on the overview falls through to Anki's
            # own importer, which chokes on it.
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
            print(f"[klaus_note] drop wrap failed, delegating: {e}")
        return original(self, evt)

    cls.dropEvent = dropEvent
    cls._klaus_note_drop_orig = original
    cls._klaus_note_drop_wrapped = True


def setup() -> None:
    """Install every deck surface; each failure is isolated and logged.

    K-146 dropped the curate button's ``DeckBrowser.drawLinks`` append and
    ``overview_will_render_bottom`` filter; Add to Library uses the same
    two installs now, in place of the drop square. K-151 dropped a
    third — the ``profile_will_close`` handler that reset the armed PDF —
    because there is no session state left in this module to reset.
    """
    try:
        _install_drop_wrap()
    except Exception as e:
        print(f"[klaus_note] drop wrap setup failed: {type(e).__name__}: {e}")

    try:
        gui_hooks.webview_did_receive_js_message.append(on_deck_js_message)
    except Exception as e:
        print(f"[klaus_note] deck js hook failed: {e}")
    try:
        from aqt.deckbrowser import DeckBrowser

        add_library_link(DeckBrowser.drawLinks)
    except Exception as e:
        print(f"[klaus_note] deck browser Add to Library failed: {e}")
    if hasattr(gui_hooks, "overview_will_render_bottom"):
        try:
            gui_hooks.overview_will_render_bottom.append(on_overview_will_render_bottom)
        except Exception as e:
            print(f"[klaus_note] overview Add to Library failed: {e}")
