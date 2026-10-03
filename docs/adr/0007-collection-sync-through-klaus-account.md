# Collections sync through the Klaus Account, automatically, on Anki's sync protocol

> Domain superseded by ADR-0008: klaus.ink is now klaus.so (auth.klaus.so for the Klaus Account, note.klaus.so for the web app).

Klaus syncs the Collection with klaus.ink under the user's Klaus Account, not with AnkiWeb. klaus.ink runs Anki's own sync server (rslib's, AGPL) behind Klaus Accounts, so Klaus's client is rslib's sync client pointed at klaus.ink, and AnkiMobile and AnkiDroid can still sync with the same Collection through their custom-sync-server setting. Users sign in in their browser (OAuth with PKCE); the token klaus.ink hands back is the sync key, kept in the system keychain. Syncing is automatic: on open, on quit, and in the background whenever the Collection has changed or klaus.ink has changes (Anki's `syncStatus`, which checks locally for free and asks the server at most every 5 minutes), started only after ~30 s without activity, because a sync holds the Collection for its network round-trip. The contract klaus.ink must implement is in `docs/klaus-ink-sync.md`.

This supersedes the milestone-1 spec's AnkiWeb sync and its "Klaus Account out of scope", and ADR-0003's "later Collection sync": Collection sync is the first thing the Klaus Account does.

## Consequences

- A full sync (a schema change on one side, or both) still needs the user's choice; it is the one sync Klaus can't do on its own, and it's asked for on the deck list.
- An existing Anki user moves to Klaus by exporting a `.colpkg` from Anki, importing it into Klaus (#17), letting Klaus upload it, then pointing their phone's Anki at klaus.ink.
- Until klaus.ink exists, sync is tested against rslib's sync server and a fake authorisation server started inside the test binary.

## Considered Options

- AnkiWeb: rejected by the product decision that sync belongs to the Klaus Account.
- A Klaus-specific sync protocol: rejected for now; Anki's mobile apps couldn't sync with it, and automatic sync doesn't need it.
- Email and password inside Klaus: rejected; browser sign-in brings password managers, two-factor sign-in, social sign-in and the subscription with it.
