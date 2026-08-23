# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

## Ready

### K-006: Slice klausmate/__init__.py into modules
owner: -
priority: P3
tags: sonnet-safe,large
files: klausmate/__init__.py
verify: python3 -m py_compile via the symlink, then the full suite
created: 2026-08-23

5,980 lines in one file. Too large for one card — the orchestrator must slice it into file-disjoint pieces first, or every worker collides on the same path.

Blocked on grooming, not on skill. Candidate seams: the Manage models dialog (~1000 lines), the editor panel and PDF bar, the Browse toolbar toggles, hook registration and bootstrap.

### K-002: Visual polish pass: Manage models dialog and Klaus panel
owner: -
priority: P2
tags: design
files: klausmate/web/search.css,klausmate/web/search.html
verify: designer sign-off; screenshots attached to this card
created: 2026-08-23

Needs a design spec before any code. The Manage models dialog was reorganised by job (What Klaus uses / Local model library) but never got a visual pass. The Klaus panel still uses Bootstrap-era defaults.

Designer: write the spec into this card, then move it to Ready. Do not hand this to a worker un-specced.

### K-009: Make model setup for curation and embeddings understandable
owner: -
priority: P1
tags: design
verify: designer sign-off against the spec in this card
created: 2026-08-23

Pouya, on K-001: 'It's not easy to understand the model installation process for a curation or an embedded model.'

This is the second time this surface has been called confusing — the Manage models dialog was reorganised by job on 2026-08-23 for the same reason, and it clearly did not go far enough. The remaining gap is the install/provisioning path rather than the assignment path: what has to be downloaded, what it costs, what a key is for, and what happens if you skip it.

Designer: write the spec into this card before anyone touches code. Worth covering — what the user sees when no embedding model is installed and they press Index cards; whether Voyage-by-default is discoverable at all before it fails; how pulling a local embedding model is offered; and what distinguishes the Ask engine from the search provider in the user's mind, given both are 'models'.

Not sonnet-safe. Needs a spec first.

## Doing

## Review

### K-001: Manual-verify PDF drive and deck-curate surfaces in live Anki
owner: Pouya
priority: P1
tags: needs-human
verify: human confirms each checklist item in Anki
created: 2026-08-23
claimed: 2026-08-23

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
