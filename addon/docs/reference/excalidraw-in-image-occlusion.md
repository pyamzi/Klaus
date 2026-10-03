# Excalidraw inside Image Occlusion: options

Research note, 2026-10-01. Question from Pouya: "I do not want excalidraw to show up in the browser, rather I want it to feel like it's native to the image occlusion tool itself, can you not take from the original files and work with them?"

## Summary

1. Today no Klaus code opens Excalidraw. The page exists (`klausmate/image_occlusion/excalidraw/`), but `excal_window.py` (plan Task 7) has not been written. The plan puts it in its own window. The page also still shows Excalidraw's full web-app chrome: hamburger menu with GitHub/X/Discord links, library button, help button.
2. **Option A** (Excalidraw as a "Draw" tab in the existing occlusion editor window, chrome hidden, Klaus colours) is the smallest change. It reuses the vendored bundle and keeps IOE's note format and the PNG approach in the spec.
3. **Option C** (Excalidraw becomes the editor for diagram notes, with masks drawn on the same canvas) gives one canvas for drawing and masking. svg-edit stays for photo notes. Medium effort.
4. **Option B** (add hand-drawn tools to svg-edit using roughjs and perfect-freehand, the libraries Excalidraw itself uses) is the literal "take from the original files". It is the largest job. Fonts and svg-edit's sanitiser are real blockers for text.
5. Recommendation: A first, since it alone removes the "separate web page" feel at low cost. Move to C only if drawing and masking must share one canvas. The decision is Pouya's.

## 1. How Excalidraw surfaces today

What exists in the repo:

- The page: `klausmate/image_occlusion/excalidraw/index.html:1-20`. Its title is "Draw a diagram" (`index.html:6`). It loads fonts from `/_addons/klausmate/image_occlusion/excalidraw/` (`index.html:7`), Anki's local add-on web server.
- `entry.jsx` mounts the full `<Excalidraw>` component in `#root`, full page (`entry.jsx:111-127`, `index.html:10`). It adds "Occlude" and "Cancel" through `renderTopRightUI` (`entry.jsx:102-109`, `:119`). It hides only `loadScene`, `saveToActiveFile` and `export` (`entry.jsx:120-122`).
- The bundle is built by `scripts/build_excalidraw.sh` (Excalidraw 0.18.1, React 18.3.1, esbuild IIFE; `build_excalidraw.sh:15-17`, `:55-67`).
- The only Python wiring is the web-exports regex (`klausmate/__init__.py:570-580`). A grep of `klausmate/` for `klausexcal`, `excalidraw` and "Draw a diagram" finds no other Python caller. `klausmate/image_occlusion/excal_window.py` does not exist.

What the plan says will happen:

- Spec: "Klaus opens a window-modal Excalidraw editor: a webview running a vendored, prebuilt `@excalidraw/excalidraw` bundle" (`docs/superpowers/specs/2026-10-01-image-occlusion-design.md:55`).
- Plan Task 7: `ExcalidrawWindow(QDialog)`, window-modal, `AnkiWebView` (`docs/superpowers/plans/2026-10-01-image-occlusion.md:280`). After "Occlude" it closes and opens IOE's own editor window (`ImgOccEdit`) on the PNG (spec `:63`).

So the design is two separate windows, one after the other. The first is a Qt webview, not the system browser. It is still a full-page web app.

How the page may have been seen:

- Plan Task 5 Step 4 says to load the page "in Anki through `/_addons/klausmate/image_occlusion/excalidraw/index.html`" (plan `:239`). That is a URL on Anki's local server, so it can be opened in any browser.
- Commit `ec9f6e1` ("the Excalidraw page's 'ready' waits for Anki's bridge") suggests it has run inside an Anki webview at least once.
- **Unverified:** how Pouya actually saw it, whether in a system browser at the `/_addons/` URL or in a test webview.

Why it reads as "a web page" even inside Anki (Excalidraw v0.18.1 source):

- **Default main menu.** It renders unless the host supplies its own `<MainMenu>` (`packages/excalidraw/components/LayerUI.tsx:85-110`, rendered at `:390`). With Klaus's `UIOptions`, Open and Save hide themselves (`components/main-menu/DefaultItems.tsx:46-52`, `:89-94`) and Export is gated off (`LayerUI.tsx:93`). Still shown: Save as image, Find, Help, Reset canvas, an "Excalidraw links" group with GitHub/X/Discord, and background colour. The theme toggle self-checks through `isActionEnabled` (`DefaultItems.tsx:211-229`). **Unverified:** whether it shows with no `theme` prop.
- **Library button.** Always rendered as a fallback trigger, top right (`LayerUI.tsx:391-407`, `:342-347`).
- **Help "?" button** in the footer (`components/footer/Footer.tsx:81-83`).
- **External links.** The GitHub/X/Discord menu items and the help dialog's links use `target="_blank"` (`components/dropdownMenu/DropdownMenuItemLink.tsx:35`, `components/HelpDialog.tsx:18-45`). "Browse libraries" targets `_excalidraw_libraries` (`components/LibraryMenuBrowseButton.tsx:24`). In Anki 25.09.2, a `_blank` link makes `AnkiWebView.createWindow` return a new `AnkiWebView` (`qt/aqt/webview.py:413-416`). `AnkiWebPage.acceptNavigationRequest` then hands non-Anki URLs to `open_url_if_supported_scheme`, the system browser (`webview.py:242-271`). So a click there does open the system browser. **Unverified on the installed 26.09.2:** these lines come from the local 25.09.2 checkout (`/Users/pyamzi/Documents/Github/R36XX AnkiBoy/anki-main`).
- **Look.** Excalidraw's own purple and its Assistant UI font (`css/theme.scss:85`, `css/styles.scss:32`). The page's own Occlude button is also Excalidraw purple, `#6965db` (`index.html:13`).
- **No welcome screen.** Excalidraw shows its welcome screen only when the host renders `<WelcomeScreen>` (docs: welcome-screen; `components/App.tsx:1597-1602` only gates the tunnels). `entry.jsx` doesn't render it.

IOE's own editor, for contrast, is a `QDialog` with a `QTabWidget`. Its tabs are "Masks Editor" (the svg-edit webview) and "Fields" (`klausmate/image_occlusion/editor.py:320-330`), with Qt buttons below (`editor.py:292-299`). svg-edit loads from a `file://` URL (`add.py:249`, `:275`) and is not web-exported (spec `:106`).

## 2. Option A: Excalidraw as a tab inside the occlusion editor

**Shape.** Add a third tab, "Draw", to `ImgOccEdit.tab_widget` (`editor.py:325-330`). It holds a second `AnkiWebView` that loads the existing page. A Klaus button such as "Use drawing" (in Qt, or in the page) exports the PNG plus label masks. It then feeds them to the open editor through IOE's change-image path, which Task 8 already plans (plan `:314`), and switches to the "Masks Editor" tab. Everything stays in one window and one deck/tags/fields form.

**Entry-flow gap.** `ImgOccEdit` is opened by `occlude(image_path)` and needs the image's width, height and URL before it loads svg-edit (`add.py:249-256`). "Draw a diagram…" therefore needs one of two designs: open the editor on a generated blank PNG and start on the Draw tab, or enable the Draw tab only once an image exists. This is a design decision for the spec.

**Same page or sibling webview: use a sibling webview.**

- **Origins.** svg-edit loads by `file://` (`add.py:249`). The Excalidraw page needs `/_addons/...` for its fonts (`index.html:7`; the build points Excalidraw's font fallback at that path, `build_excalidraw.sh:33-34`). Mounting both in one page would move svg-edit onto `/_addons/` too, which changes IOE's loading and the exports regex.
- **CSS.** `excalidraw.css` is mostly scoped to `.excalidraw`. It also has unscoped selectors: `:root`, `.visually-hidden`, `.zoom-button`, `.undo-redo-buttons`, `.footer-center`, `.exc-stats` (scan of the built `excalidraw.css`).
- **Keys.** svg-edit binds its hotkeys on `document` (`svg-edit/editor/svg-editor.js:938`, `:1339`, `:2057`). Excalidraw binds keys on its own container unless `handleKeyboardGlobally` is set (`components/App.tsx:1559`; docs: props, default `false`). One page would work with care. Two webviews avoid all three problems.

**What the API can hide or change (v0.18.1):**

| Piece | By API | How |
|---|---|---|
| Main menu items (Open, Save, Help, socials, theme…) | Yes | Render your own `<MainMenu>` child. It replaces the default (docs: main-menu; fallback logic `LayerUI.tsx:390`). |
| The hamburger button itself | No | `MainMenu` always renders its trigger (`components/main-menu/MainMenu.tsx:39-49`). Hide `.main-menu-trigger` with CSS. |
| Library button and sidebar | No | Fallback trigger, class `sidebar-trigger` (`components/Sidebar/SidebarTrigger.tsx:38`). CSS. |
| Help "?" button | No | `help-icon` class (`components/HelpButton.tsx:12`). CSS. |
| Export / save / load dialogs | Yes | `UIOptions.canvasActions` (`types.ts:614-622`, defaults `constants.ts:282-295`). |
| Theme toggle | Yes | `canvasActions.toggleTheme`, plus the `theme` prop (`types.ts:543`; docs: props "theme"). |
| Toolbar tools | Only the image tool | `UIOptions.tools` is `{ image: boolean }` (`types.ts:627-629`, used at `components/Actions.tsx:292`). The full tool list is in `shapes.tsx:57-120`. Others can only be hidden with CSS. |
| Welcome screen | Off by default | Opt-in child component (docs: welcome-screen). |
| Custom buttons | Yes | `renderTopRightUI` (`types.ts:533-536`), `<Footer>` child, custom `<MainMenu.Item>` (docs: render-props, footer, main-menu). |
| Everything but the canvas | Partly | `zenModeEnabled` slides the shape-actions panel and top-right group out (`LayerUI.tsx:200-201`, `:329-331`) and hides stats (`:231`). It also hides the toolbar's lock and extra tools (`LayerUI.tsx:254-272`). It is a mode, not a chrome switch. **Unverified:** exactly which pieces stay visible in zen mode (not run). |

**Theming.** Set CSS variables on a higher-specificity `.excalidraw` selector, e.g. `--color-primary` and family (docs: customizing-styles; full list `css/theme.scss`). The UI font is `--ui-font` (`css/styles.scss:32`). Klaus's theme lives in `klausmate/theme.py`. Note that the spec lists restyling the occlusion editor as out of scope (spec `:122`), and svg-edit's own UI is unchanged 2010-era jQuery. "Native" here means matching that window, not Klaus's MD3 look.

**Sizing.** Excalidraw fills its container's width and height, so the container needs a non-zero size (docs: installation). `index.html:10` already sets `html, body, #root { height: 100% }`.

**Fonts offline.** Already solved by the build: the fallback URL is patched to `EXCALIDRAW_ASSET_PATH` (`build_excalidraw.sh:8-13`, `:47-52`), and the fonts are copied (`:75`).

**Bundle size.** No change. `excalidraw.js` is 3,214,415 bytes and `excalidraw.css` 144,681 bytes (`ls -la`). `fonts/` is 13 MB, of which `Xiaolai` (the CJK fallback) is 12 MB (`du -sh`).

**Effort and risk.** Small, roughly 1–2 days. Task 7's `ExcalidrawWindow` becomes a tab, and `prepare_occlusion` / `excal_masks` are reused as they are. Risks:
- The canvas still looks like Excalidraw: its toolbar island and fonts.
- Drawing and masking are still two steps on two canvases.
- CSS that hides internal classes can break on an Excalidraw upgrade (the pinned version contains this).

## 3. Option B: hand-drawn tools inside svg-edit ("take from the original files")

**What Excalidraw is built from.**
- `@excalidraw/excalidraw` 0.18.1 depends on `roughjs` 4.6.4 and `perfect-freehand` 1.2.0 (npm registry metadata for 0.18.1).
- Shapes are drawn with roughjs. The options mapping is `generateRoughOptions` (`packages/excalidraw/scene/Shape.ts:57-100` @ v0.18.1).
- Freehand strokes use perfect-freehand's `getStroke` with Excalidraw's own options (`renderer/renderElement.ts:1018-1037`), turned into a path by `getSvgPathFromStroke` (`:1049`).
- SVG export calls roughjs's `rsvg.draw` (`renderer/staticSvgScene.ts:42-56`, `:140-160`).

**Which Excalidraw packages are separate.**
- At tag v0.18.1 the repo has `packages/excalidraw`, `packages/math` and `packages/utils` only.
- On master (`1919728`) it also has `common`, `element`, `fractional-indexing` and `laser-pointer`.
- `@excalidraw/element` on npm has only prerelease versions: `latest` is `0.18.0-f0063e113`, and none of its versions lacks a `-` suffix (npm registry, all versions checked).
- `@excalidraw/utils` 0.1.5 is 97 MB unpacked (npm registry).
- So the stable, reusable parts are roughjs, perfect-freehand, and small MIT functions copied out of Excalidraw. The element package is not yet a stable dependency.

**Libraries.**
- roughjs 4.6.6 ships an IIFE, `bundled/rough.js`, 27,762 bytes. `rough.svg(svgEl).rectangle(x, y, w, h, opts)` returns an `SVGGElement` (`bundled/svg.d.ts:14`). MIT, © 2019 Preet Shihn.
- perfect-freehand 1.2.3: `dist/esm/index.mjs` is 4,532 bytes, default export `getStroke` (`dist/types/index.d.ts:2`). It needs a tiny esbuild wrap to run as a classic script. MIT, © 2021 Stephen Ruiz Ltd.

**svg-edit's extension API (the vendored version).**
- IOE vendors svg-edit 2.6-beta. `svg-editor.html:563` reads "SVG-edit v2.6-beta". `svgcanvas.js` differs from upstream branch `svn/2.6` (commit `92b9f6ab`) by 157 diff lines, and IOE's edits are noted in `svg-editor.js:19-24`.
- `svgEditor.addExtension(name, fn)` (`svgcanvas.js:580-599`; example `extensions/ext-helloworld.js`). An extension returns `buttons` (`type: "mode"`, `"context"`, `"mode_flyout"`) and handlers.
- Canvas hooks: `mouseDown`, `mouseMove`, `mouseUp`, `zoomChanged` (`svgcanvas.js:2755`, `:3154`, `:3397`, `:6770`). Editor hooks: `selectedChanged`, `elementTransition`, `elementChanged`, `onNewDocument`, `toolButtonStateUpdate`, `langChanged` (`svg-editor.js:724`, `:755`, `:800`, `:2626`, `:3449`, `:4853`).
- Extensions get private methods including `addSvgElementFromJson`, `addCommandToHistory`, `InsertElementCommand` and `ChangeElementCommand` (`svgcanvas.js:8774-8814`), so new shapes can join undo. `ext-shapes.js:262-367` is a working example of a drag-to-draw tool.
- svg-edit already has a freehand pencil, `fhpath` (`svgcanvas.js:2579-2583`).
- The sanitiser keeps `g` and `path` with `stroke-linecap`, `fill-opacity`, `stroke-dasharray` and `transform` (`sanitize.js:59`, `:66`), so roughjs output survives.

**Where the drawing would live.**
- svg-edit creates two layers, "Labels" and "Masks" (`svgcanvas.js:6458-6459`). `ngen` treats only the topmost layer as masks (`ngen.py:237-238`). All other layers are copied unchanged into every question, answer and original mask SVG (`ngen.py:427-435`, `:534-562`).
- So a diagram drawn in "Labels" appears on every card, over a blank background image. IOE needs a background image (`add.py:251-253`), so a blank PNG would be generated.

**The real blockers are text and fonts, not shapes.**
- Mask SVGs are shown through `<img src="…svg">` (`utils.py:55-58`, `template.py:45`, `:82`). MDN: an SVG used as an image cannot load external resources unless they are inlined as `data:` URLs (MDN "SVG as an image"). MDN does not name fonts explicitly. **Unverified:** that an external `@font-face` URL fails in Anki's reviewers, though it is the expected reading. A hand-drawn font (Excalifont, 80 KB of woff2 here) would have to be inlined into all three mask SVGs of every note, or text converted to paths.
- svg-edit's sanitiser has no `style` element in its whitelist (element list in `sanitize.js`). It removes non-whitelisted elements on load (`sanitize.js:253-264`). An inlined `<style>@font-face…</style>` would be stripped when edit mode reloads the original mask (`add.py:266-268`).
- A workaround is to flatten the "Labels" layer into the PNG on Add (rasterise in the webview), keeping masks as SVG. That is the spec's PNG approach (spec `:59`), but the drawing is then no longer editable.

**What has to be rebuilt.** roughjs output is static paths. Excalidraw re-generates shapes on resize and keeps arrows bound to shapes and text bound in containers. None of that comes with roughjs. Resizing a rough `<g>` in svg-edit scales its strokes, unless an `elementChanged` handler regenerates it.

**Effort and risk.** Large, roughly 2–3 weeks for rectangle, ellipse, diamond, arrow, line, freehand and text with the hand-drawn look, undo, and editing. Risks:
- Fonts, as above.
- Rebuilding Excalidraw features (binding, re-rendering, label editing) on top of a 2012 jQuery editor.
- The spec's auto-masking of labels would need to read svg-edit text elements instead of an Excalidraw scene.

## 4. Option C: Excalidraw as the whole editor for diagram notes

**Shape.**
- In the occlusion window, diagram notes get Excalidraw in place of svg-edit in the "Masks Editor" tab. Photo notes keep svg-edit.
- Masks are Excalidraw rectangles tagged with `customData`, an optional free-form record on every element (`packages/excalidraw/element/types.ts:79`). `restore` keeps `customData` (`data/restore.ts:209-211`).
- A Klaus "Mask" button (`renderTopRightUI` or a `<Footer>` child) adds one through `excalidrawAPI.updateScene` (`entry.jsx:61` already uses it).

**Output stays IOE-compatible:**
- What `ngen` needs: an `<svg>` with `width`/`height` in image pixels (`ngen.py:234-236`); the topmost `<g>` as the masks layer (`ngen.py:216-226`, `:238`); one element child per mask (`ngen.py:241-283`); and in edit mode an `id` per mask that matches the note (`ngen.py:281-282`).
- `excal_masks.masks_svg` already writes this format (`excal_masks.py:41-50`).
- The PNG stays from `exportToBlob` with the mask elements filtered out, which keeps the font-free card rendering in the spec (spec `:59`).
- Mask geometry comes from the tagged elements with the same mapping as `label_rects` (`excal_masks.py:12-33`).
- The IOE mask `id` can be stored in the element's `customData`. Task 8's IoU matching (plan `:319-323`) would then be unnecessary for masks.

**Do not use `exportToSvg` for masks.**
- It draws every shape as roughjs `<g><path>` with a `translate … rotate` transform (`renderer/staticSvgScene.ts:140-160`).
- It inlines fonts in a `<style>` by default (`scene/export.ts:414-425`).
- Its structure is not IOE's layer layout.
- The scene JSON is the right source.

**Compatibility limits.**
- Only diagram notes can use it. The spec keeps "Replacing svg-edit" out of scope (spec `:123`).
- Existing IOE notes have masks that svg-edit may have drawn as ellipses, polygons, paths or groups (`ngen.py:271-274` handles `g`). These have no clean Excalidraw equivalent. Re-editing an old photo note in Excalidraw would lose them, so those notes must stay on svg-edit.
- Masks should be drawn with `roughness: 0` and a solid fill. Excalidraw renders rough by default, while IOE renders plain rectangles. **Unverified:** the visual match on cards (not tested).

**Effort and risk.** Medium, roughly 1 week on top of Tasks 5–6. Task 7 changes from "Excalidraw window, then svg-edit" to "Excalidraw in the editor tab". Task 8 gets simpler. Risks:
- Two mask editors with different feel (diagram vs photo).
- Edit-mode note ids must round-trip through `customData`.
- Excalidraw's chrome must still be stripped as in Option A.

## 5. Licensing

| Component | Licence | Ships today | What has to ship |
|---|---|---|---|
| Excalidraw 0.18.1 | MIT, "Copyright (c) 2020 Excalidraw" (repo `LICENSE` @ v0.18.1) | `excalidraw/LICENSE-excalidraw.txt` | Same, for A and C. For B, the MIT notice beside any copied function (e.g. `generateRoughOptions`, `getSvgPathFromStroke`). |
| React 18.3.1 | MIT | `excalidraw/LICENSE-react.txt`, plus `excalidraw.js.LEGAL.txt` for bundled deps | Same (A, C). Not needed for B. |
| Excalidraw fonts | Mostly OFL-1.1; Comic Shanns MIT; Liberation GPLv2 with font exception | `excalidraw/fonts/LICENSES.txt:15-23` | Same (A, C). For B, OFL text if Excalifont is shipped. |
| roughjs | MIT, © 2019 Preet Shihn (npm tarball `LICENSE`) | Inside `excalidraw.js` (bundled dependency) | Its own LICENSE file if vendored separately (B). |
| perfect-freehand | MIT, © 2021 Stephen Ruiz Ltd (npm tarball `LICENSE`) | Inside `excalidraw.js` | Its own LICENSE file if vendored separately (B). |
| svg-edit 2.6-beta | MIT ("Copyright (c) 2009-2012 by SVG-edit authors", `LICENSE` @ `92b9f6ab`); file headers say MIT (`svg-editor.js:4`) | Headers only. No svg-edit MIT licence text is in `image_occlusion/svg-edit/`; `find` finds only `jgraduate/LICENSE`. `contextmenu.js:4` is Apache-2. | Already owed in every option. B also edits svg-edit, so mark the changed files. |
| IOE and Klaus | AGPL-3 with Section 7 terms (`image_occlusion/LICENSE.txt`) | Yes | Keep every header. Modified IOE files must be marked as modified (Section 7 term 2, end of `LICENSE.txt`). |

The FSF lists the Expat (MIT) licence as GPL-compatible (https://www.gnu.org/licenses/license-list.html#Expat), so MIT code can go into an AGPL-3 work as long as its notice ships. All three options are licence-compatible.

## 6. Recommendation and what changes in the spec and plan

The constraint that separates the options:
- "Not in the browser" is fixed by Option A alone: one Qt window, no web-app menu, no outbound links.
- "Native to the occlusion tool" depends on how far that goes.
  - **A:** same window and same form, two canvases. Small effort.
  - **C:** one canvas for drawing and masking on diagram notes. Medium effort.
  - **B:** one svg-edit canvas, no Excalidraw UI at all. Large effort, with font blockers.

| | Effort | Main risk |
|---|---|---|
| A, Draw tab | ~1–2 days | Excalidraw's toolbar look stays; CSS hides internal classes |
| B, svg-edit + roughjs/perfect-freehand | ~2–3 weeks | Text/fonts in `<img>` SVG and the sanitiser; rebuilding Excalidraw behaviour on a 2012 editor |
| C, Excalidraw editor for diagrams | ~1 week | Two different mask editors; note-id round trip |

Effort figures are estimates, not measured.

Suggested path: A now. Then C if Pouya wants masks drawn directly on the diagram. B only if no Excalidraw UI is acceptable at all.

What would change:

- **A**
  - Spec `:53-57` ("Entry", "Editor window"): replace "window-modal Excalidraw editor" with "a Draw tab in the occlusion editor", and state the hidden chrome (main menu reduced to Klaus items; library, help and socials hidden).
  - Plan Task 7 (`:277-306`): `excal_window.ExcalidrawWindow(QDialog)` becomes a tab and webview owned by `ImgOccEdit` (`editor.py:320-330`). "Occlude" becomes "Use drawing", which loads the PNG and masks into the Masks tab.
  - Plan Task 5: `entry.jsx` gains a `<MainMenu>` child, theme variables and the CSS hides.
  - Tasks 6 and 8 unchanged.
- **C**
  - Same as A for the window.
  - Spec `:58-63` changes: masks are drawn in Excalidraw, there is no second hop to svg-edit for diagram notes, and spec `:123` ("Replacing svg-edit") is narrowed to "svg-edit stays for photo notes".
  - Task 6 gains a mask-element-to-omask function.
  - Task 8's `remap_masks` (plan `:319-323`) is replaced by ids stored in `customData`.
- **B**
  - Spec "Excalidraw diagrams (new)" is rewritten.
  - Tasks 5–8 (the bundle, scene masks, the window and the sidecar) are largely dropped and replaced by svg-edit extensions plus a blank-canvas entry point.
  - A decision is needed on fonts: flatten to PNG, or inline fonts.

## Sources

Local code (Klaus Addon repo, read 2026-10-01):
- `klausmate/image_occlusion/excalidraw/index.html`, `entry.jsx`, `LICENSE-excalidraw.txt`, `fonts/LICENSES.txt`
- `klausmate/image_occlusion/editor.py`, `add.py`, `ngen.py`, `excal_masks.py`, `utils.py`, `template.py`, `web.py`, `LICENSE.txt`, `UPSTREAM.md`
- `klausmate/image_occlusion/svg-edit/editor/svg-editor.html`, `svg-editor.js`, `svgcanvas.js`, `sanitize.js`, `extensions/ext-helloworld.js`, `extensions/ext-image-occlusion.js`, `extensions/ext-shapes.js`
- `klausmate/__init__.py:570-580`
- `scripts/build_excalidraw.sh`
- `tests/test_excalidraw_bundle.py`
- `docs/superpowers/specs/2026-10-01-image-occlusion-design.md`
- `docs/superpowers/plans/2026-10-01-image-occlusion.md`
- Git commits `0472e6e`, `ec9f6e1`

Excalidraw:
- Tag v0.18.1, commit `a2ec2889babf7d2295469c6d90ebe77fae57df84`: https://github.com/excalidraw/excalidraw/tree/v0.18.1
  - `packages/excalidraw/types.ts:497-586` (ExcalidrawProps), `:614-632` (CanvasActions, UIOptions)
  - `packages/excalidraw/constants.ts:282-295` (DEFAULT_UI_OPTIONS)
  - `packages/excalidraw/components/LayerUI.tsx:85-110`, `:200-272`, `:329-347`, `:390-407`
  - `packages/excalidraw/components/footer/Footer.tsx:81-83`, `components/HelpButton.tsx:12`, `components/main-menu/MainMenu.tsx:39-49`, `components/main-menu/DefaultItems.tsx:338-360`, `components/dropdownMenu/DropdownMenuItemLink.tsx:35`, `components/HelpDialog.tsx:18-45`, `components/LibraryMenuBrowseButton.tsx:24`, `components/Sidebar/SidebarTrigger.tsx:38`, `components/Actions.tsx:292`, `components/App.tsx:1559`, `:1597-1602`
  - `packages/excalidraw/shapes.tsx:57-120`
  - `packages/excalidraw/scene/Shape.ts:57-100`, `renderer/renderElement.ts:1018-1049`, `renderer/staticSvgScene.ts:42-56`, `:140-160`, `scene/export.ts:265-286`, `:414-425`
  - `packages/excalidraw/element/types.ts:79`, `data/restore.ts:209-211`
  - `packages/excalidraw/css/theme.scss:4`, `:85-90`, `:166`, `css/styles.scss:32`
  - `LICENSE` (MIT)
  - `dev-docs/docs/@excalidraw/excalidraw/` (same text as the docs site)
- Master, commit `1919728724a1b71af73cb7e6d2d1a418a1415b1c` (2026-09-30): `packages/` holds common, element, excalidraw, fractional-indexing, laser-pointer, math, utils.
- Docs (each returned HTTP 200 on 2026-10-01):
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/props
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/props/ui-options
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/props/render-props
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/children-components/main-menu
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/children-components/welcome-screen
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/children-components/footer
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/children-components/sidebar
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/utils/export
  - https://docs.excalidraw.com/docs/@excalidraw/excalidraw/customizing-styles
- npm registry (2026-10-01):
  - https://registry.npmjs.org/@excalidraw/excalidraw (latest 0.18.1, MIT, deps roughjs 4.6.4 and perfect-freehand 1.2.0)
  - https://registry.npmjs.org/@excalidraw/element (latest `0.18.0-f0063e113`, MIT)
  - https://registry.npmjs.org/@excalidraw/utils (0.1.5, 97 MB unpacked)

roughjs and perfect-freehand:
- https://registry.npmjs.org/roughjs (4.6.6, MIT, repo https://github.com/pshihn/rough). Tarball `bundled/rough.js`, `bundled/svg.d.ts`, `LICENSE`.
- https://registry.npmjs.org/perfect-freehand (1.2.3, MIT, repo https://github.com/steveruizok/perfect-freehand). Tarball `dist/esm/index.mjs`, `dist/types/index.d.ts`, `LICENSE`.

svg-edit:
- https://github.com/SVG-Edit/svgedit, branch `svn/2.6`, commit `92b9f6abeaca87aafa71aeba73658e7962896df9`: `LICENSE`, `editor/svgcanvas.js`, `editor/svg-editor.html:567`.
- Current upstream licence: `LICENSE-MIT.txt` (GitHub API, spdx MIT). npm `svgedit` 7.4.2, `@svgedit/svgcanvas` 7.4.2.

Anki:
- Local checkout 25.09.2 at `/Users/pyamzi/Documents/Github/R36XX AnkiBoy/anki-main/qt/aqt/webview.py:242-271`, `:413-416`. The installed Anki is 26.09.2, which was not checked.

Licensing:
- FSF licence list, Expat: https://www.gnu.org/licenses/license-list.html#Expat

Web platform:
- MDN, "SVG as an image": https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image

Not verified:
- How Pouya actually saw the page (system browser vs webview).
- Anki 26.09.2's link handling.
- Exactly what zen mode leaves on screen.
- Whether the theme toggle shows in Klaus's page.
- Whether external fonts fail inside `<img>` SVG in each Anki client.
- How Excalidraw-drawn masks look on cards.
- All effort figures.
