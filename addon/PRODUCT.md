# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

KlausMate is a PyQt6 addon running inside Anki (macOS today; Anki also
ships on Windows/Linux). Not web/ios/android: the UI is Qt widgets
styled with QSS from `klausmate/theme.py`, plus three embedded webview
surfaces (the restyled top toolbar, the bottom toolbar, and
`web/pdfjs_viewer.html`) where HTML/CSS tooling genuinely applies.
Impeccable's browser-side tooling is valid only on those webview
surfaces.

## Users

Primary user today: Pouya, a medical student, studying from dense
lecture-slide PDFs with high card volumes on exam-driven cycles — the
classic Anki heavy-use profile. Confirmed trajectory: **personal now,
public later** — a public AnkiWeb release is a realistic goal, so
first-run experience, safe defaults, licensing hygiene, and surviving
machines that aren't this one are product concerns, not nice-to-haves.

## Product Purpose

KlausMate ("Klaus") turns Anki into a lecture-PDF study cockpit. All
four jobs are confirmed as genuinely central, not ranked:

1. **Exam prep from lectures** — turn a lecture PDF into a curated deck
   fast (semantic curation: embed the PDF, match the collection, copy
   matches into a new deck).
2. **Daily review companion** — per-PDF retention scores tell the user
   what to study today (FSRS retrievability aggregated over each PDF's
   matched cards).
3. **Prioritization help** — the Library ranks lecture material by how
   poorly it is currently retained; study order falls out of the data.
4. **Annotation workspace** — reading and annotating PDFs (highlights,
   sticky notes, image crops) beside the cards is a primary activity in
   its own right.

Success means the lecture→deck→review loop lives entirely inside Anki:
no external PDF reader, no manual triage of what to study next.

## Positioning

Everything runs inside Anki against the user's own collection, and the
one AI capability is embeddings-only semantic search (Voyage cloud by
default; Ollama fully local as the private option; OpenAI as a second
cloud option). No chat, no generation, no autocomplete — those were
built and deliberately deleted (2026-08). A neighboring addon could not
truthfully claim: per-PDF retention scoring joined to FSRS, semantic
curation from the user's own lecture PDFs, and a native annotation
viewer, in one addon with no mandatory cloud dependency.

## Operating Context

- Lives inside Anki 26.x as an addon loaded via symlink; Anki must
  restart to pick up code changes. Multi-window (Anki stock); the
  addon deliberately does NOT embed Anki's windows (two attempts
  removed — a durable decision).
- Study ritual: import lecture PDFs into the Library (a user-chosen
  on-disk folder mirrored two-way), index them, curate decks per
  lecture, review daily guided by retention scores, annotate while
  reviewing.
- Coordination for development: multi-agent kanban board
  (`board/BOARD.md` via `board/board.py`), archived history in
  `board/ARCHIVE.md`.

## Capabilities and Constraints

- Anki's bundled Python 3.13 is bytecode-only; no venv, no numpy, no
  native code. Vendored pure-Python only (pypdf 6.11.0 is vendored).
- Headless testing = stubbed `aqt`/`anki` (see `.claude/skills/
  klaus-test`); Qt widgets are never constructed in tests.
- The addon package name `klausmate` (lowercase) is load-bearing
  (symlink, URLs, config); user-facing name is "KlausMate".
- Personal data boundaries: `user_files/` (PDFs, annotations, card
  index) and `meta.json` (API keys) are never staged, read, or shipped.
- **Licensing (material because of "public later"):**
  `klausmate/browse_highlight.py` is adapted from Glutanimate's
  highlight-search-results under AGPLv3 with header-retention terms —
  a public release must be AGPL-compatible or that module must be
  removed/relicensed. Vendored pypdf is BSD. The SynapsePro-derived
  theme/design conventions were adapted from its public source
  (`scripts/SynapsePro-main`); an AnkiWeb release should audit what is
  "inspired by" versus "copied" and attribute accordingly. Recorded as
  an open pre-release task, not yet resolved.
- Open decision: no AnkiWeb release date or versioning/update policy
  has been set.

## Brand Commitments

Volunteered and binding from the owner:

- Names: **"KlausMate"** (the addon, titles/menus) and **"Klaus"** (the
  short product name in prose and tooltips). The mixed usage is
  deliberate.
- Mark: the hand-drawn point-down pentagram star (traced from Pouya's
  sketch, `top_bar._STAR_PATH` is the single source of truth), drawn as
  an open accent-coloured stroke — never inside an icon square.
- Wordmark: "KlausMate" in Garamond, light weight (like Claude's serif
  wordmark).
- Visual language: the SynapsePro-derived Apple-system-palette token
  discipline in `klausmate/theme.py` — semantic tokens, identical
  light/dark key sets, user-selectable accent themes (six presets +
  custom colour), translucent Apple-material state veils, a documented
  radius/type scale enforced by tests. Seamless window chrome (top and
  bottom toolbars matching, frosted over custom backgrounds) is a
  committed identity feature.

## Evidence on Hand

- A real, live medical-study collection and PDF library exist on the
  owner's machine (FSRS on) but are private (`user_files/`, ignored) —
  design/test work uses scratch copies, never the real data.
- Vendored reference sources: `scripts/SynapsePro-main` (design
  reference), `References/highlight-search-results-main` (AGPL
  upstream), `References/addon-docs-main`.
- No testimonials, benchmarks, or public users exist — nothing may
  fabricate them.

## Product Principles

1. **The collection is sacred.** Curation copies, never moves; every
   mutation is undoable; tags are owned and reconciled, not sprayed.
2. **Local-first privacy is a feature.** Cloud embeddings are the
   convenient default, but a fully-local path (Ollama) must always
   exist and never degrade to mandatory cloud.
3. **Restyle, never rebuild, Anki.** Klaus lives inside Anki's own
   surfaces (toolbar restyled in place, Browse extended, stock
   multi-window). Attempts to replace Anki's shell failed twice and
   are permanently out of scope.
4. **One token module rules every surface.** No UI file hardcodes
   colour or type; a theme/accent change must reach every surface with
   zero per-surface code.
5. **Deliberate deletion.** Features that don't earn their place get
   removed fully (chat, autocomplete, single-window) — stale language
   about them is treated as a bug.

## Accessibility & Inclusion

No product-specific requirement established yet. Open decision for the
public release: baseline keyboard reachability and contrast on Klaus's
own dialogs (colour tokens already maintain light/dark contrast by
construction; a colour-square accent picker currently carries names
only in tooltips — noted for the pre-release audit).
