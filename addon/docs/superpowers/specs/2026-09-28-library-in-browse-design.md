# Library in Browse — design

Agreed with Pouya on 2026-09-28 through a grilling session (Q1–Q29).

## Goal

The Library moves out of its embedded main-window screen (`library_tab.py`)
and into Browse's sidebar. Why: the Library belongs next to the cards
(select a lecture, act on its cards), and there should be one less place to
go. The embedded screen also kept breaking (stacking under the deck list,
Anki's shortcuts live behind it, layout never saved).

## Shape

The Library **is** the existing `!Library::<folder>::<leaf>` tag branch in
Anki's Browse sidebar, extended by Klaus. No separate tree of data.

Revised 2026-09-30 (Pouya): the branch is shown as **its own section**,
first in the sidebar, apart from Tags, with a library icon on the root,
folder icons on folders and PDF icons on PDFs. It is still made of Anki's
own TAG rows (moved out of the Tags section at the `browser_will_build_tree`
TAGS stage), so Anki's rename, drag, delete and search keep working.

Facts this rests on (checked 2026-09-28):

- Every indexed PDF already owns one `!Library` tag; renaming it in the
  sidebar renames the PDF (K-054, `tag_sync.reconcile_from_tags`).
- Custom sidebar items cannot be renamed in place, dragged, or deleted
  (`SidebarItemType.is_editable/is_deletable`, `handle_drag_drop` in
  `aqt/browser/sidebar`). Tags can. That is why the tag branch, not a
  custom section.
- A tag search on a folder tag matches its children, so clicking a folder
  filters to every PDF in it for free.
- `col.tags.set_collapsed(tag, …)` registers a zero-note tag (`register()`
  is a no-op). Check Database and Clear Unused Tags drop zero-note tags.
  Anki refuses to rename or reparent a zero-note tag (`rename.rs:46`,
  `reparent.rs:51`).
- Anki's rename/reparent remove EVERY tag row under the old prefix
  (including zero-note rows) but only re-register the names that notes
  carry. Empty PDF tags inside a renamed folder vanish rather than move.

## Behaviour

**Click.** A PDF or folder tag filters the table to its matched cards
(native tag search; Ctrl/Shift combine). Clicking a PDF also loads it into
Browse's PDF panel if that panel is already showing; right-click › Open PDF
shows the panel.

**Row display.** Every tag (not only `!Library`) shows a right-aligned,
dimmed grey retention %. Plain mean FSRS retrievability over the tag's
cards, parents including children, new cards excluded, "—" when no studied
cards. PDF tags use the same formula (numbers shift slightly from today's
similarity-weighted value). No card or note counts. PDFs that are not
embedded, need re-embedding, are indexing or failed get a warning icon in
place of the tag icon, reason in the tooltip.

**Import.** Dropping a PDF anywhere on the sidebar imports to the Library
root. An "Import PDFs…" button at the bottom of the sidebar also imports to
the root. Right-click a folder › Import PDFs here… imports into it. Editor
drop bar, deck-screen drop and folder auto-import stay. A status line above
the button shows indexing progress with ✕ to cancel.

**Tag ↔ PDF sync**, live on every tag change (`operation_did_execute` with
`changes.tag`, debounced), in addition to profile open:

- Every PDF and every empty folder has a tag, even with zero matches,
  re-registered after Check Database / Clear Unused Tags. Empty tags are
  renamed via right-click only.
- Fix: a zero-match PDF's recorded tag never existed, so today one stray
  `!Library::` tag makes reconcile rename that PDF to it.
- Renaming a PDF tag renames the PDF and its file on disk.
- Dragging a PDF tag into another folder moves the PDF and its file.
- Renaming or reparenting a folder tag renames/moves the folder, its
  directory on disk and every PDF in it (empty ones included).
- Deleting a tag with matched cards asks "Delete the PDF too?"
  ("Delete N PDFs in X?" for a folder). Yes moves the file(s) to the
  macOS Trash; No restores the tag(s). Revised 2026-09-30 (K-316): the
  same prompt follows Delete on a PDF tag with no matched cards, so
  Anki's Delete replaces a separate Delete PDF… item.
- A vanished tag with no matched cards (Check Database, Clear Unused
  Tags, deleting an empty tag) is silently re-registered, never a prompt.
  Removing an empty folder or empty PDF is a right-click action.
- Undoing a tag delete after answering Yes brings back an unowned tag;
  nothing further happens. The file stays in the Trash.

**Right-click menus** (Anki's own items stay above a separator):

- PDF tag: Match Sensitivity…, Retention History…, Show in Finder.
  (Revised 2026-09-30, K-316: opening is a double-click, rename and delete
  are Anki's own items, PDFs embed themselves, and suspending is ⌘A ⌘J.)
- Folder tag: New Folder…, Import PDFs here…; Rename Folder… and Remove
  Folder only when it is empty (Anki's own items skip an empty tag).
- `!Library` root: Import PDFs…, New Folder….

**Removed** (Part 3): `DriveWindow`, `library_tab.py`, the top-bar Library
link, the map (for now). The editor's "Library…" button and the reviewer's
"Library" button are separate features and stay.

## Earlier Library GUI review fixes

#1 (shortcuts behind the screen) and #7 (embedded layout never saved) are
moot. #2 (rescan/OCR on main thread), #3 (synchronous drop import) and #8
(annotation bakes refresh everything) are folded in. #4, #5, #6 go with the
window; Anki's native sidebar keys replace #6.

## Parts (one board card each, in order)

1. **Tag-sync hardening** (no UI): empty-tag registration, live reconcile,
   folder-rename detection, disk moves, delete prompt + Trash, misrename
   fix. `DriveWindow` keeps working.
2. **Sidebar UI**: menus, retention numbers and warning icons, drop import,
   Import button, status line, click-to-load into the PDF panel.
3. **Removal**: `DriveWindow`, `library_tab`, top-bar link, test migration.
