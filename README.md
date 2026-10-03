<p align="center"><img src="static/klaus-logo.svg" width="96" alt="Klaus logo"></p>

<h1 align="center">KlausNote</h1>

<p align="center">An open-source study app built on Anki's engine: spaced-repetition flashcards today, with PDF annotation, lecture recording and Markdown notes on the way.</p>

---

KlausNote is a desktop app (Tauri + SvelteKit) that runs on [Anki](https://apps.ankiweb.net)'s own Rust core. Your decks, review history and scheduling (including FSRS) behave exactly as they do in Anki, and KlausNote adds a place for the material you study from: PDFs, lecture recordings and Markdown pages that link to each other and to your cards.

> **Status: early development.** Milestone 1 (everything you use Anki for, in KlausNote) is in progress. macOS is the first target; Windows and Linux build but aren't release targets yet.

## What works today

- **Deck list** with new / learning / due counts.
- **Review** with Anki's card rendering: templates and styling, cloze, type-in answers, MathJax and images. Space or Enter reveals the answer, 1 to 4 grade it, and U undoes.
- **Adding notes** with Anki's own editor, including pasted images.
- **Importing `.apkg`** decks.
- **Deck options and FSRS** with Anki's deck-options page: daily limits, learning steps, desired retention and parameter optimisation.
- **Browser**: Anki's search syntax, a Cards/Notes table with sortable, configurable columns, a sidebar (saved searches, decks, note types, tags, flags), Anki's editor for the selected note, and a card preview.
- **Deck management**: create, rename and nest (`Parent::Child`), delete with undo, collapse and expand, plus filtered decks (build, rebuild and empty).

## Roadmap

Milestone 1 is tracked in [issue #4](../../issues/4). Still to come:

- Browser bulk actions
- Review actions: bury, suspend, flag and edit; card info; audio
- Sync through your Klaus account (klaus.ink): automatic, with AnkiMobile and AnkiDroid able to sync with it too
- Note types, change notetype and image occlusion
- Import, export and backups
- Stats and Check Database
- A native macOS shell and preferences

Later milestones add **Documents** (PDF annotation), **Linking** (sections, links and related material), **Recordings** (lecture audio and transcripts embedded in PDFs), **Pages** (Markdown and LaTeX), a **Klaus account**, and **card generation**.

## How it works

```
┌────────────── Tauri window (WKWebView) ──────────────┐
│ KlausNote screens (Svelte 5)    Anki's pages (Svelte)    │
└───────────────┬──────────────────────────────────────┘
                │  POST /_anki/<method>  (protobuf, Anki's contract)
┌───────────────▼──────────────────────────────────────┐
│ Backend Bridge (Rust, 127.0.0.1, per-launch token)   │
│ allowlist → Anki rslib Backend → Collection          │
└──────────────────────────────────────────────────────┘
```

- Anki's `rslib` is a pinned git submodule (`vendor/anki`). KlausNote calls it through one seam, the **Backend Bridge** (`crates/bridge`), which serves the same `/_anki/<method>` HTTP contract Anki's desktop app uses. That lets Anki's Svelte pages (editor, deck options, import, graphs) run unmodified.
- KlausNote's own screens (deck list, reviewer) live in `src/`. Cards render in a sandboxed frame using Anki's reviewer code, and card scripts can't reach your Collection.
- KlausNote keeps its own Collection in its app data folder. It never opens Anki desktop's files directly; it syncs through your Klaus account on klaus.ink, using Anki's sync protocol ([ADR 0007](docs/adr/0007-collection-sync-through-klaus-account.md)).

The design decisions are in [`docs/adr`](docs/adr), and the vocabulary (Collection, Note, Card, Document, Page…) is in [`CONTEXT.md`](CONTEXT.md).

## Build from source

Prerequisites: Rust (toolchain pinned in `rust-toolchain.toml`), Node 22, and `protoc` (`brew install protobuf` on macOS).

```sh
git clone --recurse-submodules https://github.com/pyamzi/klaus-note.git
cd klaus-note
git -C vendor/anki submodule update --init --depth 1 ftl/core-repo ftl/qt-repo
npm install
npm run tauri dev
```

The first build compiles Anki's backend and its web pages, which takes a few minutes. After that:

```sh
cargo test -p klaus-bridge    # bridge tests against a real Collection
npm run check                 # typecheck the frontend
npx tauri build --bundles app # build KlausNote.app
```

See [`AGENTS.md`](AGENTS.md) for the development notes.

## License

KlausNote embeds Anki's `rslib`, which is licensed under the GNU AGPL v3, so KlausNote is **AGPL-3.0-or-later** ([LICENSE](LICENSE), [ADR 0001](docs/adr/0001-build-on-anki-rslib.md)). KlausNote is not affiliated with or endorsed by Ankitects.
