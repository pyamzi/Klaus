# Image Occlusion in Klaus Implementation Plan

> **Historical record: shipped, do not execute.** This plan was carried out and the work is in the code, which is the source of truth. It predates two changes: the package `klausmate/` is now `klaus_note/`, and the local board (`board/board.py`) is retired in favour of GitHub Issues (see `docs/agents/issue-tracker.md`). Unchecked boxes are not open work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Image Occlusion Enhanced (IOE) v1.4.0 becomes `klausmate/image_occlusion/`. The PDF reader can occlude a page or region, and a diagram drawn in Excalidraw can be occluded with its labels auto-masked.

**Architecture:** IOE is vendored close to verbatim (Task 1), then adapted only where Klaus rules require (Tasks 2–3). Two thin entry points call IOE's own `ImgOccAdd.occlude`: the reader (Task 4) and an offline Excalidraw window (Tasks 5–7). Mask geometry for Excalidraw is a pure module (Task 6) so it is tested headless.

**Tech Stack:** Python 3.9 (tests) / 3.13 (Anki 26.09), PyQt6 via `aqt.qt`, svg-edit 2.x (vendored by IOE), `@excalidraw/excalidraw` 0.18.1 + React, bundled once with esbuild into an IIFE.

**Spec:** `docs/superpowers/specs/2026-10-01-image-occlusion-design.md`

## Global Constraints

- **Source:** port from `~/Library/Application Support/Anki2/addons21/1374772155/` (IOE v1.4.0, AGPL-3).
  - Keep every copyright header, and put IOE's `LICENSE.txt` at `klausmate/image_occlusion/LICENSE.txt`.
  - Never write into the installed add-on folder.
- **Note type:** keep `IO_MODEL_NAME = "Image Occlusion Enhanced"`, `IO_FLDS`, the templates and the mask SVG format byte-compatible:
  - `<svg width height>`
  - `<g><title>Labels</title></g>`
  - `<g><title>Masks</title><rect …/></g>`
- **Settings:** stay in collection config `imgocc` (via `col.get_config`/`col.set_config`) and profile `mw.pm.profile["imgocc"]`. No migration.
- **K-114:** no `exec()` on dialogs or message boxes. Also banned: `askUser`, `askUserDialog`, `getText`, `getOnlyText`, `chooseList`, `QMessageBox.question` / `.information` / `.critical` / `.warning` (static) and `QInputDialog.getX`. Use window-modal `open()` / `show()` with signals. `QMenu.exec` is fine.
- **No attributes that shadow Qt methods:** no instance attribute named `parent`, `window`, `close`, `show` or `hide`.
- **No monkey-patching** of `aqt` classes when a `gui_hooks` hook exists.
- **Web exports:** one `setWebExports` call per add-on (the existing one at `klausmate/__init__.py` ~573), widened:
  - It must still match today's paths.
  - It must add `image_occlusion/web/.*\.(css|js)` and `image_occlusion/excalidraw/.*\.(html|js|css|woff2|png)`.
  - svg-edit keeps loading via `QUrl.fromLocalFile`.
- **No network at runtime.** The Excalidraw bundle is built by `scripts/build_excalidraw.sh` with pinned versions and committed.
- **Copy, verbatim:**
  - Conflict tooltip: "Image Occlusion is now built into Klaus. Disable the separate Image Occlusion Enhanced add-on and restart Anki."
  - No-editor tooltip: "Open Add or Edit to make an occlusion note".
  - Menu labels: "Occlude this page", "Occlude this region", "Choose image…", "Draw a diagram…", the tab "&Draw", and the button "Use drawing" (amended 2026-10-01).
- **Excalidraw export:** PNG at `scale = 2`, `padding = 20` scene px, label margin `4` image px. The sidecar is `_<image media name>.excalidraw` (R19).
- **Tests:**
  - Use the `klaus-test` harness (`.claude/skills/klaus-test/scripts/anki_stubs.py`) and run with `env QT_QPA_PLATFORM=offscreen python3 tests/<name>.py`.
  - Use temp dirs only. Never touch `klausmate/user_files` or the real collection media.
  - PyQt6 aborts on unhandled slot exceptions, so call handlers directly or guard them with a restored excepthook.
- **Repo rules:**
  - Coordinate through `python3 board/board.py`; never hand-edit `board/BOARD.md`.
  - Other sessions' uncommitted hunks are staged around by name (R26 in `.superpowers/sdd/2026-09-30-pdf-reader/constraints.md`), never reverted.
  - Don't touch `single_window.py`, `host_keys.py` or `reader_host.py`.
  - Commit only when the user has approved execution. Never push.

## Review Focus

1. **Pre-port IOE notes edited with the ported editor.** Masks keep their ids, so existing notes update in place with no duplicates and no review history lost. Test in Task 3.
2. **The same PDF page occluded twice.** The second image gets a distinct media name, and the notes reference the name Anki returned, not the requested one. Test in Task 4.
3. **Multiline, non-ASCII and very large labels; very large diagrams.**
   - Each label gives one mask covering all its lines.
   - A PNG over IOE's image-size limit gives a tooltip, not a crash.

   Tests in Tasks 6 and 7.
4. **Closing the Add/Edit window or switching profile mid-draw.** The occlusion editor (and its Draw tab) closes, nothing is written to media, and no orphan dialog is left. Test in Task 7.
5. **Re-edit after adding elements to the left or top of the diagram.** The scene origin shifts, and hand-added masks shift with it so they stay on the same spot. Test in Task 8.

---

## Phase 1 — card "Image Occlusion 1/3: port IOE"

### Task 1: Vendor IOE v1.4.0 verbatim

**Files:**
- Create `klausmate/image_occlusion/` containing these, copied byte-for-byte:
  - `__init__.py` (empty, replacing IOE's add-on bootstrap)
  - `add.py`, `config.py`, `consts.py`, `dialogs.py`, `editor.py`, `lang.py`, `main.py`, `nconvert.py`, `ngen.py`, `options.py`, `qt.py`, `template.py`, `utils.py`, `web.py`, `_version.py`
  - `_vendor/`, `icons/`, `svg-edit/`, `web/`
  - `LICENSE.txt`
  - `UPSTREAM.md`, recording the source path, version v1.4.0, the IOE GitHub URL, and that IOE's own `__init__.py` was not copied.
- Test: `tests/test_image_occlusion_vendor.py`

**Interfaces:**
- Produces: the package `klausmate.image_occlusion`, nothing wired.

- [ ] **Step 1: Write the failing test.**
  - Every vendored `.py` is byte-identical to the installed add-on's file of the same name, except `__init__.py`.
  - `LICENSE.txt` exists and contains "GNU AFFERO GENERAL PUBLIC LICENSE".
  - `UPSTREAM.md` names "v1.4.0".
  - No vendored file is imported by `klausmate/__init__.py` yet.

  The byte-identity check is skipped with a printed note if the installed add-on folder is absent.
- [ ] **Step 2: Run it. Expect FAIL** (the package is missing).
- [ ] **Step 3: Copy the files.** Skip `__pycache__` and `meta.json`.
- [ ] **Step 4: Run the test (PASS) and the full suite.**
- [ ] **Step 5: Commit** "Image Occlusion 1/3: vendor IOE v1.4.0 verbatim (not wired)".

### Task 2: Klaus rules on the vendored code

**Files:**
- Modify: `klausmate/image_occlusion/{dialogs,editor,options,main,ngen,nconvert,add,config,consts,web}.py`
- Modify: `tests/test_bridge_reentrancy.py` (add the image_occlusion modules to its K-114 roster)
- Test: `tests/test_image_occlusion_rules.py`

**Interfaces:**
- Produces:
  - `dialogs.io_ask(parent, text, on_answer: Callable[[bool], None], title: str = "") -> QMessageBox` (window-modal, `open()`), replacing `ioAskUser`.
  - `dialogs.io_info(...)` and `dialogs.io_critical(...)`: same arguments as today, non-blocking (`open()`).
  - `editor.ImgOccEdit.parent_window` (was `self.parent`).
  - `options.ImgOccOpts.parent_window` (was `self.parent`).

- [ ] **Step 1: Write the failing tests.** The AST checks over every `image_occlusion/*.py` are:
  - no banned call from Global Constraints;
  - no `Attribute(attr="parent")` assignment;
  - no assignment to `Reviewer._showAnswer` and no `wrap(` import from `anki.hooks`;
  - no `mw.col.conf` subscript;
  - no `addHook`/`remHook`;
  - web asset URLs read `/_addons/klausmate/image_occlusion/web/`.

  Behaviour checks:
  - `io_ask` calls `on_answer(True)` / `on_answer(False)` from the box's `finished` signal (drive with real offscreen Qt, answer by `done()`).
  - The ngen delete-confirm path (ngen.py ~397) and the nconvert confirm path (~253) continue only via the callback.
  - `ImgOccEdit` close-with-changes asks through `io_ask` and closes only on True.
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement.**
  - Turn each blocking ask into a callback continuation: split the function at the ask and move the remainder into the callback.
  - Rename the `self.parent` attributes.
  - Replace the reviewer scroll wrap with two hooks:
    - capture the scroll position in the `card_will_show` filter when `kind == "reviewAnswer"` (it runs before the answer renders);
    - restore it in `reviewer_did_show_answer`.

    Both run only when `card.note_type()["name"] == IO_MODEL_NAME`. Test both, including that a non-IO card is left alone.
  - Replace legacy hooks with `gui_hooks` (`profile_will_close`, `browser_menus_did_init`).
  - Make `config.py` read/write `col.get_config("imgocc")` / `col.set_config("imgocc", …)`, keeping the same dict and the version-upgrade logic.
  - Set `MODULE_ADDON` URLs to `klausmate/image_occlusion`.
- [ ] **Step 4: Run the new test, `test_bridge_reentrancy`, and the full suite. PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 1/3: the port follows Klaus rules (window-modal asks, hooks, no parent shadow)".

### Task 3: Wire it in — setup, conflict guard, menus, web exports, model

**Files:**
- Modify: `klausmate/image_occlusion/__init__.py` (add `setup()`)
- Modify: `klausmate/image_occlusion/main.py` (`setup_main` → called by `setup`; menu labels)
- Modify: `klausmate/__init__.py` (one `image_occlusion.setup()` call at bootstrap; the widened `setWebExports` regex)
- Docs: `CLAUDE.md` / `AGENTS.md` module map lines for `image_occlusion/`
- Test: `tests/test_image_occlusion_setup.py`, plus `tests/fixtures/io/` (a 400×300 PNG, an `-O.svg` with two masks with ids `abc-ao-1`/`abc-ao-2`, and the expected `-Q`/`-A` SVGs for both modes, generated once by running the Task 1 verbatim `ngen` and committed)

**Interfaces:**
- Produces:
  - `image_occlusion.setup() -> bool`: False when the conflict guard trips.
  - `image_occlusion.CONFLICT_ADDON = "1374772155"`.
  - `image_occlusion.occlude(editor, image_path: str, initial_svg: str | None = None) -> bool`. This builds `ImgOccAdd(editor, "addcards" if editor.addMode else "editcurrent")` and calls `.occlude(image_path, initial_svg)`.
  - `ImgOccAdd.occlude(image_path=None, initial_svg=None)`: `initial_svg` adds svg-edit's `url` query item in add mode, the same way edit mode passes `omask`.

- [ ] **Step 1: Write the failing tests.**
  - With a fake `mw.addonManager` reporting `1374772155` enabled, `setup()` returns False, registers no `gui_hooks` callback and no menu action, and shows exactly the conflict tooltip.
  - Disabled or absent: `setup()` returns True and registers `editor_did_init_buttons`, `editor_will_show_context_menu`, `editor_did_load_note`, `profile_did_open` and `state_shortcuts_will_change`.
  - The `setWebExports` regex, read with `ast` from `klausmate/__init__.py`, fullmatches:
    - `web/x.css`
    - `user_files/backgrounds/A.JPG`
    - `image_occlusion/web/editor.js`
    - `image_occlusion/excalidraw/index.html`

    and does not match `image_occlusion/svg-edit/editor/svg-editor.html`.
  - The model is created once when missing; an existing model with the same name is returned untouched (fields and templates equal before and after).
  - **Review Focus 1:** `IoGenHideAllRevealOne` and `IoGenHideOneRevealAll` on the fixture produce `-Q`/`-A` SVGs equal to the committed expected files. `updateNotes` on a fixture note set whose masks keep ids `abc-ao-1`/`abc-ao-2` updates those two notes and adds none (stub collection).
  - `occlude(editor, png, initial_svg)` passes a `url=` query item pointing at `initial_svg` while `initTool=rect` (add mode).
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement**, then update the module map docs. Stage `__init__.py`, CLAUDE.md and AGENTS.md around foreign hunks.
- [ ] **Step 4: Run them, plus the full suite. PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 1/3: built into Klaus (guarded against the separate add-on)".

Board: move card 1 to Review. The live checklist goes on the card:
- draw, add and review in both modes
- edit a pre-port note
- options
- Browse conversion
- with single-window on, click into an occlusion field with no crash

## Phase 2 — card "Image Occlusion 2/3: occlude from the reader"

### Task 4: "Occlude this page / region"

**Files:**
- Modify: `klausmate/web/pdfjs_viewer.html` (context menu items; reuse `copyRegionImage`'s render to post `occlude-image`)
- Modify: `klausmate/pdfjs_viewer.py` (`_bridge_occlude_image`; an `on_occlude` hook)
- Modify: `klausmate/reader_panel.py` (wire `on_occlude` → `image_occlusion.occlude(self._editor, …)`)
- Test: `tests/test_reader_occlude.py`

**Interfaces:**
- Consumes: `image_occlusion.occlude` (Task 3).
- Produces:
  - Bridge action `occlude-image` with base64 JSON `{png: <b64>, page: int (0-based), region: bool}`.
  - `PdfJsViewer.on_occlude: Callable[[bytes, int, bool], None] | None`.
  - `reader_panel.occlude_media_stem(safe: str, page0: int, region: bool) -> str`, returning `f"{safe}-p{page0+1}"` plus `"-region"` when `region`.

- [ ] **Step 1: Write the failing tests.**
  - `occlude_media_stem("Heme", 4, False) == "Heme-p5"` and `occlude_media_stem("Heme", 4, True) == "Heme-p5-region"`.
  - `_bridge_occlude_image` decodes the payload and calls `on_occlude(png_bytes, 4, True)`.
  - A bad payload, non-PNG bytes, or empty bytes give a tooltip and no call.
  - With `_editor is None`:
    - the page source's menu builder marks both items disabled with the no-editor tooltip (source/AST pin on the html);
    - `PdfSidebar`'s handler shows the tooltip and never calls `occlude`.
  - With a fake editor, the handler writes `<tmp>/<stem>.png` and calls `occlude(editor, path, None)`.
  - **Review Focus 2:** a stub `col.media.add_file` returns `Heme-p5-1.png` for the second call, and the note's image field references the returned name. This exercises IOE's own media add path with a stub collection.
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement.**
  - Show "Occlude this page" always.
  - Show "Occlude this region" only while `state.persistMarquee` stands.
  - Both render at the same scale `copyRegionImage` uses.
  - Pass `editor_present` into the page whenever `_editor` changes (`klausSetOcclusionEnabled(bool)`).
- [ ] **Step 4: Run the tests, `test_pdfjs_viewer`, and the full suite. PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 2/3: occlude a page or region from the PDF reader".

## Phase 3 — card "Image Occlusion 3/3: Excalidraw diagrams"

### Task 5: Offline Excalidraw bundle (go/no-go)

**Files:**
- Create: `scripts/build_excalidraw.sh`
  - npm install into a temp dir: `@excalidraw/excalidraw@0.18.1`, plus the `react`, `react-dom` and `esbuild` versions it peers with, pinned exactly in the script.
  - Bundle `entry.jsx` as an IIFE.
  - Copy fonts.
- Create: `klausmate/image_occlusion/excalidraw/` containing:
  - `index.html`
  - `excalidraw.js`
  - `excalidraw.css`
  - `fonts/`
  - `LICENSE-excalidraw.txt` (MIT)
  - `entry.jsx`
- Test: `tests/test_excalidraw_bundle.py`

**Interfaces:**
- Produces a page API, `window.klausExcalidraw`:
  - `load(sceneJson: string | null)`
  - `exportForOcclusion() -> Promise<string>`. It resolves to JSON `{png: b64, scene: <excalidraw scene JSON>, originX, originY, width, height}`.
    - `origin` is the `getCommonBounds` min x/y of non-deleted elements.
    - The PNG is from `exportToBlob` with `exportPadding: 20` and `getDimensions` giving scale 2.
  - The page sends `pycmd("klausexcal:<action>:<b64 json>")` for actions `ready`, `occlude` and `cancel`.

- [ ] **Step 1: Write the failing test.**
  - The files exist.
  - `index.html` and the bundle contain no `http://` or `https://` URL to a non-local origin. Scan them; allow `xmlns` and licence-comment URLs.
  - `EXCALIDRAW_ASSET_PATH` points at `/_addons/klausmate/image_occlusion/excalidraw/`.
  - The bundle is under 8 MB, and the actual size is printed.
- [ ] **Step 2: Run it. Expect FAIL.**
- [ ] **Step 3: Implement and build.** Run `bash scripts/build_excalidraw.sh` and record the bundle size in the commit message.
- [ ] **Step 4: Go/no-go, live.**
  1. Load the page in Anki through `/_addons/klausmate/image_occlusion/excalidraw/index.html`.
  2. Draw a box with text, with the network off.
  3. Call `exportForOcclusion()`.
  4. Confirm the PNG shows the hand-drawn font and that `originX`/`originY` are numbers.

  If fonts or export fail offline, STOP and report BLOCKED with the console output. Don't work around it with a CDN.
- [ ] **Step 5: Run the test and the full suite. PASS.**
- [ ] **Step 6: Commit** "Image Occlusion 3/3: vendored offline Excalidraw (0.18.1) bundle".

### Task 6: Label masks from a scene (pure)

**Files:**
- Create: `klausmate/image_occlusion/excal_masks.py`. It must import nothing from `aqt`, so it is testable headless.
- Test: `tests/test_excal_masks.py` and `tests/fixtures/io/flowchart.excalidraw`. The fixture holds:
  - two rectangles with bound text
  - one free text
  - one deleted text
  - one whitespace-only text
  - one two-line text
  - one text with `angle = 0.5`

**Interfaces:**
- Produces:
  - `label_rects(scene: dict, origin_x: float, origin_y: float, padding: float = 20, scale: float = 2, margin: float = 4) -> list[tuple[str, float, float, float, float]]`. Each tuple is `(element_id, x, y, w, h)` in image px, in scene element order.
  - `masks_svg(width: int, height: int, rects: list[tuple[str, float, float, float, float]], fill: str, stroke: str) -> str`. This is IOE's omask format: an empty Labels group, then a Masks group with one `<rect>` per entry, no `id`, and 5-decimal numbers like IOE's.

- [ ] **Step 1: Write the failing tests, using the fixture with `origin=(0,0)`, padding 20 and scale 2.**
  - **Free text** at x=100, y=50, w=80, h=25 gives `(id, (100-0+20)*2-4, (50-0+20)*2-4, 80*2+8, 25*2+8) == (id, 236, 136, 168, 58)`.
  - **Text bound inside a shape** uses the text element's own box, not the container's.
  - **Deleted and whitespace-only text** are skipped.
  - **Two-line text** gives one rect (Review Focus 3).
  - **Non-ASCII text**, `"Hämoglobin β"`, gives one rect.
  - **`angle=0.5`** gives the axis-aligned bounding box of the rotated rectangle.
  - **A scene with no text** gives `[]`.
  - **`masks_svg(400, 300, rects, "#FFEBA2", "#2D2D2D")`** parses as XML, has `width="400" height="300"`, and has a Masks group with `len(rects)` rects carrying those fill/stroke values.
- [ ] **Step 2: Run them. Expect FAIL. Step 3: Implement. Step 4: PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 3/3: label masks from an Excalidraw scene".

### Task 7: "Draw a diagram…" → a Draw tab in the occlusion editor

Amended 2026-10-01 (Pouya chose Option A of `docs/reference/excalidraw-in-image-occlusion.md`: Excalidraw native to the occlusion tool, no separate window, no web-app chrome). See the spec's "A Draw tab in the occlusion editor".

**Files:**
- Create: `klausmate/image_occlusion/excal_tab.py`
  - `DrawTab(QWidget)`: an `AnkiWebView` on the Excalidraw page, with a Qt "Use drawing" button below it.
  - `prepare_occlusion` and `blank_png`.
- Modify: `klausmate/image_occlusion/excalidraw/entry.jsx` and `index.html`, then rebuild with `scripts/build_excalidraw.sh` (network for npm only).
  - Drop the in-page Occlude/Cancel buttons (`renderTopRightUI`).
  - Render a `<MainMenu>` child with no items, so the default menu, with its GitHub/X/Discord links, never renders.
  - Expose `klausExcalidraw.occlude()`, the page's existing export-then-`send("occlude", …)` path.
  - CSS in `index.html` hides `.main-menu-trigger`, `.sidebar-trigger` (library) and `.help-icon`.
- Modify: `klausmate/image_occlusion/editor.py` / `add.py`
  - `ImgOccEdit` gains an optional third tab "&Draw", shown only for draw sessions.
  - `ImgOccAdd` gains `use_drawing(result)`, which goes through the change-image path.
  - Add buttons are disabled until a drawing is used.
- Modify: `klausmate/image_occlusion/__init__.py`. `occlude(editor, image_path=None, initial_svg=None, draw=False)`: with `draw=True`, the image is `blank_png()` and the editor opens on the Draw tab.
- Modify: `klausmate/image_occlusion/main.py`. The editor button opens a `QMenu` with "Choose image…" (IOE's existing picker) and "Draw a diagram…".
- Modify: `klausmate/web/pdfjs_viewer.html` and `reader_panel.py`. Add "Draw a diagram…" to the reader's occlusion items, with the same no-editor rule as Task 4.
- Add: `klausmate/image_occlusion/svg-edit/LICENSE-svg-edit.txt`, the MIT text that is owed (research note §5), listed in `UPSTREAM.md`.
- Test: `tests/test_excal_flow.py`

**Interfaces:**
- Consumes:
  - `label_rects`, `masks_svg` (Task 6)
  - the page API (Task 5): `load(sceneJson|null)`; the `ready`/`occlude` pycmds `klausexcal:<action>:<b64 json>`; `occlude` carries a result whose `scene` is an object, or `{error}`
  - `image_occlusion.occlude` (Task 3)
- Produces:
  - `DrawTab(parent, on_use: Callable[[dict], None])`, with `.load(scene: dict | None)` (it waits for `ready` before calling the page) and `.use()` (the button: it calls `klausExcalidraw.occlude()`).
    - A result with `error` gives a tooltip and stays on the tab.
    - The tab's webview never opens a new window or the system browser: `createWindow` returns None, and navigation off the `/_addons/` page is refused.
    - Its accent colour and UI font come from `klausmate.theme`, injected as `.excalidraw` CSS variables at load.
  - `blank_png(tmpdir) -> str`: an 800×600 white PNG.
  - `excal_tab.prepare_occlusion(result: dict, tmpdir: str, fill: str, stroke: str) -> tuple[str, str, str]`, returning `(png_path, svg_path, sidecar_json)`.
    - The PNG is named `diagram-%Y%m%d-%H%M%S.png`.
    - The sidecar is JSON `{"type": "excalidraw", …scene…, "klaus": {"originX", "originY", "padding": 20, "scale": 2}}`. It is written to media as `_<image media name>.excalidraw` (R19) after the notes are added.
  - `ImgOccAdd.use_drawing(result: dict) -> bool`. It takes these steps:
    1. `prepare_occlusion`.
    2. svg-edit `setBackground`/`setResolution` to the new PNG.
    3. Load the mask SVG; masks are replaced, and Task 8 makes this keep hand masks.
    4. Set `self.image_path`.
    5. Enable the Add buttons.
    6. Switch to the Masks Editor tab.

- [ ] **Step 1: Write the failing tests.**
  - `prepare_occlusion` on a fixture result writes a real PNG, writes an SVG whose rects equal `label_rects(...)`, and returns a sidecar carrying `klaus.originX/originY`.
  - **An empty scene, or an `{error}` result:** tooltip, no files written, the Draw tab stays current.
  - **An oversized PNG** (dimensions above IOE's limit): tooltip, no media written, the image unchanged (Review Focus 3).
  - `occlude(editor, draw=True)` opens `ImgOccEdit` with three tabs, the Draw tab current, and the Add buttons disabled. `occlude(editor, path)` without `draw` has the original two tabs.
  - `use_drawing` on a stub dialog:
    - evals `setBackground`/`setResolution` with the new PNG's URL and size;
    - loads masks equal to `masks_svg(...)`;
    - sets `image_path`, enables Add, and selects tab 0.
  - **After IOE adds the notes**, the sidecar is added to media under `_<returned image name>.excalidraw`. The test hooks the IOE add-success path with a stub collection.
  - **Closing the editor window or `profile_will_close` mid-draw** (Review Focus 4): no media is touched and `on_use` is never called.
  - **Page chrome:** the rebuilt bundle no longer contains `klaus-actions`. `index.html` hides `.main-menu-trigger`, `.sidebar-trigger` and `.help-icon`. `DrawTab`'s webview `createWindow` returns None.
  - **The editor button menu** offers exactly "Choose image…" and "Draw a diagram…". Build it offscreen and read the action texts; don't trigger them.
  - `tests/test_excalidraw_bundle.py` stays green after the rebuild.
- [ ] **Step 2: Run them. Expect FAIL. Step 3: Implement (rebuild the bundle). Step 4: Run them plus the full suite. PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 3/3: draw a diagram on the occlusion editor's Draw tab; labels become masks".

### Task 8: Re-edit a diagram — keep hand masks, keep note ids

**Files:**
- Modify: `klausmate/image_occlusion/excal_masks.py` (add `remap_masks`)
- Modify: `klausmate/image_occlusion/editor.py` / `add.py`
  - In `ImgOccEdit` edit mode, show Task 7's Draw tab, loaded with the saved scene, only when `_<image>.excalidraw` exists in media and parses. The Masks Editor stays the current tab.
  - "Use drawing" (edit mode, and a repeat use in add mode) goes through `use_drawing` with the remapped SVG (`remap_masks`) instead of a plain replace.
- Docs: the `CLAUDE.md` image_occlusion entry (Excalidraw, the sidecar, re-edit)
- Test: `tests/test_excal_reedit.py`

**Interfaces:**
- Produces: `remap_masks(old_svg: str, old_scene: dict, old_meta: dict, new_scene: dict, new_meta: dict, new_w: int, new_h: int) -> str`. It works in four steps:
  1. An old mask is "label" when its rect has IoU ≥ 0.8 with an old `label_rects` entry. That entry's element id is the key; every other mask is "hand".
  2. Each new label rect reuses the `id` of the old label mask with the same element id, or gets no id if it is new.
  3. Hand masks shift by `((old.originX − new.originX)·scale, (old.originY − new.originY)·scale)`. A hand mask is dropped if it now lies outside `0..new_w` × `0..new_h`.
  4. The output is IOE's omask format.

- [ ] **Step 1: Write the failing tests.**
  - **Unchanged scene:** the output masks equal the input (ids kept).
  - **Label text edited:** its mask keeps its id, and the geometry follows the new box.
  - **Label deleted:** its mask is gone.
  - **Element added to the left** (origin x −50; Review Focus 5): hand masks move +100 px in x, and label masks still match their labels.
  - **Hand mask outside the new bounds:** dropped.
  - **Sidecar missing or invalid JSON:** the Draw tab is not shown in edit mode. Check the predicate function `has_diagram(media_dir, image_name) -> bool`.
- [ ] **Step 2: Run them. Expect FAIL. Step 3: Implement. Step 4: Run them plus the full suite. PASS.**
- [ ] **Step 5: Commit** "Image Occlusion 3/3: re-edit a diagram on the Draw tab; note ids and hand masks survive".

Board: move card 3 to Review. The live checklist goes on the card:
- draw a flowchart, check the auto-masks, add, and review on desktop and on a phone after sync
- edit the note, change a label on its Draw tab, "Use drawing", and update
- occlude a page and a region from the reader
