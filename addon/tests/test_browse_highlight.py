"""Headless tests for Browse search-term highlighting (K-113).

Only the aqt-free SearchTokenizer is exercised here (module imports
aqt-free at top, per the module's own docstring) -- highlight_terms/
clear_highlights/the hook callbacks all touch a live Browser/webview and
are exercised via tests/test_imports.py's import-smoke pass instead.
"""
import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
bh = importlib.import_module("klausmate.browse_highlight")

tok = bh.SearchTokenizer()

section("tokenize: ported from upstream's _assert_common_tokenizations")
check("plain words split on whitespace",
      tok.tokenize("hello world") == ["hello", "world"])
check("repeated spaces collapse",
      tok.tokenize("hello  world") == ["hello", "world"])
check("a lone '-' negation marker becomes its own token",
      tok.tokenize("one -two") == ["one", "-", "two"])
check("repeated '-' collapses to one marker",
      tok.tokenize("one --two") == ["one", "-", "two"])
check("a spaced-out '-' is the same marker",
      tok.tokenize("one - two") == ["one", "-", "two"])
check("an operator before a negation still splits the marker",
      tok.tokenize("one or -two") == ["one", "or", "-", "two"])
check("a quoted phrase survives tokenizing as one token",
      tok.tokenize('"hello world"') == ["hello world"])
check("nesting parens are their own tokens",
      tok.tokenize("one (two or ( three or four))") ==
      ["one", "(", "two", "or", "(", "three", "or", "four", ")", ")"])
check("an apostrophe embedded mid-word is not a quote delimiter",
      tok.tokenize("embedded'string") == ["embedded'string"])

section("tokenize: ANKI2124-only quoting (single quotes also open spans)")
check("a single-quoted phrase tokenizes like a double-quoted one",
      tok.tokenize("'hello world'") == ["hello world"])
check("a quote is only a delimiter right after a ':'",
      tok.tokenize("front:'card one'") == ["front:card one"])

section("get_searchable_tokens: ignored search tags (deck:/tag:/re:/nc:)")
check("deck: is dropped",
      tok.get_searchable_tokens(tok.tokenize("deck:Spanish hello")) == ["hello"])
check("tag: is dropped",
      tok.get_searchable_tokens(tok.tokenize("tag:leech hello")) == ["hello"])
check("re: (ANKI2124-only tag) is dropped",
      tok.get_searchable_tokens(tok.tokenize("re:^foo hello")) == ["hello"])
check("nc: (ANKI2124-only tag) is dropped",
      tok.get_searchable_tokens(tok.tokenize("nc:foo hello")) == ["hello"])
check("a common tag not specific to 2124 is still dropped",
      tok.get_searchable_tokens(tok.tokenize("is:due hello")) == ["hello"])

section("get_searchable_tokens: operators and negation markers dropped")
check("AND/OR operators (either case) are filtered out",
      tok.get_searchable_tokens(tok.tokenize("one AND two or three")) ==
      ["one", "two", "three"])
check("the '+' operator is filtered out",
      tok.get_searchable_tokens(tok.tokenize("one + two")) == ["one", "two"])
check("the '-' negation marker token itself is dropped",
      "-" not in tok.get_searchable_tokens(tok.tokenize("one -two")))
# NOTE: this pins the upstream algorithm's actual behaviour, not an
# idealized one -- tokenize() always splits "-word" into a separate "-"
# marker token plus a plain "word" token (never a single "-word" token),
# so get_searchable_tokens' `token.startswith("-")` check only ever
# matches the marker itself. The negated word survives as if positive.
check("the negated word survives search-token extraction (upstream quirk, not a bug we're fixing)",
      tok.get_searchable_tokens(tok.tokenize("one -two")) == ["one", "two"])

section("get_searchable_tokens: quote/wildcard stripping on the extracted value")
check("a lone wildcard value is dropped entirely",
      tok.get_searchable_tokens(["front:*"]) == [])
check("a trailing wildcard is stripped off a real value",
      tok.get_searchable_tokens(["front:hell*"]) == ["hell"])
check("stray double-quote/comma/semicolon/asterisk chars are stripped",
      tok.get_searchable_tokens(['"hello*"']) == ["hello"])
check("an empty tag value is dropped",
      tok.get_searchable_tokens(["deck:"]) == [])

raise SystemExit(report())
