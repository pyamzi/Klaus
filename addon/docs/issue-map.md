# Add-on issue numbers

On 2026-10-03 the add-on's issues moved from `pyamzi/klaus-note-addon` to this repository, under the `addon` label. Old references (`#12` in add-on commits, `Addon:#12` on boards) map as follows.

| Old (klaus-note-addon) | New (klaus-note) | State | Title |
| --- | --- | --- | --- |
| pyamzi/klaus-note-addon#10 | #73 | closed | Re-importing a PDF whose name is already mapped overwrites the Library file and wipes its marks |
| pyamzi/klaus-note-addon#11 | #74 | closed | Edits to adopted outside annotations are never baked and are reverted on the next open |
| pyamzi/klaus-note-addon#12 | #75 | closed | Re-highlighting a noted highlight in another ink deletes its note |
| pyamzi/klaus-note-addon#13 | #76 | closed | Image Occlusion: validate note ID and image fields before using them in file paths |
| pyamzi/klaus-note-addon#14 | #77 | closed | Library PDF tag can collide with a folder tag, so indexing strips sibling PDFs' tags and a rename moves a folder on disk |
| pyamzi/klaus-note-addon#15 | #78 | closed | PDF reader: switching tabs discards an open text box, note or card editor |
| pyamzi/klaus-note-addon#16 | #79 | closed | Write-approval preview strips HTML and never shows old field values |
| pyamzi/klaus-note-addon#17 | #80 | closed | Quiet auto-sync reloads open editors via mw.reset() while the user may be typing |
| pyamzi/klaus-note-addon#18 | #81 | closed | First-run Library folder move: closing the profile or quitting mid-move leaves moved PDFs unopenable |
| pyamzi/klaus-note-addon#19 | #82 | closed | Image Occlusion: Edit Cards and Ctrl+Return discard unused drawing changes without asking |
| pyamzi/klaus-note-addon#20 | #83 | closed | Image Occlusion conflict guard misses IOE installed from its .ankiaddon package |
| pyamzi/klaus-note-addon#21 | #84 | closed | Removing a Library tag raises TypeError (list passed to tags.remove), so deleted PDFs and folders keep their tags |
| pyamzi/klaus-note-addon#22 | #85 | closed | Index queue strands for good after the busy-wait gives up; refresh then reports "Everything is indexed" |
| pyamzi/klaus-note-addon#23 | #86 | closed | PDF reader: resizing the panel at fit-width leaves the visible pages blank |
| pyamzi/klaus-note-addon#24 | #87 | closed | Single window: reopening Edit Current within ~5 s of closing it deletes the new window |
| pyamzi/klaus-note-addon#25 | #88 | closed | Top-bar pane toggles don't follow tab switches when the profile auto-loads at startup |
| pyamzi/klaus-note-addon#26 | #89 | closed | Background image with ', #, ? or % in its filename breaks the deck/study wallpaper CSS |
| pyamzi/klaus-note-addon#27 | #90 | closed | Remove dead modules and stale "OCR not supported" wording |
| pyamzi/klaus-note-addon#28 | #91 | closed | Legacy-store migration races a running bake and can lose freshly baked marks |
| pyamzi/klaus-note-addon#29 | #92 | closed | Annotation JSON atomic writes are not fsynced, so a crash can leave an unreadable marks file |
| pyamzi/klaus-note-addon#30 | #93 | closed | Image Occlusion: old _<image>.excalidraw diagram files are never cleaned up |
| pyamzi/klaus-note-addon#31 | #94 | closed | Excluding the PDF currently being indexed fails the whole queued batch with a misleading error |
| pyamzi/klaus-note-addon#32 | #95 | closed | PDF reader: evicted pages keep their pdf.js caches, so memory grows with every page visited |
| pyamzi/klaus-note-addon#33 | #96 | closed | PDF reader: a page render still running across a document switch can leave a page of the new document blank |
| pyamzi/klaus-note-addon#34 | #97 | closed | Auto-sync ignores an Anki sync started while a quiet sync is running |
| pyamzi/klaus-note-addon#35 | #98 | closed | Preferences removes its profile_will_close handler mid-dispatch, skipping the next handler |
| pyamzi/klaus-note-addon#36 | #99 | open | Browse: "wrapped C/C++ object of type ProgressDialog has been deleted"; confirm the cause and remove the temporary progress logger |
| pyamzi/klaus-note-addon#37 | #100 | open | Image Occlusion: live verification checklist in a running Anki |
| pyamzi/klaus-note-addon#38 | #101 | open | Per-PDF notes space: decide whether it's still wanted now that the reader has sticky notes, then wire it in or delete it |
| pyamzi/klaus-note-addon#39 | #102 | open | pdf.js reader: live acceptance trial |
| pyamzi/klaus-note-addon#43 | #103 | closed | Library: a rescan during a Library folder move can drop library_map.json entries |
| pyamzi/klaus-note-addon#44 | #104 | open | Library: refuse clashing names in Anki's own sidebar renames and drags |
| pyamzi/klaus-note-addon#45 | #105 | open | Reader: upgrade the vendored pdf.js from 3.11.174 to 4.x |
| pyamzi/klaus-note-addon#46 | #106 | open | Default accent zinc and Zinc base greys, matching KlausNote |
| pyamzi/klaus-note-addon#47 | #107 | open | Reader: a Marks document behind the bridge handlers |
| pyamzi/klaus-note-addon#48 | #108 | open | Indexing: the Index runner owns every way in (Preferences' Index Now bypasses it) |
| pyamzi/klaus-note-addon#49 | #109 | open | Status bar: derive the Task readout once for both renderers |
| pyamzi/klaus-note-addon#50 | #110 | open | Library: one model behind Browse's sidebar and the Add tab's tree |
| pyamzi/klaus-note-addon#51 | #111 | open | Preferences: Ollama install/pull/delete out of the dialog's closures |
| pyamzi/klaus-note-addon#53 | #112 | open | Library: an interrupted Preferences "Change…" folder move leaves moved PDFs unopenable |
