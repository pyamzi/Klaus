# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

## Ready

### K-002: Visual polish pass: Manage models dialog and Klaus panel
owner: -
priority: P0
tags: design
files: klausmate/web/search.css, klausmate/web/search.html
verify: designer sign-off; screenshots attached to this card
created: 2026-08-23

Needs a design spec before any code. The Manage models dialog was reorganised by job (What Klaus uses / Local model library) but never got a visual pass. The Klaus panel still uses Bootstrap-era defaults.

Designer: write the spec into this card, then move it to Ready. Do not hand this to a worker un-specced.

### K-009: Make model setup for curation and embeddings understandable
owner: -
priority: P0
tags: design
files: 
verify: designer sign-off against the spec in this card
created: 2026-08-23

Pouya, on K-001: 'It's not easy to understand the model installation process for a curation or an embedded model.'

This is the second time this surface has been called confusing — the Manage models dialog was reorganised by job on 2026-08-23 for the same reason, and it clearly did not go far enough. The remaining gap is the install/provisioning path rather than the assignment path: what has to be downloaded, what it costs, what a key is for, and what happens if you skip it.

Designer: write the spec into this card before anyone touches code. Worth covering — what the user sees when no embedding model is installed and they press Index cards; whether Voyage-by-default is discoverable at all before it fails; how pulling a local embedding model is offered; and what distinguishes the Ask engine from the search provider in the user's mind, given both are 'models'.

Not sonnet-safe. Needs a spec first.

### K-001: Manual-verify PDF drive and deck-curate surfaces in live Anki
owner: -
priority: P0
tags: 
files: 
verify: human confirms each checklist item in Anki
created: 2026-08-23

Only a human can do this: it needs a running Anki with a real collection.

Checklist:
- Toolbar shows the PDFs link; it opens the drive window and re-raises on second click.
- Drive tree lists imported PDFs; folder create/move/rename and display-rename survive a restart.
- Double-click opens a PDF in the right pane with annotations intact.
- Retention columns populate; Embed runs with progress and can be cancelled; the threshold slider re-aggregates live.
- Deck browser shows the Curate Deck button; dropping a PDF imports and arms it without Anki's own importer opening.
- Curate at root offers the all-decks/specific chooser; inside a deck it scopes silently.

Report failures as new cards rather than fixing them here.

#### Comments
- [2026-08-23 Pouya] PDF viewer just doesn't work at all. It's not even opening. I can't figure out exactly how to. It's not easy to understand the model installation process for a curation or an embedded model, so that needs to be fixed as well.
- [2026-08-23 Pouya] PDF shows up at the top. It just doesn't open into anything, like it doesn't open a window or anything.

## Doing

## Review

## Done

### K-022: The PDFs button at the top still does not open anything.
owner: sonnet-p
priority: P1
tags: sonnet-safe
files: klausmate/pdf_drive.py
verify: grep -q 'self.show()' klausmate/pdf_drive.py && python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Pouya, after restarting Anki: the PDFs toolbar button still opens nothing. Root cause found by orchestrator code-reading, confirmed twice-over by prior evidence (K-008 ruled out import/setup errors; open_drive's except-with-showWarning never fired, so nothing raises):

DriveWindow NEVER SHOWS ITSELF. aqt.dialogs.open() constructs a new instance via the registered creator and stores it — it does not call show(); every Anki dialog calls self.show() in its own __init__ (see Browser/AddCards in the aqt source). So the click builds a complete window that stays invisible. The existing reopen() only helps a window that was shown once.

Fix, all in klausmate/pdf_drive.py:
1. End of DriveWindow.__init__ (after _restore_geometry/rebuild): self.show() + self.raise_() + self.activateWindow(), try/excepted per house style.
2. Related defect, fix in the same pass: user_files/drive.json currently holds window.splitter [46, 46] — closeEvent saved sizes() from the never-shown window, i.e. garbage. Guard BOTH ends: _restore_geometry must ignore splitter sizes that are absurd (e.g. either pane < 120px → fall back to the default split), and closeEvent must not persist sizes when the window was never visible (isVisible() check) or sizes are degenerate.
3. reopen() should also defensively show()+raise_() in case the stored instance is hidden.

Do NOT edit user_files/drive.json itself — it is user data and the restore guard makes stale values harmless.

Done when: the gate passes, imports pass, and the handoff explains where show() landed and how the splitter guard decides.

#### Comments
- [2026-08-23 sonnet-p] Decisions: put self.show()+raise_()+activateWindow() at the end of __init__ (after _restore_geometry/rebuild_tree/_refresh_rows), so the window is fully populated before it appears on screen; same 3 calls added to reopen() defensively in case aqt.dialogs hands back a hidden stored instance. Splitter guard: new _sane_splitter_sizes(sizes) helper rejects anything that isn't a 2-int list or has either pane < 120px (the _MIN_PANE threshold) — used on both ends: _restore_geometry falls back to the [300, 740] default when the stored value is insane (harmless against the existing stale [46, 46] in the user's drive.json, which I did not touch), and _save_geometry now (a) skips persisting anything at all when self.isVisible() is False, since a never-shown window's geometry/splitter are meaningless, and (b) even when visible, only writes the splitter key when _sane_splitter_sizes approves it — x/y/w/h still save either way. Files: klausmate/pdf_drive.py. Risks: reviewer should sanity-check that show() at the very end of __init__ doesn't race with aqt.dialogs.open()'s own bookkeeping (register_dialog's creator lambda just returns _create()'s instance; Browser/AddCards call self.show() in __init__ the same way per the card's own research, so this follows house pattern). Next: none — K-001's manual-verify checklist item ('opens the drive window and re-raises on second click') can now actually be exercised by a human.
- [2026-08-23 orchestrator] Code review passed: show/raise/activateWindow at the end of __init__ (after the tree is populated, so no blank flash) and defensively in reopen(); _sane_splitter_sizes rejects panes under 120px so the stale [46,46] in drive.json is neutralized on restore without touching the file; _save_geometry bails when the window was never visible and omits degenerate splitter values otherwise. Compiles, imports green. HOLDING IN REVIEW: this family of card has burned us with should-work-but-doesnt twice, so it gets the same gate as everything else — Pouya, after the NEXT Anki restart, click PDFs: the drive window should appear frontmost with a sensible split. Then move to Done.

### K-017: Align the add pdf thing to the bottom, right above the four buttons.
owner: sonnet-q
priority: P1
tags: sonnet-safe
files: klausmate/__init__.py
verify: python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

REWORK — Pouya checked in live Anki after the first attempt: 'This was not done properly, the add pdf square is still aligned to the top. I want it aligned to the bottom, above the four buttons.'

Attempt #1 (kept in history, commit 03219da): deferred layout.addWidget(panel) by one tick so the bar appends last to editor.widget.layout(). The position did not change, so appending last to THAT layout does not put the bar at the visual bottom — wrong container, or that layout does not own the vertical order we care about.

New approach — target the host window, not the editor's internal layout: from editor.widget, walk up parents to the top-level window (AddCards). Find the layout that directly contains the window's bottom button box (QDialogButtonBox / the widget holding History/Help/Close/Add), and insertWidget the Klaus panel into THAT layout at the index just before the button box. Fall back to the current editor-layout append if the walk fails (guarded, logged), so Browse/EditCurrent hosts — which have different bottoms — keep working as today.

Investigate before coding: print/log the widget tree once if needed (temporary, removed before commit) is NOT possible headlessly — instead read aqt/addcards.py in the Anki source tree conceptually via CLAUDE.md's guidance: generated forms show setupUi only, Anki mutates layouts afterwards; grep the aqt source strings if useful. State your layout reasoning explicitly in the handoff since nobody can see the window until Pouya restarts Anki.

Keep attempt #1's deferral if still needed for construction-order safety, or revert it if superseded — your call, justify it.

Done when: imports pass, compile passes, and the handoff explains exactly which layout now hosts the bar and at what index. Card stops in Review for Pouya's visual check, same as before.

#### Comments
- [2026-08-23 sonnet-n] Decisions: I read the code differently than the card's literal pointer. The _KlausmatePanel.__init__ 'outer' QVBoxLayout at __init__.py (outer.addWidget(self._pdf_bar), now line 4370) only ever holds that one widget — it's trivially already first/last, nothing to reorder there. The real placement is decided where the whole panel (which just wraps the bar) gets attached to the ACTUAL editor layout: layout.addWidget(panel) inside on_editor_did_init (now line 5786), where layout = editor.widget.layout() — that's the fieldsArea layout that sits directly above the Add window's buttonBox row. That call ran synchronously inside editor_did_init, i.e. before Editor.__init__ necessarily finishes building out editor.widget's own layout. This file already has a documented precedent for exactly this race: _install_panel (a few lines below) is deferred via QTimer.singleShot(0, ...) specifically because 'the window's layout is fully constructed' only after one event-loop tick. I applied the same fix: wrapped the panel-creation-and-addWidget block in a new _install_klaus_bar() closure and scheduled it with QTimer.singleShot(0, _install_klaus_bar), so it now runs after Anki finishes constructing the rest of that layout, guaranteeing our bar is appended last. Files: klausmate/__init__.py — only the on_editor_did_init function changed (added _install_klaus_bar, deferred the existing 4-line block into it unchanged, added a try/except RuntimeError for the case the widget is gone by the time the timer fires). Nothing else in the layout was reordered; the two lines that set _klausmate_target_field_index/_klausmate_active_pdf defaults stayed synchronous since nothing depends on timing there. Risks: Qt widgets can't be instantiated in this repo's offscreen test harness (see .claude/skills/klaus-test), so I could not empirically confirm this was the actual root cause of the misplacement vs. some other layout detail I'm not seeing — please eyeball the Add window after restarting Anki, specifically that the 'Drop lecture PDF here' bar sits directly above the History/Help/Close/Add row with nothing (e.g. stray whitespace or another widget) between them. Also worth confirming the PDF bar still shows up immediately (not with a visible flash/delay) since it now waits one 0ms timer tick before appearing — should be imperceptible but flag it if not. Next: none identified beyond the visual check this card already calls for.
- [2026-08-23 orchestrator] Code review passed: minimal deferred-install change with a defensive RuntimeError guard, mirroring the established _install_panel pattern; compiles through the symlink; imports green. The worker's disagreement with my grooming was correct — the card pointed at outer.addWidget inside _KlausmatePanel, which only ever holds one widget; the real ordering happens at layout.addWidget(panel) in on_editor_did_init, and that is what was deferred. HOLDING IN REVIEW: position is visual. Pouya — restart Anki, open the Add window, and check the 'Drop lecture PDF here' bar now sits at the very bottom, directly above History/Help/Close/Add. Move to Done if right; comment and move to Doing if not.
- [2026-08-23 Pouya] This was not done properly, the add pdf square is still aligned to the top. I want it aligned to the bottom, above the four buttons.
- [2026-08-23 sonnet-q] Decisions: I disagreed with attempt #1/#2's target (editor.widget.layout(), i.e. Editor.outerLayout) and confirmed why via Anki's actual source (checked out at /Users/pyamzi/Documents/Github/R36XX AnkiBoy/anki-main/qt/aqt, v25.09.2, close to the installed 26.8.1). Editor.setupOuter() (aqt/editor.py:196-201) gives editor.widget (= form.fieldsArea) its OWN private QVBoxLayout holding only the field-editing webview (self.web, stretch=1) -- setupTags() exists but is never called in this Anki version (tags are HTML inside the webview now), so that layout has nothing else in it besides our appended panel. Appending there only ever controls order INSIDE fieldsArea; fieldsArea itself is a SIBLING widget one level up, positioned above the button row by the window's OWN layout, so nothing done inside outerLayout can move the bar past fieldsArea's own boundary -- this is why attempts #1/#2 stayed pinned to the top edge of that box regardless of ordering. Confirmed from the real .ui forms: aqt/forms/addcards.ui and aqt/forms/editcurrent.ui both define centralwidget's QVBoxLayout as items [..., fieldsArea, buttonBox] in that order -- buttonBox (QDialogButtonBox, holds History/Help/Close/Add in AddCards) is fieldsArea's direct next sibling in THAT outer layout, not a descendant of fieldsArea. New fix in on_editor_did_init's _install_klaus_bar (klausmate/__init__.py): after building the panel, call host = editor.parentWindow, then button_box = host.findChild(QDialogButtonBox). If found, get box_parent = button_box.parentWidget() (== centralwidget) and box_layout = box_parent.layout() (== verticalLayout_3 / verticalLayout), compute idx = box_layout.indexOf(button_box), and box_layout.insertWidget(idx, panel) -- inserting the bar as buttonBox's immediate previous sibling in the WINDOW's layout, i.e. index (idx), which pushes buttonBox to idx+1. This places the bar directly above History/Help/Close/Add in AddCards, and directly above Close in EditCurrent (same centralwidget/buttonBox shape per editcurrent.ui). If host.findChild(QDialogButtonBox) returns None -- true for the Browser window, which has no QDialogButtonBox anywhere in its widget tree (grepped aqt/browser/browser.py and forms/browser.ui, zero matches) -- placed stays False and we fall back to the pre-existing layout.addWidget(panel) on editor.widget.layout(), i.e. Browse keeps exactly today's behavior. Kept attempt #1/#2's QTimer.singleShot(0, ...) deferral for panel-construction-order safety (unrelated to the actual bug, but harmless and already-established pattern in this file via _install_panel); the button box widget itself is built by aqt's setupUi() before editor_did_init ever fires, so the deferral was never needed for FINDING it, only for constructing the panel safely. Files: klausmate/__init__.py -- added QDialogButtonBox to the aqt.qt import block, rewrote _install_klaus_bar inside on_editor_did_init to try the host-window insertWidget path before falling back to the old append. Nothing else touched. Risks: I could not visually confirm this in a live Anki window (Qt widgets can't be instantiated in this repo's offscreen test harness) -- please restart Anki and check the Add window: the 'Drop lecture PDF here' bar should now sit directly above the History/Help/Close/Add row, and the EditCurrent window (opened from Browser, Ctrl+E on a card) should show it directly above Close. One thing worth eyeballing: findChild(QDialogButtonBox) does a recursive search of the ENTIRE host window, so if some other klausmate feature (e.g. the PDF drive dialog) ever adds a QDialogButtonBox as a descendant of the SAME AddCards/EditCurrent window before this runs, it could match the wrong one -- I checked and found no such case today. Next: none identified beyond the visual check this card already calls for.
- [2026-08-23 orchestrator] Code review passed, and I independently re-verified the investigation rather than taking it on trust: pulled the real addcards.ui/editcurrent.ui from the anki-main checkout at /Users/pyamzi/Documents/Github/R36XX AnkiBoy/anki-main/qt/aqt/forms/ and confirmed line-for-line that centralwidget's QVBoxLayout holds [modelArea/deckArea row, fieldsArea, buttonBox] as three direct siblings — fieldsArea and buttonBox are NOT nested, exactly as the handoff claims. Also confirmed editor.parentWindow is unconditionally set in Editor.__init__ (aqt/editor.py:167) and that Browser has zero QDialogButtonBox anywhere in browser.py or browser.ui, so the fallback path is real, not speculative. This is the correct container this time — insertWidget(idx, panel) lands the bar between fieldsArea and buttonBox, i.e. directly above it. Compiles, imports green. Still HOLDING IN REVIEW per the card's own rule: Pouya, next Anki restart, check the Add window bar sits right above History/Help/Close/Add, and separately check the same PDFs-button fix from K-022 while you're in there.

### K-023: Slice 1/3: extract the Manage-models dialog to manage_models.py
owner: sonnet-r
priority: P2
tags: sonnet-safe,slice
files: klausmate/__init__.py,klausmate/manage_models.py
verify: test -f klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23
claimed: 2026-08-23

First slice of K-006 (parent card). Pure code MOVE, zero behavior change.

Move from klausmate/__init__.py into a new klausmate/manage_models.py:
- _MODEL_PRESETS (line ~2922), _format_pull_event (~2949), _KlausManageDialog (~2970), manage_models_dialog (~2996 through ~4050). Roughly 1,130 lines.

Hard requirements:
- __init__.py keeps working references: it calls manage_models_dialog at ~8 sites (first-run, readiness, install_menu, settings glue) and passes it into settings_ui.open_settings_dialog. After the move, import it back: 'from .manage_models import manage_models_dialog, _MODEL_PRESETS' near the other relative imports, so every existing call site and any external reference keeps resolving. ollama_runtime.py's docstring mentions _format_pull_event — docstring only, no import to fix.
- CIRCULAR IMPORTS: the moved code references names living in __init__.py (get_config, write_config, client, _save_config_on_main, autocomplete_model, ask_model, klaus_engine, open_config, _DEFAULT_CLAUDE_MODEL, and runtime helpers). __init__ will import manage_models at module load, so manage_models must NOT import __init__ at module load. Use the established pattern from curation.py:56 — a lazy _pkg() via importlib.import_module(__package__) inside functions — or import from the true leaf module where one exists (ollama_setup: install_methods/run_install_method/ollama_reachable; ollama_runtime: full_setup/runtime_download_size_hint; ollama_client). Grep every name the moved block references before deciding; list your import decisions in the handoff.
- Qt imports: copy exactly the aqt.qt names the moved code uses into the new module's own import block; remove any that become unused in __init__.py ONLY if truly unused elsewhere (grep first).
- tests/test_dialog_logic.py transcribes this dialog's logic; it must still pass unmodified — if it fails, your move changed behavior.
- Run the FULL suite before committing, not just the verify gate. Compile hook fires on every klausmate/*.py edit.

Done when: verify passes, full suite green, __init__.py is ~1,100 lines shorter, and the handoff lists every name whose import path changed.

#### Comments
- [2026-08-23 sonnet-r] Decisions: Moved lines 2917-4050 of __init__.py (the '# --- model manager ---' header through end of manage_models_dialog, 1134 lines) verbatim into klausmate/manage_models.py, plus a 1-line blank-line trim at the seam so __init__.py keeps exactly 2 blank lines before def open_config. Circular imports: 9 names the block calls that live in __init__.py (get_config, write_config, client, autocomplete_model, ask_model, klaus_engine, open_config, _DEFAULT_CLAUDE_MODEL, _save_config_on_main) are now reached via a _pkg() lazy importlib.import_module(__package__) helper (curation.py:56 pattern) — every call site got a mechanical _pkg().<name> prefix via regex on \b<name>\(, verified against a full AST free-name scan so dict-key string collisions (e.g. cfg['autocomplete_model']) were not touched. embeddings/curation were already locally imported inside nested functions ('from . import embeddings' etc.) in the original code, so those needed no change. Import decisions for the 46 names the AST scan found free in the block: stdlib (threading, time, Any, Callable) -> direct imports in manage_models.py; aqt.qt widgets (QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QTimer, QVBoxLayout, QWidget, Qt) -> from aqt.qt import (...) in manage_models.py; aqt/aqt.operations/aqt.utils (mw, QueryOp, openLink, showInfo, showWarning, tooltip) -> their own module imports; .ollama_client (OllamaError), .ollama_setup (OLLAMA_DOWNLOAD_URL, InstallMethod, install_methods, ollama_reachable, run_install_method), .ollama_runtime (RuntimeProvisionError, full_setup, runtime_download_size_hint) -> re-imported directly into manage_models.py from those leaf modules (no back-import to package __init__, confirmed by reading their headers). __init__.py gets back 'from .manage_models import _MODEL_PRESETS, manage_models_dialog' placed after the ollama_runtime import block. Cleanup: grepped every one of those names for outside-the-block usage in __init__.py and removed the now-genuinely-unused ones from __init__.py's own imports: import threading; QFormLayout, QListWidget, QListWidgetItem, QProgressBar, QSizePolicy, QStackedWidget from aqt.qt; InstallMethod, install_methods, ollama_reachable, run_install_method from .ollama_setup (collapsed to a single-line 'from .ollama_setup import OLLAMA_DOWNLOAD_URL'); RuntimeProvisionError, full_setup from .ollama_runtime. Every other aqt/typing name stayed in __init__.py's imports because it's still used elsewhere there. Files: klausmate/__init__.py (import block edits + block deletion), klausmate/manage_models.py (new, 1197 lines). Risks: the _pkg() indirection is the only semantic-looking diff in the moved block (12 get_config, 5 client, 3 write_config, 3 each of autocomplete_model/ask_model/klaus_engine, 1 each of open_config/_DEFAULT_CLAUDE_MODEL/_save_config_on_main) — worth a careful read since it's the one place text != the original beyond import lines, though behavior is identical (same object, same package, just resolved lazily instead of at module scope). Next: none — K-024 and K-025 (siblings) still need to slice the rest of __init__.py; I did not touch anything past line 4050 (old numbering) / line 2916 (new).
- [2026-08-23 orchestrator] Independently re-verified: full suite (232 assertions across 5 files) green, py_compile clean both in-repo and through the Anki symlink, _pkg() indirection counts match exactly (12/5/3/3/3/1/1/1), no leftover unqualified references to the 9 relocated names, no module-level circular import, all ~9 call sites in __init__.py resolve via the re-export. Signed off.

### K-024: Slice 2/3: extract Browse toolbar toggles to browse_toggles.py
owner: sonnet-s
priority: P3
tags: sonnet-safe,slice
files: klausmate/__init__.py,klausmate/browse_toggles.py
verify: test -f klausmate/browse_toggles.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Second slice of K-006. Pure move, zero behavior change. BLOCKED behind slice 1 by design — both touch __init__.py; the claim guard enforces the ordering.

Move from klausmate/__init__.py into new klausmate/browse_toggles.py:
- _KLAUS_TOGGLE_QSS (~2040), _make_klaus_toggle (~2061), _VisibilityWatcher (~2072), _install_browser_sidebar_toggle (~2094) and everything through on_browser_will_show (~2186, ends before ~2230). Roughly 190 lines. (Line numbers shift after slice 1 — locate by name, not number.)

Requirements:
- __init__.py registers on_browser_will_show on gui_hooks.browser_will_show near the bottom; after the move import it back ('from .browse_toggles import on_browser_will_show') so the registration line is untouched or minimally adjusted.
- Check what the moved code references (mw? get_config? pure Qt?) — grep before assuming; use lazy _pkg() only if actually needed.
- Preserve the hard-won comments in this block verbatim (the grid-repack trick and QTimer deferral notes are documented gotchas).
- Full suite before committing.

#### Comments
- [2026-08-23 sonnet-s] Decisions: pure move of _KLAUS_TOGGLE_QSS, _make_klaus_toggle, _VisibilityWatcher, _install_browser_sidebar_toggle, on_browser_will_show (lines ~2026-2223 pre-move) into new klausmate/browse_toggles.py, reusing K-023's _pkg() lazy-import pattern verbatim (importlib.import_module(__package__)). __init__.py still defines _remap_browser_mark_hotkey, _install_browser_search_klaus, _reset_browse_layout_to_defaults (they weren't part of this card's block); on_browser_will_show's inner _deferred() now calls them as _pkg()._remap_browser_mark_hotkey(browser) etc. since they still live in __init__.py. Direct aqt.qt imports (QEvent, QHBoxLayout, QObject, QTimer, QToolButton, QWidget) and typing (Any, Callable) added to browse_toggles.py — no _pkg() needed for those, they're leaf-importable. __init__.py: removed the now-unused QObject import from its aqt.qt import block (last remaining reference was _VisibilityWatcher, which moved out), and added 'from .browse_toggles import on_browser_will_show' right after the manage_models import (line ~119-120) so the existing 'gui_hooks.browser_will_show.append(on_browser_will_show)' registration line (~4639) is untouched. Import paths that changed: on_browser_will_show, _KLAUS_TOGGLE_QSS, _make_klaus_toggle, _VisibilityWatcher, _install_browser_sidebar_toggle now live in klausmate.browse_toggles instead of klausmate (__init__.py re-exports on_browser_will_show only, since that's the only one anything outside the block calls). Files: klausmate/__init__.py (removed the 198-line block + QObject import + added 1 import line), klausmate/browse_toggles.py (new, 234 lines, verbatim comments preserved including the gridLayout cell-(0,0) repack note and the QTimer.singleShot(0) deferral note). Verify: 'test -f klausmate/browse_toggles.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py' exits 0 (21 passed, 0 failed). Full suite: all 5 tests/test_*.py exit 0, 233 total assertions passed (up from the 232 baseline — test_imports.py's new klausmate.browse_toggles import check adds one), 0 failed. py_compile through the real Anki symlink (~/Library/Application Support/Anki2/addons21/klausmate/{__init__.py,browse_toggles.py}) exits 0. Risks: the three _pkg()-routed helpers (_remap_browser_mark_hotkey, _install_browser_search_klaus, _reset_browse_layout_to_defaults) stay in __init__.py — if a future slice moves those too, browse_toggles.py's _deferred() calls need updating to match wherever they land. Next: none. Commit: 6993713.
- [2026-08-23 orchestrator] Independently re-verified: full suite (233 assertions across 5 files) green, py_compile clean both in-repo and through the Anki symlink, all 3 _pkg()-routed helpers (_remap_browser_mark_hotkey, _install_browser_search_klaus, _reset_browse_layout_to_defaults) confirmed still resident in __init__.py, gridLayout and QTimer.singleShot(0) gotcha comments preserved verbatim, on_browser_will_show re-import wired correctly to the existing gui_hooks registration line. __init__.py now 4,662 lines. Signed off.

### K-025: Slice 3/3: extract first-run and readiness flows to setup_flow.py
owner: sonnet-t
priority: P3
tags: sonnet-safe,slice
files: klausmate/__init__.py,klausmate/setup_flow.py
verify: test -f klausmate/setup_flow.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Third slice of K-006. Pure move, zero behavior change. Runs after slices 1 and 2 (same-file serialization via the claim guard).

Move from klausmate/__init__.py into new klausmate/setup_flow.py:
- _first_run_dialog_shown_this_session (~2561), first_run_check (~2564), setup_readiness_check (~2649), _maybe_offer_runtime_update (~2689), _readiness_check_body (~2729) and their private helpers up to but NOT including the manage-models block boundary. Roughly 360 lines. Locate by name; numbers will have shifted.

Requirements:
- These functions are registered on gui_hooks.profile_did_open near the bottom of __init__.py — import them back so registrations keep working.
- first_run_check calls manage_models_dialog: after slice 1 that lives in manage_models.py — import it from there directly, not via the package.
- The module-level mutable _first_run_dialog_shown_this_session is read/written across first_run_check and setup_readiness_check — keep both users in the SAME module so the global stays coherent; do not leave one behind in __init__.
- Mind the migration guard interplay: _migrate_config stays in __init__.py (it is config plumbing, not setup flow) — do not move it.
- Full suite before committing.

#### Comments
- [2026-08-23 sonnet-t] Decisions: pure move of the comment header + _first_run_dialog_shown_this_session, first_run_check, setup_readiness_check, _maybe_offer_runtime_update, _readiness_check_body (old __init__.py lines 2344-2648, 305 lines) into new klausmate/setup_flow.py, reusing the established _pkg() lazy importlib.import_module(__package__) pattern verbatim from manage_models.py/browse_toggles.py. AST free-name scan of the block found 5 names still resident in __init__.py that needed the _pkg() indirection: get_config (8 call sites), write_config (3), client (3), _save_config_on_main (2, both passed as a bare callable reference via save_config=_pkg()._save_config_on_main rather than called), and open_settings_dialog (1 - the settings_btn branch in _readiness_check_body; open_settings_dialog itself stays defined in __init__.py right after the moved block, so this is a genuine back-reference, not a leaf import). Per the card's requirement #2, manage_models_dialog is imported directly from .manage_models (leaf module, not _pkg()) - used 4x in the moved code (first_run_check x2, _readiness_check_body x2). Other names were leaf-importable directly with no circularity: ensure_server + runtime_download_size_hint from .ollama_runtime, the ollama_runtime module itself via 'from . import ollama_runtime' (used as ollama_runtime.OLLAMA_VERSION / ollama_runtime.update_runtime), OLLAMA_DOWNLOAD_URL from .ollama_setup, QMessageBox from aqt.qt, QueryOp from aqt.operations, askUser/openLink/tooltip from aqt.utils, mw from aqt, Any from typing. _first_run_dialog_shown_this_session (module-level mutable) and both its readers/writers (first_run_check, setup_readiness_check) landed together in setup_flow.py per requirement #3 - no split. _migrate_config was left untouched in __init__.py per requirement #4 (not moved, not referenced by the moved block). Registration lines at __init__.py:4326-4327 (gui_hooks.profile_did_open.append(first_run_check) / (setup_readiness_check)) needed zero changes - 'from .setup_flow import first_run_check, setup_readiness_check' added to the import block (after the browse_toggles import) makes them resolve exactly as before. Cleanup in __init__.py: removed openLink from the aqt.utils import (now unused there, its only other use was in the moved block) and removed runtime_download_size_hint plus the .ollama_setup import of OLLAMA_DOWNLOAD_URL entirely (both now fully unused in __init__.py, verified by grep). Kept ensure_server, manage_models_dialog, QMessageBox, QueryOp, askUser, tooltip, and the ollama_runtime module import in __init__.py's own import block since each still has independent call sites elsewhere in the file (grepped individually before removing anything). Also trimmed a 4-blank-line seam left after deletion down to the standard 2 blank lines before 'def open_settings_dialog'. Files: klausmate/__init__.py (import block edits + 305-line block deletion + blank-line trim, now 4,354 lines), klausmate/setup_flow.py (new, 344 lines, header docstring documents the _pkg() rationale and lists the 5 back-referenced names). Verify: 'test -f klausmate/setup_flow.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py' exits 0 (22 passed, 0 failed - up from 21 in K-024's baseline; test_imports.py's klausmate.setup_flow import check is the +1). Full suite: all 5 tests/test_*.py exit 0, 234 total assertions passed (up from 233), 0 failed. py_compile clean both in-repo and through the real Anki symlink (~/Library/Application Support/Anki2/addons21/klausmate/{__init__.py,setup_flow.py}). Risks: the 5 _pkg()-indirected call sites are the only semantic-looking diff inside the moved block beyond import lines - same objects, same package, just resolved lazily; worth a quick read since the save_config=_pkg()._save_config_on_main line wraps to two lines where the original didn't (line length). This is the final slice of K-006 - after sign-off the parent tracking card can close. Next: none. Commit: 709a081.
- [2026-08-23 orchestrator] Independently re-verified: full suite (234 assertions across 5 files) green, py_compile clean both in-repo and through the Anki symlink, _migrate_config confirmed untouched (still at __init__.py:147, registered independently at 4325), manage_models_dialog confirmed imported directly from .manage_models (not via _pkg(), per the card's explicit requirement), first_run_check and setup_readiness_check both landed in setup_flow.py together with their shared _first_run_dialog_shown_this_session global, gui_hooks.profile_did_open registrations for both intact. __init__.py now 4,354 lines. Signed off.

### K-006: Slice klausmate/__init__.py into modules
owner: -
priority: P3
tags: sonnet-safe,large
files: klausmate/__init__.py
verify: python3 -m py_compile via the symlink, then the full suite
created: 2026-08-23

5,980 lines in one file. Too large for one card — the orchestrator must slice it into file-disjoint pieces first, or every worker collides on the same path.

Blocked on grooming, not on skill. Candidate seams: the Manage models dialog (~1000 lines), the editor panel and PDF bar, the Browse toolbar toggles, hook registration and bootstrap.

#### Comments
- [2026-08-23 orchestrator] Sliced into K-023 (manage-models dialog, ~1130 lines), K-024 (browse toggles, ~190), K-025 (first-run/readiness, ~360) — a serial pipeline, since every slice removes code from __init__.py and the claim guard refuses overlapping claims. The PDF panel machinery (~2000 lines) deliberately stays put: highest risk, least separable, and untestable headlessly. K-006 stays in Backlog as the tracking parent; it closes when all three slices are Done. Expected end state: __init__.py drops from 6,010 to ~4,300 lines.
- [2026-08-23 orchestrator] All three slices landed and independently verified: K-023 (manage_models.py, 1197 lines), K-024 (browse_toggles.py, 233 lines), K-025 (setup_flow.py, 344 lines). __init__.py dropped from 6,010 to 4,354 lines (target was ~4,300 — on target). Full suite grew from 132 to 234 assertions across the pipeline with zero regressions at any step, and every intermediate commit compiles clean through the real Anki symlink. Closing this tracking card.

### K-026: Split model library into Text / Embedding tabs, add embedding presets
owner: sonnet-u
priority: P2
tags: sonnet-safe
files: klausmate/manage_models.py,tests/test_dialog_logic.py
verify: grep -q _EMBED_MODEL_PRESETS klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23
claimed: 2026-08-23

The Manage-models dialog's 'Local model library (Ollama)' box is one flat QListWidget, and _MODEL_PRESETS holds only text-generation models — there is not a single embedding model a user can pull with one click, even though Semantic search on the local provider needs one (default: nomic-embed-text). Requested by Pouya: separate tabs for embedding vs text models, and download presets that are good for embedding.

Scope (all in klausmate/manage_models.py):

1. Add _EMBED_MODEL_PRESETS next to _MODEL_PRESETS, exactly these entries (all verified real Ollama library names; index 0 must stay nomic-embed-text since it is embeddings.DEFAULT_MODELS['ollama']):
   ('nomic-embed-text', 'default, best all-round · ~274 MB')
   ('all-minilm', 'tiny, fastest · ~46 MB')
   ('snowflake-arctic-embed', 'strong retrieval · ~670 MB')
   ('mxbai-embed-large', 'best quality · ~670 MB')
   ('bge-m3', 'multilingual, long context · ~1.2 GB')
   ('embeddinggemma', 'Google, newest · ~620 MB')
   Do NOT invent additional model names.

2. Add a module-level helper _is_embedding_model(name: str) -> bool: True when the bare name (strip any :tag suffix) matches a _EMBED_MODEL_PRESETS entry, or contains 'embed' or 'minilm', or starts with 'bge'. One function, used everywhere the split is decided — no inline duplicates.

3. Replace the single lst QListWidget in lib_box with a QTabWidget holding two tabs: 'Text models' and 'Embedding models', each a QListWidget. rebuild_library_list() partitions ui_state['models'] via _is_embedding_model. The 'used by' badges (autocomplete/Ask/search) must follow each model into whichever tab it lands in — a text model configured as the search model still shows its 'search' badge on the Text tab. Per-tab empty placeholders ('(no text models installed — pull one below)' / embedding equivalent), NoItemFlags like the current placeholder.

4. The pull row (pull_input combo + Pull/Delete/Refresh buttons) stays SHARED below the tab widget, but pull_input's preset items repopulate when the active tab changes: Text tab -> _MODEL_PRESETS, Embedding tab -> _EMBED_MODEL_PRESETS. Keep it editable with the same placeholder text. Repopulating may clear typed text — acceptable.

5. get_selected_model() must read from the ACTIVE tab's list widget. delete_selected() and the post-pull reselect path go through it, so they follow automatically — verify they do.

6. In sync_embed_widgets(), when provider == 'ollama', populate embed_model_combo from installed models that pass _is_embedding_model (instead of all installed models). Keep the existing behavior where the combo stays editable and setEditText preserves the configured value even when not in the list — a user who genuinely wants a text model as embedder can still type it.

7. QTabWidget import: add to the aqt.qt import block in manage_models.py only.

Constraints: tests/test_dialog_logic.py transcribes this dialog's logic — it must still pass; extend it ONLY if it directly models something you changed, and keep every existing assertion. maybe_auto_pull_starter() keeps using _MODEL_PRESETS[0] (text starter). Do not touch embeddings.py. Full suite (234 assertions, 5 files) before committing; py_compile through the Anki symlink.

Done when: verify passes, both tabs render correct partitions with badges, embedding presets pull-able from the Embedding tab, embed model dropdown suggests only embedding models.

#### Comments
- [2026-08-23 sonnet-u] Implemented all 7 scope items in klausmate/manage_models.py. _EMBED_MODEL_PRESETS added verbatim (6 entries, nomic-embed-text at index 0) right after _MODEL_PRESETS; _is_embedding_model(name) strips :tag, checks membership in a set built from the preset names, then 'embed'/'minilm' substring and 'bge' prefix — single source of truth, used in rebuild_library_list's partition and sync_embed_widgets' filter. Decisions: lib_box's flat 'lst' QListWidget became a QTabWidget (lib_tabs) with two fresh QListWidgets, text_lst and embed_lst ('Text models' / 'Embedding models'). Added a small _active_lib_list() closure (returns text_lst if lib_tabs.currentIndex()==0 else embed_lst) so get_selected_model() just delegates to it — delete_selected() and the post-pull reselect in start_pull()/refresh() go through get_selected_model() already, so they follow for free, verified by reading both call sites. rebuild_library_list() now partitions ui_state['models'] via _is_embedding_model into text_models/embed_models lists, then a local populate(list_widget, names, empty_text) helper builds badges (autocomplete/Ask/search — unchanged logic) and restores selection into whichever tab the previously-selected model landed in (does not force-switch the active tab, matching the card's wording). Each tab gets its own NoItemFlags placeholder. Pull row stays shared below the QTabWidget; added _fill_pull_presets() which clears+refills pull_input from _MODEL_PRESETS or _EMBED_MODEL_PRESETS based on lib_tabs.currentIndex(), resets currentIndex(-1), and sets a tab-appropriate placeholder string; wired via lib_tabs.currentChanged.connect(lambda _i: _fill_pull_presets()) in the final connect block alongside the other .connect() calls. This repopulation only touches pull_input (no ui_state['syncing'] guard needed — pull_input has no currentIndexChanged save path, confirmed by grep). sync_embed_widgets() now adds only _is_embedding_model-passing names to embed_model_combo when provider=='ollama'; setEditText(cfg value) still runs unconditionally after, so a configured text-model embedder still shows correctly (per item 6). QTabWidget added to the aqt.qt import block, alphabetically between QStackedWidget and QTimer. Files: klausmate/manage_models.py only — tests/test_dialog_logic.py was not touched; it transcribes sync_jobs_widgets/save_jobs/ask_selection, none of which changed, and it has no model of the library-list split or sync_embed_widgets, so extending it wasn't warranted by the card's 'only if it directly models something you changed' rule. Risks: a reviewer should double check the 'used by search' badge case for a text model configured as the embedder (e.g. someone manually configured embedding_model to a qwen model) — it will show 'search' badge on the Text tab per item 3's requirement, verified by reading rebuild_library_list's shared auto_active/ask_active/embed_active computation which is unchanged and applied identically to both tabs via the populate() helper. Also worth a visual check that lib_tabs default tab (index 0, Text) matches maybe_auto_pull_starter()'s assumption of _MODEL_PRESETS[0] via pull_input.setCurrentIndex(0) — confirmed correct since _fill_pull_presets() is called once at dialog build before any tab change, populating pull_input from _MODEL_PRESETS. Next: none — all 7 scope items done. Full suite: 234 assertions across 5 test files, 0 regressions (68+29+58+22+57). py_compile through the Anki symlink passed. Verify gate passes clean.
- [2026-08-23 orchestrator] Independently re-verified: preset list matches the card verbatim (6 entries, nomic-embed-text at index 0), _is_embedding_model is the single source of truth for the split and correctly classifies every current preset on both sides (embeddinggemma -> embed via 'embed' substring, gemma3n -> text), zero stray references to the removed single-list variable, get_selected_model reads the active tab via _active_lib_list so Delete and post-pull reselect follow, badges applied identically in both tabs, per-tab placeholders present, lib_tabs.currentChanged wired to _fill_pull_presets with no save path attached, embed_model_combo filter preserves the editable setEditText fallback. py_compile clean in-repo and through the Anki symlink; full suite 234 assertions green. Signed off — visual tab layout still needs Pouya's eyes in a restarted Anki (Qt untestable headlessly).
