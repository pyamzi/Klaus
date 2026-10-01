---
name: KlausMate
description: The Quiet Clinic — Apple-calm study chrome inside Anki, with one hand-drawn star.
colors:
  fog-white: "#F5F5F7"
  pure-surface: "#FFFFFF"
  chrome-light: "#FFFFFF"
  graphite-chrome: "#232323"
  night-window: "#191919"
  night-surface: "#2C2C2C"
  system-blue: "#0071D3"
  system-blue-bright: "#007AFF"
  night-accent: "#4FACFE"
  fog-border: "#E5E5EA"
  fog-mid: "#D1D1D6"
  fog-deep: "#AEAEB2"
  whisper-hover: "#F0F0F0"
  selection-tint: "#E4F2FF"
  ink: "#1D1D1F"
  ink-muted: "#6A6A6F"
  ink-faint: "#AAAAAA"
  night-ink: "#E0E0E0"
  system-red: "#FF3B30"
  system-green: "#28CD41"
  claude-terracotta: "#D97757"
typography:
  wordmark:
    fontFamily: "Excalifont, EB Garamond, Garamond, Georgia, serif"
    fontSize: "18px"
    fontWeight: 400
  page-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "24px"
    fontWeight: 600
  heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 700
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  subtitle:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 400
  micro:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "10px"
    fontWeight: 400
rounded:
  container: "12px"
  control: "8px"
  small: "6px"
  handle: "7px"
  bar: "4px"
  groove: "2px"
spacing:
  gap: "6px"
  row: "10px"
  card: "16px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.system-blue}"
    textColor: "#FFFFFF"
    rounded: "{rounded.control}"
    padding: "6px 14px"
  button-primary-hover:
    backgroundColor: "#0062C4"
  button-secondary:
    backgroundColor: "{colors.fog-border}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "6px 14px"
  chip-toolbar:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  nav-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "32px"
  card:
    backgroundColor: "{colors.pure-surface}"
    rounded: "{rounded.container}"
    padding: "16px"
  input:
    backgroundColor: "{colors.pure-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "4px 8px"
---

# Design System: KlausMate

## Overview

**Creative North Star: "The Quiet Clinic"**

KlausMate dresses Anki the way a well-run clinic dresses a hospital:
calm, sterile-clean Apple surfaces where nothing shouts, because the
patient — a medical student mid-exam-cycle — is already carrying enough
stimulation. The visual world is the Apple system palette held under
strict token discipline: fog-white fields, hairline borders, white
cards, and exactly one saturated voice (the user's chosen accent) used
sparingly. Into this sterile field walks one deliberately human
artifact: a hand-drawn, point-down star, traced from the owner's
sketch, always an open stroke in the accent colour, never boxed into an
icon square — the warm pulse in the clinic. Beside it, the "KlausMate"
wordmark in Excalifont, the same hand-drawn hand as the star, is the
single display voice in an otherwise system-sans world.

The system is implemented as one Python module (`klausmate/theme.py`)
of semantic tokens and per-surface QSS builders; the entire look of
every dialog, panel, toolbar, and webview is a function of
`palette(night)`. That is not an implementation detail, it is the
design philosophy: a user switching accent theme or the OS switching to
dark mode recolours every surface with zero per-surface code. The feel
of controls is **refined and restrained** — visible but understated,
never loud, answering interaction with soft tints rather than hard
state flips.

**Key Characteristics:**
- Apple system palette, light and dark, with identical semantic key
  sets — dark is a first-class citizen, not an afterthought filter.
- One accent family, user-selectable (13 presets + a custom colour),
  overriding only the blue-family tokens.
- Flat, hairline-divided surfaces; depth from tone and translucency,
  never drop shadows.
- Seamless window chrome: the top and bottom toolbars read as part of
  the OS window, matching its own colour — independent of whatever
  custom wallpaper is chosen for the deck screen.
- One hand-drawn mark and one hand-drawn (Excalifont) wordmark carrying
  the entire brand; everything else defers to the system.

## Colors

An Apple-literal palette: quiet neutrals doing the work, a single blue
family speaking, and dark mode as a parallel world with the same
vocabulary.

### Primary
- **System Blue** (#0071D3): the default accent — primary buttons,
  checked checkboxes, selected fills, progress. In dark mode the accent
  brightens to **Night Accent** (#4FACFE) because saturation reads
  differently on graphite; `blue_accent` encodes exactly this rule
  (base in light, bright in dark).
- **System Blue Bright** (#007AFF): focus rings, the toolbar star, and
  translucent selection tints (via `accent_rgba`).
- The whole blue family (`blue`, `blue_hover`, `blue_pressed`,
  `blue_border`, `blue_bright`, `blue_accent`) is what an accent theme
  replaces: SynapsePro's six presets (ocean, orchid, forest, deluge,
  horizon, dusty), seven community/one-off palettes (nord, solarized,
  catppuccin, gruvbox, everforest, dracula, and **Claude Terracotta**
  #D97757), plus a custom colour from which hover/pressed/bright are
  derived.

### Neutral
- **Fog White** (#F5F5F7): the window and page ground in light mode.
- **Pure Surface** (#FFFFFF): cards, inputs, trees — content sits on
  white above the fog.
- **Chrome Light** (#FFFFFF) / **Graphite Chrome** (#232323): the
  window-chrome token for the toolbars. Chrome must *separate* from the
  canvas behind it — brighter than canvas in light, a step darker than
  Anki's own #2C2C2C canvas in dark.
- **Fog Border** (#E5E5EA), **Fog Mid** (#D1D1D6), **Fog Deep**
  (#AEAEB2): hairlines/secondary fills, input borders/hovers, pressed
  states — three greys, three jobs.
- **Whisper Hover** (#F0F0F0): the barely-there Qt hover ground.
- **Ink** (#1D1D1F), **Ink Muted** (#6A6A6F), **Ink Faint** (#AAAAAA):
  body text, secondary labels, placeholders/disabled — every label is
  one of these three. Ink Muted was darkened from an original #86868B
  (3.3:1 on Fog White — failed WCAG AA for the 11px captions it backs
  everywhere) to 4.9:1+ in both light contexts, same cool lean.
- **Night Window** (#191919), **Night Surface** (#2C2C2C), **Night
  Ink** (#E0E0E0): the dark-mode counterparts, same keys, same jobs.

### Tertiary
- **System Red** (#FF3B30 family): destructive only — the DangerButton
  treatment (soft red ground #FFEBEB with red text, filling solid on
  hover).
- **System Green** (#28CD41 family): success states only.

### Named Rules
**The One Module Rule.** No UI file hardcodes a colour. Every surface
builds its stylesheet from `theme.palette(night)`; an accent or theme
change must reach every surface with zero per-surface code.

**The Blue-Family-Only Rule.** Accent themes override the six
blue-family tokens and nothing else. Backgrounds, text, and greys never
fork per theme — that is why every accent works in both light and dark.

**The Chrome Separation Rule.** Chrome is never the canvas colour:
brighter than canvas in light, darker in dark. A bar that matches the
page dissolves into it.

## Typography

**Display Font:** Excalifont (bundled as `klausmate/web/fonts/
Excalifont-Regular.ttf`, registered by `theme.register_wordmark_font`;
falls back to Garamond → Georgia → serif) — the wordmark only.
**Body Font:** the Apple system stack (-apple-system, BlinkMacSystemFont,
"Segoe UI", Roboto, Helvetica, Arial).

**Character:** a single hand-drawn signature over a fully system-native
text world — a handwritten name on an otherwise standardized door, in
the same hand as the star.

### Hierarchy
- **Wordmark** (400, 18px): "KlausMate" in Excalifont, sidebar and
  identity moments only. Excalifont has one weight; the hand is the point.
- **Page Title** (600, 24px): one per settings page ("General",
  "Appearance"…).
- **Heading** (700, 14px): section/card headings (SubHeaderLabel,
  InstallHeading).
- **Body** (400–600, 13px): the default; controls and setting names
  (600 for names and chips).
- **Subtitle** (400, 12px): page subtitles, muted.
- **Caption** (400, 11px): hints, statuses, descriptions — always in
  Ink Muted.
- **Micro** (400, 10px): progress text, tab-close glyphs.

### Named Rules
**The Scale-Or-Drift Rule.** Only the sanctioned sizes (10 / 11 / 12 /
13 / 14 / 18 / 24) and radii exist; `tests/test_theme.py` scans every
builder's emitted CSS and fails the suite on any other value. An
off-scale value is drift, not a style choice.

**The One Display Font Rule.** Excalifont appears exactly once — the
wordmark. No headings, no body text, no second display moment. (Until
2026-10-01 this was the One Serif Rule, with a Garamond wordmark.)

## Layout

Dialogs sit on Fog White with white rounded cards; content pages use a
24px page margin, a large title + muted subtitle, then one rounded
group of settings rows. A settings row is: bold name over a muted
wordwrapped description on the left, the control pinned right, 10px
vertical padding, 1px hairline separators between rows — and rows
disable or hide as *whole units* (name, description, control,
separator together). The Preferences shell is a fixed 192px sidebar
(wordmark, version, search field, nav list) beside a stacked page area;
the sidebar runs edge-to-edge into the window and down to a full-width
hairline above the Cancel/Save bar. Recurring rhythm: 6px between
sibling pills/swatches, 10px row padding, 16px card padding, 24px page
margins.

**The Hard Geometry Rule.** Sidebar and row geometry comes from view
properties (fixed heights, `setSizeHint`, layout spacing) — never from
QSS-derived size hints, whose polish timing made first paints differ
from restyles. Navigation lists are ONE QListWidget with delegate-drawn
rows, never per-item buttons.

## Elevation & Depth

Flat by conviction. There are **no drop shadows anywhere** — the only
`box-shadow` declarations in the system are `none !important`
flatteners killing Anki's own toolbar card. Depth is conveyed three
ways: tonal layering (white surfaces on fog ground), hairline borders
(Fog Border at 1px), and translucency. The deck panels are the
showpiece: over a custom photo they take a real `backdrop-filter`
blur — panel and wallpaper share one document, so the compositor does
the actual work, no painted copy required. Over a flat colour the
blur is a no-op by definition, so the panel simply reads as that
colour; the seam disappears by construction, not by measurement. The
top and bottom toolbars are flat chrome always, deliberately
independent of the wallpaper (2026-08-30) — they used to fake the
same frost with a painted copy, since their webview can't composite
with the window behind it, and that mechanism was removed rather than
kept as a second, weaker version of what the panels now do for real.
Two sanctioned exceptions,
both inside the PDF viewer's webview canvas: **paper** (rendered PDF
pages carry a soft 1-4px page shadow — the paper metaphor, as Preview
does) and **floating overlays** (the viewer's custom context menu
floats on a soft 16px shadow, as native menus do). Plus a soft
text-shadow on toolbar text over photos, for legibility only. Nothing
else casts.

**The Veil Rule.** On the chrome bars, interactive state feedback is a
translucent veil — rgba black over light chrome (5% hover / 9% press),
rgba white over dark (10% / 16%) — never an opaque fill. A veil tints
whatever is actually behind the control, so highlights work over any
background by construction. (Qt widget hovers inside dialogs use the
opaque Whisper Hover ground instead; the veil is chrome-bar language.)

## Shapes

Soft-rectangle geometry on a strict scale: 12px for containers (cards,
group frames, trees), 8px for everything you click or type in (buttons,
inputs, chips, nav rows), 6px for small controls (swatches, list items,
checkbox indicators), 7px only as the slider handle's circle
(height/2), 4px and 2px for slim fills (progress, grooves), and 0 only
as a deliberate flattener. Hairlines are always 1px in Fog Border. The
star mark is the one irregular shape in the system — a hand-traced,
self-crossing pentagram stroke with round caps and joins, its
imperfection deliberately preserved.

## Components

### Buttons
- **Shape:** softly rounded (8px), 6px 14px padding, weight 600.
- **Primary:** System Blue fill and white text for the default action or an explicit `PrimaryButton`. Utility actions use a quiet neutral fill.
- **SecondaryButton (opt-out):** Fog Border fill, Ink text; hover
  deepens through Fog Mid to Fog Deep pressed.
- **DangerButton:** soft red ground (#FFEBEB) with red text; fills
  solid System Red with white text on hover — destructive intent is
  quiet until engaged.
- **Disabled:** every `:disabled` rule repeats the id selector it must
  beat (`QPushButton#SecondaryButton:disabled`) — an id outranks a
  pseudo-state, and an inert control MUST look inert.
- **Library window:** neutral controls with explicit `PrimaryButton` emphasis, consistent with dialogs.

### Chips (toolbar / bottom bar)
- **Style:** transparent at rest, Ink Muted 13px/600 text, 8px radius,
  5px 12px padding; hover = the veil + text lifting to full Ink; press
  = the stronger veil.
- **The Byte-Identical Chip Rule.** Top-bar links and bottom-bar
  buttons emit the *same shared declaration blocks*
  (`_chip_base_rules` etc.), pinned byte-identical by tests. The two
  bars cannot drift apart.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** Pure Surface on Fog White ground.
- **Border:** 1px Fog Border; no shadow (see Elevation).
- **Internal Padding:** 16px horizontal.

### Inputs / Fields
- **Style:** Pure Surface fill, 1px Fog Mid border, 8px radius,
  4px 8px padding.
- **Focus:** border flips to System Blue Bright — the focus ring is a
  border, not a glow.
- **Disabled:** Fog ground, faint text, Fog Border border.

### Navigation (Preferences sidebar)
- ONE QListWidget (`SettingsNav`): transparent, borderless, 32px rows
  on hard size hints, 3px view spacing, pointing-hand cursor.
- **Selected:** a soft accent tint (16%-alpha `accent_rgba`) with the
  accent as text colour — a muted highlight, never a solid block.
- **Hover:** Whisper Hover. **No-hit (search):** faint text +
  unclickable, still visible.

### Settings Rows
- Bold 13px name over muted 11px description left, control right,
  hairline separators; the first visible row in a group carries no
  hairline. Rows carry search haystacks; structural hiding (a provider
  hiding its key row) always beats a search hit.

### Switches (signature control)
- MD3's track-and-thumb switch, not a checkbox — the semantically
  correct control for a settings row's on/off, and the one place MD3
  language was deliberately adopted into an otherwise Apple-system
  world. Track: Fog Border off, the active accent on, crossfading
  rather than snapping; thumb: Fog Deep off (a small MD3-spec dot),
  white on, growing as it slides (MD3's signature switch motion,
  200ms). Recolours under all 13 accent presets like everything else —
  the switch is drawn from `theme.palette()`, never a fixed hex.
  Clicking anywhere on the control toggles it; keyboard focus draws
  its own accent ring, since a self-painted widget can't inherit the
  shared `QPushButton:focus` rule.

### Accent Swatches
- Bare 22px colour squares, 6px radius — the swatch IS the label
  (names live in tooltips); selection is a white inner ring. The last
  square is the user's own colour and opens the picker; cancelling the
  picker still selects custom with its held colour.

### PDF Reader
- **One reader, identical everywhere.** Every place a PDF opens shows
  the same surface: pdf.js pages in a webview, with the tab strip
  (`[＋] [tabs] … [page n/m]`) above them. Each host keeps its own tab
  set; nothing about the reader changes with the window it sits in,
  because the panel styles itself (`pdf_panel_qss`) and the page takes
  its colours from `theme.css_vars`.
- **Paper on ground.** Pages are white paper with a 4px radius and
  the soft page shadow (see Elevation) on the panel's ground; the
  thumbnail strip repeats them in miniature.
- **Tools.** The find bar is a flat strip above the pages (hairline
  below it). The annotation pill (Highlight, Add Text, the ink row,
  −/%/+/fit) and the context menu float over the page on soft shadows
  — with paper, the only things that cast one. Inks are page colours,
  not chrome: they bake into the PDF.
- The native renderer was deleted in PDF reader 5/5; there is no
  second renderer to match.

### The Star (signature)
- The hand-drawn point-down pentagram from `top_bar._STAR_PATH` — the
  single source of truth for both the toolbar SVG and any Qt-side
  pixmap. Always an open stroke in the accent (`--klaus-accent` /
  `blue_accent`), round caps and joins, **never** filled, boxed, or
  squared. Clicking it opens KlausMate Preferences.

## Do's and Don'ts

### Do:
- **Do** use the MD3 switch (`md3_switch.Md3Switch`) for any settings
  row on/off — never a bare `QCheckBox` for that job again.
- **Do** build every stylesheet from `theme.palette(night)` and the
  shared builders; add new ids to `dialog_qss` rather than styling
  widgets inline.
- **Do** ship BOTH palettes in one sheet for webview surfaces, keyed on
  Anki's night-mode classes — Anki toggles classes with JS and never
  re-runs content hooks, so a baked single-palette sheet freezes on the
  draw-time theme.
- **Do** disable and hide settings rows as whole units — a live-looking
  label over a dead control reads as broken, not inactive.
- **Do** keep the accent reachable everywhere: any new surface must
  recolour correctly under all 13 presets + custom, in both light and
  dark, with no code changes.
- **Do** repeat the id selector in every `:disabled` rule that must
  beat an id-styled base.

### Don't:
- **Don't** hardcode hex, font families, radii, or font sizes in UI
  files — the test suite scans for off-scale values and will fail.
- **Don't** use drop shadows; depth is tone, hairline, and frost.
- **Don't** use opaque fills for chrome-bar hover states — veils only.
- **Don't** box, fill, or "iconify" the star, and don't introduce a
  second display-font moment beyond the Excalifont wordmark.
- **Don't** build sidebar navigation from per-item buttons, or derive
  control geometry from QSS size hints — hard view geometry only.
- **Don't** fork backgrounds or text per accent theme, and don't let
  any accent state read as a loud solid block where a translucent tint
  is the established voice.


## Apple design application

See [the cross-surface application notes](docs/reference/apple-design.md) for action hierarchy, immediate feedback, keyboard focus, material fallbacks, and the native/web boundary.
