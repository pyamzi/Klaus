# Local lecture transcription implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve lecture recording and per-page transcripts while replacing paid transcription with a user-installed whisper.cpp binary.

**Architecture:** A small stdlib-only adapter discovers the executable and reads its JSON output. The existing recorder FIFO, page assignment, failed-WAV retention and profile-close latch remain the owners of recording state. This plan runs before Ollama restoration so transcription remains usable while provider keys are subsequently retired.

**Tech Stack:** Python 3.9-compatible syntax with postponed annotations, Anki/PyQt6, whisper.cpp CLI.

**Spec:** `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`, D6.

## Global Constraints

- No third-party Python dependencies, embedded native bindings, venv, cloud transcription, microphone tests, or live Anki fixtures.
- Never read real `meta.json` or `user_files`; use temporary directories and the klaus-test bootstrap.
- Keep current Preferences shell and existing recording/page/transcript behavior.
- Use the main checkout required by the Anki symlink; preserve unrelated logo edits, including the existing `_logo_pixmap` hunk in `manage_models.py`.
- No push or merge. New prose and commit messages contain no em dash.
- Spike prerequisite is complete: `/tmp/klaus-whisper-spike/spike-evidence.json`, actual CLI v1.9.4, mono and 48 kHz stereo WAV both transcribed. Command: `whisper-cli -m MODEL -f WAV -l en -oj -of PREFIX --prompt TEXT`. Parse `PREFIX.json`, `transcription[].text`.
- Ordering ruling: `openai_client.py` stays only for embeddings after this plan. D4 deletes it and its tests once that final caller is gone. Never delete a module with a live caller.

## Review Focus

- GUI PATH omits the binary: discovery has safe fixed-command shell and known-path fallbacks, with an explicit override for a custom executable.
- Paths contain spaces: subprocess receives an argv list, never a composed shell command.
- Binary fails, times out, or emits malformed JSON: raise a typed local error and preserve the queued source WAV.
- Profile closes during transcription: existing stopped-uploader latch prevents append and unlink after completion.
- Preferences reopen and save: model path, binary override and language round-trip without rewriting unrelated settings.

### Task 1: Build the local transcription adapter

**Files:** Create `klausmate/local_transcription.py`, `tests/test_local_transcription.py`.

**Interfaces:** `TranscriptionError(Exception).user_message() -> str`; `find_binary(configured: str = "") -> str | None`; `transcribe(wav: bytes, model_path: str, *, binary: str = "", language: str = "en", prompt: str = "", timeout: float = 600.0) -> str`.

- [ ] **Step 1: Write a failing behavioral adapter test using the existing bootstrap.** Include this executable fixture in a temporary directory and call the real adapter, not a copied parser:

```python
fake.write_text("#!" + sys.executable + "\n" +
    "import json,pathlib,sys\n" +
    "a=sys.argv; p=a[a.index('-of')+1]\n" +
    "assert '-oj' in a and a[a.index('-l')+1]=='en'\n" +
    "pathlib.Path(p+'.json').write_text(json.dumps({'transcription':[{'text':' hello '},{'text':'world'}]}))\n")
fake.chmod(0o755)
model.write_bytes(b"fixture")
check("JSON segments joined", local_transcription.transcribe(
    b"fixture WAV", str(model), binary=str(fake), prompt="slide words") == "hello world")
```

Add fixture modes for exit1, absent JSON, invalid JSON, empty transcription, timeout, invalid model path and missing binary. Assert `TranscriptionError` and actionable messages. Add paths with spaces and assert prompt is one argv value. Patch discovery dependencies for PATH, fixed login-shell fallback, known paths and explicit invalid override (never silently choose a different binary).

- [ ] **Step 2: Run `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_local_transcription.py` and record the expected missing-module failure.**
- [ ] **Step 3: Implement the adapter.** Use `tempfile.TemporaryDirectory`, write a private WAV inside it, execute with `subprocess.run(..., capture_output=True, timeout=timeout)` and load JSON from the output prefix. Reject absent executable/model before spawning. Discover `whisper-cli` and `whisper-cpp`; a generic `main` is accepted only as an explicit path, since a PATH program named main need not be whisper.cpp. Fixed shell discovery commands contain no user text. Normalize nonempty segment text with `" ".join(...)`; an empty list returns `""`. Do not parse stdout or log audio, prompts, transcript or raw stderr. Convert OS/process/JSON/shape failures into the typed error, and always remove temporary output. No automatic downloads or install hooks.
- [ ] **Step 4: Run focused tests and the actual spike through the new adapter.** Load the upstream sample from `/tmp/klaus-whisper-spike/whisper.cpp-1.9.4/samples/jfk.wav`, binary `/tmp/klaus-whisper-spike/build/bin/whisper-cli`, model `/tmp/klaus-whisper-spike/ggml-tiny.en.bin`; assert nonempty text includes `country`. Record command and result in the task report. No microphone.
- [ ] **Step 5: Compile the new module directly and through the Anki symlink, inspect diff, commit only these two files.**

### Task 2: Wire recording and Preferences to local transcription

**Files:** Modify `klausmate/lecture_recorder.py`, `klausmate/manage_models.py`, `klausmate/config.json`, `klausmate/__init__.py`, `klausmate/config.md`, `tests/test_lecture_recorder.py`, relevant settings/config/dialog tests, `scripts/mutation_audit.py`. Create `tests/test_local_transcription_settings.py` if needed for real widget coverage.

**Interfaces:** Consume Task1 `transcribe`; keep recorder `_transcribe` patch seam, now assigned to `local_transcription.transcribe`. Config keys: `transcription_model_path` default `""`, `transcription_binary` default `""`, `transcription_language` default `"en"`. Retire `transcription_model`; retain embedding API keys until D4.

- [ ] **Step 1: Add failing recorder tests by adapting the actual uploader seam.** The fake captures WAV/model/binary/language/prompt. Verify the segment is appended to its original page and successful WAV deleted. Raise `TranscriptionError` and verify source WAV remains and no segment is appended. Retain the existing stop-during-request, leftover retry, FIFO, page-boundary and silence tests. Add a config migration assertion with defaults merged under saved values:

```python
old = dict(defaults, transcription_model="gpt-4o-mini-transcribe")
migrated = migrate_fixture(old)
check("cloud model retired", "transcription_model" not in migrated)
check("local path default", migrated["transcription_model_path"] == "")
check("migration idempotent", migrate_fixture(migrated) == migrated)
```

Here `migrate_fixture` is a local test helper that invokes the real `_migrate_config` using `exec_klausmate_under_qt` and captured config writers, following `test_api_first_config.py`.

- [ ] **Step 2: Run the focused tests and record the expected failures.**
- [ ] **Step 3: Replace only the uploader provider seam and error classification.** Call:

```python
text = _transcribe(wav, str(cfg.get("transcription_model_path") or ""),
    binary=str(cfg.get("transcription_binary") or ""),
    language=str(cfg.get("transcription_language") or "en"), prompt=prompt)
```

Remove its OpenAI import/key/model handling. Keep failed-audio retention, one-time user-facing error delivery, queue accounting, prior-text prompt seeding and profile-close guard. Missing configuration must say to select a local whisper.cpp model in Preferences. Existing consumers of uploader errors continue receiving a concise message.

- [ ] **Step 4: Replace the transcription model row in the current Preferences shell.** Add model-file path with Browse, optional executable path with Browse, and language text (default en). Use existing `_row`, load/save and dirty wiring. No provider picker, automatic download, new chat surface or redesign. Add concise whisper.cpp setup copy and an official source link in `config.md`. Real offscreen widget tests with fake task manager must verify rows populate, save, and reopen; no real app or audio device.
- [ ] **Step 5: Update defaults and retirement, then the mutation roster.** Preserve explicitly saved local paths across repeated migrations. Transcription-only retirement must preserve `_embed_key_setup_declined`, because this task changes no embedding-key requirement; extend the narrow retirement exemption and test it. Add `local_transcription` to `AUDIT_MODULES`; remove no OpenAI module yet because embeddings still uses it. Update only obsolete transcription assertions in existing tests.
- [ ] **Step 6: Run focused suites, then the full aggregate suite, mutation selftest, direct and symlink compiles.** Use the existing aggregate runner copied into this plan's ignored workspace. No paid tests. Record all skips and existing Qt/stub diagnostics. Resolve any real regression before commit.
- [ ] **Step 7: Stage only owned changes and commit.** In `manage_models.py`, exclude the preexisting logo hunk saved at `/tmp/klaus-existing-logo-manage-models.patch`; inspect the staged diff. Final review covers both tasks before proceeding to D4.

## Self-review

D6 discovery, real CLI spike, local model selection, preserved recorder state, explicit failure, no cloud fallback and tests are each assigned above. D4 owns final OpenAI deletion because this execution order retains its embedding caller. All five review conditions have direct tests. No live user data or external application config is changed.
