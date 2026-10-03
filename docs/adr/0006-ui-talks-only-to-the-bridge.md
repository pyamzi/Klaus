# Klaus's UI talks only to the bridge, so app.klaus.ink can serve it

> Domain superseded by ADR-0008: klaus.ink is now klaus.so (app.klaus.so for the Klaus account, note.klaus.so for the web app).

Klaus's screens (and the Anki pages it hosts) reach the Collection and the host only through the bridge's `/_anki/<method>` HTTP contract: backend calls, plus host requests (native dialogs, navigation, file pickers) as named hooks. Svelte code never calls Tauri APIs. The desktop app serves the UI from its local bridge today; later, app.klaus.ink will serve the same UI against a server-side bridge, which answers the same methods for a signed-in Klaus Account and implements the hooks in the browser.

## Consequences

- New host features are added as bridge hooks or bridge-answered methods, not `@tauri-apps/api` calls in the UI.
- Browser-only constraints already hold (in-page `<dialog>` for input, `alert`/`confirm` routed through hooks), so the web build needs no UI fork.
- The web version needs its own hosting of rslib per user, storage and auth; that work belongs with the Klaus Account (ADR-0003), not the UI.
