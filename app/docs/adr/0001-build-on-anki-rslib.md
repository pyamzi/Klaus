# Build on Anki's rslib; Klaus is AGPL-3.0

Klaus embeds Anki's Rust backend (`rslib`) as its flashcard core instead of writing its own data model and scheduler. This gives real Collection compatibility, `.apkg` import/export, Anki's scheduler including FSRS, and a path to AnkiWeb sync, all in the same language as the Tauri shell.

## Consequences

`rslib` is AGPL-3.0, so Klaus is AGPL-3.0. In exchange, code from the AGPL reference apps (SiYuan, LeedPDF) and GPL Zed crates can be ported, not just studied.

## Considered Options

- Own data model with one-way `.apkg` import: rejected, months of rework before the first review screen.
- Clean break from Anki: rejected, loses existing decks and the mobile Anki clients.
