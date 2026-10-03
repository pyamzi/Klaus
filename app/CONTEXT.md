# KlausNote

KlausNote is a study app: spaced-repetition Cards on an Anki Collection, plus Documents, Pages and Recordings that link to each other and to Cards.

## Language

### Flashcards

**Collection**:
The user's Anki collection, the same data Anki itself reads and writes.
_Avoid_: Database, library, profile

**Note**:
An Anki note: one set of field values that generates one or more Cards.
_Avoid_: Fact, entry

**Card**:
A single reviewable prompt generated from a Note, scheduled independently.
_Avoid_: Flashcard (in code and docs), item

### Materials

**Material**:
Anything the user studies from in KlausNote: a Page or a Document. Lives as a plain file in the user's library folder.
_Avoid_: Note, file, resource, item

**Page**:
A Markdown file with LaTeX math; the Wikipedia-style article of KlausNote.
_Avoid_: Note, text note, article, markdown file

**Document**:
A PDF file, imported or created blank in KlausNote. Its annotations and Transcripts live inside the PDF.
_Avoid_: PDF (as a domain term), file, slides

**PDF page**:
One page of a Document. Always qualified; a bare "Page" never means this.
_Avoid_: Page, slide

### Linking

**Section**:
The span of a Material under one level-1 or level-2 heading; the unit that is linked, embedded, and matched to Cards. Deeper headings stay inside their Section.
_Avoid_: Chunk, block, passage

**Link**:
A definite, user-accepted connection from a Material to a Section or Material, as in Wikipedia: a `[[…]]` in a Page, or a hidden link stored inside a Document. Matching headings only suggest Links; KlausNote never inserts one on its own. Renaming a heading updates every Link to it.
_Avoid_: Backlink, reference, relation

**Unresolved Link**:
A Link whose target Section does not exist yet; it resolves when a matching Section appears.
_Avoid_: Red link, broken link, dangling link

**Related**:
A ranked, embedding-similarity suggestion between a Section and another Section or a Card. Never treated as definite; can change when content or the model changes.
_Avoid_: Similar, match, recommendation

**Pin**:
A user's explicit choice that a Card belongs to a Section. Always outranks Related.
_Avoid_: Attach, bookmark

**Hide**:
A user's explicit choice that a Related Card does not belong to a Section. Always outranks Related.
_Avoid_: Dismiss, block, suppress

### Recording

**Recording**:
One continuous audio capture, such as a lecture or a meeting.
_Avoid_: Lecture, audio, session

**Clip**:
The part of a Recording captured while one PDF page was in view, attached to that PDF page. It can be moved to another PDF page afterwards.
_Avoid_: Segment, snippet

**Transcript**:
The text of a Clip, stored on its PDF page like speaker notes; or of a whole Recording made with no Material open, which becomes a Page.
_Avoid_: Captions, notes

### Screens

**Home**:
The first screen: the decks with their due counts, and the way into everything else.
_Avoid_: Deck list, deck browser, main page, dashboard

**Study**:
The screen that shows one Card at a time from one deck and takes the answer; a Study Session is one sitting on it. "Review" is what Anki calls a Card's scheduling event, never this screen.
_Avoid_: Review (as a screen), reviewer, study mode

**Browser**:
The table of Cards or Notes with search, columns and bulk actions, Anki's browser rebuilt in KlausNote.
_Avoid_: Browse (as a noun), card list, search page

**Sidebar**:
The column of decks, Materials and tags on the left of the Browser (and the Library, when it exists) on desktop and web. Home has none: its navigation is the top bar's chips, as in the add-on.
_Avoid_: Nav, drawer, side panel

**Dashboard**:
Home's main pane: the grid of widgets (Decks, Review Heatmap, later stats) a person arranges in Edit Widgets, the same screen as the add-on's deck screen.
_Avoid_: Deck browser, widget area, home page

**Command Palette**:
The searchable list of every action, opened with ⌘K, each with its shortcut.
_Avoid_: Quick actions, launcher, omnibar

### Products

**KlausNote**:
This app. A standalone desktop product built on Anki's own engine.
_Avoid_: Klaus Note, Klaus, KlausBook, Klaus App

**KlausNote for Anki**:
The sibling Anki add-on (`klaus_note`) that runs inside Anki desktop and shares formats with KlausNote.
_Avoid_: Klaus Addon, KlausMate, the plugin

**Klaus account**:
The user's identity, signed into at app.klaus.so (ADR-0008) from KlausNote. The page app.klaus.so shows after sign-in is the account dashboard, not this app's Dashboard.
_Avoid_: Klaus Plus, profile, login
