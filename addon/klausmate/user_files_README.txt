This folder stores Klaus data that survives add-on upgrades:

- pdfs/, pdf_originals/, annotations/ — your imported lecture PDFs, their
  pristine originals, and your highlights and notes.
- contexts/ — extracted PDF text, used to match cards to a PDF.
- card_index/, pdf_index/ — embedding vectors and match scores for
  semantic search, plus each PDF's sensitivity setting.
- drive.json, pdf_tabs.json — Library folders and open-tab state.
- runtime/ — the Klaus-managed Ollama install, if you chose local
  embeddings. Safe to delete after disabling "Manage Ollama
  automatically" in Klausmate Preferences.

Deleting anything else here loses that data permanently; Klaus keeps no
second copy. Do not edit these files by hand.
