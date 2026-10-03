# Klaus brand assets

`klaus-logo.svg` — the canonical logo: Pouya's hand-drawn k (2026-10-01,
replacing the 2026-09-18 "impossible star"). The file is a 1254×1254 box
holding a `#2393f4` square and ONE white `fill-rule="evenodd"` path made
of M/L/Z polygon subpaths (the k's body and the dash at its left). It is
Pouya's file verbatim; never edit it by hand. Everywhere else the mark
appears is derived from it, not a second original:

- **Inside Klaus (the Anki add-on)**: just the k, no square, filled in
  the accent colour. `klaus_note/top_bar.py` holds the white path verbatim
  as `_LOGO_PATH` (pinned equal to this file by `tests/test_top_bar.py`)
  in `LOGO_VIEWBOX`, the 1254 box cropped to the k plus about 4% margin.
  `top_bar.logo_svg(fill)` serves both the toolbar (filled
  `var(--klaus-accent, currentColor)`) and the Preferences sidebar
  pixmap (`manage_models._logo_pixmap`, the `blue_accent` hex).
- **App icon** (`klaus-note/app/src-tauri/icons/`): the full
  tile, a white k on `#2393f4`, as a macOS-style rounded square (body
  824 of 1024 on the Apple icon grid, about 22% corner radius).
  `icon.svg` is that master; the PNG, `.icns` and `.ico` files are
  generated from a 1024 px render of it with `npx tauri icon`, not
  hand-edited. Re-run that if this file changes.
- **klaus.ink** (the website's favicon and lockups): the k alone, no
  tile, in `#2393f4` on a transparent ground (decided 2026-10-01).
