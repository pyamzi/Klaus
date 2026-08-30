"""KlausBook chrome for Anki's OTHER windows — Add Cards, Browse,
Stats, and the reviewer's bottom bar.

The deck screen's design layer (top_bar.py, background.py,
dashboard.py) stops at the main window. This module carries the same
layer into the rest of the app, under the same rules:

* every style string is a theme.py builder — this file owns GLUE only,
  so all emitted bytes sit under test_theme's design-scale audit;
* everything gates on ``background.design_enabled`` read through the
  ``effective_cfg`` preview seam, AT the painters — native mode is
  byte-stock, and Preferences previews reach every window live;
* Browse is HARMONIZED, never transformed (Pouya's call): tokens for
  selection, hairlines, search and type — Anki's layout and density
  stay. The delegate-painted flag/marked/suspended tints and the
  custom-painted Cards/Notes switch are deliberately untouched
  (semantic, and unreachable by QSS without app-wide colour surgery);
* the reviewer gets CHROME only: bar surface + the shared Klaus chip
  language on its buttons. Its scheduling colours live in the count
  and interval spans, which reviewer_bar_css never styles — the
  semantics survive by omission, and tests pin the omission.

Why tracked refresh instead of style-at-open: ``aqt.dialogs`` CACHES
the Browser and Add Cards instances for the whole session, so a
window opened while native must be restylable later, and a styled
window must restore when the toggle flips off. Widgets register here
at their init hooks REGARDLESS of gate state; ``refresh()`` walks
them, applying or un-applying against the gate read at walk time.
Un-apply restores each widget's ORIGINAL stylesheet, stashed on first
touch — a bare ``setStyleSheet("")`` would also strip the sheets Anki
itself puts on the sidebar tree and the tag bar.

The sidebar tree is the one widget that fights back: Anki's
SidebarTreeView sets its own widget-level sheet and RE-APPLIES it on
every theme flip, from a handler registered at Browser construction —
so winning by hook-registration order is luck, not law. The fix is
structural: our theme_did_change work runs one tick deferred
(QTimer.singleShot(0)), after the entire hook chain — Anki's re-apply
included — has finished. That is top_bar's sanctioned
event-driven-single-deferral pattern, not a style-race retry timer.

Anki 26.8.1 facts this module is built on (verified against the
shipped bytecode, 2026-08-29): macOS-default Anki applies NO app QSS
(so these sheets are unopposed — but they carry explicit backgrounds
to survive the optional "Anki" widget style's app-scope
``QWidget{background:none}``); the Stats page is sveltekit and only
``webview_did_inject_style_into_page`` reaches it (post-load,
pre-show); the editor is dual-path — legacy stdHtml today, a Svelte
rewrite behind an experiment flag — and the Svelte path degrades to
stock here, feature-detected, never probed.

SynapsePro (the design reference) styles none of these windows — this
extension's design is original by construction.

Everything above the "aqt glue" divider is aqt-free and pure, for
``tests/test_window_chrome.py``.
"""

from __future__ import annotations

import json
from typing import Any

from . import background, theme

# The <style> node id on the Stats page. Injection is idempotent by
# removing any previous node with this id before appending — a redraw
# or repeated hook fire must never stack sheets.
STATS_STYLE_ID = "klaus-stats-style"


def stats_inject_js(css: str) -> str:
    """JS that installs *css* on the Stats page, replace-not-stack.

    The CSS rides through ``json.dumps`` so no content of it can
    terminate the script or escape into the page as markup — the same
    escaping discipline as top_bar.chrome_override_js.
    """
    return (
        "(function(){"
        f"var old=document.getElementById({json.dumps(STATS_STYLE_ID)});"
        "if(old)old.remove();"
        "var s=document.createElement('style');"
        f"s.id={json.dumps(STATS_STYLE_ID)};"
        f"s.textContent={json.dumps(css)};"
        "document.head.appendChild(s);"
        "})();"
    )


# ─────────────────────────────────────────────────────────────────────
# aqt glue — everything below here talks to Anki
# ─────────────────────────────────────────────────────────────────────

# widget -> kind. Weak keys: aqt closes these windows on profile
# switch and the entries evaporate with them — no reset hook needed.
_TRACKED: Any = None  # created lazily; WeakKeyDictionary needs weakref

# kind -> the theme builder that styles it. Registry shape so a future
# window is one line here plus its init hook.
_BUILDERS = {
    "browser": "browse_qss",
    "browser_tree": "sidebar_tree_qss",
    "addcards": "utility_window_qss",
    "stats": "utility_window_qss",
    "editor_tags": "editor_tags_qss",
}


def _config() -> dict:
    """Stored config through the SAME preview seam as every other
    design-layer reader, so Preferences previews reach these windows
    before Save."""
    try:
        from aqt import mw

        stored = mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}
    return background.effective_cfg(stored)


def _gate_on() -> bool:
    return background.design_enabled(_config())


def _tracked() -> Any:
    global _TRACKED
    if _TRACKED is None:
        import weakref

        _TRACKED = weakref.WeakKeyDictionary()
    return _TRACKED


def _remember(widget: Any, kind: str) -> None:
    """Register *widget* for the tracked walk — ALWAYS, gate on or
    off: a window opened while native must be reachable when the
    toggle flips on later (aqt.dialogs caches instances all session)."""
    try:
        if widget is not None:
            _tracked()[widget] = kind
    except Exception as exc:
        print(f"[klausmate] window chrome remember failed: {exc}")


def _apply_kind(widget: Any, kind: str, night: bool) -> None:
    """Style one widget, stashing its ORIGINAL sheet on first touch so
    un-apply can restore Anki's own widget-level styling exactly."""
    try:
        if not hasattr(widget, "_klausmate_saved_qss"):
            widget._klausmate_saved_qss = widget.styleSheet()
        builder = getattr(theme, _BUILDERS[kind])
        widget.setStyleSheet(builder(night))
    except Exception as exc:
        print(f"[klausmate] window chrome apply ({kind}) failed: {exc}")


def _unapply(widget: Any) -> None:
    try:
        saved = getattr(widget, "_klausmate_saved_qss", None)
        if saved is not None:
            widget.setStyleSheet(saved)
    except Exception as exc:
        print(f"[klausmate] window chrome unapply failed: {exc}")


def refresh() -> None:
    """Walk every tracked widget: gate on -> (re)apply with the
    current palette; gate off -> restore the stashed original.

    Called from the Preferences live-preview path
    (apply_appearance_live / revert_appearance_preview), so the toggle
    and every accent/theme edit reach ALREADY-OPEN windows without a
    restart; and from the deferred theme-change walk below.
    """
    try:
        on = _gate_on()
        night = theme.night_mode()
        for widget, kind in list(_tracked().items()):
            if on:
                _apply_kind(widget, kind, night)
            else:
                _unapply(widget)
    except Exception as exc:
        print(f"[klausmate] window chrome refresh failed: {exc}")


def _on_add_cards_did_init(addcards: Any) -> None:
    try:
        _remember(addcards, "addcards")
        if _gate_on():
            _apply_kind(addcards, "addcards", theme.night_mode())
    except Exception as exc:
        print(f"[klausmate] add-cards chrome failed: {exc}")


def _on_browser_will_show(browser: Any) -> None:
    """Fires with all children built, geometry not yet restored. The
    window and the sidebar tree are styled SEPARATELY: the tree
    carries Anki's own widget-level sheet, which beats anything set on
    an ancestor, so only an instance sheet can reach it."""
    try:
        _remember(browser, "browser")
        tree = getattr(browser, "sidebar", None)
        if tree is not None:
            _remember(tree, "browser_tree")
        if _gate_on():
            night = theme.night_mode()
            _apply_kind(browser, "browser", night)
            if tree is not None:
                _apply_kind(tree, "browser_tree", night)
    except Exception as exc:
        print(f"[klausmate] browse chrome failed: {exc}")


def _on_stats_dialog_will_show(dialog: Any) -> None:
    try:
        _remember(dialog, "stats")
        if _gate_on():
            _apply_kind(dialog, "stats", theme.night_mode())
    except Exception as exc:
        print(f"[klausmate] stats chrome failed: {exc}")


def _on_editor_did_init(editor: Any) -> None:
    """The legacy editor's Qt tag bar (a group box + TagEdit, both
    carrying Anki widget-level sheets). The Svelte editor has no Qt
    tag bar — getattr misses and this is a clean no-op."""
    try:
        tags = getattr(editor, "tags", None)
        if tags is None:
            return
        # The group box wrapping the tag row is the styling root; the
        # TagEdit (a QLineEdit subclass) is reached by class from it.
        box = None
        try:
            box = tags.parentWidget()
        except Exception:
            box = None
        target = box if box is not None else tags
        _remember(target, "editor_tags")
        if _gate_on():
            _apply_kind(target, "editor_tags", theme.night_mode())
    except Exception as exc:
        print(f"[klausmate] editor tag chrome failed: {exc}")


def _on_webview_will_set_content(web_content: Any, context: Any) -> None:
    """The two stdHtml webviews this module owns: the editor page
    (Add Cards / Browse / Edit Current) and the reviewer's bottom
    bar. Everything else falls through untouched — the deck screen,
    both its bars and the top toolbar belong to top_bar.py."""
    try:
        if not _gate_on():
            return
        # Name-match like top_bar's bottom-bar branch: importing
        # aqt.reviewer here just for isinstance would be needless
        # coupling, and the context class name is stable API.
        if type(context).__name__ == "ReviewerBottomBar":
            web_content.head += (
                "<style>" + theme.reviewer_bar_css() + "</style>"
            )
            return
        from aqt.editor import Editor

        if isinstance(context, Editor):
            web_content.head += "<style>" + theme.editor_css() + "</style>"
    except Exception as exc:
        print(f"[klausmate] window chrome css failed: {exc}")


def _on_inject_style(webview: Any) -> None:
    """The Stats page (sveltekit — stdHtml hooks never fire for it).
    This hook fires post-load, pre-show: inject the variables sheet by
    eval, replace-not-stack. Identified by webview kind, with the URL
    basename as the cross-version fallback."""
    try:
        if not _gate_on():
            return
        is_stats = False
        try:
            from aqt.webview import AnkiWebViewKind

            is_stats = getattr(webview, "kind", None) == AnkiWebViewKind.DECK_STATS
        except Exception:
            pass
        if not is_stats:
            try:
                import os

                path = webview.page().url().path()
                is_stats = os.path.basename(path).lower().startswith("graphs")
            except Exception:
                return
        if not is_stats:
            return
        webview.eval(stats_inject_js(theme.stats_css()))
    except Exception as exc:
        print(f"[klausmate] stats css failed: {exc}")


def _on_theme_change() -> None:
    """Re-walk one tick AFTER the whole theme_did_change chain — the
    sidebar tree re-applies its own stock sheet from a handler
    registered at Browser construction, so only running after the
    entire chain (not merely after Anki's core handlers) beats it
    deterministically."""
    try:
        from aqt.qt import QTimer

        QTimer.singleShot(0, refresh)
    except Exception as exc:
        print(f"[klausmate] window chrome theme walk failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.add_cards_did_init.append(_on_add_cards_did_init)
        gui_hooks.browser_will_show.append(_on_browser_will_show)
        gui_hooks.stats_dialog_will_show.append(_on_stats_dialog_will_show)
        gui_hooks.editor_did_init.append(_on_editor_did_init)
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        # Newer-hook guard: present in 26.8.1; absence just means the
        # Stats page stays stock on an older Anki.
        if hasattr(gui_hooks, "webview_did_inject_style_into_page"):
            gui_hooks.webview_did_inject_style_into_page.append(
                _on_inject_style
            )
        gui_hooks.theme_did_change.append(_on_theme_change)
    except Exception as exc:
        print(f"[klausmate] window chrome setup failed: {exc}")
