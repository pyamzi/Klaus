# klausbook board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### KB-001: Bundle klaus-pdf as a built-in extension
owner: -
priority: P1
tags: fork
created: 2026-08-24

Launch Klausbook without --extensionDevelopmentPath: wire extensions/klaus-pdf into the fork's dev/build extension set so it loads like a shipped extension. Keep the fork patch minimal.

### KB-002: Port klausmate annotation model: JSON source of truth + bake
owner: -
priority: P1
created: 2026-08-24

Highlights + per-slide side notes stored as JSON sidecars in Klausbook's own user_data; bake writes them into the PDF as real annotations from a pristine original (klausmate pdf_handler.bake_annotations model, vendored pypdf). Never incremental; empty JSON = restore.

### KB-004: klaus-core: pdf_index.py chunking + /search endpoint
owner: -
priority: P2
created: 2026-08-24

Remainder of the original KB-004 after slicing out the embeddings.py port (see the new embeddings card — this depends on it landing first, since /search needs both the embedding client and the chunk/index storage). Port klausmate/pdf_index.py's chunking + packed-array index storage, and expose GET /search over chunks of all PDFs in the library.

### KB-005: Anki bridge: slim klausmate addon serving HTTP
owner: -
priority: P2
created: 2026-08-24

Endpoints Klausbook needs from a running Anki: FSRS retrievability per card, batch note snapshots (id, mod, flds), undoable deck copy. Evolved from klausmate, not AnkiConnect.

### KB-006: Retention scores in the Library view
owner: -
priority: P2
created: 2026-08-24

Per-PDF retention/study-priority in the tree view (description text), klausmate retention.py model: max-cosine card matches x FSRS retrievability via the bridge.

### KB-007: Chat assistant in klaus-core
owner: -
priority: P2
created: 2026-08-24

Agent endpoint with tools: search_library, read_page (image+text+notes), get_retention, show_html. Multimodal model (Claude default) answers questions about PDF images without OCR. UI panel card follows separately.

### KB-008: Notes: Markdown folder + PDF deep links
owner: -
priority: P2
created: 2026-08-24

User-owned notes folder (plain .md, native VS Code editing) with links to PDF page/region that open the viewer at that spot.

### KB-009: Retention-driven podcast pipeline
owner: -
priority: P3
created: 2026-08-24

Async job in core: select what you're about to forget (FSRS via bridge) -> script -> TTS, provider-pluggable like embeddings. The signature feature; needs bridge + retention first.

### KB-010: Packaging: product build + core sidecar
owner: -
priority: P3
created: 2026-08-24

Signed app build of the fork; klaus-core bundled via PyInstaller and supervised by the app; port 7863 token hardening.

### KB-011: Theme PDF viewer with --vscode-* variables
owner: -
priority: P3
tags: sonnet-safe
created: 2026-08-24

viewer.css uses a fixed dark palette; key it off --vscode-editor-background/-foreground etc. so all themes work.

#### Comments
- [2026-09-17 orchestrator] Direction change (2026-09-17): the design north star for BOTH KlausBook and klausmate is Obsidian (dark-first, sidebar-driven, one accent family) — not the Quiet Clinic palette. First pass landed on the impress-editor branch: viewer.css now ships Obsidian dark+light tokens keyed off vscode-light. Remaining scope of this card: bind to --vscode-* variables / user themes where sensible.

### KB-012: klausmate: re-skin library + viewer to the Obsidian look
owner: -
priority: P2
tags: design,needs-human
files: klausmate/theme.py,DESIGN.md,tests/test_theme.py,docs/reference/design-tokens.json
created: 2026-09-17

Pouya wants klausmate (inside Anki) and KlausBook to look almost identical, with Obsidian as the shared north star (dark-first, sidebar file-tree feel, quiet chrome, one accent family). klausmate's Quiet Clinic palette (KlausMate-Context/DESIGN.md) keeps its token discipline but the palette direction is superseded. This is addon-side work in the klausmate repo: theme.py palette swap + DESIGN.md rewrite + test_theme.py scale updates. Coordinate tokens with KlausBook's extensions/klaus-pdf/webview-src/viewer.css so the two stay in lockstep.

#### Comments
- [2026-09-18 orchestrator] Shared tokens file landed 2026-09-18: docs/reference/design-tokens.json (canonical here, byte-identical copy at the same path in KlausMate-Context — run scripts/check-token-sync.sh after editing either). This card's job is now literal: make theme.py's palette() emit tokens.colors.{dark,light} exactly, rewrite DESIGN.md's frontmatter to match, and update test_theme.py's scale checks to the new hex values. HIGHLIGHT_INKS is already synced and now has a real test (tests/test_theme.py 'design-tokens.json sync' section) instead of being two independent hand-copies.

### KB-015: Sticky notes on highlights
owner: -
priority: P3
tags: parity
created: 2026-09-17

Per-highlight notes per parity spec: Add note.../Edit note... via context menu, box anchored top-right of first rect, rgba(255,245,170,235) fill, 1px rgb(190,170,80) border, rgb(70,60,20) 10px text, <=180px wide, <=4 lines, radius 3. Distinct from the per-slide notes sidebar.

### KB-018: Persistent state vs the Klaus voice in the editor
owner: -
priority: P3
tags: design
created: 2026-09-17

Raised by review on PR #2 (KB-016). The parity spec says every piece of feedback is a transient toast prefixed "Klaus: ", never inline text. Three places still speak inline, all of them persistent state rather than feedback: NotesSidebar's save status ("Saving…" / "Saved" / "Save failed"), its "Notes unavailable: {error}", and the stage's "Opening {name}…" / "Could not open {name}: {error}" panels. A 2.2s toast would lose a condition that should stay on screen, so KB-016 narrowed the invariant in toast.ts instead of rerouting them. Decide the rule: does persistent state get the Klaus prefix and a quiet inline treatment, or stay voiceless? klausmate's own answer is worth checking first - its degraded states have exact copy (see docs/reference/klausmate-viewer-parity.md, "Voice") and are inline, which suggests inline is right and only the wording needs aligning. Needs a decision before anyone edits NotesSidebar.tsx.

### KB-019: Confirm the editor's Cmd shortcuts survive the workbench
owner: -
priority: P2
tags: parity,needs-human
created: 2026-09-17

KB-016 and KB-014 shipped keyboard parity that cannot be verified headless: VS Code binds Cmd+= / Cmd+- / Cmd+0 (workbench zoom) and Cmd+F at the workbench level, and whether the webview's preventDefault wins is only observable in a running window. Static evidence so far: createWebviewPanel in extensions/klaus-pdf/src/extension.ts never sets enableFindWidget, so VS Code's own find widget is off for this panel and Cmd+F should reach the webview; the zoom keys have no such argument either way.

Check in a running Klausbook window, with a PDF open on the stage: Cmd+= / Cmd+- step the slide by 1.25x with no shell zoom; Cmd+0 fits; Cmd+F opens the Klaus find strip and not VS Code's; Cmd+A selects only the slide's text; Cmd+Alt+G focuses the page field; double- and triple-click select a word and a paragraph on the slide. If any key is swallowed by the workbench, the fix is a keybinding contribution in package.json with a 'when' clause scoped to the webview - not more preventDefault.

## Ready

## Doing

### KB-013: Context menu parity in the PDF editor
owner: worker-kb013
priority: P2
tags: parity
files: extensions/klaus-pdf/webview-src/ContextMenu.tsx,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/highlights.ts,extensions/klaus-pdf/webview-src/notesStore.ts,extensions/klaus-pdf/webview-src/viewer.css,tests/highlights_test.mjs
verify: node --test tests/highlights_test.mjs tests/shortcuts_test.mjs && python3 tests/test_notes.py && (cd extensions/klaus-pdf && npx tsc --noEmit)
created: 2026-09-17
claimed: 2026-09-18

Per docs/reference/klausmate-viewer-parity.md's 'Context menu (exact order)' section. Scope, deliberately narrowed to what's buildable without new infrastructure (see Out of scope below):

Menu, right-click on the stage (not the filmstrip): Copy · Highlight · [ink swatch row: five klausmate inks, klicking recolors the highlight under the cursor if any] · Remove Highlight · ─── · Zoom In (Cmd+=) · Zoom Out (Cmd+-) · Actual Size (Cmd+0).

Acceptance criteria:
1. Right-click on the stage opens a floating menu at the cursor (16px shadow per parity spec's sanctioned exception), closes on Escape / click-outside / an item firing.
2. 'Copy' disabled when there is no live selection, else copies selected text (execCommand or Clipboard API) and closes the menu.
3. 'Highlight' disabled when there is no live selection; when enabled, does exactly what Cmd+Shift+H already does (reuse ImpressView's highlightSelection, do not duplicate it).
4. Right-clicking ON an existing highlight (hit-test its rects) enables 'Remove Highlight' and shows the five-ink swatch row (klausmate's HIGHLIGHT_INKS via highlights.ts) with the highlight's current ink marked selected; clicking a swatch updates that highlight's color in place. Right-clicking elsewhere disables both and hides the swatch row.
5. 'Remove Highlight' deletes the highlight from the notes store (new notesStore.removeHighlight / updateHighlightColor, alongside the existing addHighlight) and re-renders without it.
6. Zoom In / Zoom Out / Actual Size call the same handlers the toolbar buttons already use (reuse, do not duplicate the zoom ladder in shortcuts.ts).
7. Items disable rather than disappear (parity spec rule) — verify by right-clicking with no selection and confirming Copy/Highlight render greyed-out, not absent.

Out of scope (do not attempt): 'Copy Selection as Image' / 'Copy Page Text' / 'Copy Slide as Image' (klausmate's marquee-select and page-image-capture do not exist in KlausBook yet); 'Add note…/Edit note…' (KB-015, sticky notes, not built yet). Leave these out of the menu entirely rather than adding disabled placeholders for unbuilt features.

## Review

## Done

### KB-016: Shortcut + toast parity in the PDF editor
owner: orchestrator
priority: P2
tags: parity,sonnet-safe
files: extensions/klaus-pdf/webview-src/shortcuts.ts,extensions/klaus-pdf/webview-src/toast.ts,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/viewer.css,tests/shortcuts_test.mjs
verify: node --test tests/shortcuts_test.mjs && cd extensions/klaus-pdf && npm run typecheck
created: 2026-09-17
claimed: 2026-09-17

Per docs/reference/klausmate-viewer-parity.md, bring the editor's keyboard and feedback behavior up to klausmate's.

Behavior:
- Cmd/Ctrl+= and Cmd/Ctrl++ zoom in x1.25, Cmd/Ctrl+- zooms out /1.25, clamped 0.25-5.0. The toolbar buttons use the same step and clamp (today they are x1.2 / 0.1-6).
- Cmd/Ctrl+0 fits the slide to the stage.
- Cmd/Ctrl+A selects the current slide's text layer; with no text on the page, toast "Klaus: no selectable text on this page" and change nothing.
- Cmd/Ctrl+Alt+G focuses an inline page field in the toolbar; the page label is click-to-edit too. Out-of-range or non-numeric input is refused with a toast and leaves the slide unchanged. No native dialog: a webview has no prompt(), and the voice rule forbids modals.
- PageUp/PageDown/Home/End keep working; nothing above fires while focus is in the notes textarea or the page field.
- Double-click selects a word, triple-click a paragraph, on the slide text layer.
- Every piece of feedback goes through one transient toast, each message prefixed "Klaus: ", auto-dismissed, never a modal and never inline text.

Acceptance criteria:
- Shortcut matching, the zoom ladder and page-number parsing live in a pure module with no React/DOM imports, so the gate needs no browser.
- tests/shortcuts_test.mjs asserts: the zoom step is exactly 1.25 and clamps at 0.25 and 5.0 from both directions; each shortcut in the table maps to its action for both Cmd and Ctrl; a plain key or a typing target yields no action; page parsing rejects "", "abc", "0" and n+1 while accepting "1" and n.
- npm run typecheck in extensions/klaus-pdf is clean.
- The verify command fails on the pre-card tree (the module and test do not exist) and passes after.

#### Comments
- [2026-09-17 orchestrator] Implemented on branch kb-016-shortcuts (b5212f5, branched off impress-editor so it carries the unmerged Obsidian retheme dbc6544). verify exits 0 (5 node:test cases + tsc --noEmit); it exited 1 on the pre-card tree. node build.mjs bundles clean. Divergence from the card, deliberate: Cmd+Alt+G focuses an inline page field in the toolbar instead of klausmate's getInt dialog - a webview has no prompt() and the voice rule forbids modals; the page indicator became the field, format '{n} / {total}' kept. Double/triple-click selection is native pdf.js text-layer behaviour and nothing in viewer.css blocks it - not machine-verified. NEEDS A REAL-WINDOW CHECK before Done: VS Code binds Cmd+= / Cmd+- / Cmd+0 at the workbench level, so confirm the webview's preventDefault wins and the shell does not also zoom.
- [2026-09-17 orchestrator] PR #2 open: https://github.com/pyamzi/KlausBook-Context/pull/2 (1 commit, based on the merged retheme). Stays in Review until the real-window shortcut check.
- [2026-09-17 orchestrator] PR #2 review addressed in ca8d776: fitScale now goes through clampZoom so Cmd+0 and the initial/resize fits cannot leave the 0.25-5.0 ladder; the page field sizes from the digit count of doc.numPages (content-box) instead of a fixed 3ch that clipped at 1000+ pages; toast.ts's 'only feedback channel' claim narrowed to transient feedback, with KB-018 filed for whether persistent state (notes save status, loading/error panels) adopts the Klaus voice. Three threads replied to and resolved. Gate still green; kb-016-shortcuts merged forward into kb-014-find-bar so PR #3 carries the fixes.
- [2026-09-17 orchestrator] Merged: PR #2 -> main (6b4e371). Signed off by Pouya. The in-app shortcut check moved to KB-019 rather than being dropped.

### KB-014: Find bar (Cmd+F) in the PDF editor
owner: orchestrator
priority: P2
tags: parity
files: extensions/klaus-pdf/webview-src/find.ts,extensions/klaus-pdf/webview-src/FindBar.tsx,extensions/klaus-pdf/webview-src/shortcuts.ts,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/viewer.css,tests/find_test.mjs,tests/shortcuts_test.mjs
verify: node --test tests/find_test.mjs tests/shortcuts_test.mjs && cd extensions/klaus-pdf && npm run typecheck
created: 2026-09-17
claimed: 2026-09-17

Top strip in the PDF editor per docs/reference/klausmate-viewer-parity.md, "Find bar".

Behavior:
- Cmd/Ctrl+F reveals the bar, focuses the input and selects what is in it. Esc hides it, clears the search and returns focus to the slide.
- Input placeholder "Find in PDF…" with a clear button. Live search debounced 250ms.
- Count label is exactly one of: "" (empty query) / "0 matches" / "{i+1} of {count}" / "{count} matches" (a query with matches but no current one).
- Prev (‹, Shift+Enter) and next (›, Enter) cycle with wraparound. Cmd/Ctrl+G and Cmd/Ctrl+Shift+G do the same from anywhere, and are a silent no-op while the bar is hidden.
- Search spans the whole document over pdf.js text content, not just the visible slide; selecting a match navigates to its page.
- The current match is highlighted in the slide's text layer via the CSS Custom Highlight API - no DOM mutation - and degrades to plain navigation where unsupported, per the repo's None-guard house style.
- The bar hides and clears when the document changes.

Note: this card extends shortcuts.ts, which KB-016 owns and which is in Review. Cmd+Shift+G currently asserts as "no action" in tests/shortcuts_test.mjs; this card flips that assertion to "find-prev" and must keep the rest of that gate green. Branch from kb-016-shortcuts (PR #2) so the two do not conflict.

Acceptance criteria:
- Match finding, count-label formatting and index cycling live in a pure module (no React, no DOM), so the gate needs no browser.
- tests/find_test.mjs asserts: case-insensitive matching with per-page positions over a fake two-page document; overlapping-candidate and zero-match queries; the four count-label forms verbatim; cycling next/prev wraps at both ends; an empty or whitespace query yields no matches and the empty label.
- tests/shortcuts_test.mjs still passes with find shortcuts added, and Cmd+Shift+H stays unclaimed for KB-003.
- npm run typecheck in extensions/klaus-pdf is clean.

#### Comments
- [2026-09-17 orchestrator] Implemented on kb-014-find-bar (7d87e12), PR #3 stacked on PR #2 (it extends shortcuts.ts and updates KB-016's gate; retarget to main once #2 lands). verify exits 0 (9 node:test cases + tsc), exited 1 before. Two deliberate calls, both narrower than the card: (1) a fresh query selects no match - the label reads '{n} matches' until Enter/Cmd+G moves to one, so live typing never yanks the stage, and all four label forms stay reachable; (2) the current match is shown by selecting its range in the text layer (which already tints ::selection) rather than via the CSS Custom Highlight API - no new API, no extra CSS, and it degrades to plain navigation when offsets do not map. NEEDS A REAL-WINDOW CHECK: whether VS Code passes Cmd+F to the webview instead of opening its own find widget; also the 250ms debounce and the offset mapping onto the rendered text layer.
- [2026-09-17 orchestrator] PR #3 review addressed in d64b523; 7 threads replied to and resolved. Five distinct findings, all real: (1) case folding is not length-preserving ('Istanbul'-style dotted capital I lowercases to two UTF-16 units), so folded offsets selected the wrong characters - find.ts now folds per code point with a map back to the original string and reports original-text offsets, with a regression test that fails on the old code; (2) the 120ms reveal delay raced PdfPage's async render, so a match on a slow page navigated but was never selected - a MutationObserver waits for that page's text layer with a 4s give-up; (3) that fix exposed a worse bug of mine - the reveal effect runs before the slide swap commits, so an unpinned '.textLayer' matched the page being LEFT, which is populated, and would have selected against the wrong text; the query is now pinned to [data-page]; (4) Enter/Cmd+G inside the 250ms debounce acted on the previous query's matches - cycling flushes the pending search first; (5) Esc only worked from the input, and the glyph buttons had no accessible names. Gate now 10 cases, green. Still unverified in a window: whether VS Code passes Cmd+F through (enableFindWidget is unset, which suggests yes).
- [2026-09-17 orchestrator] Merged: PR #3 -> main (d8f5bc1), retargeted from kb-016-shortcuts once #2 landed. Signed off by Pouya. Gate green on merged main (10 cases) and the bundle builds. In-app Cmd+F check is KB-019.

### KB-017: Fix stale repo paths (library default + README run commands)
owner: fable
priority: P1
tags: sonnet-safe
files: core/klaus_core/library.py,README.md,context/PROJECT.md,context/prompts/worker.md,context/prompts/designer.md
verify: python3 -c "import sys; sys.path.insert(0,'core'); from klaus_core import library; ps=library.list_pdfs(); assert ps, 'library empty with default paths'; print(len(ps),'pdfs')" && ! grep -rn 'Github/klausbook\|klausbook-code' README.md context/
created: 2026-09-17
claimed: 2026-09-17

The session fixing these was deleted before landing. (1) core/klaus_core/library.py DEFAULT_USER_FILES still points at ~/Documents/Github/Addons/klausmate/user_files which no longer exists — the real library is ~/Documents/Github/KlausMate-Context/klausmate/user_files ({pdfs,pdf_originals}); without KLAUS_LIBRARY_DIR the app lists an empty library. (2) README.md Run/Architecture sections still say klausbook-code / ../klausbook — should be KlausBook-Code / KlausBook-Context. Also sweep context/PROJECT.md and context/prompts/*.md for the same stale paths. Verify: curl -s -H 'X-Klaus-Token: dev' localhost:7863/library lists 5 PDFs with no env override; python3 tests/test_notes.py passes.

#### Comments
- [2026-09-17 orchestrator] Same rename fallout hit core/.venv: script shebangs pointed at the old klausbook/ path (bad interpreter). Rebuilt 2026-09-17; card's README sweep should add a note that any repo rename requires rm -rf core/.venv + recreate.
- [2026-09-17 fable] Decisions: library default -> ~/Documents/Github/KlausMate-Context/klausmate/user_files (both dirs, pdfs/ still shadows pdf_originals/); docs sweep ordered longest-prefix-first so klausbook-code didn't collide with klausbook. Files: core/klaus_core/library.py, README.md, context/PROJECT.md, context/prompts/worker.md, context/prompts/designer.md. Risks: none — gate asserts 5 pdfs on defaults and zero stale refs; both suites pass. Next: none.
- [2026-09-17 orchestrator] Sign-off: gate green (5 pdfs on defaults, no stale refs), suites pass. Done.

### KB-003: Highlight flow: selection -> Cmd+Shift+H, stored + rendered
owner: fable
priority: P1
tags: parity
files: extensions/klaus-pdf/webview-src/highlights.ts,extensions/klaus-pdf/webview-src/notesStore.ts,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/NotesSidebar.tsx,extensions/klaus-pdf/webview-src/PdfPage.tsx,extensions/klaus-pdf/webview-src/core.ts,extensions/klaus-pdf/webview-src/shortcuts.ts,extensions/klaus-pdf/webview-src/viewer.css,tests/highlights_test.mjs,tests/shortcuts_test.mjs,core/klaus_core/notes.py,tests/test_notes.py
verify: node --test tests/highlights_test.mjs tests/shortcuts_test.mjs && python3 tests/test_notes.py && (cd extensions/klaus-pdf && npx tsc --noEmit)
created: 2026-08-24
claimed: 2026-09-17

Per docs/reference/klausmate-viewer-parity.md. Acceptance: (1) selecting text on the stage and pressing Cmd+Shift+H or Cmd+Shift+A creates a highlight on the current slide - default ink #FADC50 painted at alpha 110/255, square corners, rendered between canvas and text layer; (2) no selection -> toast 'Klaus: select text first, then highlight'; after create the selection clears and 'Klaus: highlight added' toasts; (3) records {id, rects:[[x,y,w,h]...] in scale-1 page coords, color} persist in the notes doc under top-level highlights.{page}, validated server-side, one save pipeline shared with notes (doc state lifted to a notesStore hook - no second writer); (4) highlights survive reload and re-project across zoom. Out of scope: delete + ink picker (KB-013 context menu), sticky notes (KB-015), bake (KB-002).

#### Comments
- [2026-09-17 orchestrator] Spec landed: docs/reference/klausmate-viewer-parity.md (full inventory of klausmate's viewer with exact colors/strings/shortcuts). This card's scope is now the highlight flow: selection -> Cmd+Shift+H / context-menu Highlight, five inks (#FADC50 default, #8AE08C, #7FC6F2, #F79AC8, #F7B267) at 43% alpha, one record per page, stored in the klaus-core notes doc. Sliced follow-ups: KB-013 context menu, KB-014 find bar, KB-015 sticky notes, KB-016 shortcuts+toasts.
- [2026-09-17 fable] Decisions: doc ownership lifted into notesStore.ts (useNotesDoc) so notes + highlights share ONE serialized save pipeline - no second writer; highlight geometry is a pure module (highlights.ts) node-tested like shortcuts.ts; rects stored scale-1 page coords, clipped/deduped/sliver-dropped. Files: highlights.ts, notesStore.ts, ImpressView.tsx, NotesSidebar.tsx, PdfPage.tsx, core.ts, shortcuts.ts, viewer.css, tests/highlights_test.mjs, tests/shortcuts_test.mjs, core/klaus_core/notes.py, tests/test_notes.py. Risks: none known - E2E verified in browser harness (create at rgba(250,220,80,0.43), both toasts, selection clears, server persists, survives reload, re-projects across zoom). Next: delete + ink picker are KB-013; sticky notes KB-015; bake reads highlights from this store (KB-002).
- [2026-09-17 orchestrator] Sign-off: gate green (12 node + 28 py checks, tsc clean), E2E verified incl. reload + zoom re-projection. Done.

### KB-020: klaus-core: port embeddings.py (OpenAI provider, aqt-free)
owner: worker-kb020
priority: P2
tags: sonnet-safe
files: core/klaus_core/embeddings.py,tests/test_embeddings.py
verify: python3 tests/test_embeddings.py
created: 2026-09-18
claimed: 2026-09-18

Slice of KB-004 (first real seam — see grooming note there). Port klausmate/embeddings.py verbatim-in-spirit into core/klaus_core/embeddings.py: OpenAIEmbeddings class, normalize(), embed_batches(), index_signature()/signature_matches(), EmbeddingError. Source is aqt-free and stdlib-only already (confirmed 2026-09-18: only imports math/threading/array/typing at module level; the actual HTTP call is injected, not imported at top) — port its shape faithfully rather than redesigning it. It needs an HTTP call to OpenAI's embeddings endpoint (see klausmate/openai_client.py's embed() function, ~line 101, stdlib urllib — port only what embeddings.py actually calls, not the whole file's transcribe() half).

Acceptance criteria:
1. core/klaus_core/embeddings.py exports the same public shape as klausmate's version (OpenAIEmbeddings, normalize, embed_batches, index_signature, signature_matches, EmbeddingError) with klaus-core's existing conventions (from __future__ import annotations, no aqt/PyQt import anywhere).
2. API key comes from an env var (KLAUS_OPENAI_KEY or similar — pick one and document it in the module docstring), not hardcoded, not required to be set for the module to import cleanly.
3. embed_batches() produces unit-normalized vectors (dot product = cosine similarity) — port normalize()'s exact math, don't reimplement.
4. Tests use a fake/injected HTTP layer (mirror the GetConfig-callable pattern already in the source — do NOT make real network calls in tests).
5. No new third-party dependency — stdlib urllib only, matching the source.

Explicitly out of scope (separate seams, do not attempt): pdf_index.py's chunking/packed-array storage, the /search HTTP endpoint, wiring this into app.py. KB-004 (edited) now covers only that remainder, depends on this card.

#### Comments
- [2026-09-18 worker-kb020] Decisions: ported OpenAIEmbeddings/normalize()/embed_batches()/index_signature()/signature_matches()/EmbeddingError from klausmate/embeddings.py, plus the embed() HTTP call from klausmate/openai_client.py, inlined into one module since file scope is just embeddings.py+test (no separate openai_client.py). Dropped the Klaus Plus (plus.py) branch and multi-provider DEFAULT_MODELS dict as out of scope/nonexistent in klaus-core — OpenAI is the only provider here, matching KB-020's acceptance criteria. API key env var: KLAUS_OPENAI_KEY (read in default_config(), unset is valid at import and only errors on .embed() with status=401). HTTP call uses a module-level _urlopen = urllib.request.urlopen alias (same seam openai_client.py used) so tests monkeypatch it instead of hitting the network; GetConfig stays a plain injected callable per the source's pattern. Files: core/klaus_core/embeddings.py (new), tests/test_embeddings.py (new). Risks: check the one-retry-on-429/5xx logic in _post_json and the dimensions-gating in _dimensions_for (DIMENSION_CAPABLE_MODELS) hardest — both are faithful ports of openai_client._request/embed but now live inlined in this file, so a future openai_client.py upstream change won't auto-sync here. Next: KB-004 wires this into app.py/an endpoint and covers pdf_index.py chunking — not attempted here, out of scope.
- [2026-09-18 orchestrator] Sign-off: verified independently, not just the worker's self-report — re-ran python3 tests/test_embeddings.py (0 failures), AST-scanned embeddings.py to confirm stdlib-only imports, re-ran test_notes.py/test_board.py to confirm no regression, and diffed the port against klausmate/embeddings.py + openai_client.py line-by-line. normalize()/embed_batches()/index_signature()/signature_matches() are faithful ports; the Klaus-Plus branch (plus.active/patch_config/alternate endpoints) was correctly dropped as out of scope rather than half-ported; API key is env-var only, never logged. One note for later, not filed as a card: the HTTP retry logic (_post_json) is now a second copy of openai_client.py's _request — if klausmate's retry/backoff behavior changes, this port won't follow automatically. Done.
