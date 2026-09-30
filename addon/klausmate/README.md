# KlausMate: lecture PDFs and local matching

**Privacy:** Embeddings run against the configured local Ollama server. Runtime
and model downloads use the network. An external MCP client can request lecture
text, images and card context, and its chosen model provider may receive
that context. Local inference in Klaus does not make external-client processing
local. See [configuration](config.md), [embeddings](embeddings.py)
and [endpoint](anki_endpoint.py).

## What it does

- **Adding a lecture PDF** — drop it onto the deck list or a deck's
  overview screen, use the **Browse…** button on the square there, or drop
  it straight into the Library window. Every route lands in the same
  library.
- **Card matching** — right-click a PDF in the Library and choose **Add to
  Search Index**. Klaus reads the PDF, searches your whole collection by
  meaning, and tags every card that lecture covers with its own
  `!Library::…` tag, so the matches are one click away in Anki's tag
  sidebar. Re-run it as **Update Search Index** after you add cards.
- **Library** — the first section of Browse's sidebar lists every PDF
  you've imported, in folders mirrored as real folders on disk. Each row
  shows a retention % (how much of its cards you'd recall right now).
  Click a PDF to see its cards; double-click it to read it in place of the
  cards (Esc or a click goes back). Anki's own Rename, drag and Delete act
  on the PDF itself. Right-click adds Match Sensitivity…, Retention
  History… and Show in Finder.
- **Copying matches into a deck** — select the notes you want in Browse and
  use **Notes → KlausMate: Create Curated Deck from Selection…**. It's one
  undo step, and your originals are untouched.
- **PDF viewer** — opens PDFs from the Library or the editor's drop panel.
  Drag-select text and copy it (**Cmd+C** or right-click **Copy**);
  **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**,
  to copy it as an image. Highlight text and attach sticky notes — both are
  baked into the stored PDF as real annotations, so they're still there if
  you open the file elsewhere.
- **Image cropping** — right-click or double-click any image in a note
  field, drag a crop box, and the result saves as a **new** media file. The
  original image, and any other note using it, is untouched.

## Local model setup

Open **Tools → KlausMate Preferences… → Local models** (the toolbar star
also opens Preferences). The initial endpoint is `http://127.0.0.1:11434`
and embedding model is `nomic-embed-text`.

1. Use **Install/start** to authorize installation or start a local Ollama
   runtime, or enter the endpoint of your own local Ollama server. **Automatic
   management** starts an installed runtime on profile open; it does not download
   a runtime or model automatically. See [Ollama's official quickstart](https://docs.ollama.com/quickstart).
2. Use **Refresh** to inspect **Installed models**. Enter `nomic-embed-text`
   under **Download model** and choose **Pull** if needed. Select a model,
   check **Embedding model**, then **Save**. Changing models offers a local
   re-index. **Update runtime**, **Stop managed server** and confirmed
   **Delete** manage runtime/model resources; progress is shown during downloads.
3. Optional external client: install a separate Python **3.9 or newer**, then
   use **External clients → Copy configuration**. Merge the `klaus` entry into
   Claude Desktop's `mcpServers` configuration and restart that client. Keep
   Anki open with a profile loaded. The copied block uses absolute Python,
   bridge and discovery-file paths, without a token or port. Copy again after
   moving Python or the add-on. Klaus does not modify the client's settings.
   Follow the [official local MCP setup guide](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers).

`current_view` supplies view metadata; `current_page` supplies slide text,
selection and an image when available. Collection writes require
approval in Anki. Treat lecture content as untrusted input. The bridge is local;
this is not a public endpoint or a direct ChatGPT connector. Real Claude Desktop
and live Anki integration remain installation checks, not automated-test claims.

The exact defaults and controls are documented in [configuration](config.md)
and implemented by [Preferences](manage_models.py).

## Matching

Lecture recording lives in the Klaus app, not the add-on.

Cosine sensitivity controls matching and retention. There is no reasoning judge
or Doubtful menu. Existing historical tags are preserved. See [tag sync](tag_sync.py)
and [matching](retention.py).

## Reclaiming runtime disk space

Turn off **Automatic management**, **Save**, and stop the managed server before
removing `user_files/runtime/`. Model storage belongs to the configured Ollama
server; use the confirmed **Delete** control for installed models. See
[runtime management](ollama_runtime.py). Keep backups of personal library data.

## Tags

Klaus's tags live under `!Library` (the leading `!` keeps them near the top
of Anki's tag sidebar). Indexing a PDF gives it one tag of its own —
`!Library::<folder>::<PDF name>` — whose members are exactly the cards that
lecture covers; rename it in Anki's tag sidebar and the PDF is renamed with
it. Notes copied into a deck from Browse also get a permanent
`!Library::Curated`. Upgrading from an older version that used
`klaus::`-prefixed tags renames them automatically, once, the first time you
open Anki after updating.

## Support

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY).
