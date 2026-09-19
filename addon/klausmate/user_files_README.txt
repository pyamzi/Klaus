This folder stores Klaus data that survives add-on upgrades.
Implementation references are relative to the add-on folder one level up.

- pdfs/, pdf_originals/, annotations/: imported PDFs, originals and annotations
  (pdf_handler.py).
- contexts/: extracted PDF text; card_index/ and pdf_index/: local vectors,
  matches and per-PDF sensitivity (card_index.py, pdf_index.py).
- drive.json, pdf_tabs.json: Library folders and viewer state (drive_store.py,
  pdf_handler.py). backgrounds/: copied background images (background.py).
- recordings/: audio chunks awaiting local transcription. Failures remain for
  retry when recording that lecture again; successfully processed chunks are
  removed. pages/: page records with slide text and transcript segments
  (lecture_recorder.py, page_store.py).
- runtime/: Klaus-managed Ollama runtime (ollama_runtime.py). Disable Automatic
  management, Save and stop the managed server before removing this install.
  Ollama model storage belongs to the configured server, not necessarily here.
- mcp_connection.json: private runtime discovery for the external MCP bridge
  (anki_endpoint.py, scripts/mcp_stdio_bridge.py). Contains the current local
  address and token. Do not share it. A fresh token is generated on endpoint
  startup; matching discovery is removed on shutdown. A crash may leave a stale
  file until the next startup. The bridge reads it for each request; copied
  client configuration contains only stable paths, no credentials. POSIX mode
  0600 is tested; native Windows ACL privacy still needs verification.

Runtime/model downloads use the network. Klaus's embedding/transcription
inference is local. An external client's selected provider may receive the
context that client requests. Keep backups of personal data before deleting
files. Do not hand-edit runtime discovery or storage records.
