"""Klaus reader panel: ``PdfSidebar``, the PDF reader every host wraps.

The editor dock, the Lecture panel and Browse's viewer mode each hold one.
It renders through pdf.js (``pdfjs_viewer.PdfJsViewer``); without
QtWebEngine it shows a "PDF viewer is unavailable" label instead (PDF
reader 5/5 deleted the native QPdfView renderer, so there is no fallback).
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import weakref
from typing import Callable, Optional

from aqt.editor import Editor
from aqt.qt import QLabel, QMenu, QSizePolicy, Qt, QTimer, QVBoxLayout, QWidget
from aqt.utils import tooltip

from . import settings
from .slot_guard import guarded as _guarded

# Every live PdfSidebar, weakly held (K-078): the profile-close sweep and
# a Library delete reach them all. Weak so a closed Library window's
# sidebar can be collected.
_open_sidebars: "weakref.WeakSet" = weakref.WeakSet()


def cleanup_all_sidebars() -> None:
    """Backstop for the AnkiWebView-hook leak (see PdfSidebar.cleanup).

    The explicit teardown paths (Library close, editor panel close)
    cover the common cases; this sweeps every live sidebar on profile
    switch and on quit so a path nobody enumerated still can't leave a
    dangling webview in Anki's theme_did_change hook. Idempotent —
    cleanup() is safe to call twice."""
    for sb in list(_open_sidebars):
        try:
            sb.cleanup()
        except Exception as exc:
            print(f"[klausmate] sidebar cleanup sweep failed: {exc}")


def occlude_media_stem(safe: str, page0: int, region: bool) -> str:
    """Media name (no extension) for an occluded page or region."""
    return f"{safe}-p{page0 + 1}" + ("-region" if region else "")


def _pdf_display_name(safe: str) -> str:
    """Human label for a stored PDF, falling back to its safe basename.

    A drive_store lookup that is safe on any failure: display names are
    bookkeeping, and a missing or corrupt drive.json must cost a label,
    never a menu.
    """
    try:
        from . import drive_store
        from . import settings

        return drive_store.display_name(settings.user_files(), safe)
    except Exception:
        return safe


class PdfSidebar(QWidget):
    """Right-side sidebar: one scrollable PDF document."""

    def __init__(
        self,
        editor: Editor,
        parent: Optional[QWidget] = None,
        host_key: str = "editor",
    ) -> None:
        super().__init__(parent)
        # The panel styles ITSELF (K-153), exactly as the find bar and
        # the thumb strip already do — those two are the only parts of
        # the viewer that looked identical in all three hosts, and that
        # is precisely because they never depended on which window they
        # landed in. This widget used to carry no sheet and no styled
        # background, so it painted nothing and the host showed through
        # every gap. Applied here, on the one widget every host wraps,
        # rather than in any host: no host can forget it, the viewer sits
        # inside it, and a fourth host gets the look for free. See
        # theme.pdf_panel_qss for each rule.
        try:
            from . import theme as _theme

            self.setObjectName("KlausPdfPanel")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(_theme.pdf_panel_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] pdf panel theme failed: {exc}")
        self._editor = editor
        self._name: Optional[str] = None
        # Which host this panel lives in ("editor", "lecture"); _path is
        # where the shown PDF is now. Open readers follow the folder through
        # doc_sync's events (PDF reader 1/5), each registered under its own
        # key so two panels of one host never close each other's (R36).
        self.host_key = host_key
        self._sync_key = f"{host_key}:{id(self)}"
        self._path: Optional[str] = None
        self._held: Optional[str] = None  # the name open in doc_sync
        self._unsub_doc: Optional[Callable[[], None]] = None
        try:
            _open_sidebars.add(self)
        except Exception:
            pass
        self._page_count = 0
        self._current_page = 0
        # Task 10 (K-196) fix round 1: which document _on_pdfjs_count's
        # eventual callback belongs to. Set in load_pdf's pdf.js branch
        # at the same moment as self._name; _on_pdfjs_count compares the
        # two by IDENTITY (not just "is self._name truthy") before
        # touching viewer_context, so a late count for a document this
        # sidebar has since left cannot resurrect it.
        self._pending_count_name: Optional[str] = None
        # Set by a host that wants to hear every load (any call site).
        self.on_loaded: Optional[Callable[[str], None]] = None
        # Per-tab reading position for the session (PDF reader 3/5).
        self._syncing = False
        self._last_page: dict[str, int] = {}

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Every reader runs on pdf.js. Without QtWebEngine there is no
        # viewer (PDF reader 5/5 deleted the native one): the panel says
        # so in a label rather than showing blank (R45).
        try:
            from . import pdfjs_viewer as _pdfjs
        except Exception as exc:
            print(f"[klausmate] pdf.js viewer import failed: {exc}")
            _pdfjs = None

        self._viewer = None
        self._fallback_label = None
        if _pdfjs is not None and _pdfjs.PDFJS_AVAILABLE:
            self._viewer = _pdfjs.PdfJsViewer(
                on_page_changed=self.notify_page_changed,
                parent=self,
            )
            self._viewer.on_selection = self._report_selection
            self._viewer.on_stale = self._on_viewer_stale
            self._viewer.on_occlude = self._on_occlude
            self._tell_occlusion_enabled()  # built with an editor already
            outer.addWidget(self._viewer, 1)
        else:
            if _pdfjs is not None:
                print("[klausmate] pdf.js unavailable (no QtWebEngine): no PDF viewer")
            self._fallback_label = QLabel(
                "PDF viewer is unavailable on this Anki build.\n"
                "Klaus will still index it for curation and retention scoring.",
                self,
            )
            self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fallback_label.setWordWrap(True)
            outer.addWidget(self._fallback_label, 1)

        # The tab strip lives in the reader (PDF reader 3/5), so every host
        # has its own tab set, stored under its host_key. It adopts the
        # viewer's page label. Last session's set comes back as labels
        # only; a document loads when a tab is selected.
        from .reader_tabs import ReaderTabs

        self.tabs = ReaderTabs(
            self, page_label=getattr(self._viewer, "_page_label", None)
        )
        outer.insertWidget(0, self.tabs)
        self.tabs.activated.connect(self._on_tab_changed)
        self.tabs.closed.connect(self._on_tab_close)
        self.tabs.add_requested.connect(self._show_add_menu)
        self.tabs.bar.tabMoved.connect(lambda *_: self._persist())
        try:
            from . import pdf_handler

            restored = pdf_handler.load_open_tabs(settings.user_files(), self.host_key)
        except Exception as exc:
            print(f"[klausmate] tab restore failed: {exc}")
            restored = []
        self.tabs.set_tabs(restored, None)

    @property
    def _editor(self) -> Optional[Editor]:
        return self._editor_ref

    @_editor.setter
    def _editor(self, editor: Optional[Editor]) -> None:
        """reader_host assigns this directly as the Add/Edit window comes and
        goes, so the page's "Occlude" items follow it from here."""
        self._editor_ref = editor
        self._tell_occlusion_enabled()

    def _tell_occlusion_enabled(self) -> None:
        # No viewer yet (the first assignment is in __init__), or a stand-in
        # that predates the call: nothing to tell.
        push = getattr(getattr(self, "_viewer", None), "set_occlusion_enabled", None)
        if push is not None:
            push(self._editor_ref is not None)

    def _on_occlude(self, png: bytes, page0: int, region: bool) -> None:
        """Write the rendered page/region as <stem>.png in a fresh temp dir
        and open the mask editor on it. IOE copies the image into the
        collection's media itself (``col.media.add_file``) when the notes are
        made, so nothing here touches user_files or the media folder."""
        from . import image_occlusion
        from .pdfjs_viewer import NO_EDITOR_TIP

        editor = self._editor_ref
        if editor is None:
            tooltip(NO_EDITOR_TIP)
            return
        if not self._name:
            return
        folder = tempfile.mkdtemp(prefix="klaus-occlude-")
        # The editor reads the file after this returns (svg-edit loads it
        # by URL), so it can only go at exit.
        atexit.register(shutil.rmtree, folder, True)
        path = os.path.join(folder, occlude_media_stem(self._name, page0, region) + ".png")
        with open(path, "wb") as f:
            f.write(png)
        if not image_occlusion.occlude(editor, path, None):
            tooltip(
                image_occlusion.CONFLICT_TOOLTIP
                if not image_occlusion._active
                else "Klaus: couldn't open the occlusion editor"
            )

    def notify_page_changed(self, page: int) -> None:
        self._on_page_changed(page)

    def _report_selection(self, text: str) -> None:
        """Task 10 (K-196): forward a live selection into viewer_context.

        Wired as the viewer's ``on_selection`` hook (plain text), so
        there is one guarded viewer_context call site.
        """
        try:
            from . import viewer_context

            viewer_context.report_selection(id(self), text)
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def is_loaded(self, name: str | None = None) -> bool:
        if self._name is None or self._page_count <= 0:
            return False
        if name is not None and self._name != name:
            return False
        return True

    def load_pdf(self, name: str) -> None:
        from . import pdf_handler, viewer_context
        from . import settings

        path = pdf_handler.pdf_path_for(settings.user_files(), name)
        if not path:
            if self._fallback_label is not None:
                self._fallback_label.setText(
                    f"The raw PDF for '{name}' is not stored.\n"
                    "Re-add it via the editor's PDF panel or the Library to enable the viewer."
                )
            viewer_context.forget(id(self))
            self._release(flush=False)
            self._name = None
            self._page_count = 0
            if self._viewer is not None:  # never the previous document under this tab
                self._viewer.clear_document()
            return
        self._follow(name, path)
        self._request_save_if_stale(name, path)

        self._name = name
        pages_text = pdf_handler.load_pages(settings.user_files(), name) or []
        self._page_count = len(pages_text)
        if self._viewer is not None:
            # The webview loads from bytes; the page count arrives async
            # over the bridge (on_count refines the text-pages
            # approximation used until then).
            # Task 10 (K-196) fix round 1: the name THIS load belongs to,
            # captured now so the eventual async count callback can tell
            # a late count for an abandoned load apart from a fresh one.
            self._pending_count_name = name
            self._viewer.set_page_texts(pages_text)
            self._viewer.on_count = self._on_pdfjs_count
            self._viewer.load_path(path, name)
            # Annotations restore right after the document feed (the
            # viewer re-pushes them on the page's async "ready", so
            # ordering is safe).
            try:
                self._viewer.load_annotations(name)
            except Exception as exc:
                print(f"[klausmate] annotations restore failed: {exc}")
            self._on_page_changed(0)
        self._notify_loaded(name)

    def _on_pdfjs_count(self, count: int) -> None:
        """Task 10 (K-196) fix round 1: the async pdf.js count refines
        the text-layer estimate report_document (already fired from
        _notify_loaded) used — but this callback is registered once per
        load and can still arrive AFTER the sidebar has moved on to a
        different document (a fast reload-before-count race). Guarded on
        IDENTITY, not presence: self._name == self._pending_count_name
        is "this count still belongs to the document that is actually
        showing", not just "some document happens to be loaded". A
        stale count is a complete no-op — it must not touch
        self._page_count (that would be reporting a foreign page count
        as this sidebar's own) and, critically, must not call
        viewer_context.activate() or reset page/selection the way a
        full _report_document() re-call would: it goes through the
        narrower report_page_count instead, which touches only
        page_count in place."""
        if count > 0 and self._name and self._name == self._pending_count_name:
            self._page_count = count
            try:
                from . import viewer_context

                viewer_context.report_page_count(id(self), self._page_count)
            except Exception as exc:
                print(f"[klausmate] viewer_context: {exc}")

    def _report_document(self) -> None:
        """Task 10 (K-196): tell viewer_context which document this
        sidebar shows and mark it the active one. Called once a
        document is actually on screen (every load_pdf success path
        funnels through _notify_loaded). _on_pdfjs_count's later,
        narrower catch-up goes through report_page_count instead — see
        its own docstring for why re-calling this one would be wrong."""
        try:
            from . import drive_store, pdf_handler, viewer_context
            from . import settings

            display = drive_store.display_name(settings.user_files(), self._name) or self._name
            path = pdf_handler.pdf_path_for(settings.user_files(), self._name) or ""
            viewer_context.report_document(
                id(self), self._name, display, path, self._page_count
            )
            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def _notify_loaded(self, name: str) -> None:
        self._report_document()
        try:
            self._on_sidebar_loaded(name)
        except Exception as exc:
            print(f"[klausmate] tab sync after load failed for {name}: {exc}")
        cb = self.on_loaded
        if cb is None:
            return
        try:
            cb(name)
        except Exception:
            pass

    # ---- following the folder (doc_sync) ---------------------------------

    def _follow(self, name: str, path: str) -> None:
        """Hold ``name`` open in doc_sync for this host, releasing the
        document shown before, and hear its events. Never raises."""
        if self._held is not None and self._held != name:
            self._release(flush=False)
        self._held, self._path = name, path
        try:
            from . import doc_sync

            if self._unsub_doc is None:
                self._unsub_doc = doc_sync.subscribe(self._on_doc_event)
            doc_sync.open_doc(self._sync_key, name, path)
        except Exception as exc:
            print(f"[klausmate] doc_sync open failed: {exc}")

    def _release(self, flush: bool = True) -> None:
        """Stop holding the document in doc_sync; with ``flush``, bake its
        pending marks first. Idempotent. Never raises."""
        name, self._held = self._held, None
        if name is None:
            return
        if flush:
            try:
                from . import annotation_save

                annotation_save.pipeline().flush(name)
            except Exception as exc:
                print(f"[klausmate] save flush failed for {name}: {exc}")
        try:
            from . import doc_sync

            doc_sync.close_doc(self._sync_key, name)
        except Exception as exc:
            print(f"[klausmate] doc_sync close failed: {exc}")

    def _request_save_if_stale(self, name: str, path: str) -> None:
        """Marks in the JSON newer than the PDF (a quit mid-debounce, a save
        that failed before a restart) are baked now. Never raises."""
        try:
            from . import annotation_save, pdf_handler, pdf_source

            jpath = pdf_handler.annotations_path_for(pdf_source.user_files_dir(), name)
            if os.path.isfile(jpath) and os.path.getmtime(jpath) > os.path.getmtime(path) + 1.0:
                print(f"[klausmate] marks newer than {name}'s file; saving")
                annotation_save.pipeline().request(name)
        except Exception as exc:
            print(f"[klausmate] stale-save check failed for {name}: {exc}")

    def _on_doc_event(self, event: str, safe: str, path: Optional[str]) -> None:
        """doc_sync: the shown PDF changed outside Klaus, moved, or left the
        Library folder (that one also closes a background tab). Other
        documents' events are ignored."""
        if safe != self._name and event != "missing":
            return
        try:
            self.isVisible()
        except RuntimeError:  # C++ side already deleted: let go of doc_sync
            self._release(flush=False)
            unsub, self._unsub_doc = self._unsub_doc, None
            if unsub is not None:
                unsub()
            return
        if safe != self._name:  # a background tab's PDF left the folder
            self.tabs.close(safe)
            return
        if event == "changed":
            self._reload_from_disk(safe, toast=True)
        elif event == "moved" and path:
            self._path = path
            repoint = getattr(self._viewer, "repoint", None)
            if repoint is not None:
                repoint(path)
        elif event == "missing":
            # Close the document and its tab (R50). Marks, the JSON, context
            # and prefs stay: in a bulk Finder rename the next scan reports
            # the same file "moved" and it can be reopened (R33). No flush:
            # a bake now would recreate the file at its old path. The tab
            # closes last: that selects (and loads) a neighbour, which a
            # clear() after it would wipe.
            try:
                from . import drive_store, pdf_source

                display = drive_store.display_name(pdf_source.user_files_dir(), safe) or safe
            except Exception:
                display = safe
            self._release(flush=False)
            self.clear()
            self.tabs.close(safe)
            tooltip(f"{display} was removed from your Library folder.")

    def _on_viewer_stale(self) -> None:
        """pdf.js read a range of a file that changed under it: the same
        reload as "changed", silently (R21)."""
        self._reload_from_disk(self._name, toast=False)

    def _reload_from_disk(self, name: Optional[str], toast: bool) -> None:
        """Bake pending marks, let an open text box commit, then reload in
        place keeping page and zoom; the reload re-reads the marks and
        mirrors outside ones."""
        if name is None or name != self._name:
            return
        try:
            from . import annotation_save

            annotation_save.pipeline().flush(name)
        except Exception as exc:
            print(f"[klausmate] save flush failed for {name}: {exc}")

        def _reload() -> None:
            try:
                if self._name != name or self._held != name:
                    return  # left, cleared or cleaned up while waiting
                self.isVisible()
                print(f"[klausmate] {name} changed on disk — reloading viewer")
                self._reload_in_place(name)
                if toast:
                    tooltip("Updated from disk")
            except Exception as exc:
                print(f"[klausmate] reload from disk failed: {exc}")

        commit = getattr(self._viewer, "commit_open_edit", None)
        if commit is None:
            _reload()
        else:
            commit(_reload)

    def _reload_in_place(self, name: str) -> None:
        v = self._viewer
        if v is None:
            self.load_pdf(name)
            return
        v.load_path(self._path, name, keep_view=True)
        v.load_annotations(name)

    def jump_to_page(self, page: int) -> None:
        if self._viewer is None or self._page_count <= 0:
            return
        page = max(0, min(int(page), self._page_count - 1))
        self._viewer.go_to_page(page)

    def cleanup(self) -> None:
        """Release renderer resources before this widget tree is
        destroyed. The pdf.js viewer owns an AnkiWebView, which must be
        unregistered from Anki's global hooks (see PdfJsViewer.cleanup),
        and drops its save-pipeline subscription. Bakes pending marks and
        releases the document in doc_sync first. Call from every path
        that tears a sidebar down."""
        self._release()
        unsub, self._unsub_doc = self._unsub_doc, None
        if unsub is not None:
            unsub()
        v = self._viewer
        fn = getattr(v, "cleanup", None) if v is not None else None
        if fn is not None:
            try:
                fn()
            except Exception as exc:
                print(f"[klausmate] viewer cleanup failed: {exc}")
        try:
            from . import viewer_context

            viewer_context.forget(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def clear(self) -> None:
        self._release()
        self._name = None
        self._page_count = 0
        self._current_page = 0
        if self._viewer is not None:
            self._viewer.clear_document()
        try:
            from . import viewer_context

            viewer_context.forget(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def _on_page_changed(self, page: int) -> None:
        if self._name is None or self._page_count <= 0:
            return
        try:
            page = int(page)
        except (TypeError, ValueError):
            return
        last = max(0, self._page_count - 1)
        self._current_page = max(0, min(page, last))
        if self._viewer is None:  # no viewer label to adopt: ours shows it
            self.tabs.set_page(self._current_page + 1, self._page_count)
        try:
            from . import viewer_context

            viewer_context.report_page(id(self), self._current_page)
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def showEvent(self, ev) -> None:  # noqa: N802
        # Task 10 (K-196): the assistant dock follows viewer_context's
        # last-ACTIVATED viewer — the Library's, Browse's editor pane and
        # the Lecture dock all reuse this one widget, so becoming visible
        # (a tab switch, an unhide) is "the user is looking at this one"
        # regardless of which host it lives in.
        super().showEvent(ev)
        try:
            from . import viewer_context

            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        # Same seam as showEvent: a click into an already-visible sidebar
        # (e.g. the user switches focus between two open panes without
        # either one being re-shown) still moves it to "current".
        super().mousePressEvent(ev)
        try:
            from . import viewer_context

            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    # ---- tabs (moved from PdfDock, PDF reader 3/5) ----

    def _persist(self) -> None:
        try:
            from . import pdf_handler
            from . import settings

            pdf_handler.save_open_tabs(settings.user_files(), self.tabs.names(), self.host_key)
        except Exception:
            pass

    def _set_active_pointer(self, name: str) -> None:
        from . import pdf_handler
        from . import settings

        # The active PDF is the editor dock's pointer (what it opens next
        # session); another host's reader must not move it.
        if self.host_key == "editor":
            try:
                pdf_handler.set_active_pdf(settings.user_files(), name)
            except Exception:
                pass
        try:
            # Recency signal for the ＋ menu's most-recent-first ordering.
            pdf_handler.touch_last_used(settings.user_files(), name)
        except Exception:
            pass

    def _on_sidebar_loaded(self, name: str) -> None:
        """A PDF loaded (from any call site): make sure a tab exists for
        it and is selected, without re-triggering a load."""
        if not name:
            return
        self._last_page.setdefault(name, 0)
        self._syncing = True
        try:
            self.tabs.open(name)
        finally:
            self._syncing = False
        self._persist()
        self._set_active_pointer(name)

    @_guarded
    def _on_tab_changed(self, name: str) -> None:
        if self._syncing or not name:
            return
        prev = self._name
        if prev and prev != name:
            self._last_page[prev] = self._current_page
        if self.is_loaded(name):
            self._set_active_pointer(name)
            return
        self.load_pdf(name)
        page = self._last_page.get(name, 0)
        if page > 0:
            # One tick so the viewer takes the new document before we
            # jump back to the remembered position.
            QTimer.singleShot(
                0, lambda: self.jump_to_page(page)
            )

    @_guarded
    def _on_tab_close(self, name: str) -> None:
        # The strip removed the tab first; closing the current one has
        # already selected (and loaded) a neighbour.
        self._last_page.pop(name, None)
        self._persist()
        if not self.tabs.names():
            try:
                self.clear()
            except Exception:
                pass
            if self.host_key == "editor":
                try:
                    from . import pdf_handler
                    from . import settings

                    pdf_handler.clear_active_pdf(settings.user_files())
                except Exception:
                    pass

    @_guarded
    def _show_add_menu(self, *_args) -> None:
        # *_args: @_guarded's wrapper accepts every signal argument.
        from . import pdf_handler
        from . import settings

        menu = QMenu(self)
        open_names = set(self.tabs.names())
        stored: list[str] = []
        # Most recently used first (pdf_handler.list_by_recency ranks by
        # last_used, falling back to contexts/<safe>.txt mtime — ingest
        # time — rather than pdfs/<safe>.pdf's mtime, which shutil.copy2
        # preserves from the source file).
        for base in pdf_handler.list_by_recency(settings.user_files()):
            if base in open_names:
                continue
            if pdf_handler.pdf_path_for(settings.user_files(), base):
                stored.append(base)
        # No cap. This menu is the only way to open a stored PDF in the
        # editor's viewer, so truncating it would strand every PDF past
        # the cut with no route in. (The deck screen used to carry a
        # top-20 curate-from-recent menu, the shortcut this was
        # contrasted against; K-146 removed it and the Library is the
        # full path now.) QMenu scrolls natively when it overflows.
        for base in stored:
            act = menu.addAction(_pdf_display_name(base))
            act.triggered.connect(
                lambda _=False, b=base: self.load_pdf(b)
            )
        if not stored:
            # The editor deliberately has no way to ADD a PDF (K-056) —
            # only the Library window's drop zone imports new ones.
            hint = menu.addAction(
                "Every Library PDF is already open"
                if open_names
                else "No PDFs in your Library yet"
            )
            hint.setEnabled(False)
        add_btn = self.tabs.add_btn
        menu.exec(add_btn.mapToGlobal(add_btn.rect().bottomLeft()))
        menu.deleteLater()  # its actions already fired inside exec()
