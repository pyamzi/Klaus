# Materials are plain PDF and Markdown files; everything else is cache or Anki tags

Every Material is a plain file in a user-chosen folder so any other tool (Preview, Acrobat, Zotero, Obsidian, an AI agent) can read it without Klaus. Annotations are standard PDF annotations inside the Document, Clip Transcripts are stored on their PDF page, and OCR writes an invisible text layer into the PDF. Recording audio sits beside the Document as `.m4a`. Pins and Hides are Anki tags on the Note (`klaus::pin::…`), so they sync through AnkiWeb. Links live in the Materials too: `[[…]]` in Pages, and hidden `klaus:`-prefixed annotations in Documents that other tools do not display. Embeddings, OCR results and the Link index are a rebuildable cache in app storage, never source data, never synced.

## Consequences

- Klaus has no proprietary Material format and no sidecar. It reads the Klaus Addon's annotation JSON v1 when present but never writes it; Klaus's own PDF annotations carry a `klaus:` name prefix so the add-on's bake treats them as external marks and preserves them.
- Whiteboards (infinite canvas) are dropped for now: no PDF/Markdown representation fits them.

## Considered Options

- One Klaus canvas format for Documents and Whiteboards: rejected, unreadable by other tools.
- Audio embedded in the PDF: rejected, makes Documents too large to email or sync.

## Amendment (2026-10-01): edit history

To allow live co-editing later, a Material's edit history (see ADR-0005) is the one source of data besides the files. The files are always kept current from it, so other tools still see everything.
