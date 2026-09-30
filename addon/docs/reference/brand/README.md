# Klaus brand assets

`klaus-logo.svg` — the canonical logo (pyamzi's "impossible star" mark,
2026-09-18). This is the master; everywhere else it appears is derived
from it, not a second original:

- **App icon** (`KlausBook-Code/resources/darwin/code.icns`, and its live
  copy at `.build/electron/Klausbook.app/Contents/Resources/Klausbook.icns`):
  rasterized via `rsvg-convert` at 16/32/64/128/256/512/1024px into an
  iconset, packed with `iconutil -c icns`. Re-run that if the source SVG
  changes — the .icns files are generated, not hand-edited.
- **klaus-pdf activity-bar icon** (`extensions/klaus-pdf/media/klaus.svg`):
  same path data, with the hardcoded `fill="#171717"` changed to
  `fill="currentColor"` so it recolors with VS Code's active/inactive
  theme states like every other native icon — a flat black fill would sit
  invisible-to-barely-visible in a dark activity bar otherwise.
- **`~/Applications/Klausbook.app`** (the double-click launcher,
  `KlausBook-Code/scripts/open-klausbook.sh` wrapped via `osacompile`):
  uses the same rasterized .icns as the app icon above.
