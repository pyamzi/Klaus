Place vendored pure-Python dependencies here. The add-on auto-adds this
folder to sys.path on startup.

To enable PDF support without requiring users to install anything:

    cd klaus_note
    pip install --target vendor pypdf

That's all. Restart Anki — the "Manage lecture PDFs…" menu item will now work.
