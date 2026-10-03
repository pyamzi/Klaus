# What would rebuilding Anki's editor, deck options and import in shadcn-svelte take, in the app and inside Anki?

Wayfinder research ticket [#52](https://github.com/pyamzi/klaus-note/issues/52), child of map #37. Written 2026-10-03. It feeds #53 (which pages, in what order, how the add-on hosts them) and #54 (how the three surfaces stay in step).

## Verdict

**Rebuild the chrome, keep the engine, and do it in this order: import, then deck options, then the editor. Keep image occlusion, graphs and card info on Anki's pages, restyled, for now.** Every page's backend surface is already inside the bridge's `/_anki` allowlist (two Qt-side post handlers are missing, below), so the app side is a UI job, not a backend job. The add-on side is feasible and cheap for import and deck options (swap the URL inside Anki's own dialog), and costly for the editor, because Anki ships two editors with two different Python-to-page protocols and add-ons are wired to both.

- **Import** (3 pages, 1.8k lines of Anki source): smallest, cleanest contract, no add-on hooks. Build it first to prove the shared package and the host interface.
- **Deck options** (33 components, 5.1k lines): forms, shadcn-svelte's home turf. Keep Anki's `lib.ts` state machine, rewrite the components. The add-on loses the deck-options extension API unless a shim is written.
- **Editor** (65 components plus 5k lines of shared editing code): rebuild the toolbar, field labels and badges, choosers, tag editor, history, context menu and action buttons. Do not rewrite contenteditable, paste, MathJax, the HTML filter or the cloze and surround logic: import them from Anki's `ts/` (same AGPL) and wrap them.
- **Keep restyled**: image occlusion (fabric.js canvas, 5.2k), graphs (d3, 5.2k; stats are headed for dashboard widgets under #18 anyway), card info (forgetting-curve d3), change notetype (until `changeNotetype` is in the bridge), congrats and preferences (Home and #19 replace them).
- **One package, built twice.** A single Svelte 5 package of pages plus a thin host interface, consumed by the app as source and shipped into the add-on as a static build under `web/`. Anki's `/_anki/<method>` contract is already what the bridge speaks, so the page code is the same in all three surfaces; only the host differs.

## Sources

Primary, read from the main checkout (the worktree's `vendor/anki` is an empty submodule):

- `klaus-note/app/vendor/anki` at commit `29bb700b`, `.version` **26.09.3**: `ts/routes/*`, `ts/lib/*`, `qt/aqt/{editor,editor_legacy,addcards,editcurrent,deckoptions,mediasrv,webview,main,browser/browser}.py`, `qt/aqt/import_export/*`, `qt/tools/genhooks_gui.py`, `proto/anki/config.proto`, `docs-site/addons/hooks-and-filters.mdx`, `package.json`.
- The installed Anki **26.09.2** (`/Applications/Anki.app/Contents/Resources/app_packages/aqt`, bytecode, read with `strings`), to check the shipped version has the same classes.
- The six add-ons installed on this Mac (`~/Library/Application Support/Anki2/addons21`): AMBOSS, AnkiHub, Image Occlusion Enhanced, AnkiCollab, SynapsePro, export-tag. Read as evidence of how real add-ons use the editor and deck options hooks.
- Klaus app: `crates/bridge/src/lib.rs`, `src-tauri/src/main.rs`, `static/anki-host.{js,css}`, `static/native-dialogs.js`, `scripts/build-anki-pages.sh`, `scripts/gen-ts.sh`, `src/routes/**`, `package.json`, ADR-0004 and ADR-0006.
- Klaus add-on (read only): `klaus_note/__init__.py`, `window_chrome.py`, `single_window.py`, `web/copilot.js`, `image_occlusion/`, `scripts/package.sh`.

## 1. What each page does that a rebuild must keep

### Editor (`ts/routes/editor`)

One Svelte component, `NoteEditor.svelte` (1,690 lines), is both the SvelteKit route (`mode` = `add`, `browser`, `current`) and, with `isLegacy = true`, the page of the legacy Qt editor. A rebuild must keep:

- **Field types.** Per field, a rich-text input (a `contenteditable` in an open shadow root, `RichTextInput.svelte`) and a plain-text HTML input (CodeMirror 5, `PlainTextInput.svelte`), each hideable with a badge; which one is the default comes from the notetype's `plainText` flag. Per-field notetype config: collapsed by default, description, font family and size, right-to-left, sticky.
- **Rich-text engine** (the part not to rewrite): `lib/editable` (1.5k: `ContentEditable`, `Mathjax`, `<anki-mathjax>` decorated elements, `FrameElement` and `FrameHandle` for images and MathJax), `lib/domlib` (1.7k: caret, surround, move-nodes), `lib/html-filter` (0.3k, what paste keeps), `editor/surround.ts` (formatting toggles), `rich-text-input/data-transfer.ts` (494 lines: paste and drop, image and audio files, `convertPastedImage`, clipboard formats, shift-paste inversion of `PASTE_STRIPS_FORMATTING`).
- **MathJax and LaTeX.** MathJax 3 rendering in fields, the MathJax overlay editor (`mathjax-overlay`, 0.5k), the LaTeX menu (`\(..\)`, `\[..\]`, `\ce{}`, `[latex]`), the per-collection `renderMathjax` switch.
- **Cloze.** Cloze notetypes show the cloze buttons (cloze deletion and the same-number variant), the page asks `getClozeFieldOrds`, `noteFieldsCheck` produces the "cloze outside a cloze notetype/field" hints and the "you have a cloze deletion note type but no cloze" confirmation on add.
- **Sticky fields** (add mode): badge per field, Shift+F9 toggles all, stored on the notetype (`updateNotetype`); the next note keeps sticky values and tags (`stickyFieldsFrom`).
- **Tag editor** (`lib/tag-editor`, 13 components, 1.7k): chips, drag, autocomplete through `completeTag`, collapse state in profile meta, Control+Shift+T.
- **Image occlusion** (`routes/image-occlusion`, 5.2k, fabric.js 5): the picker, the mask editor, `saveOcclusions` into the occlusion field, add and edit modes. It lives inside the editor page.
- **Paste handling, images, media**: image overlay (resize, shrink-by-default, float buttons, 0.45k), `addMediaFile`, `addMediaFromPath`, `addMediaFromUrl`, `extractMediaFiles`, `encodeIriPaths` and `decodeIriPaths` (media URLs round trip), attach file and record audio buttons.
- **Add-mode chrome**: notetype chooser and deck chooser (`defaultsForAdding`, `defaultDeckForNotetype`, `ADDING_DEFAULTS_TO_CURRENT_DECK`), duplicate highlighting (`noteFieldsCheck`), history modal of added notes (`htmlToTextLine`), Add and Close with a discard prompt (`closeAddCards`), toast on add.
- **Autosave**: per-field 600 ms `ChangeTimer`, save on blur, `saveNow` before close and on page hide, `updateNotes` in non-add modes. The new editor saves through `updateNotes` itself.
- **Toolbar**: bold, italic, underline, sub, super, remove format, text and highlight colour (last colours in profile config, custom palette through `getCustomColours`/`saveCustomColours`), lists, alignment, indent, notetype buttons (Fields, Cards, Preview), options, and an add-on button slot.
- **Context menu** (Svelte, in the new editor): paste, cut, copy, copy image, open image, show in folder.

### Deck options (`ts/routes/deck-options`)

- **Presets**: `ConfigSelector` (switch, add, clone, rename, remove, a used-by-decks count) and a Save menu with save-to-all-subdecks, per-deck assignment, "this deck / preset / today only" tabbed limits (`TabbedValue`).
- **Settings**: 14 `SpinBoxRow`, 10 `SpinBoxFloatRow`, 10 `EnumSelectorRow`, 16 `SwitchRow`, 2 `StepsInputRow`, 7 `ConfigInput`, 18 `Warning`, 54 `SettingTitle` (each with its help text) across daily limits, new cards, lapses, display order, burying, audio, timers, auto advance, easy days, advanced (maximum interval, starting ease, leech, custom scheduling JS in `CardStateCustomizer`).
- **FSRS** (`FsrsOptions.svelte` 520 lines, `SimulatorModal.svelte` 694, `ParamsInput`): enable switch, desired retention, parameters field, optimise (`computeFsrsParams`, progress from `latestProgress`, abort with `setWantsAbort`), evaluate (`evaluateParamsLegacy`), health check, `getRetentionWorkload`, the review and workload simulators (`simulateFsrsReview`, `simulateFsrsWorkload`, a d3 graph in `graphs/simulator.ts`), `computeOptimalRetention`, ignore-reviews-before date (`getIgnoredBeforeCount`), reschedule-on-change.
- **Save**: `updateDeckConfigs` with modes (normal, apply to children, compute all params). Anki's `update_deck_configs` closes the dialog on success unless it was "compute all". The page also asks before discarding unsaved changes.

### Import (`import-csv`, `import-anki-package`, `import-page`)

- **Formats** (from `qt/aqt/import_export/importing.py`): `.apkg` and `.zip` through the package page (`getImportAnkiPackagePresets`, `importAnkiPackage`: include reviews and scheduling, with deck configs, merge notetypes, update notes, update notetypes); `.csv`, `.tsv`, `.txt` through the CSV page (`getCsvMetadata`, `importCsv`: field separator, allow HTML, notetype, deck, existing-notes policy and match scope, tag all notes and tag updated notes, field and tags-column mapping with a preview); `.anki-json` and Mnemosyne `.db` through the log page (`importJsonFile`, `importJsonString`); `.colpkg` and `collection.apkg` replace the collection.
- **Log page** (`ImportLogPage`): one status per row (added, duplicate added, existing skipped, updated, skipped for notetype mismatch, missing notetype, missing deck or empty first field, failed), with a table per queue and a "search in browser" link (`searchInBrowser`).
- Two formats are not page work: `.colpkg` (a destructive replace, done in Python by `mw.backend.import_collection_package` after a backup and a collection unload) and Mnemosyne (`anki.foreign_data.mnemosyne.serialize`, Python only). Neither is in the bridge today.

### The other pages, for sizing

Change notetype (8 components) saves with `changeNotetype`; card info (7) reads `cardStats` and draws the forgetting curve; graphs (31) read `graphs` and the graph preferences; congrats (2) reads `congratsInfo`; preferences (2) reads and writes a few collection configs.

## 2. Backend methods, and the bridge allowlist

Method names collected from each route's imports of `@generated/backend` plus the profile helpers (`getProfileConfig`, `getMeta`, `getColConfig`, which go to `getProfileConfigJson`, `getMetaJson`, `getConfigJson`). The check against the bridge was done by script: Anki's `mediasrv.py` `exposed_backend_list` (54 methods) and `post_handler_list` (32 handlers) against the bridge's `ALLOWED`, `HOOKS` and `LOCAL` (85, 21 and 10 names).

| Page | Backend methods and host calls | In the bridge |
| --- | --- | --- |
| Editor | `getNote` `newNote` `addNote` `updateNotes` `noteFieldsCheck` `getNotetype` `updateNotetype` `getFieldNames` `getClozeFieldOrds` `defaultsForAdding` `defaultDeckForNotetype` `getConfigBool` `getCard` `htmlToTextLine` `encodeIriPaths` `decodeIriPaths` `addMediaFile` `addMediaFromPath` `addMediaFromUrl` `extractMediaFiles` `getAbsoluteMediaPath` `convertPastedImage` `completeTag` `getImageOcclusionFields` `getCustomColours`; hooks `askUser` `showMessageBox` `openFilePicker` `closeAddCards` `openFieldsDialog` `openCardsDialog` `openLink` `openMedia` `showInMediaFolder` `playFile` `recordAudio` `readClipboard` `writeClipboard` `saveCustomColours` `searchInBrowser` | All present, except **`closeEditCurrent`** (the editor's Close in `mode=current`; the app uses `add` and `browser` today, but #41's Study "Edit" chip needs it) |
| Image occlusion | `getImageForOcclusion` `addImageOcclusionNote` `getImageOcclusionNote` `updateImageOcclusionNote` `getImageOcclusionFields` `getCustomColours` `saveCustomColours` | All present |
| Deck options | `getDeckConfigsForUpdate` `updateDeckConfigs` `computeFsrsParams` `computeOptimalRetention` `evaluateParamsLegacy` `getIgnoredBeforeCount` `getRetentionWorkload` `simulateFsrsReview` `simulateFsrsWorkload` `setWantsAbort`; hooks `deckOptionsReady` `deckOptionsRequireClose` | All present; `updateDeckConfigs` is special-cased by `save_deck_configs`, not a passthrough |
| Import | `getCsvMetadata` `importCsv` `getImportAnkiPackagePresets` `importAnkiPackage` `importJsonFile` `importJsonString` `getDeckNames` `getNotetypeNames` `getFieldNames`; hooks `importDone` `importDialogRequireClose` `searchInBrowser` | All present. Not present and not page work: `importCollectionPackage` (colpkg), Mnemosyne |
| Change notetype | `getChangeNotetypeInfo` `getNotetypeNames` `changeNotetype` | **`changeNotetype` is missing**: the page loads but cannot save. In Anki it is a post handler that hands the page's `ChangeNotetypeRequest` to the Qt `ChangeNotetypeDialog.save`, which adds the note ids it holds, asks `confirm_schema_modification`, then runs the backend change-notetype operation; the bridge needs a hook that does the same |
| Graphs, card info, congrats, preferences | `graphs` `getGraphPreferences` `setGraphPreferences` `cardStats` `congratsInfo` `getConfigJson` `setConfigJson`; `browserSearch` pycmd | All present |
| Shared components | `getDeck` `getDeckNames` `getNotetype` `getNotetypeNames` `importDialogRequireClose` | All present |

Also not in the bridge and not needed by these pages: `getSchedulingStatesWithContext`, `setSchedulingStates` (reviewer only; Study has its own path).

**Hooks the bridge declares but `src-tauri/src/main.rs` leaves as a cancel**: `recordAudio`, `readClipboard`, `writeClipboard`, `playFile`, `openMedia`, `showInMediaFolder`, `openFieldsDialog`, `openCardsDialog`, `searchInBrowser`, `importDone`, `saveCustomColours`. The pages treat the empty reply as cancel. These are host features, not page work; a rebuild neither fixes nor worsens them, but the editor's attach-file (`openFilePicker`) works and audio recording and playback do not. A browser build (note.klaus.so) can implement most of them with web APIs (`MediaRecorder`, `navigator.clipboard`, `<input type=file>`), which ADR-0006 already anticipates.

**What Anki does by pycmd that the app ignores.** The editor sends `key:N`, `blur:N`, `focus:N`, `saved`, `editorState:new:old`, `ioImageLoaded`, `editorReady`. `anki-host.js` answers only `editorReady`, cut, copy and paste. In the Browser's iframe the same commands go to the parent by `postMessage` (`klausEditor`). Anki's `operation_did_execute` (the Python side telling pages that a backend operation changed notes or the notetype, so the editor reloads) has no equivalent in the app today except a wrapper around `fetch` for `updateNotes`; a single-page Svelte editor replaces it with a store.

## 3. How the app hosts Anki's pages today, and what a rebuild removes

- `scripts/build-anki-pages.sh` (34 lines) installs Anki's pinned yarn dependencies, builds the whole Anki SvelteKit app (`out/sveltekit`), and builds `out/klaus` (reviewer, MathJax, `webview.css`, `reviewer.css`) with Anki's esbuild and sass entry points.
- The bridge (`ANKI_PAGES`, `anki_page`, `anki_page_or_media`, about 150 lines of Rust) serves Anki's single `index.html` for eleven routes, strips SvelteKit's CSP meta tag, injects `anki-host.css`, `native-dialogs.js` and `anki-host.js` into `<head>`, and sets the page CSP Anki's mediasrv sets (the editor and image occlusion get a restricted `script-src`; the editor may be framed by Klaus's own pages).
- `static/anki-host.js` (85 lines) is the stand-in for Qt: `bridgeCommand`, `editorReady`, the `Escape` and `← Decks` link, the deck-options discard prompt, the embedded-editor `postMessage` protocol. `static/native-dialogs.js` (28) turns `alert` and `confirm` into synchronous hook calls because WKWebView has none. `static/anki-host.css` (22) is the #38 restyle.
- Today the app links to three of the eleven pages, the editor in two modes: `/editor/?mode=add` (Home), `/editor/?mode=browser` in an iframe (Browser), `/deck-options/<id>` (deck row menu), and `import-anki-package/<path>` (the shell's import action). Graphs, card info, change notetype, import CSV, import log, image occlusion (inside the editor), congrats and preferences are served but not reached from a screen.

**What replacing import, deck options and the editor in SvelteKit removes**: the `← Decks` link and its `MutationObserver` (a route has a back button), the `#night` hash plumbing for those pages (the app's own `dark:` variant follows the system), the host-side `deckOptionsReady` and `deckOptionsRequireClose` and `importDialogRequireClose` hooks, the iframe and `postMessage` protocol in the Browser (the editor becomes a component), the `html:root:root` restyle for these pages and the whole cascade trap from #38, and the editor's restricted-CSP route. **What it does not remove until every page is gone**: `build-anki-pages.sh` (the Anki SvelteKit build and its yarn install are needed for graphs, card info, image occlusion's engine, change notetype and the rest), `ANKI_PAGES` and `anki_page` for the pages that remain, `anki-host.js` and `native-dialogs.js` for the same pages. The `out/klaus` half of the build stays regardless: it is the reviewer's own bundle.

**What it needs from the app that exists**: the Svelte 5.56, Kit 2.70, Vite 6, `bits-ui` 2.19 and Tailwind 4 stack matches Anki's own (`svelte ^5.56.9`, Kit `^2.70.3`, Vite 6); `@generated/backend` and the `*_pb` types already come from Anki's generator through `scripts/gen-ts.sh` and `svelte.config.js`'s alias (the Browser and Home use them); the shadcn-svelte components for these pages mostly exist or are one `add` away (Field, Input, Select, Switch, Tabs, Accordion, Collapsible, Popover, Tooltip, Badge, Textarea, Progress, Alert, Toggle, Command for the tag autocomplete). The app has `button`, `checkbox`, `dialog`, `dropdown-menu`, `field`, `input`, `label`, `scroll-area`, `separator`, `sonner`, `table`, `toggle`, `toggle-group` today.

**One technical trap**: Anki's `ts/` imports through aliases `$lib`, `@tslib` and `@generated`. `$lib` is also SvelteKit's reserved alias in Klaus. Importing Anki's editing engine into the app therefore cannot be a plain path alias; it needs either a Vite resolve plugin that maps `$lib` by importer path, or a copy step that rewrites the aliases into a vendored package. Anki's components also mix legacy syntax (`export let`, `$:`, slots) with runes, so each is a dependency rather than a drop-in. Not tried.

## 4. Inside Anki: what the add-on can replace, and what other add-ons lose

### There are two editors, and the default is the old one

Anki 26.09 (source and installed bytecode both) ships two editors:

- `aqt.editor_legacy.Editor` (the default). Loads its page with **`stdHtml`** (`css/editor.css`, `js/mathjax.js`, `js/editor.js`), then `eval("setupEditor('add', true)")`. Python owns the saving: the page sends `key:ord:nid:html` and `blur:ord:nid:html` by pycmd, Python writes the note. Python evals about 16 setters at load (`setFields`, `setFonts`, `setCollapsed`, `setNotetypeMeta`, `setTags`, `setSticky`, …).
- `aqt.editor.NewEditor` (behind `ExperimentFlag.SVELTE_EDITOR`; `Collection.experiment_enabled` reads `experimentalFeatures` and defaults to False; Shift inverts it per open, in `main.py` and `browser/browser.py`). Loads the **SvelteKit** route with `load_sveltekit_page("editor/?mode=…")`. The page owns the saving through `updateNotes`; Python receives eight pycmds and calls `loadNote({...})`, `saveNow`, `reloadNote`. The class docstring is explicit that it relies on `operation_did_execute`.

The two fire different hooks. From the source:

| | `Editor` (legacy, default) | `NewEditor` |
| --- | --- | --- |
| Fired | `editor_did_init`, `editor_did_init_buttons`, `editor_did_init_left_buttons`, `editor_did_init_shortcuts`, `editor_did_load_note`, `editor_state_did_change`, `editor_mask_editor_did_load_image`, `editor_web_view_did_init`, and also: | the same eight |
| Only legacy | `editor_will_load_note` (filter on the JS string), `editor_will_munge_html`, `editor_did_unfocus_field`, `editor_did_focus_field`, `editor_did_fire_typing_timer`, `editor_did_update_tags`, `editor_did_paste`, `editor_will_process_mime`, `editor_will_show_context_menu`, `editor_will_use_font_for_field` | none of these |
| `webview_will_set_content` with the editor as context | fires (it is a `stdHtml` page) | **never fires** (`load_sveltekit_page` skips it; Anki's docs say the hook "will not work for external pages") |

Two consequences before any Klaus design choice:

1. **A Klaus editor that honours NewEditor's contract loses nothing beyond what Anki's own 26.09 editor already drops.** It loses the ten legacy-only hooks relative to the default editor, as Anki's own experiment does. AnkiHub registers `editor_will_load_note` and `editor_did_unfocus_field`; those do not run on Anki's own new editor either.
2. **The add-on's editor restyle (#42's "the editor gets the add-on's `editor_css`") only reaches the legacy editor today.** `window_chrome.py` and `__init__.py` inject on `webview_will_set_content` and gate on `isinstance(context, Editor)`; in 26.09 `aqt.editor.Editor` is the legacy class (`from aqt.editor_legacy import *`), and the new editor's `NewEditorWebView` never goes through `stdHtml`. On the NewEditor the add-on has to inject through `webview_did_inject_style_into_page` or an `eval`, as it already does for the Stats page.

### What the add-on can replace, mechanism by mechanism

**Deck options. Yes, cleanly.** `DeckOptionsDialog._setup_ui` does `self.web = AnkiWebView(kind=AnkiWebViewKind.DECK_OPTIONS)` then `self.web.load_sveltekit_page(f"deck-options/{deck_id}")`. Wrap or patch that one call (AnkiHub patches `DeckOptionsDialog.__init__` the same way; Anki's docs have a monkey-patching page) to `load_url(QUrl(f"{mw.serverURL()}_addons/klaus_note/web/pages/deck-options.html#<deck id>"))`. Keep the dialog class, because `deck_options_ready` and `deck_options_require_close` in `mediasrv.py` find the window with `isinstance(aqt.mw.app.activeModalWidget(), DeckOptionsDialog)`. The replacement page must keep Anki's page contract: POST `deckOptionsReady` once loaded (fires `deck_options_did_load`), define `window.anki.deckOptionsPendingChanges` (the dialog's `closeEvent` evals it; `anki-host.js` already mirrors this), POST `deckOptionsRequireClose` after a confirmed discard, and save with `updateDeckConfigs` (mediasrv closes the dialog on success unless the mode is "compute all"). If the page never posts `deckOptionsReady`, `_ready` stays False and the dialog closes without the unsaved-changes prompt.

**Import. Yes, cleanly.** `ImportDialog._setup_ui` does `load_sveltekit_page(f"{ts_page}/{quote(path)}")` for `import-csv`, `import-anki-package` and `import-page`. Contract: `importDone` (mediasrv makes the dialog non-modal), `importDialogRequireClose`, `searchInBrowser`, and `set_wants_abort` on reject. Same URL swap.

**Editor. Possible, with more strings attached.**
- On the **legacy path**, `webview_will_set_content` fires with the `Editor` as context and `web_content.js` and `.css` are mutable lists, so the add-on can replace `js/editor.js` with its own bundle and keep every Python hook, as long as the bundle implements the legacy page contract (`setupEditor`, the setters above, the `key/blur/focus/saveTags/toggleSticky/...` pycmds, `require("anki/ui")`).
- On the **NewEditor path**, patch `NewEditor.setupWeb` to `load_url` the add-on's page. The contract is smaller: pycmd `editorReady`, `focus:N`, `blur:N`, `saved`, `editorState:a:b`, `ioImageLoaded`; globals `loadNote`, `reloadNote`, `reloadNoteIfEmpty`, `saveNow`, `focusField`; `require("anki/ui").loaded`; the page saves through `/_anki/updateNotes`.
- Which editor appears is Anki's choice per window open. The add-on must either set `experimentalFeatures` for its users, or register its own classes under `AddCards` and `EditCurrent` in `aqt.dialogs._dialogs` and `Browser.setupEditor` (which also branches on the flag). **Recommend targeting NewEditor's contract**: smaller, matches the direction Anki is moving (the legacy modules are kept beside it), and the Klaus pages then work in the app and in Anki with the same save path.

**What other add-ons lose** (from the six installed add-ons on this Mac, by code reading; none was run against a replacement):

| Add-on | What it does | Effect of a replacement editor page |
| --- | --- | --- |
| AnkiHub | `editor_did_init_buttons`, `editor_did_load_note`, `editor_will_load_note`, `editor_did_unfocus_field`; `eval`s `require('anki/NoteEditor').instances[0].fields[i].element` to hide a field and count fields; `deck_options_did_load` plus `deck_options_dialog.web.eval(js)` to inject an FSRS revert button into Anki's deck options DOM | Buttons survive if the page renders the `AddonButtons` HTML strings; the `NoteEditor.instances[0]` API must be re-exposed; the FSRS revert button is injected into DOM that no longer exists, so it silently disappears unless the shim offers an equivalent slot |
| Image Occlusion Enhanced | `editor_did_init_buttons`, `editor_did_load_note`, `editor_will_show_context_menu` (legacy only), `web/editor.js` calling `require("anki/NoteEditor").instances[0].fields[...]` | Same `instances[0]` need. The add-on vendors its own copy of IOE (`image_occlusion/`), so Klaus users do not depend on the installed one |
| AnkiCollab | `editor_did_init_buttons` | Works if the HTML-string buttons are rendered |
| AMBOSS, SynapsePro | `editor.addButton(...)`, `webview_will_set_content` (a legacy-editor injection), SynapsePro also `editor_will_show_context_menu` | Buttons work if rendered; `webview_will_set_content` injections never reach a SvelteKit editor (same as Anki's own new editor) |
| export-tag | none | none |

The public JS surface add-ons can reach is the thirteen `registerPackage` names (`anki/NoteEditor`, `EditorField`, `PlainTextInput`, `RichTextInput`, `TemplateButtons`, `packages`, `bridgecommand`, `shortcuts`, `theme`, `location`, `surround`, `ui`, `reviewer`), the `editorToolbar` global and the `components` global (`IconButton`, `LabelButton`, `WithContext`, `WithState`, `contextKeys`). A Klaus editor can re-export compatible shapes for `ui`, `NoteEditor.instances`, `fields[i].element` and the toolbar's `append` and `appendButton`; it cannot honour add-ons that pass Anki's own Svelte component classes into the toolbar. Deck options has a smaller API (`addHtmlAddon(html, mounted)`, `addSvelteAddon(component)`, `auxData`, and the `components` map). An HTML add-on is easy to support; a Svelte add-on built against Anki's `SpinBoxRow` and `TitledContainer` is not.

The add-on's own editor dependencies would also need porting: `web/copilot.js` (field-focus tracking and image double-click crop; it reads `.fname`, `.field-name`, `[contenteditable]` and pierces the rich-text shadow DOM) and `theme.editor_css()`.

### Serving a built Svelte page from the add-on

- **`setWebExports(__name__, pattern)`** stores one regex per add-on (`self._webExports[addon] = pattern`; the last call wins) and mediasrv serves `/_addons/<pkg>/<sub path>` when `re.fullmatch(pattern, sub_path)`. The add-on's one call today allows `web/.*\.(css|js|ttf)`; the Svelte pages need `html`, `svg`, `woff2`, `json` added, still in that single string literal (the add-on's tests read the first literal).
- **No SPA fallback and no directory index** in `_handle_local_file_request`, so build one static HTML per page (Vite multi-page, or SvelteKit with `router.type = "hash"` and relative asset paths), not an adapter-static fallback.
- **It gets the bridge and the API key, by code reading.** `AnkiWebView._profileForPage` gives the profile with `AuthInterceptor(api_enabled=True)` to `DECK_OPTIONS`, `EDITOR`, `CHANGE_NOTETYPE`, `IMPORT_CSV`, `IMPORT_ANKI_PACKAGE`, `IMPORT_LOG` (among others) and the interceptor adds `Authorization: Bearer <key>` to every request to the server's origin, which `/_addons/` shares. `_check_dynamic_request_permissions` then accepts the POSTs (`Content-Type: application/binary` required). The QWebChannel bridge script is a profile user script, so `pycmd` works on any page in such a view. So the add-on creates or reuses an `AnkiWebView(kind=…)` and `load_url`s its page; nothing else is needed for the 54 exposed methods and the 32 post handlers. Not run against a live Anki.
- **No CSP on add-on exports.** `LocalFileRequest(untrusted=False)` for `/_addons/` sets no Content-Security-Policy, while Anki's own editor route is served with a restricted `script-src` precisely because field HTML can carry `<script>` and the page holds the API key. A Klaus editor page served from `/_addons/` must ship its own CSP meta tag (`script-src` limited to `'self'` and no inline handlers, `form-action 'none'`) or it is a security regression against Anki's own editor. The app has the same constraint: a rebuilt editor route must be served with the restricted CSP the bridge sets for `editor` today, or rendered inside a sandboxed frame like the Study card.
- **Version coupling.** The pages bundle the generated protobuf client (`@generated`, `@bufbuild/protobuf`) of one Anki version; the user runs another. The add-on already declares a supported range; deck options is the most exposed (FSRS parameter fields have changed names between releases: the page reads `fsrsParams6`). Whether protobuf-es keeps unknown fields on a read-modify-write of `DeckConfig` was not checked.
- **Build step.** The add-on has no Node build today; it already ships built, vendored assets with their own scripts (`build_excalidraw.sh`, `build_roughjs.sh`, pdf.js). A `scripts/build_pages.sh` that copies the shared package's `dist/` into `klaus_note/web/pages/` fits that pattern and keeps Node out of the `.ankiaddon`.

## 5. Size

Non-test source lines (Svelte, TS, SCSS) in `vendor/anki/ts` at 26.09.3, counted by script:

| Page | Svelte components | Files | Lines | Notes |
| --- | --- | --- | --- | --- |
| Editor route | 65 | 88 | 8,631 | `NoteEditor` 1,690; toolbar 1,988; rich-text 1,149; mathjax overlay 508; image overlay 450; plain-text 246 |
| Editor shared code | 15 | 60 | 5,179 | `lib/editable` 1,513, `lib/tag-editor` 1,716 (13 components), `lib/domlib` 1,675, `lib/html-filter` 275 |
| Image occlusion | 12 | 53 | 5,157 | fabric.js 5; 21 files import it |
| Deck options | 33 | 39 | 5,060 | `SimulatorModal` 694, `FsrsOptions` 520, `lib.ts` 476 |
| Import (csv + package + log) | 3 + 8 + 8 | 33 | 1,774 | 869 + 286 + 619 |
| Change notetype | 8 | 12 | 617 | |
| Card info | 7 | 11 | 1,094 | `forgetting-curve.ts` 354 |
| Graphs | 31 | 53 | 5,232 | d3 v7, 16 files use it |
| Congrats, preferences | 2 + 2 | 9 | 322 | |
| Shared components (`lib/components`) | 52 | 57 | 4,366 | Bootstrap-era button, select, modal, spinbox, switch: what shadcn replaces |

Rough rebuild size, an estimate not a measurement: import about 1k lines of new Svelte; deck options about 2.5k (components only, `lib.ts` and `choices.ts` kept, the simulator graph kept as a d3 module); editor chrome about 3k new Svelte plus about 5k lines of Anki engine imported rather than rewritten. A full rewrite of the editor engine would be 14k lines with the paste, IME and caret edge cases that the 494-line `data-transfer.ts` and the 1.7k-line `domlib` exist for. Not recommended.

## 6. What the app and the add-on can share

One Svelte 5 package, say `klaus-pages`, in the app repo (a workspace folder) or a third repo (decide under #54):

- **Pages** (import, deck options, editor, later change notetype and card info) built from shadcn-svelte components with the Klaus tokens. They call only `@generated/backend` over `POST /_anki/<method>`. That contract is already the bridge's and Anki's mediasrv's, with the same method names, so the page code does not change between surfaces.
- **A `Host` interface** for what differs: `askUser`, `showMessageBox`, `openFilePicker`, `openLink`, `closePage`, `bridgeCommand`, `readClipboard`, `recordAudio`, `playFile`. In Anki, almost every one is an existing mediasrv post handler the page can call directly. In the app they are the bridge's `HOOKS`; on the web they are browser APIs. The page code calls `host.*`; three small implementations differ.
- **Two build outputs**: the app imports the package as source (so Tailwind and tokens are the app's); the add-on gets a static multi-page build copied into `klaus_note/web/pages/`. Tokens come from #54's `tokens.json`, one source for both.
- What is **not** shared: the host implementations, the add-on's Python glue (URL swaps, the `NewEditor.setupWeb` patch, the compat shim for add-on hooks), and the app's route shell.

## 7. Recommendation, order, and what is interim

1. **Shared infrastructure first** (small): the package, the `Host` interface, a Vite multi-page build, `closeEditCurrent` and `changeNotetype` added to the bridge (the second as a hook that appends the note ids and confirms the schema change, as `ChangeNotetypeDialog.save` does), a CSP story for the editor route. Settle the `$lib` alias question by importing one Anki engine module end to end.
2. **Import** (page triple, ~1.8k source lines). Proves the pipeline in both surfaces: the app route and the add-on's `ImportDialog` URL swap. No add-on hook is lost.
3. **Deck options** (~5k source lines). The app first (Home's gear is a Milestone 1 screen); then the add-on's URL swap with the page contract above. Decide and write down: Anki's HTML add-on API is re-exposed in a minimal shim; AnkiHub's FSRS-revert injection is declared lost, or AnkiHub gets a documented slot.
4. **Editor** (the biggest). Rebuild the chrome on the imported engine, in the app first (Add, then the Browser's pane replacing the iframe, then Edit Current), then the add-on on **NewEditor's contract**. Image occlusion stays Anki's mask editor inside the new chrome until a later ticket.
5. **Keep Anki's pages, restyled with #38's variables** for image occlusion, graphs, card info, change notetype (until step 1's bridge fix; it is a small rebuild after), congrats and preferences. Graphs become dashboard widgets under #18; congrats is Home's overview; preferences is #19.

**Interim (for #53).** The `anki-host.css` restyle (#38) and the Browser's Anki-editor pane (#42) stand until each page's rebuild ships; each rebuild deletes that page's share of both. #42's statement about the add-on's `editor_css` is true only for the legacy editor and should say so. The restyle does nothing for deck options' Bootstrap-blue buttons (#38), so rebuilding deck options is the first place the Klaus look becomes visibly better than the variables-only restyle.

## 8. Risks

- **Two editors in Anki.** Targeting NewEditor leaves the default (legacy) users on a different code path than the pages the add-on was tested with unless the add-on controls the choice. If Anki removes the legacy modules, add-ons wired to their ten extra hooks break regardless of Klaus.
- **Keeping up with Anki.** Deck options and the editor gain options with Anki releases (new FSRS settings are the usual case). A rebuild is a permanent parity task; the deck-options page is the worst case. Churn per page could not be measured: `vendor/anki` is a shallow, single-commit checkout.
- **Security.** Field HTML can carry script. The rebuilt editor needs Anki's CSP in the app and its own CSP meta in the add-on; both are easy to get wrong.
- **Re-implementing the add-on compatibility shim.** `require("anki/NoteEditor").instances[0]`, the toolbar `append`, the HTML-string add-on buttons (`.linkb`, `perm`, `toggleEditorButton`) are small to write and silent to break.
- **AGPL.** Importing Anki's engine modules is fine under AGPL-3.0, but it is a fork of those files the day an alias rewrite or a patch is needed; the standing rule "never patch `vendor/anki`" implies a copy step with a diff check, not an in-place edit.

## Not verified

- No live run: not the app, not Anki. The add-on's ability to serve an HTML page from `/_addons/` into an `AnkiWebView(kind=DECK_OPTIONS)` and get the API key and `pycmd` is read from code only.
- The installed Anki is 26.09.2 and the checkout is 26.09.3. Class and handler names were checked in the installed bytecode (`NewEditor`, `NewAddCards`, `NewEditCurrent`, `editor_legacy`, `SVELTE_EDITOR`, `deck_options_did_load` in `deckoptions.pyc`, the mediasrv handler names, `_profileForPage`, `AuthInterceptor`). A `strings` check of `gui_hooks.pyc` for hook names returned nothing and is not evidence either way.
- Whether the add-on's users run the experimental editor was not checked. The flag is a per-collection config, off by default.
- Whether `@bufbuild/protobuf` keeps unknown fields through a deck-config read-modify-write across Anki versions.
- Bundle size and load time of the shared package in a QtWebEngine view.
- The `$lib` alias workaround and the amount of the legacy-syntax Anki components that import cleanly into Svelte 5 runes mode.
- Upstream churn per page (shallow checkout), and Anki's stated plans for removing the legacy editor.
- Line estimates for the rebuild are rough guesses from component counts, not from a prototype.
