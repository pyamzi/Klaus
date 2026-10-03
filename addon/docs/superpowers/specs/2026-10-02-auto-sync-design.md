# Automatic sync — design

Date: 2026-10-02. Status: draft for review.

## Intent

The user should never have to remember to press Sync. Klaus syncs with
AnkiWeb on its own, quietly, and the Sync button goes away. What the
button did — logging in, syncing on demand, choosing upload or download
for a full sync — moves to places that already exist.

Built into Klaus (decision b), not by bundling or depending on the
Auto Sync add-on (Robin Haupt, GPL-3, last commit 2023-11). That add-on
is read for its ideas only; no code is copied. Its strict mode checks
`aqt.dialogs.allClosed()` and main-window focus, which would likely
never pass in Klaus's single window (inferred, not tested).

## Decisions (from grilling, 2026-10-02)

| # | Decision |
|---|----------|
| Q1 | Syncs on any tab except review. |
| Q2 | After 2 idle minutes; AnkiWeb asked at most every 5 minutes; 30 s after leaving a review. |
| Q3/Q7 | The Sync button is hidden while logged in and auto sync is on. Logged out, it reads **Log In**. |
| Q4 | Failures retry silently; red status after 3 failures in a row; nothing at all while logged out. |
| Q5 | Anki's own sync on profile open/close is left alone. |
| Q6 | Preferences switch "Sync automatically", default on. Klaus stands down if the Auto Sync add-on is installed and enabled. |
| Q8 | Manual sync: Anki's `y` key, or a click on the sync entry in Klaus's status bar. |
| Q9 | A full sync never starts by itself. A red "Full sync needed — click to choose" stays until clicked; the click runs Anki's own sync, which asks upload or download. |
| Q10 | Switching it off brings the Sync button back at once and stops automatic syncs. |
| Q11 | **Log In** opens Anki's own AnkiWeb login window (`aqt.sync.sync_login`), which syncs once you are logged in. |

## Verified facts (Anki 26.09.2 bytecode, 25.09 source for bodies)

- `toolbar._create_sync_link()` returns one `<a class=hitem id="sync">`
  holding `<img id=sync-spinner>`; its pycmd is `sync` →
  `mw.on_sync_button_clicked()`. It is appended to `links` BEFORE
  `gui_hooks.top_toolbar_did_init_links(links, toolbar)` runs.
- `toolbar.set_sync_active` evals `getElementById('sync-spinner')` and
  `set_sync_status` evals `updateSyncColor`, which reads
  `getElementById("sync")`. **Deleting the link makes both throw**, so
  Klaus hides it and keeps both ids.
- `mw.on_sync_button_clicked()`: media syncing → show the media log;
  logged out → `sync_login(mw, then sync)`; else
  `_sync_collection_and_media`, which fires `sync_will_start`, runs
  `aqt.sync.sync_collection`, then `sync_did_finish` and `mw.reset()`.
- `aqt.sync.sync_collection` is unsuitable for unattended runs: it opens
  Anki's progress window every time (`taskman.with_progress(...,
  immediate=True)`), a warning dialog on every error
  (`handle_sync_error` → `show_warning`), a "Collection synced" tooltip
  on success, and goes straight into `full_sync`'s upload/download
  question when one is needed.
- `mw._can_sync_unattended()` = logged in, not safe mode, not restoring
  a backup.

## Design

### `auto_sync.py` (new; aqt-free above its "aqt glue" divider)

**Policy (pure).** `IDLE_S = 120`, `MIN_GAP_S = 300`,
`AFTER_REVIEW_S = 30`, `AFTER_REVIEW_QUIET_S = 5`, `FAIL_LIMIT = 3`,
`TICK_MS = 10_000`.

`due(now, *, last_input, last_attempt, review_left_at, state, ready)
-> bool` is True only when all of these hold:

- `ready`: enabled, not standing down, `_can_sync_unattended()`, no
  sync of either kind running, no media sync running, no full sync
  pending;
- `state != "review"`;
- `now - last_attempt >= MIN_GAP_S`;
- and either `now - last_input >= IDLE_S`, or a review ended at least
  `AFTER_REVIEW_S` ago with no attempt since, and there has been no
  input for `AFTER_REVIEW_QUIET_S`. A short quiet window keeps a sync
  from starting under the user's hands.

**Activity.** An app-wide event filter records the time of the last
KeyPress, MouseButtonPress or Wheel event. It only records; it never
consumes events.

**Tick.** A `QTimer` (`TICK_MS`) on `mw` runs while a profile is open:
it starts on `profile_did_open` and stops on `profile_will_close`, so it
never races Anki's close sync. Each tick:

1. Redraws the toolbar if the login state changed since the last draw.
   This covers logout in Anki's Preferences.
2. Calls `due(...)`, and if it is True, runs one quiet sync.

`state_did_change` records `review_left_at`.

**Quiet sync.** It is Klaus's own call of the same backend method; it
never goes through `sync_collection`:

1. `gui_hooks.sync_will_start()`. The status bar's existing `sync`
   sync icon spins (2026-10-02 revision: icons replace the text entry).
2. `mw.taskman.run_in_background(lambda: mw.col.sync_collection(auth,
   mw.pm.media_syncing_enabled()), done)`. This uses the collection,
   so collection ops queue behind it.
3. `done`, on the main thread:
   - `mw.col._load_scheduler()`.
   - **`Interrupted`:** nothing.
   - **`SyncError` of kind AUTH:** `mw.pm.clear_sync_auth()` and a
     toolbar redraw, so the button reads **Log In**. No dialog.
   - **Any other error:** `failures += 1`. At `FAIL_LIMIT` the entry
     turns red. No dialog.
   - **Success:**
     - Apply `set_host_number`, then `new_endpoint` if present.
     - Show `server_message` if present, through `showText`. AnkiWeb
       uses it for messages the user must see, and Anki shows it the
       same way.
     - `failures = 0`.
     - If the result is `NO_CHANGES`, `mw.media_syncer.start_monitoring()`.
     - Otherwise set **full sync pending**. Nothing more is sent, and
       auto sync pauses until a sync started by the user clears it.
   - In every case:
     - `mw.col.models._clear_cache()`
     - `gui_hooks.sync_did_finish()`
     - `mw.reset()`, which is what Anki does after a sync
     - `mw.toolbar.update_sync_status()`

Anki's own syncs (the `y` key, a status-entry click, Log In, profile
open/close) are watched through `sync_will_start` and `sync_did_finish`.
A sync running counts as busy. When one finishes, Klaus counts it as an
attempt and clears **full sync pending** and the failure count, because
Anki's own flow already showed the user any error.

**Stand-down.** `standing_down(addon_manager) -> bool` is True when any
installed, enabled add-on has a manifest or meta name containing
"auto sync" (case-insensitive). The check uses `allAddons()` first,
then `isEnabled`, the same as Image Occlusion's guard. It matches by
name because the add-on's AnkiWeb ID couldn't be confirmed, and a
GitHub install has a different folder name anyway. While Klaus stands
down:

- nothing is scheduled;
- the toolbar is untouched;
- the Preferences switch is disabled, with the description "The Auto
  Sync add-on is installed and handles syncing."

### The Sync button (`top_toolbar_did_init_links`)

Find the link containing `id="sync"` and replace it in place:

| Condition | Link |
|---|---|
| Standing down, or switch off | Untouched |
| Logged out | Same `<a id="sync">` and spinner, label **Log In**, title "Log in to AnkiWeb", same `sync` pycmd. Anki's handler logs in through `sync_login` and then syncs. Its `_refresh_after_sync` only calls `toolbar.redraw()`, which doesn't rebuild links, so Klaus calls `mw.toolbar.draw()` itself when the login state changes, and that hides the button. |
| Logged in | Same element with `style="display:none"`. Both ids stay, so Anki's spinner and colour scripts keep working. |

`link_html(original, *, logged_in, active) -> str` is pure.

### The sync entry (status bar)

**Revised 2026-10-02 (user):** the entry is an icon at the far bottom
right, not text — cloud with a check (synced), spinning arrows
(syncing), plain cloud (never synced), red cloud with an ✕ (failed), red
up/down arrows (full sync needed). Hovering shows a tooltip that says
what the icon means and what a click does, e.g. "Synced with AnkiWeb
4 min ago. Click to sync now." The table below lists the original text
states; each is now that state's icon plus tooltip.

A small clickable entry beside the task readout. It appears in the
Decks and overview bottom row (`bottom_row`) and in the Add and Browse
strips (`status_bar.StatusBar`). It is not shown during review, whose
row is untouched, and it is hidden while logged out (the top bar shows
**Log In**).

| State | Text | Colour |
|---|---|---|
| Synced | "Synced just now" / "Synced 4 min ago" / "Synced 2 h ago" | muted |
| Never synced | "Not synced yet" | muted |
| `FAIL_LIMIT` reached | "Sync failed — click to retry" | red |
| Full sync pending | "Full sync needed — click to choose" | red |

- **Click:** it calls `mw.on_sync_button_clicked()` a tick later, by
  the `bridge_reentrancy` deferral rule. That is Anki's own sync, with
  progress and error dialogs, because the user asked for it. For a
  pending full sync, this is the call that shows upload or download.
- **Last sync time:** it comes from the collection, so the time is the
  same whichever path synced. The source is `select ls from col`, in
  milliseconds (0 means never).
- **Refresh:** the entry re-renders on each tick and on
  `sync_did_finish`.
- **Pure helpers:** `entry_text(now, last_sync, failures,
  full_pending) -> (text, red)` and `ago(seconds) -> str`.

### Preferences

- Key `auto_sync`: `(True, _bool(True))` in `prefs_state._SPEC`, and
  `"auto_sync": true` in `config.json` (documented in `config.md`).
- An `Md3Switch` row on General, "Sync automatically", with the
  description "Sync with AnkiWeb in the background and hide the Sync
  button. Press Y or click the sync icon to sync now."
- Commit effect `("auto_sync", value)` → `auto_sync.set_enabled(value)`,
  which redraws the toolbar and starts or stops the tick.

### Wiring

`__init__` calls `auto_sync.setup()` once. It registers:

- the hooks above;
- the event filter;
- the toolbar link hook.

## Out of scope

- Changing Anki's own open/close sync, its "sync on open/close"
  preference, or media-sync settings.
- Network pre-checks, like the Auto Sync add-on's ping of 8.8.8.8. A
  silent failure costs nothing.
- Syncing during review.
- A setting for the intervals. They are constants until someone asks.

## Risks

- **The quiet sync holds the collection for a second or two.** A
  main-thread collection call made during that time waits. The idle and
  quiet-window gates keep a sync from starting while the user is
  typing.
- **`mw.reset()` after each quiet sync redraws the deck list.** The
  user has been idle, so nothing is lost, but a deck screen left open
  redraws at most every 5 minutes.
- **Anki's `toolbar.redraw()` doesn't rebuild links.** Only `draw()`
  re-runs `top_toolbar_did_init_links`. Klaus calls `mw.toolbar.draw()`
  whenever the login state changes: on each tick and at the end of every
  sync. Without that, "Log In" would stay after you log in.

## Testing

`tests/test_auto_sync.py`, headless:

- **`due`, as a table:**
  - idle 119 s versus 120 s;
  - 299 s versus 300 s since the last attempt;
  - review state;
  - after review at 29 s versus 30 s;
  - after review with input 4 s versus 5 s ago;
  - logged out;
  - standing down;
  - switch off;
  - full sync pending;
  - an Anki sync running;
  - media running.
- **Quiet-sync results, on a fake collection:**
  - `NO_CHANGES` starts media monitoring;
  - a full-sync result sets pending and sends nothing more;
  - an AUTH error clears auth and shows no dialog;
  - a network error counts silently and turns red at 3;
  - `Interrupted` does nothing;
  - `sync_will_start` and `sync_did_finish` fire around every run.
- **`link_html`:** both ids are kept in the hidden and Log In forms;
  the link is untouched when the switch is off or standing down; other
  links are left alone.
- **`standing_down`:** a manifest name match, a disabled add-on, and a
  missing folder.
- **`entry_text` and `ago`:** every row of the entry table.
- **Preferences:** `prefs_state` has the key, its default and the
  `auto_sync` effect.

Live checklist (the user):

1. Logged in: there's no Sync button, and the entry reads "Synced …".
2. Leave Anki idle on Decks for over 2 min after a change: it syncs
   with no window, and the time updates.
3. Finish a review: about 30 s after leaving review it syncs.
4. Turn Wi-Fi off: no dialogs; after about 15 min the entry is red;
   Wi-Fi back on, click it, and it syncs.
5. Log out in Anki's Preferences: the top bar shows **Log In**; it
   opens AnkiWeb's login, syncs, and the button hides.
6. Turn the switch off: Anki's Sync button is back and there are no
   automatic syncs.
7. Press `y`: Anki's normal sync runs.
