# -*- coding: utf-8 -*-

# Highlight Search Results in the Browser Add-on for Anki
#
# Copyright (C) 2017-2020  Aristotelis P. <https://glutanimate.com/>
# Copyright (C) 2006-2020 Ankitects Pty Ltd and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.
#
# Adapted for KlausMate (K-113, 2026-08): ported search.py's
# SearchTokenizer/get_searchable_tokens (ANKI2124 dialect only -- the
# QueryLanguageVersion enum and the 2100-dialect branches from upstream
# are dropped), webview.py's findText-based highlighting, and browser.py's
# browser_did_change_row re-highlighting + View-menu checkable toggle into
# a single module. Upstream's select-next/select-all search shortcuts are
# out of scope and were not ported.

"""Browse search-term highlighting: while searching in Browse, highlight
the matched terms in the editor pane of the selected row.

Structure mirrors background.py: the tokenizer is pure/aqt-free at module
top so tests/test_browse_highlight.py can exercise it without stubbing
aqt; everything that touches a live Browser/webview lives below, with aqt
imported inside functions.
"""

from __future__ import annotations

from . import settings

import unicodedata
from typing import Any, List, Tuple


# --------------------------------------------------------------------------
# Pure tokenizer (aqt-free). Ported from search.py, ANKI2124 dialect only.
# --------------------------------------------------------------------------


class SearchTokenizer:
    """Splits an Anki Browse search string into tokens, then filters those
    down to the terms worth highlighting. ANKI2124 dialect only: backslash
    escapes are always supported, both ``"`` and ``'`` open quoted spans,
    and ``re:``/``nc:`` are ignored search tags alongside the common ones.
    """

    _operators: Tuple[str, ...] = ("or", "OR", "and", "AND", "+")
    _stripped_chars: str = '",*;'
    _ignored_values: Tuple[str, ...] = ("*", "_", "_*")
    _quotes: Tuple[str, ...] = ('"', "'")

    _ignored_tags: Tuple[str, ...] = (
        # default query language:
        "added:",
        "deck:",
        "note:",
        "tag:",
        "mid:",
        "nid:",
        "cid:",
        "card:",
        "is:",
        "flag:",
        "rated:",
        "dupe:",
        "prop:",
        # added by add-ons:
        "seen:",
        "rid:",
        # ANKI2124-only search tags:
        "re:",
        "nc:",
    )

    def tokenize(self, query: str) -> List[str]:
        """Tokenize search string.

        Based on finder code in Anki versions 2.1.23 and lower
        (anki.find.Finder._tokenize).
        """

        in_quote: Any = False
        in_escape: bool = False
        tokens: List[str] = []
        token: str = ""

        for c in query:
            # quoted text
            if c in self._quotes:
                if in_quote:
                    if c == in_quote and not in_escape:
                        in_quote = False
                    else:
                        token += c
                elif token:
                    # quotes are allowed to start directly after a :
                    if token[-1] == ":":
                        in_quote = c
                    else:
                        token += c
                else:
                    in_quote = c
            # escaped characters
            elif c == "\\":
                if in_escape:
                    # escaped "\"
                    token += c
                    in_escape = False
                else:
                    in_escape = True
            # separator (space and ideographic space)
            elif c in (" ", "　"):
                if in_quote:
                    token += c
                elif token:
                    # space marks token finished
                    tokens.append(token)
                    token = ""
            # nesting
            elif c in ("(", ")"):
                if in_quote:
                    token += c
                else:
                    if c == ")" and token:
                        tokens.append(token)
                        token = ""
                    tokens.append(c)
            # negation
            elif c == "-":
                if token:
                    token += c
                elif not tokens or tokens[-1] != "-":
                    tokens.append("-")
            # normal character
            else:
                in_escape = False
                token += c
        # if we finished in a token, add it
        if token:
            tokens.append(token)

        return tokens

    def get_searchable_tokens(self, tokens: List[str]) -> List[str]:
        """Filter raw tokens down to the values worth calling findText on:
        drops operator/negation markers and ignored search tags, then
        strips quote/wildcard artifacts off whatever value remains.
        """
        searchable_tokens: List[str] = []

        for token in tokens:
            if (
                token in self._operators
                or token.startswith("-")
                or token.startswith(self._ignored_tags)
            ):
                continue

            if ":" in token:
                value = token.split(":", 1)[1]
                if not value or value in self._ignored_values:
                    continue
            else:
                value = token

            value = value.strip(self._stripped_chars)

            searchable_tokens.append(value)

        return searchable_tokens


_search_tokenizer = SearchTokenizer()


# --------------------------------------------------------------------------
# aqt glue below this line -- imported lazily inside each function.
# --------------------------------------------------------------------------


def _config() -> dict:
    from . import settings

    return settings.read()


def highlight_default(cfg: dict | None = None) -> bool:
    """Resolve the ``browse_highlight_default`` config key. Each Browser's
    toggle is seeded from this on menu init."""
    if cfg is None:
        cfg = _config()
    if not isinstance(cfg, dict):
        return True
    return bool(cfg.get("browse_highlight_default", True))


def highlight_terms(webview: Any, terms: List[str]) -> None:
    """webview.findText per term (adapted from webview.py). Qt's findText
    doesn't support highlighting more than one term at once -- each call
    replaces the previous match state -- so, as upstream notes, only the
    last term's occurrences end up highlighted; harmless, matches upstream.
    """
    for term in terms:
        try:
            webview.findText(term)
        except Exception as exc:
            print(f"[klausmate] browse highlight findText failed: {exc}")


def clear_highlights(webview: Any) -> None:
    try:
        webview.findText("")
    except Exception as exc:
        print(f"[klausmate] browse highlight clear failed: {exc}")


def on_browser_did_change_row(
    browser: Any, current: Any = None, previous: Any = None
) -> None:
    """gui_hooks.browser_did_change_row: re-highlight the current row's
    editor pane with the active search's terms, if this browser's toggle
    is on (adapted from browser.py's on_browser_did_change_row)."""
    if not getattr(browser, "_klausmate_highlight_results", False):
        return

    try:
        search_text = browser.form.searchEdit.lineEdit().text()
    except Exception:
        return

    search_text = unicodedata.normalize("NFC", search_text)
    if not search_text:
        return

    tokens = _search_tokenizer.tokenize(search_text)
    searchable_tokens = _search_tokenizer.get_searchable_tokens(tokens)
    if not searchable_tokens:
        return

    try:
        highlight_terms(browser.editor.web, searchable_tokens)
    except Exception as exc:
        print(f"[klausmate] browse highlight row change failed: {exc}")


def toggle_search_highlights(browser: Any, checked: bool) -> None:
    """Toggle search highlights on or off for one Browser."""
    browser._klausmate_highlight_results = checked  # type: ignore[attr-defined]
    try:
        if not checked:
            clear_highlights(browser.editor.web)
        else:
            on_browser_did_change_row(browser)
    except Exception as exc:
        print(f"[klausmate] browse highlight toggle failed: {exc}")


def on_browser_menus_did_init(browser: Any) -> None:
    """gui_hooks.browser_menus_did_init: add a checkable View-menu action,
    seeded from the browse_highlight_default config key (adapted from
    browser.py's on_browser_menus_did_init). Upstream's extra hotkeys for
    select-next/select-all matching cards are not ported -- out of scope.
    """
    try:
        from aqt.qt import QMenu

        browser._klausmate_highlight_results = highlight_default()  # type: ignore[attr-defined]

        try:
            # Other add-ons also add a View menu; reuse it if one exists.
            menu = browser.menuView
        except AttributeError:
            browser.menuView = QMenu("&View")  # type: ignore[attr-defined]
            browser.menuBar().insertMenu(
                browser.mw.form.menuTools.menuAction(), browser.menuView
            )
            menu = browser.menuView

        menu.addSeparator()

        action = menu.addAction("Highlight Search Results")
        action.setCheckable(True)
        action.setChecked(browser._klausmate_highlight_results)
        action.toggled.connect(
            lambda checked: toggle_search_highlights(browser, checked)
        )
    except Exception as exc:
        print(f"[klausmate] browse highlight menu setup failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.browser_did_change_row.append(on_browser_did_change_row)
        gui_hooks.browser_menus_did_init.append(on_browser_menus_did_init)
    except Exception as exc:
        print(f"[klausmate] browse highlight setup failed: {exc}")
