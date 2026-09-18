"""Drift gate: the CSS baked into klausplus/templates.py vs. the tokens it
claims to come from. Mirrors KlausBook-Context's tests/design_tokens_test.mjs
applied to this repo's third consumer of docs/reference/design-tokens.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from klausplus import templates

_ROOT = Path(__file__).resolve().parents[2]  # service/tests -> repo root
_TOKENS = json.loads((_ROOT / "docs/reference/design-tokens.json").read_text())

_KEBAB_TO_CAMEL = re.compile(r"-([a-z])")


def _camel(kebab: str) -> str:
    return _KEBAB_TO_CAMEL.sub(lambda m: m.group(1).upper(), kebab)


def _block(css: str, selector: str) -> dict:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no {selector!r} block found in _PAGE's <style>"
    return {
        _camel(k): v.strip()
        for k, v in re.findall(r"--([a-z-]+):\s*([^;]+);", m.group(1))
    }


def test_root_block_matches_dark_tokens():
    css = templates._PAGE
    root = _block(css, ":root")
    want = _TOKENS["colors"]["dark"]
    # accentTint/danger exist in the token file for other consumers but this
    # page frame never uses them — check only what it declares.
    for key, value in root.items():
        assert want[key] == value, f"--{key}: expected {want[key]}, got {value}"


def test_light_media_query_matches_light_tokens():
    css = templates._PAGE
    light = _block(css, ":root")  # placeholder; real block is inside the media query below
    m = re.search(r"@media \(prefers-color-scheme: light\)\s*\{(.*)\}\s*body", css, re.DOTALL)
    assert m, "no light-scheme media query found"
    light = _block(m.group(1), ":root")
    want = _TOKENS["colors"]["light"]
    for key, value in light.items():
        assert want[key] == value, f"--{key}: expected {want[key]}, got {value}"


def test_logo_is_the_canonical_brand_svg():
    logo_svg = (_ROOT / "docs/reference/brand/klaus-logo.svg").read_text()
    # The frame inlines the same path data with fill swapped to currentColor
    # (so it recolors with the page, unlike the flat-black master file) —
    # check every path's "d" attribute survived the copy untouched.
    paths = re.findall(r'<path d="([^"]+)"', logo_svg)
    assert len(paths) == 5, "expected 5 path elements in the master logo"
    for d in paths:
        assert d in templates._LOGO_SVG, "a logo path drifted from the brand master"
    assert 'fill="currentColor"' in templates._LOGO_SVG
    assert "#171717" not in templates._LOGO_SVG


def test_no_stray_hardcoded_colors_outside_the_token_block():
    css = templates._PAGE
    # Strip the :root/media-query block (the one place hex values are meant
    # to live) and confirm nothing outside it hardcodes a color.
    stripped = re.sub(r":root\s*\{[^}]*\}", "", css)
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", stripped), "a hardcoded hex color leaked outside the token block"
