# KlausBook

A Tauri rewrite of Anki: spaced-repetition flashcards (priority), a PDF annotator with lecture recorder, and a Markdown/LaTeX editor. Reference apps live in `references/` (gitignored): leed_pdf_viewer, openwhispr, siyuan, zed.

## Develop

Anki is a pinned git submodule at `vendor/anki` (ADR-0001); its crates are path dependencies. Prerequisites: Rust (toolchain pinned in `rust-toolchain.toml`), Node 22, `protoc` (`brew install protobuf`).

```sh
git submodule update --init
git -C vendor/anki submodule update --init --depth 1 ftl/core-repo ftl/qt-repo
npm install
npm run tauri dev               # build frontend + run the app
cargo test -p klaus-bridge      # the one automated seam
npm run check                   # typecheck the frontend
npx tauri build --bundles app && ditto target/release/bundle/macos/Klaus.app /Applications/Klaus.app   # install the app
```

- `crates/bridge`: the Backend Bridge. Serves the frontend and Anki's `/_anki/<method>` contract from 127.0.0.1; only methods in its allowlist are callable from the webview.
- `src-tauri`: the Tauri shell. Opens the Collection in the app data dir and points the window at the bridge.
- `src/`: SvelteKit frontend (assets under `/_klaus`). `@generated` is Anki's TS library, generated into `vendor/anki/out/ts/lib/generated` by `npm run gen`.
- Anki's own pages (import, deck options, graphs, …) are built from `vendor/anki/ts` by `scripts/build-anki-pages.sh` (Anki's pinned yarn; skipped when already built for the current Anki commit) and served by the bridge at their Anki routes plus `/_app`. Requests those pages make to their Qt host go to the shell as hooks (native dialogs, navigation) or are answered by the bridge (profile settings in `klaus-settings.json` beside the Collection, pasted-image conversion). `static/anki-host.js` stands in for Qt's `bridgeCommand`/`pycmd` and is injected, with `anki-host.css`, into every Anki page; media files are served at the page-relative URLs Anki pages use. Tauri's macOS webview has no `alert()`/`confirm()` UI, so `static/native-dialogs.js` (loaded first on Klaus's and Anki's pages) routes them to the shell's `showMessageBox`/`askUser` with a synchronous request; Klaus's own screens use in-page `<dialog>`s for input instead of `prompt()`. Deck options' save (`updateDeckConfigs`) returns at once and runs in the background, as in Anki, then fires `deckOptionsRequireClose` (or `showMessageBox` on failure).
- Debug builds print a `Klaus dev URL` with the session token, so a browser can drive the same pages. `KLAUS_DATA_DIR=<dir>` (a scratch Collection) and `KLAUS_OPEN=<page>` (e.g. `review?deck=1`) are honoured in debug builds only.
- Review (`src/routes/review`): Klaus's screen owns queue, grading and undo; cards render in a sandboxed (opaque-origin) frame, `static/card.html` + `static/card-host.js`, running Anki's reviewer JS from `/_anki/js` (built into `vendor/anki/out/klaus` by `build-anki-pages.sh`). The frame can't reach `/_anki`, only `postMessage` the review screen, which accepts a fixed command set. Card HTML is assembled by the bridge's `klausRenderCard` (`crates/bridge/proto/klaus.proto`).
- Browser (`src/routes/browse`): Anki's Qt browser rebuilt on the backend's browser rows (`searchCards`/`searchNotes`, `browserRowForId` for the columns set by `setActiveBrowserColumns`, Anki's config keys for columns, sort and notes mode). The side editor is Anki's editor page in `mode=browser`, framed by the browser (only the editor's CSP allows same-origin framing); embedded, `anki-host.js` forwards its bridge commands and an `updateNotes` completion (`noteUpdated`, by watching `fetch` for `/_anki/updateNotes`: recheck on Anki upgrades) to the page. Preview reuses the review card frame (`src/lib/card.ts`).
- The UI reaches the Collection and host only through `/_anki` (ADR-0006), so app.klaus.ink can later serve it against a server bridge: no Tauri API calls in Svelte.
- Logo: `static/klaus-logo.svg` is the brand master (also the favicon). `src-tauri/icons/icon.svg` places it on the macOS icon grid; regenerate the icon set with `npx tauri icon src-tauri/icons/icon.svg -o src-tauri/icons`.
- Upgrading Anki: check out a new release tag in `vendor/anki`, re-copy its `rust-toolchain.toml`, match the `typescript` and `@bufbuild/*` versions in `package.json` to `vendor/anki/yarn.lock` (Anki's `post.ts` must type-check unmodified), and run the tests.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `pyamzi/KlausBook-Context` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
