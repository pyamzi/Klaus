# KlausMate: a lecture-PDF library with local card matching for Anki

Klaus organizes lecture PDFs and matches them to cards using local Ollama
embeddings. Lecture recording lives in the Klaus app, not the add-on. Matching
and duplicate detection use cosine thresholds. PDF viewing, annotations,
retention scores and image cropping remain part of the add-on.
See the [user guide](klausmate/README.md) and [architecture guide](AGENTS.md).

**Privacy:** Embeddings run against the configured local Ollama server. Runtime
and model downloads use the network. An external MCP client can request lecture
text, images and card context, and its chosen model provider may receive
that context. Local inference in Klaus does not make external-client processing
local. See [configuration](klausmate/config.md), [embeddings](klausmate/embeddings.py)
and [endpoint](klausmate/anki_endpoint.py).

## What it does

| Feature | How to use |
|---------|------------|
| **One window** | Decks, Add and Browse are tabs of Anki's main window: the toolbar's three links switch between them. The Add tab is your Library on the left, the PDF reader in the middle and Anki's Add editor on the right — click a PDF, read, drag a region into a field. Edit Current opens in a panel on the right. Set `single_window` to `false` in the add-on config for Anki's separate windows. |
| **Adding a PDF** | Click **Add to Library** at the bottom of the deck list or a deck's overview, drop a lecture PDF on either screen, or drop it straight into the Library window. |
| **Card matching** | Right-click a PDF in the Library → **Add to Search Index**. Klaus searches the whole collection by meaning and tags every card that lecture covers with the PDF's own `!Library::…` tag. |
| **Library** | The **Library** link in the top toolbar opens a window listing every PDF you've imported, in folders you create, each with a retention score, card/note counts, and a right-click menu to index, re-tag, suspend, chart, or open it. |
| **Copying matches into a deck** | Select notes in Browse → **Notes → KlausMate: Create Curated Deck from Selection…**. One undo step, originals untouched. |
| **PDF viewer** | Native viewer opened from the Library or the editor's drop panel — text selection, page/slide image copy, highlights with sticky notes baked in as real PDF annotations. |
| **Image cropping** | Right-click or double-click an image in a note field to crop it; saves as a new media file. |

---

## Installation and requirements

Use [Anki](https://apps.ankiweb.net/) with Qt PDF support for the native viewer.
This local build has automated checks; compatibility across native Anki versions
and operating systems still requires installation verification.

Build with `bash scripts/package.sh`, then choose **Tools → Add-ons → Install
from file…**, select `dist/klausmate.ankiaddon`, and restart Anki. Developers can
copy or symlink `klausmate/` into `addons21/` instead. Locate that folder using
**Tools → Add-ons → View Files**. The package includes vendored pypdf.

## Local model setup

Open **Tools → KlausMate Preferences… → Local models** (the toolbar star
also opens Preferences). The initial endpoint is `http://127.0.0.1:11434`
and embedding model is `nomic-embed-text`.

1. Use **Install/Start** to authorize installation or start a local Ollama
   runtime, or enter the endpoint of your own local Ollama server. **Automatic
   management** starts an installed runtime on profile open; it does not download
   a runtime or model automatically. See [Ollama's official quickstart](https://docs.ollama.com/quickstart).
2. Use **Refresh** to inspect **Installed models**. Enter `nomic-embed-text`
   under **Download model** and choose **Pull** if needed. Select a model,
   check **Embedding model**, then **Save**. Changing models offers a local
   re-index. **Update Runtime**, **Stop Managed Server** and confirmed
   **Delete** manage runtime/model resources; progress is shown during downloads.
3. Optional external client: install a separate Python **3.9 or newer**, then
   use **External clients → Copy Configuration**. Merge the `klaus` entry into
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

The exact defaults and controls are documented in [configuration](klausmate/config.md)
and implemented by [Preferences](klausmate/manage_models.py).

## Source and packaging

- [embeddings.py](klausmate/embeddings.py), [ollama_client.py](klausmate/ollama_client.py),
  [ollama_runtime.py](klausmate/ollama_runtime.py), [ollama_setup.py](klausmate/ollama_setup.py): local embedding/runtime management.
- [anki_endpoint.py](klausmate/anki_endpoint.py) and [mcp_stdio_bridge.py](klausmate/scripts/mcp_stdio_bridge.py): authenticated local tools and external-client bridge.
- [config.json](klausmate/config.json) and [config.md](klausmate/config.md): defaults and reference.
- [package.sh](scripts/package.sh): stages only `klausmate/`, updates manifest build
  time, excludes `meta.json*`, bytecode and personal `user_files/`, and adds only
  the storage README under `user_files/`. The archive has no wrapper directory.

The [completion report](docs/superpowers/reports/2026-09-19-local-model-reversion.md)
records commits, verification and the local package hash. This build is not
published or merged. [ANKIWEB.md](ANKIWEB.md) is listing copy for a future release.

## License

See the existing [repository license](LICENSE), [packaged license](klausmate/LICENSE)
and [vendored pypdf license](klausmate/vendor/pypdf-6.11.0.dist-info/licenses/LICENSE).
External runtimes and models have their own license terms; this change does not
create new license grants.

## Support

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY).
