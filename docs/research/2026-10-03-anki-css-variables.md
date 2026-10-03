# Which Anki CSS variables can `anki-host.css` set?

Wayfinder research ticket [#38](https://github.com/pyamzi/klaus-note/issues/38), child of map #37. Written 2026-10-03.

## Verdict

**Yes for colour, radius and body font; no for the rest.** Setting Anki's custom properties from `static/anki-host.css` re-colours the editor, deck options, import and graphs chrome (surfaces, text, borders, input and button fills, radii, scrollbar-adjacent surfaces) in both light and dark. It does not give them the shadcn look: buttons keep Anki's bevel, weight and padding; Bootstrap-class buttons, alerts and checkboxes stay Bootstrap blue; graph data colours stay d3's. A tokens-only restyle is worth doing as "Klaus colours and radius", and the editor/deck-options/import pages can stay in scope on that footing; graphs get the chrome only.

**One trap the bridge's current `anki-host.css` falls into: it loses the cascade.** The bridge injects the stylesheet as the first child of `<head>`, before every Anki stylesheet, so a plain `:root { --canvas: … }` ties Anki's own `:root` on specificity and loses on order. Verified in headless Chromium against the built CSS (below). Use `html:root:root` (specificity 0,2,1), which beats both `:root` (0,1,0) and `:root.night-mode` (0,2,0) and so covers light and dark in one rule.

## Sources

Primary, read from the pinned submodule `vendor/anki` at commit `29bb700b951e3f0c0cb69b77c0180fc1fe33e6ba`. Its `.version` file reads **26.09.3**, not 25.09 as the ticket says; every statement below is about 26.09.3. The worktree's `vendor/anki` is an uninitialised (empty) submodule, so everything was read from the main checkout `klaus-note/app/vendor/anki`, including its built `out/sveltekit` and `out/klaus`.

- `ts/lib/sass/_vars.scss`, `_root-vars.scss`, `_functions.scss`, `_color-palette.scss`: the variable definitions.
- `ts/lib/sass/base.scss`, `core.scss`, `buttons.scss`, `_button-mixins.scss`, `bootstrap-dark.scss`: how they are consumed.
- `ts/routes/+layout.ts`, `ts/lib/tslib/nightmode.ts`, `ts/lib/sveltelib/theme.ts`: light/dark switching.
- `out/sveltekit/index.html` and `out/sveltekit/_app/immutable/assets/0.H7G7hbx1.css`: the generated page shell and layout stylesheet that every Anki page loads.
- Klaus: `crates/bridge/src/lib.rs` (`anki_page`), `static/anki-host.css`, `static/anki-host.js`, `src/app.css`, `src/routes/+page.svelte`, `src/routes/DeckRows.svelte`, `src-tauri/src/main.rs`.

## What Anki defines

`_vars.scss` generates 51 colour properties and 8 other properties, emitted once on `:root` for light and again on `:root.night-mode` for dark (`_root-vars.scss`; confirmed in the built `0.H7G7hbx1.css`). Generated names, grouped:

| Group | Properties |
| --- | --- |
| Text | `--fg` `--fg-subtle` `--fg-disabled` `--fg-faint` `--fg-link` |
| Surfaces | `--canvas` `--canvas-elevated` `--canvas-inset` `--canvas-overlay` `--canvas-code` `--canvas-glass` |
| Borders | `--border` `--border-subtle` `--border-strong` `--border-focus` |
| Buttons | `--button-bg` `--button-gradient-start` `--button-gradient-end` `--button-hover-border` `--button-disabled` `--button-primary-bg` `--button-primary-gradient-start` `--button-primary-gradient-end` `--button-primary-disabled` |
| Scrollbar | `--scrollbar-bg` `--scrollbar-bg-hover` `--scrollbar-bg-active` |
| Shadow | `--shadow` `--shadow-inset` `--shadow-subtle` `--shadow-focus` |
| Accents | `--accent-card` `--accent-note` `--accent-danger` |
| Flags | `--flag-1` … `--flag-7` |
| Card states | `--state-new` `--state-learn` `--state-review` `--state-buried` `--state-suspended` `--state-marked` |
| Selection | `--highlight-bg` `--highlight-fg` `--selected-bg` `--selected-fg` |
| Non-colour | `--font-size` (15px, drives `html { font-size }`), `--border-radius` (5px), `--border-radius-medium` (12px), `--border-radius-large` (15px, "fancy" pill buttons), `--transition` `--transition-medium` `--transition-slow`, `--blur` |

There is **no font-family variable**.

Bootstrap 5.3.8 is bundled into the same layout stylesheet and brings its own `--bs-*` properties. The few Anki pages read these directly: `--bs-body-bg`, `--bs-body-color` (see below), `--bs-font-sans-serif` (editor), `--bs-body-bg` again in deck options.

## What each page reads

Counts are references in `ts/routes/<page>` and `ts/lib` sources (`var(--x)` or Sass `color()`/`prop()`); they say what is read, not how prominent it is.

- **Editor** (`routes/editor`, plus shared `lib/components`, `lib/tag-editor`, `lib/editable`): `--border` (7), `--border-radius`, `--fg`, `--fg-subtle`, `--canvas`, `--canvas-elevated`, `--canvas-code`, `--border-strong`, `--border-focus`, `--accent-danger` (the field-validation outline), `--button-primary-bg` (image-occlusion button), `--transition`, and `--bs-font-sans-serif` (`editor-base.scss`: `html, body { font-family: var(--bs-font-sans-serif) }`).
- **Deck options**: `--border-radius`, `--fg`, `--border`, `--fg-subtle`, `--border-focus`, `--canvas-code`, `--border-subtle`, `--canvas-inset`, `--transition`, `--bs-body-bg`, plus the shared components. It also uses Bootstrap component classes (below).
- **Graphs**: `--fg`, `--border`, `--fg-subtle`, `--canvas-overlay` (tooltip), `--canvas`, `--canvas-elevated`, `--fg-link` (card-count links), `--transition`/`--transition-slow`. The data marks do **not** come from variables (see "What cannot be reached").
- **Import** (`import-csv`, `import-anki-package`, `import-page`): `--border`, `--border-subtle`, `--canvas`, plus shared components and the primary `IconButton` (`--button-primary-*`).
- **Shared components** (buttons, selects, switches, modals, tag editor, scroll areas): `--border-subtle` (9), `--fg` (8), `--fg-subtle` (7), `--border` (6), `--canvas-elevated`, `--canvas-inset`, `--canvas`, `--border-focus`, `--shadow`, `--border-radius`, `--border-radius-medium`, `--fg-disabled`, `--fg-faint`, `--highlight-bg/fg`.
- **Buttons** (`lib/sass/buttons.scss`, `_button-mixins.scss`): `--button-bg`, `--button-gradient-start/end`, `--button-primary-bg`, `--button-primary-gradient-start/end`, `--shadow`, `--shadow-focus`, `--border`, `--border-subtle`, `--border-radius`, `--border-radius-large` (only under the `.fancy` class), `--fg-disabled`.
- **Card info** reads `--state-new`, `--state-review`, `--state-learn`. `--accent-card`, `--accent-note`, `--flag-*`, `--state-buried/suspended/marked`, `--button-hover-border`, `--button-disabled` and `--canvas-glass` are defined but not read by the pages in scope.

## How light/dark is switched

- By a **class on `<html>`**: `night-mode` (not on `<body>`, and not a media query). `_root-vars.scss` redeclares every colour under `:root.night-mode`.
- Anki sets it in `routes/+layout.ts` → `checkNightMode()`: if `location.hash == "#night"` it sets `documentElement.className = "night-mode"` and `data-bs-theme="dark"`. Bootstrap's own dark values hang off `[data-bs-theme=dark]`. The `pageTheme` store (`sveltelib/theme.ts`) watches the `class` attribute, and graphs read it for their calendar colours.
- Klaus adds the class itself too (`static/anki-host.js`, same `#night` check), and its own pages append `#night` when `matchMedia("(prefers-color-scheme: dark)")` matches at navigation time (`src/routes/+page.svelte`, `DeckRows.svelte`, `browse/+page.svelte`). **Gap:** the import page is opened from `src-tauri/src/main.rs` (`navigate(app, "import-anki-package/…")`) with no `#night`, so it is always light today. Klaus's own look follows the media query (`src/app.css`), so the two mechanisms agree except there.

## Is `anki-host.css` late enough? No, and it must not rely on order

`crates/bridge/src/lib.rs` `anki_page` does `html.replacen("<head>", "<head><link rel=\"stylesheet\" href=\"/anki-host.css\">…", 1)`. The sheet is therefore the **first** child of `<head>`; Anki's layout stylesheet is a later `<link>` in `index.html`, and route stylesheets are added after that. Equal-specificity rules in `anki-host.css` always lose.

Headless Chromium (playwright-core from `vendor/anki/node_modules`) loaded the real built `0.H7G7hbx1.css` after a host sheet, and read the computed values:

| Host sheet | Light, `--canvas` set to `rgb(1,2,3)` | Night, `--canvas` set to `rgb(7,8,9)` |
| --- | --- | --- |
| `:root { … }` / `:root.night-mode { … }` | `#f5f5f5` (Anki wins) | `#2c2c2c` (Anki wins) |
| `html:root { … }` / `html:root.night-mode { … }` | overridden | overridden |
| same with `!important` | overridden | overridden |

Two further gotchas the test showed or the source implies:

1. **`html:root` alone is not enough for the other mode.** `html:root` (0,1,1) beats `:root` but loses to Anki's `:root.night-mode` (0,2,0), so a light-only override leaves dark untouched. `html:root:root` (0,2,1) beats both. `!important` also works but then needs separate light and dark rules; prefer the specificity bump.
2. **Body background and colour do not follow `--canvas`/`--fg`.** `base.scss` imports Bootstrap reboot with `$body-bg`/`$body-color` as literal palette values, so the built CSS has `body { background-color: var(--bs-body-bg); color: var(--bs-body-color) }` with `--bs-body-bg: #f5f5f5 / #2c2c2c` and `--bs-body-color: #020202 / #fcfcfc` hard-coded. `core.scss`'s `body { background: var(--canvas) }` is not in the page's stylesheet. The existing `body { background-color: var(--canvas) }` in `anki-host.css` has the same specificity as Bootstrap's rule and comes earlier, so by the cascade it is dead today; it only looks right because `--canvas` and `--bs-body-bg` have the same default values. Set `--bs-body-bg` and `--bs-body-color` as well.
3. **Name clash.** Klaus's `--border` and Anki's `--border` are the same name, so `--border: var(--border)` is a self-reference and silently invalid (confirmed: the computed border stayed Anki's). `anki-host.css` has to hold Klaus's values under another name, e.g. a `--k-` prefix.

## Mapping, Anki variable → Klaus token

Klaus tokens are from `src/app.css` (preset `b2GUtMueeu`, zinc). Radius: Klaus `--radius` is `0.625rem`.

| Anki variable | Klaus token | Note |
| --- | --- | --- |
| `--canvas` | `--background` | window |
| `--canvas-elevated` | `--card` | containers |
| `--canvas-inset` | `--background` | inputs inside containers |
| `--canvas-overlay` | `--popover` | menus, graph tooltip |
| `--canvas-code` | `--muted` | code editors |
| `--canvas-glass` | `color-mix(in srgb, var(--card) 40%, transparent)` | unread in scope; leave |
| `--fg` | `--foreground` | |
| `--fg-subtle` | `--muted-foreground` | placeholders, idle icons |
| `--fg-disabled`, `--fg-faint` | `color-mix(in srgb, var(--muted-foreground) 60%, var(--background))` | no Klaus token; derived |
| `--fg-link` | `--primary` | Klaus has no link colour; links lose their blue (Anki draws no underline) |
| `--border`, `--border-subtle` | `--border` | Klaus dark border is `rgba(255,255,255,.1)` (translucent) |
| `--border-strong` | `--input` | |
| `--border-focus` | `--ring` | |
| `--button-bg` | `--secondary` | |
| `--button-gradient-start` / `-end` | `--secondary` | both the same value flattens the hover gradient |
| `--button-primary-bg`, `--button-primary-gradient-start` / `-end` | `--primary` | see the dark-mode caveat below |
| `--button-primary-disabled`, `--button-disabled` | `color-mix(in srgb, var(--primary) 40%, transparent)` / `--muted` | |
| `--shadow`, `--shadow-subtle` | `--border` | |
| `--shadow-inset` | `--muted-foreground` | |
| `--shadow-focus` | `--ring` | |
| `--accent-danger` | `--destructive` | field-validation outline |
| `--state-new` / `--state-learn` / `--state-review` | `--count-new` / `--count-learn` / `--count-review` | Klaus already carries Anki's meanings |
| `--highlight-bg`, `--selected-bg` | `color-mix(in srgb, var(--primary) 20%, transparent)` | |
| `--highlight-fg`, `--selected-fg` | `--foreground` | |
| `--scrollbar-bg*` | `--border` (idle), `--muted-foreground` (hover/active) | Win/Linux only |
| `--border-radius` (5px) | `calc(var(--radius) * 0.8)` | Klaus `radius-md`, the Button/Input radius |
| `--border-radius-medium` (12px) | `--radius` | |
| `--border-radius-large` (15px) | `calc(var(--radius) * 1.8)` | |
| `--font-size` | leave at 15px | it is the page's rem base; changing it shifts every layout |
| `--bs-body-bg` / `--bs-body-color` | `--background` / `--foreground` | not Anki's own, but custom properties; required for the page background (see above) |
| `--bs-font-sans-serif` | `'Inter Variable', sans-serif` (`--font-sans`) | the editor's `html, body` font; also the body font via `--bs-body-font-family`. The `html { font-family }` already in `anki-host.css` covers the other pages. Needs an `@font-face` in `static/` (see below) |
| `--accent-card/note`, `--flag-*`, `--state-buried/suspended/marked` | leave | meaning colours, not read by the pages in scope |
| `--transition*`, `--blur` | leave | |

Tested end to end (headless Chromium, real built CSS, `colorScheme` light and dark, `night-mode` + `data-bs-theme` as Anki sets them):

```css
/* 1. Klaus's tokens under a prefix (Anki's --border would reference itself). */
:root {
	--k-background: #ffffff; --k-foreground: #09090b; --k-card: #ffffff; --k-popover: #ffffff;
	--k-primary: #18181b; --k-secondary: #f4f4f5; --k-muted: #f4f4f5; --k-muted-foreground: #71717b;
	--k-destructive: #e7000b; --k-border: #e4e4e7; --k-input: #e4e4e7; --k-ring: #71717b;
	--k-count-new: #1d4ed8; --k-count-learn: #b91c1c; --k-count-review: #15803d;
	--k-radius: 0.625rem;
}
@media (prefers-color-scheme: dark) {
	:root {
		--k-background: #09090b; --k-foreground: #fafafa; --k-card: #18181b; --k-popover: #18181b;
		--k-primary: #e4e4e7; --k-secondary: #27272a; --k-muted: #27272a; --k-muted-foreground: #9f9fa9;
		--k-destructive: #ff6467; --k-border: rgba(255, 255, 255, 0.1); --k-input: rgba(255, 255, 255, 0.15);
		--k-ring: #9f9fa9; --k-count-new: #93c5fd; --k-count-learn: #fca5a5; --k-count-review: #86efac;
	}
}
/* 2. Anki's variables. (0,2,1) beats Anki's :root and :root.night-mode although this sheet comes first. */
html:root:root {
	--canvas: var(--k-background); --canvas-elevated: var(--k-card); --canvas-inset: var(--k-background);
	--canvas-overlay: var(--k-popover); --canvas-code: var(--k-muted);
	--fg: var(--k-foreground); --fg-subtle: var(--k-muted-foreground);
	--border: var(--k-border); --border-subtle: var(--k-border); --border-strong: var(--k-input); --border-focus: var(--k-ring);
	--button-bg: var(--k-secondary); --button-gradient-start: var(--k-secondary); --button-gradient-end: var(--k-secondary);
	--button-primary-bg: var(--k-primary); --button-primary-gradient-start: var(--k-primary); --button-primary-gradient-end: var(--k-primary);
	--accent-danger: var(--k-destructive);
	--state-new: var(--k-count-new); --state-learn: var(--k-count-learn); --state-review: var(--k-count-review);
	--border-radius: calc(var(--k-radius) * 0.8); --border-radius-medium: var(--k-radius); --border-radius-large: calc(var(--k-radius) * 1.8);
	--bs-body-bg: var(--k-background); --bs-body-color: var(--k-foreground);
}
```

Computed results, light / dark: body background `#fff` / `#09090b`, body text `#09090b` / `#fafafa`, `button` background `#f4f4f5` / `#27272a`, `button` and `textarea` radius `7.5px` (was 5px), `textarea` border `#e4e4e7` / `rgba(255,255,255,.1)`. The same test showed `.btn-primary` and a checked `.form-check-input` staying `#0d6efd` in both modes.

The dark half works off the media query, matching Klaus's own look. Anki's JS and Bootstrap parts still key on the class (graphs' calendar colours, dark select arrows, `pageTheme`), so the two stay consistent only if every Anki page is opened with `#night` when dark (the import page is not today).

## What cannot be reached with variables

1. **Bootstrap component colours.** `.btn-primary`, `.btn-secondary`, `.btn-warning`, `.alert-*`, `.form-check-input:checked` and the `.form-select` arrow set their colours on the class itself (`--bs-btn-bg: #0d6efd`, `background-color: #0d6efd`), so no `:root` variable reaches them. In scope pages these are the FSRS and simulator buttons and alerts in deck options, the text-input modal, the editor's history modal, the preferences and change-notetype alerts, and import options. They stay Bootstrap blue/grey. Only class selectors in `anki-host.css` would change them, which is beyond "tokens only".
2. **Primary-button text colour in dark.** `_button-mixins.scss` hard-codes `color: white` on primary buttons (Save in deck options and change-notetype, the import header button, the editor's action button). Klaus's dark `--primary` is `#e4e4e7`, so mapping `--button-primary-bg` to it gives white on near-white (about 1.3:1). A dark-mode value for `--button-primary-*` that keeps white text legible has to be chosen instead (for example Klaus's `--chart-3` `#52525c`, about 7.6:1 with white), which is not Klaus's primary.
3. **Button shape and weight.** Bevelled border (`border-bottom-color: var(--shadow)`), impressed-shadow active state, `font-weight: 500`, padding `8px 10px`, margin `0 4px`, the `.fancy` elevation shadows (`elevation.scss`, literal `#141414`) and hover border logic. Variables can flatten the gradient and recolour the border, not remove the bevel.
4. **Hard-coded radii.** 22 source files carry literal `border-radius` values (mostly `5px`, some `!important`; the tag editor's tag is `5px`). They ignore `--border-radius`.
5. **Graph data colours.** Series colours come from d3 (`interpolateBlues`, `interpolateRdYlGn`, `schemeBlues`, `schemeCategory10`, literal `#31a354`, `#FFDC41`, calendar `#333`/`#ddd`). Only chrome (text, axes, tooltip, links) follows the variables.
6. **Fonts.** No font variable exists. The body and editor font can be set through `--bs-font-sans-serif` and the existing `html { font-family }` rule, but `static/anki-host.css` is plain CSS served as is, so Inter needs its own `@font-face` pointing at a font file served from `static/` (the app's `@fontsource-variable/inter` import is bundled by Vite and has no stable URL). Headings (DM Sans), monospace spots (CodeMirror, card-state editor) and note content (the note type's own CSS) are not reachable.
7. **Layout, density, icons.** Spacing, sizes, Anki's own icon set, sticky headers, modal chrome.
8. **Image-occlusion canvas** and its toolbar use literal colours.

## Decision and follow-ups for the map

Tokens-only gives the Klaus colour palette and corner radius on every Anki page and the Klaus body font on the editor, and leaves the structure Anki's. That is enough to stop Anki's pages looking foreign next to Klaus, not enough to read as the same component set. Record it as: **in scope as a variables-only skin; the editor toolbar can take the tokens** (the map's "Not yet specified" item about the editor toolbar depends on this).

Things the implementation issues that this blocks (#42, #46) should know:

- Write `anki-host.css` as above: prefixed Klaus tokens, then one `html:root:root` rule; keep the media-query dark half.
- Add `--bs-body-bg`, `--bs-body-color` and `--bs-font-sans-serif`; the existing `body { background-color: var(--canvas) }` is redundant and can go.
- Append `#night` to the import page navigation in `src-tauri/src/main.rs` so the class-keyed parts of Anki's JS agree with the media query.
- Decide separately whether to go past "tokens only" for the Bootstrap blue buttons and the dark primary-button text; that is a few class selectors in `anki-host.css`, not variables.

## Not verified

- Visual result in the running Klaus app: the cascade and computed values were verified on the real built Anki stylesheet in headless Chromium, but not on the live editor, deck options or graphs pages through the bridge.
- Tauri's macOS webview (WKWebView) specifically; Chromium's cascade is the standard one, and `:root:root`, `color-mix()` and `@media (prefers-color-scheme)` are all long-supported in WebKit.
- Route-level stylesheets for every page were not individually loaded; they were reasoned to come after the host sheet because the host sheet is the first element in `<head>`.
- Whether Anki 25.09 (the version named in the ticket) differs: the submodule pins 26.09.3, which is what Klaus builds.
