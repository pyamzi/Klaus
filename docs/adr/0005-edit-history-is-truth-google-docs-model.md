# Material edits are a server-ordered history, Google Docs style

So Materials can later be co-edited live, every edit to a Material (Page text, Document annotations and Links) is recorded as an operation in an edit history, the way Google Docs works: with a Klaus Account, klaus.ink orders and stores the history and is authoritative; offline edits queue locally and merge on reconnect; without an account the local history is authoritative. The `.md` and `.pdf` files are regenerated from the history after every change, and edits made to them by outside tools are detected, diffed, and folded back in as operations.

## Considered Options

- File as truth, merged at sync time: simpler, but cannot grow into live co-editing without migrating every user's data.

## Consequences

The edit history is real user data: it must be backed up, and it is the only non-file source data in Klaus (amends ADR-0002). Whether the merge algorithm is OT or a CRDT (Yjs, Loro, Automerge) is an implementation choice left open.
