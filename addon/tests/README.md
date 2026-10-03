# klaus_note tests

Headless logic tests. Anki's Python (3.13 bytecode) and its PyQt6 cannot be
imported by this machine's `python3` (3.9), so these stub `aqt`/`anki` and
test logic only — never Qt widgets. See `.claude/skills/klaus-test/`.

Run them all:

```bash
for t in tests/test_*.py; do
  echo "— $t"; env QT_QPA_PLATFORM=offscreen python3 "$t" || exit 1
done
```

| File | Covers |
|---|---|
| `test_klaus_note.py` | embedding providers + HTTP retries, `pdf_index` storage/resume, retention & FSRS math |
| `test_drive.py` | `drive_store` folders/display names, `pdf_drop` pure helpers |
| `test_dialog_logic.py` | Manage-models dialog state machine (job assignment, missing-model warnings) |

`test_dialog_logic.py` transcribes the dialog's handler logic against fake
combo widgets; if `manage_models_dialog` changes, update it in lockstep.
