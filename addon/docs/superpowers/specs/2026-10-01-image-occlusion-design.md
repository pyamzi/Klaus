# Image Occlusion in Klaus — design

Date: 2026-10-01. Approved in conversation (approach 1, sections 1–4).
Status: implemented and shipped; kept as a historical record. The code is the source of truth, and paths use the old package name `klausmate` (now `klaus_note`).

## Goal

Image Occlusion Enhanced (IOE, Glutanimate, v1.4.0, AGPL-3, installed as add-on `1374772155`) becomes a built-in klausmate feature, and the Klaus PDF reader gains "Occlude this page / region". Pouya chose a whole port over Anki's native Image Occlusion.

Success means:
- Every IOE feature works from klausmate: editor button and image context menu, the svg-edit mask editor, both modes (hide all / hide one), editing existing occlusion notes, the options window, the Browse note-conversion tool, review-time mask behaviour and its hotkey.
- Existing IOE notes, note types, settings and media keep working with no conversion.
- The separate add-on can be uninstalled afterwards.
- The reader can send a page or a selected region straight into the occlusion editor.
- You can draw a diagram in Excalidraw instead of uploading an image. Its text labels become masks automatically, the cards show on every Anki client, and the diagram stays editable on desktop.

## Constraints

- Licences: IOE and Klaus are both AGPL-3. Keep IOE's copyright headers and add its licence file next to the port.
- Keep the note type exactly: name `IO_MODEL_NAME` ("Image Occlusion Enhanced"), its fields (`IO_FLDS`: id, header, image, footer, remarks, sources, extra 1, extra 2, question mask, answer mask, original mask) and its templates. Never rename or migrate them.
- Keep settings storage exactly: synced settings in the collection config key `imgocc`, local ones in the profile key `imgocc`. Read and write the collection config through `col.get_config` / `col.set_config` on the same key.
- Klaus rules apply to the ported code:
  - No app-modal `exec()`, `askUser`, `askUserDialog`, `getText`, `QMessageBox.question` and the like (K-114). Use window-modal `open()` / `show()` plus signals. `QMenu.exec` is allowed.
  - No monkey-patches where a `gui_hooks` hook exists.
  - No instance attribute that shadows a Qt method. IOE's `self.parent = parent` breaks Klaus's single-window code (`'EmbeddedAddCards' object is not callable`).
  - Tests use temp dirs only and never touch `klausmate/user_files`.
- No network at runtime. The Excalidraw bundle is built once with a script kept in the repo (`scripts/build_excalidraw.sh`, esbuild with a pinned `@excalidraw/excalidraw` version) and committed as a static asset. Its size is recorded in the plan.
- Anki loads one web-exports pattern per add-on. Klaus's existing `setWebExports` regex is widened to cover the port's web assets and svg-edit. It is never called twice.

## Approach

**Port in place.** Copy IOE into `klausmate/image_occlusion/` close to verbatim, and change only what Klaus requires. The diff from upstream stays readable, and existing notes face the least risk. Rejected alternatives:
- A rewrite in Klaus idioms (several times the work, and every behaviour has to be re-proven).
- Loading IOE untouched as a nested add-on (the K-114 and `self.parent` problems stay).

## Architecture

- **`klausmate/image_occlusion/`** holds the ported modules: `add`, `editor`, `ngen`, `template`, `options`, `nconvert`, `dialogs`, `config`, `consts`, `utils`, `lang`, `web`, `main`, plus `_vendor/` (imagesize, imghdr), `web/`, `svg-edit/` and `icons/`.
  - Imports become package-relative.
  - `main.setup_main(mw)` becomes `image_occlusion.setup()`. `klausmate/__init__.py` calls it once at bootstrap.
- **Conflict guard.** If add-on `1374772155` is installed and enabled, `setup()` registers nothing and shows one tooltip: "Image Occlusion is now built into Klaus. Disable the separate Image Occlusion Enhanced add-on and restart Anki." The guard is checked before any hook, menu or note type work.
- **Menus.** "Image Occlusion Options…" goes under Klaus's existing Tools menu entries, and the help entry stays in Help. The add-on manager's config action for klausmate is untouched.
- **Reviewer.** The `Reviewer._showAnswer` wrap that keeps the scroll position becomes a `gui_hooks` pair: capture before the answer shows, restore after. It is scoped to IO note types only.
- **PDF reader entry point** (`reader_panel.py` plus `web/pdfjs_viewer.html`):
  - Two context-menu items: "Occlude this page", and "Occlude this region". The region item shows only while an Option-drag marquee stands.
  - The page renders the page or region to a PNG through the same path as copy-as-image (K-100) and sends it over the bridge.
  - Python writes it to a temp file and calls `ImgOccAdd(editor, "addcards"|"editcurrent").occlude(png_path)` on the reader's editor (`PdfSidebar._editor`).
  - The image's media name is `<pdf safe name>-p<page>.png`, with a region suffix when it is a region.

## Excalidraw diagrams (new)

Instead of picking an image, you can draw a diagram (a flowchart, say) in Excalidraw and occlude it. Every text label becomes a mask automatically.

- **Entry.** The occlusion entry points offer two sources: "Choose image…" (unchanged) and "Draw a diagram…" (new). These entry points are the editor button's image picker and the reader's menu.
- **A Draw tab in the occlusion editor (Pouya, 2026-10-01: "native to the image occlusion tool itself", not a web page).**
  - "Draw a diagram…" opens IOE's own occlusion editor (`ImgOccEdit`) on a blank white image and starts on a third tab, **Draw**, beside "Masks Editor" and "Fields". There is no separate window.
  - The Draw tab holds a webview running the vendored, prebuilt `@excalidraw/excalidraw` bundle (MIT, licence shipped beside it). It lives in `klausmate/image_occlusion/excalidraw/`, loads with no network, and is covered by the web-exports regex.
  - Excalidraw's web-app chrome is removed: no main menu, library, help or social links, and no Occlude/Cancel buttons in the page. Nothing in the tab can open the system browser. Its accent colour and UI font follow Klaus's theme.
  - Below the canvas, a Qt button **"Use drawing"** sits in the tab, like IOE's own Qt buttons.
  - The Draw tab appears only in sessions that need it: "Draw a diagram…", and edit mode on a note with a diagram (Re-edit below). Photo occlusions are unchanged.
  - Until a drawing has been used, the Masks Editor shows the blank image and the Add buttons are disabled, so no card is made from the blank placeholder.
- **On "Use drawing":**
  1. The scene is exported to a PNG at 2× scale with a fixed padding. A PNG is used rather than an SVG because it renders identically on every Anki client, with no Excalidraw fonts needed.
  2. For every text element in the scene, its bounding box is mapped into image pixels: `(x − sceneMinX + padding) × scale`. A few pixels of margin are added, and each box becomes one IOE mask rectangle.
     - Text bound inside a shape is masked as text, not as the whole shape, so the box outlines stay visible.
     - Empty or whitespace-only text is skipped.
  3. The same editor window swaps its image for the PNG (IOE's change-image path), loads the generated masks in IOE's own SVG mask format, and switches to the Masks Editor tab. You can add, delete or adjust masks, pick the mode, and press Add. From here everything is ordinary IOE.
  4. Going back to Draw, changing the drawing and pressing "Use drawing" again replaces the image; each label's mask follows its label, and labels new to the drawing get a mask. Masks you added by hand are kept where they still fall inside the new image (the Re-edit rule).
- **Seen on every device.**
  - Cards use only the PNG and IOE's mask SVGs, so AnkiMobile, AnkiDroid and AnkiWeb all show them.
  - The scene is also saved as `_<image name>.excalidraw` (JSON) in collection media (the leading `_` keeps Check Media from listing it as unused), so it syncs like any media file. Nothing in the card templates reads it.
- **Re-edit.**
  - On an occlusion note whose image has a matching `.excalidraw` file, the occlusion editor in edit mode shows the Draw tab, loaded with the saved scene.
  - On "Use drawing", the PNG is regenerated under a new media name (old notes keep the old image until they are updated) and each label's mask follows its label (keeping its id, so cards update in place). A label new to the drawing gets a mask; a label whose mask you resized, moved or deleted keeps what you left (Ruling R22).
  - Masks you added by hand are kept where they still fall inside the new image.
  - The notes then update the way IOE's normal edit flow updates them.
- **Errors.**
  - An empty drawing or a failed export gives a tooltip, writes nothing to media, and stays on the Draw tab.
  - A scene with no text opens the occlusion editor with no masks.
  - A missing or unreadable `.excalidraw` file hides the Draw tab. The note stays an ordinary image occlusion.

## Data flow

1. **Make notes (unchanged).** Editor button or image context menu → `ImgOccAdd.occlude` → image picked → `ImgOccEdit` (svg-edit in a webview) → masks drawn → Add → `ngen` (IoGenAO / IoGenOA) writes mask SVGs to media and adds notes to the editor's deck.
2. **Edit notes (unchanged).** The editor button on an IO note reopens `ImgOccEdit` with its stored masks. Edit then regenerates the masks and updates the notes.
3. **From the reader (new).** Menu item → PNG over the bridge → temp file → `occlude(path)` → step 1 from the editor window onward.
4. **Review (unchanged).** Templates and `reviewer.js` hide and reveal masks. The hint hotkey stays via `state_shortcuts_will_change`.

## Errors

- **Separate add-on enabled:** the port stays off, with the one tooltip above.
- **No editor attached to the reader:** the occlusion items are disabled, with the tooltip "Open Add or Edit to make an occlusion note".
- **Render fails, image empty, or over IOE's size limits:** a tooltip says why, nothing is written to media, and the editor doesn't open.
- **Profile closes while the occlusion editor is open:** it closes without saving, as IOE does today, via `profile_will_close`.
- **Prompts are all window-modal:**
  - discard unsaved masks
  - replace the image
  - "no masks drawn"
  - the options window
  - the conversion tool's confirm

## Testing

Headless tests, following the repo's anki_stubs harness:
- `ngen` output for both modes on a fixture SVG and image: mask files, the field contents, and the note count. Compare it with notes the original IOE built.
- The model is created once when missing, and an existing model is reused with its fields and templates byte-identical.
- Settings are read from and written to collection and profile `imgocc`, including the version upgrade path.
- The conflict guard registers no hooks when `1374772155` is enabled.
- The reader entry point: a real PNG reaches `occlude()` with the right media name, and the items are disabled when there is no editor.
- Pins: no banned modal call in `klausmate/image_occlusion/`, no `self.parent =` assignment, and no `Reviewer._showAnswer` wrap.
- Web exports cover `image_occlusion/web` and `image_occlusion/excalidraw`. svg-edit keeps loading from a `file://` URL, as IOE does today, so it needs no export.
- Excalidraw label masks, computed by a pure function with a test: a fixture scene gives the expected rectangles in image pixels for a given padding and scale. The cases are text inside a shape, free text, rotated-zero text, empty text skipped, and a scene with no text giving no masks.
- Excalidraw re-edit: the scene is saved next to the PNG, the Draw tab appears in edit mode only when it exists, and hand-added masks outside the new image bounds are dropped.

Live check by Pouya:
- Draw masks in svg-edit.
- Add in both modes and review.
- Edit an existing pre-port IOE note.
- Run options and the Browse conversion.
- Occlude a page and a region from the reader.
- Draw a flowchart in Excalidraw, check the auto-masks, add, then review on desktop and on a phone after sync.
- Edit the note, change a label on its Draw tab, "Use drawing", and update.
- Click into an occlusion field in single-window mode without a crash.

## Out of scope

- Restyling the occlusion editor to Klaus's theme.
- Replacing svg-edit.
- Converting IOE notes to Anki's native Image Occlusion.
