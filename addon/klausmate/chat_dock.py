"""Klaus panel — right-side dock hosting the semantic curation page.

Formerly the chat dock (the module name stays so the saved dock geometry —
keyed on the "klausmateChatDock" objectName — survives the upgrade). The
page is web/search.html: one centered search bar with one job, curating a
deck from a lecture prompt and/or PDF via curation.run_curation().

Threading contract: curation's pipeline runs on QueryOp workers and fires
its callbacks on the main thread; a seq token discards events from a
cancelled/replaced run.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from typing import Any

from aqt import mw
from aqt.qt import Qt, QDockWidget, QWidget
from aqt.webview import AnkiWebView

from . import curation

_controller: "KlausPanelController | None" = None


def _fmt_ago(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60} min ago"
    if secs < 172800:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} days ago"


class KlausPanelController:
    def __init__(self) -> None:
        self.busy = False
        self.cancel_event: threading.Event | None = None
        self.seq = 0

        self.dock = QDockWidget("Klaus", mw)
        # Keep the historical objectName: saved geometry restores across
        # the chat → curation upgrade.
        self.dock.setObjectName("klausmateChatDock")
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        # No native title bar — the in-page header has the close button.
        self.dock.setTitleBarWidget(QWidget())
        self.dock.setMinimumWidth(340)

        self.web = AnkiWebView(parent=self.dock, title="klaus panel")
        self.web.set_bridge_command(self._on_bridge, self)
        self.dock.setWidget(self.web)

        # objectName gives us saved geometry from Anki's mainWindow state.
        if not mw.restoreDockWidget(self.dock):
            mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            mw.resizeDocks([self.dock], [380], Qt.Orientation.Horizontal)

        self._render_page()

    # ------------------------------------------------------------------ UI

    def _render_page(self) -> None:
        from . import ADDON_DIR

        try:
            with open(
                os.path.join(ADDON_DIR, "web", "search.html"), encoding="utf-8"
            ) as f:
                body = f.read()
        except OSError as e:
            body = f"<pre>Klaus panel failed to load: {e}</pre>"
        pkg = mw.addonManager.addonFromModule(__name__)
        self.web.stdHtml(
            body,
            css=[f"/_addons/{pkg}/web/search.css"],
            js=[f"/_addons/{pkg}/web/search.js"],
            context=self,
        )
        # JS pushes "klaus:ready" on DOMContentLoaded; init state is sent
        # from that handler, so there is no eval-before-load race.

    def _eval(self, js: str) -> None:
        try:
            self.web.eval(f"window.klausSearch && ({js});")
        except Exception as e:
            print(f"[klausmate] panel eval failed: {e}")

    def _index_status_payload(self) -> dict:
        st = curation.index_stats()
        return {
            "exists": bool(st["exists"]),
            "count": int(st["count"]),
            "ago": _fmt_ago(st["updated_at"]) if st["exists"] else "",
        }

    def _push_init(self) -> None:
        from . import USER_FILES, pdf_handler

        pdfs = []
        for name in pdf_handler.list_contexts(USER_FILES):
            label = name[:-4] if name.endswith(".txt") else name
            pdfs.append({"value": name, "label": label})
        decks = []
        if mw.col is not None:
            for entry in mw.col.decks.all_names_and_ids():
                decks.append({"value": entry.name, "label": entry.name})
        state = {
            "pdfs": pdfs,
            "decks": decks,
            "indexStatus": self._index_status_payload(),
        }
        self._eval(f"klausSearch.init({json.dumps(state)})")

    def _push_index_status(self) -> None:
        self._eval(
            f"klausSearch.setIndexStatus({json.dumps(self._index_status_payload())})"
        )

    # -------------------------------------------------------------- bridge

    def _on_bridge(self, message: str) -> Any:
        if not message.startswith("klaus:"):
            return False
        rest = message[len("klaus:"):]
        action, _, b64 = rest.partition(":")
        payload: dict = {}
        if b64:
            try:
                payload = json.loads(base64.b64decode(b64).decode("utf-8"))
            except Exception as e:
                print(f"[klausmate] panel bridge payload error: {e}")
                return True
        try:
            self._dispatch(action, payload)
        except Exception as e:
            print(f"[klausmate] panel action '{action}' failed: {type(e).__name__}: {e}")
        return True

    def _dispatch(self, action: str, payload: dict) -> None:
        if action == "ready":
            self._push_init()
        elif action == "search":
            self._on_search(payload)
        elif action == "reindex":
            self._on_reindex()
        elif action == "cancel":
            self._on_cancel()
        elif action == "close":
            self.dock.hide()
        elif action == "log":
            print(f"[klausmate search.js] {payload.get('msg')}")

    # ------------------------------------------------------------ pipeline

    def _begin(self) -> tuple[int, threading.Event] | None:
        if self.busy:
            return None
        self.busy = True
        self.seq += 1
        self.cancel_event = threading.Event()
        return self.seq, self.cancel_event

    def _finish(self, seq: int) -> bool:
        """True when this callback belongs to the live run (not cancelled)."""
        if seq != self.seq:
            return False
        self.busy = False
        return True

    def _on_progress(self, seq: int, label: str, done: int, total: int) -> None:
        if seq != self.seq:
            return
        self._eval(
            f"klausSearch.setProgress({json.dumps(label)}, {int(done)}, {int(total)})"
        )

    def _on_search(self, payload: dict) -> None:
        handle = self._begin()
        if handle is None:
            return
        seq, cancel_event = handle
        prompt = str(payload.get("prompt") or "")
        pdf = str(payload.get("pdf") or "") or None
        deck = str(payload.get("deck") or "") or None
        create_now = bool(payload.get("create"))

        def on_done(result: dict) -> None:
            if not self._finish(seq):
                return
            self._push_index_status()  # a search may have synced the index
            out = {
                "count": len(result["nids"]),
                "previewed": bool(result["previewed"]),
            }
            self._eval(f"klausSearch.searchDone({json.dumps(out)})")
            if create_now and result["nids"]:
                curation.prompt_and_create(mw, result["nids"])

        def on_error(exc: Exception) -> None:
            if not self._finish(seq):
                return
            self._eval(f"klausSearch.showError({json.dumps(_error_text(exc))})")

        curation.run_curation(
            mw,
            prompt=prompt,
            pdf_name=pdf,
            deck_scope=deck,
            preview=not create_now,
            on_progress=lambda l, d, t: self._on_progress(seq, l, d, t),
            on_done=on_done,
            on_error=on_error,
            cancel=cancel_event,
        )

    def _on_reindex(self) -> None:
        handle = self._begin()
        if handle is None:
            return
        seq, cancel_event = handle

        def on_done(_index: Any, completed: bool) -> None:
            if not self._finish(seq):
                return
            self._push_index_status()
            self._eval("klausSearch.setBusy(false)")
            if not completed:
                self._eval(
                    'klausSearch.showError("Indexing cancelled — it resumes '
                    'where it stopped next time.")'
                )

        def on_error(exc: Exception) -> None:
            if not self._finish(seq):
                return
            self._push_index_status()
            self._eval(f"klausSearch.showError({json.dumps(_error_text(exc))})")

        curation.ensure_index(
            mw,
            on_progress=lambda l, d, t: self._on_progress(seq, l, d, t),
            on_done=on_done,
            on_error=on_error,
            cancel=cancel_event,
        )

    def _on_cancel(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
        # The pipeline notices between batches; its callbacks are then
        # discarded by the seq check.
        self.seq += 1
        self.busy = False
        self._eval("klausSearch.setBusy(false)")
        self._push_index_status()

    # ----------------------------------------------------------- lifecycle

    def show(self) -> None:
        self.dock.show()
        self.dock.raise_()
        self._push_index_status()
        self._eval("klausSearch.focusInput()")

    def toggle(self) -> None:
        if self.dock.isHidden():
            self.show()
        else:
            self.dock.hide()

    def profile_will_close(self) -> None:
        self._on_cancel()
        self._eval("klausSearch.reset()")

    def quit(self) -> None:
        self._on_cancel()
        try:
            self.web.cleanup()
        except Exception:
            pass


def _error_text(exc: Exception) -> str:
    from . import embeddings

    if isinstance(exc, embeddings.EmbeddingError):
        return exc.user_message()
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------- module API


def _get(create: bool = False) -> KlausPanelController | None:
    global _controller
    if _controller is None and create:
        _controller = KlausPanelController()
    return _controller


def toggle_chat_dock() -> None:
    ctrl = _get(create=True)
    assert ctrl is not None
    ctrl.toggle()


def show_chat_dock() -> None:
    ctrl = _get(create=True)
    assert ctrl is not None
    ctrl.show()


def on_profile_will_close() -> None:
    ctrl = _get()
    if ctrl is not None:
        ctrl.profile_will_close()


def on_quit() -> None:
    ctrl = _get()
    if ctrl is not None:
        ctrl.quit()
