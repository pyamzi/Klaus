# Local-Model Reversion — Demolition (D1+D2+D3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Klaus Plus (the subscription service), the pertinence
judge (the Claude reasoning pass over duplicate-card matches), and the
embedded Claude-Code-CLI assistant dock — the three pieces of the
API-first turn that are being torn out before local models come back.

**Architecture:** Three sequential clusters (D1 Klaus Plus, D2 the
judge, D3 the assistant dock), each landing as its own set of commits
with the full test suite green before the next cluster starts. Within
a cluster, strip every caller of the thing being deleted BEFORE
deleting the thing itself, so no task ever leaves a dangling import.

**Tech Stack:** Python 3.9-compatible stdlib-only add-on code (no pip
installs, no venv — this machine's system `python3` runs the tests
directly).

**Spec:** `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`
(sections D1, D2, D3). This plan implements those three sections only —
D4 (Ollama restoration), D5 (the MCP bridge), and D6 (local
transcription) are separate plans that build on this one's clean tree.

## Global Constraints

- **This is sequential, not swarmable.** `plus.py` has 8 real
  importers, `pertinence.py` has 5 — deleting either breaks every
  concurrent worker's `verify:` at once. One session, one task after
  another, in the order below.
- **Full test suite green between every task**, not just at the end:
  `status=0; for t in tests/test_*.py; do echo "$t"; python3 "$t" || status=1; done; exit "$status"`
  from the repo root (`/Users/pyamzi/Documents/Github/Klaus/KlausMate-Context`).
- **After every `klausmate/*.py` edit**, verify syntax through the
  symlink Anki actually loads: `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`.
  (This symlink was just re-pointed at the repo's new path after a
  folder move — confirm `ls -l` still shows it resolving before relying
  on this check.)
- **Add `PYTHONDONTWRITEBYTECODE=1`** when re-running a test right after
  editing the module it covers — this Mac's stale-bytecode trap (see
  CLAUDE.md's "Commands" section) can silently execute old code within
  the same mtime second.
- **Never hand-edit `board/BOARD.md`** — this plan does not use the
  agent-board workflow (demolition is one continuous session, not a
  claimed-card swarm), so no board interaction is needed at all here.
- **Commit after each task**, using `git add` on the exact files that
  task touched (never `git add -A`) plus a descriptive message — no
  K-numbers for this plan, since it isn't board-tracked. End every
  commit message with the attribution line your system prompt specifies.
- **Never delete `user_files/` or `meta.json`** — not touched by this
  plan, called out here only because it's a standing repo rule.

---

# Cluster D1 — Delete Klaus Plus

### Task 1: Strip Klaus Plus from `embeddings.py`

**Files:**
- Modify: `klausmate/embeddings.py:153-190`
- Test: `tests/test_klausmate.py` (embeddings tests — run after, no new file)

**Interfaces:**
- Consumes: nothing new.
- Produces: `OpenAIEmbeddings.embed()` now raises `EmbeddingError` immediately
  when no `api_key_openai` is set, with no Klaus Plus fallback path. Every
  later task in this plan that imports `embeddings` sees this simplified
  shape.

- [ ] **Step 1: Read the current method to confirm line numbers still match**

Run: `sed -n '148,206p' klausmate/embeddings.py`

Expected: the block below, starting with `def embed(self, texts...` and
ending at the `except openai_client.OpenAIError as e:` clause that closes
the method.

- [ ] **Step 2: Replace the Plus-routed `embed()` body with the direct-key-only version**

Current content (lines 148-206, to be replaced in full):
```python
    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config() or {}
        from . import openai_client, plus

        if plus.active(cfg):
            try:
                return openai_client.embed(
                    "", texts, embedding_model(cfg), _dimensions_for(cfg),
                    endpoint=plus.endpoint(cfg, "embed"),
                )
            except openai_client.OpenAIError as e:
                if e.status in (401, 402, 426):
                    # Remembered so the UI can say why — through the
                    # PACKAGE's patch_config, reached lazily: this module
                    # is aqt-free and cannot import __init__ (which
                    # imports aqt) at module top. patch_config hops to the
                    # main thread itself (this branch may run on
                    # curation's QueryOp worker thread) and MERGES into
                    # the stored config; the package's plain write_config
                    # REPLACES the whole config and must never be the
                    # sink here (a one-key patch through it would wipe
                    # every other setting). A stub package with neither
                    # attribute is a genuine wiring break, not silently
                    # swallowed.
                    pkg = __import__(__package__, fromlist=["patch_config"])
                    wc = getattr(pkg, "patch_config", None)
                    if wc is None:
                        print("[klausmate] Klaus Plus refusal not cached: package has no patch_config")
                    else:
                        plus.note_refusal(cfg, e.status, wc, message=str(e))
                # e.status is None for a connection-level failure (no HTTP
                # response at all — openai_client never learned it was
                # talking to Klaus Plus) — its message says "Could not
                # reach OpenAI ...", which on THIS path names the wrong
                # thing to blame (M-10). A real status means the service
                # itself answered, in its own words: verbatim, unprefixed.
                raise EmbeddingError(
                    str(e) if e.status is not None else f"Klaus Plus: {e}",
                    provider="Klaus Plus", status=e.status, retry_after=e.retry_after,
                ) from e

        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError(
                "OpenAI API key is not set — add it in KlausMate Preferences "
                "→ API keys & models.",
                provider="OpenAI",
                status=401,
            )
        try:
            return openai_client.embed(
                key, texts, embedding_model(cfg), _dimensions_for(cfg)
            )
        except openai_client.OpenAIError as e:
            raise EmbeddingError(
                str(e), provider="OpenAI", status=e.status, retry_after=e.retry_after
            ) from e
```

Replace with (drops the `plus.active(cfg)` branch and its import entirely):
```python
    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config() or {}
        from . import openai_client

        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError(
                "OpenAI API key is not set — add it in KlausMate Preferences "
                "→ API keys & models.",
                provider="OpenAI",
                status=401,
            )
        try:
            return openai_client.embed(
                key, texts, embedding_model(cfg), _dimensions_for(cfg)
            )
        except openai_client.OpenAIError as e:
            raise EmbeddingError(
                str(e), provider="OpenAI", status=e.status, retry_after=e.retry_after
            ) from e
```

Note: `EmbeddingError.user_message()` (earlier in the file, around line
60) has an `if self.provider == "Klaus Plus":` branch — leave it for now,
it's dead-but-harmless code that D4's full rewrite of this file replaces
anyway; don't scope-creep this task into touching it.

- [ ] **Step 3: Compile check**

Run: `python3 -m py_compile klausmate/embeddings.py`
Expected: no output, exit 0.

- [ ] **Step 4: Run the full suite**

Run: `cd klausmate/.. && status=0; for t in tests/test_*.py; do echo "$t"; python3 "$t" || status=1; done; exit "$status"`
Expected: every test passes. (`tests/test_api_first_config.py` may still
reference `plus.py` itself, not just this file's use of it — if it fails
here, note the failure and continue; Task 8 of this cluster fixes every
remaining test file in one pass rather than chasing them one at a time.)

- [ ] **Step 5: Commit**

```bash
git add klausmate/embeddings.py
git commit -m "embeddings: drop the Klaus Plus routing branch, OpenAI-key-only"
```

---

### Task 2: Strip Klaus Plus from `index_queue.py`

**Files:**
- Modify: `klausmate/index_queue.py` (lines 83, 127-129, 748, 1011-1025, plus the `plus` kwarg on `sweep_message`/`card_index_confirm_message`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `missing_key_provider(cfg)` now only checks `api_key_openai`
  (no more `plus.key(cfg)` early return). `sweep_message`/
  `card_index_confirm_message` drop their `plus: bool = False` parameter
  — later tasks/plans that call these two functions must not pass `plus=`.

- [ ] **Step 1: Fix the import line**

Find (line 83):
```python
from . import embeddings, plus
```
Replace with:
```python
from . import embeddings
```

- [ ] **Step 2: Fix `missing_key_provider`**

Find (lines 127-129, inside a larger function — confirm with
`sed -n '120,135p' klausmate/index_queue.py` first):
```python
    if plus.key(cfg):
        return ""
```
Delete these two lines entirely (leave the rest of the function's logic —
the OpenAI-key check below it — untouched).

- [ ] **Step 3: Fix the auto-embed confirm gate**

Find (line 748, confirm with `sed -n '740,755p' klausmate/index_queue.py`):
```python
    if kind != JOB_PDF or plus.active(cfg) or not card_index_from_scratch(cfg):
```
Replace with:
```python
    if kind != JOB_PDF or not card_index_from_scratch(cfg):
```

- [ ] **Step 4: Fix the sweep-pricing block**

Find (lines 1011-1025, confirm with `sed -n '1005,1030p' klausmate/index_queue.py`
— exact surrounding code varies, but the shape is):
```python
    if plus.active(_cfg()):
        estimate = ""
    else:
        estimate = cost.format_estimate(...)
    ...
    message = sweep_message(..., plus=plus.active(_cfg()))
```
Replace with the non-Plus branch made unconditional:
```python
    estimate = cost.format_estimate(...)
    ...
    message = sweep_message(...)
```
(Keep whatever the `cost.format_estimate(...)` call's actual arguments are
— only the `if/else` wrapper and the `plus=` kwarg are being removed. Read
the exact surrounding lines before editing to preserve the real argument
list.)

- [ ] **Step 5: Strip the dead `plus` kwarg from both message-builder signatures**

Find `def sweep_message(..., plus: bool = False)` (around line 239) and
`def card_index_confirm_message(..., plus: bool = False)` (around line
269) — remove the `plus: bool = False` parameter from each signature, and
remove any `if plus: ...` branch inside their bodies that referenced it
(read each function fully with `sed -n` first to find the exact branch,
since the research pass did not quote these bodies verbatim).

- [ ] **Step 6: Reword the docstrings that describe five phases as four**

The module docstring (lines 14-24) and `_run`'s own docstring (around
592-598) describe a five-phase chain ending in the judge. Leave the
WORDING alone in this task — Task 9 (Cluster D2) is what actually
collapses the phase count and rewrites these docstrings; touching them
here would just mean rewriting them twice. Skip this step for now.

- [ ] **Step 7: Compile check**

Run: `python3 -m py_compile klausmate/index_queue.py`

- [ ] **Step 8: Run the full suite**

Same command as Task 1 Step 4. `tests/test_index_queue.py` may fail on
assertions that reference the now-removed `plus` kwarg or branch — note
and continue; Task 8 of this cluster is the test-fixing pass.

- [ ] **Step 9: Commit**

```bash
git add klausmate/index_queue.py
git commit -m "index_queue: drop Klaus Plus routing from key-check, confirm gate, and sweep pricing"
```

---

### Task 3: Strip Klaus Plus from `lecture_recorder.py`

**Files:**
- Modify: `klausmate/lecture_recorder.py` (import line 48, docstring 23-33, `_patch_config_sink` 256-263, `Uploader._one` 384-435)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Uploader._one` now gates purely on `key` (no `on_plus`
  branch) — D6's later rewrite of this same method (to call local
  whisper.cpp instead of OpenAI) starts from this simplified shape, not
  from today's Plus-aware one.

- [ ] **Step 1: Fix the import**

Find (line 48):
```python
from . import openai_client, page_store, plus
```
Replace with:
```python
from . import openai_client, page_store
```

- [ ] **Step 2: Delete `_patch_config_sink`**

Find (lines 256-263):
```python
def _patch_config_sink() -> Callable[[dict], None] | None:
    """The package's ``patch_config``, reached lazily: this module is
    aqt-free and must not import ``klausmate/__init__.py`` (which imports
    aqt) at module top. Mirrors embeddings.py's own lazy lookup exactly —
    one MERGE writer every ``plus.*`` call must use, never the package's
    plain ``write_config``, which replaces the whole stored config."""
    pkg = __import__(__package__, fromlist=["patch_config"])
    return getattr(pkg, "patch_config", None)
```
Delete this function entirely (it exists only to feed Klaus Plus's
`on_headers`/refusal callbacks, both being removed below).

- [ ] **Step 3: Rewrite `Uploader._one`'s transcribe section**

Find (this is the section from the `cfg = self._get_config()` line through
the `except Exception as exc:` that follows the transcribe call — confirm
exact bounds with `sed -n '397,430p' klausmate/lecture_recorder.py`):
```python
        cfg = self._get_config() or {}
        model = str(cfg.get("transcription_model") or "gpt-4o-mini-transcribe")
        key = str(cfg.get("api_key_openai") or "").strip()
        on_plus = plus.active(cfg)
        if not key and not on_plus:
            print(f"[klausmate] lecture recorder: no OpenAI key and no Klaus Plus, keeping {os.path.basename(wav_path)}")
            return
        prompt = self._last_text.get(pdf_safe, "")[-800:]
        try:
            wav = open(wav_path, "rb").read()
            if on_plus:
                text = _transcribe("", wav, model, prompt=prompt, endpoint=plus.endpoint(cfg, "transcribe"),
                                   on_headers=lambda h: plus.note_quota(cfg, h, _patch_config_sink()))
            else:
                text = _transcribe(key, wav, model, prompt=prompt)
        except openai_client.OpenAIError as exc:
            if on_plus and exc.status in (401, 402, 426):
                sink = _patch_config_sink()
                if sink is None:
                    print("[klausmate] Klaus Plus refusal not cached: package has no patch_config")
                else:
                    plus.note_refusal(cfg, exc.status, sink, message=exc.user_message())
            # Class and status ONLY, never the message (PR #4, Codex):
            # openai_client._request folds up to 300 bytes of the provider's
            # error body into it, and that body can echo request-derived
            # text — here the continuity prompt, which IS the previous
            # segment's transcript. Same rule the judge follows.
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)} "
                  f"(OpenAIError status={exc.status})")
            return
```
Replace with (drops `on_plus` entirely; keeps the same error-class-only
logging rule the comment documents):
```python
        cfg = self._get_config() or {}
        model = str(cfg.get("transcription_model") or "gpt-4o-mini-transcribe")
        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            print(f"[klausmate] lecture recorder: no OpenAI key, keeping {os.path.basename(wav_path)}")
            return
        prompt = self._last_text.get(pdf_safe, "")[-800:]
        try:
            wav = open(wav_path, "rb").read()
            text = _transcribe(key, wav, model, prompt=prompt)
        except openai_client.OpenAIError as exc:
            # Class and status ONLY, never the message (PR #4, Codex):
            # openai_client._request folds up to 300 bytes of the provider's
            # error body into it, and that body can echo request-derived
            # text — here the continuity prompt, which IS the previous
            # segment's transcript. Same rule the judge follows.
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)} "
                  f"(OpenAIError status={exc.status})")
            return
```

- [ ] **Step 4: Reword the module docstring**

Find lines 23-33 (the paragraph describing Klaus-Plus routing for
transcription) and rewrite it to describe the current (post-edit)
direct-key-only behavior in the same prose style as the rest of the file's
docstring. Read the current full docstring first with
`sed -n '1,40p' klausmate/lecture_recorder.py` before rewriting, so the
replacement fits the surrounding paragraphs' voice.

- [ ] **Step 5: Compile check**

Run: `python3 -m py_compile klausmate/lecture_recorder.py`

- [ ] **Step 6: Run the full suite**

Same command as Task 1 Step 4. `tests/test_lecture_recorder.py` has three
test sections that specifically exercise the Klaus-Plus branch (the
"routed through plus.endpoint" section, the "402 refusal" section, and
part of the "no OpenAI key and no Klaus Plus" section) — these will now
fail or need deletion. Note failures and continue; Task 8 fixes them.

- [ ] **Step 7: Commit**

```bash
git add klausmate/lecture_recorder.py
git commit -m "lecture_recorder: drop Klaus Plus routing, direct OpenAI key only"
```

---

### Task 4: Strip Klaus Plus from `setup_flow.py`

**Files:**
- Modify: `klausmate/setup_flow.py` (import line 32, `missing_keys()` lines 117-118)

**Interfaces:**
- Consumes: nothing new.
- Produces: `missing_keys(cfg)` now always checks both provider keys
  directly — no early `[]` return for a Plus subscriber.

- [ ] **Step 1: Fix the import**

Find (line 32): a line importing `plus` alongside other modules. Run
`sed -n '25,35p' klausmate/setup_flow.py` to see the exact current import
statement, then remove `plus` from whatever comma-separated import list
it's part of.

- [ ] **Step 2: Fix `missing_keys()`**

Find (lines 117-118, confirm with `sed -n '110,122p' klausmate/setup_flow.py`):
```python
    if plus.key(cfg):
        return []
```
Delete these two lines; leave the function's remaining
`return [k for k in KEY_COPY ...]`-shaped body untouched.

- [ ] **Step 3: Compile check**

Run: `python3 -m py_compile klausmate/setup_flow.py`

- [ ] **Step 4: Run the full suite**

Same command as Task 1 Step 4.

- [ ] **Step 5: Commit**

```bash
git add klausmate/setup_flow.py
git commit -m "setup_flow: drop the Klaus Plus early-return from missing_keys"
```

---

### Task 5: Strip Klaus Plus UI from `manage_models.py`

**Files:**
- Modify: `klausmate/manage_models.py` (multiple regions — see below)

**Interfaces:**
- Consumes: nothing new.
- Produces: the "API keys & models" page has no Klaus Plus group; the
  "General" page has no "Klaus Plus service" row. `sync_embed_widgets()`,
  `save_general()`, `save_embed()`, and `test_connection()` lose their
  Plus-specific lines but keep every other line untouched.

- [ ] **Step 1: Delete the "Klaus Plus" group on the API-keys page**

Read `sed -n '705,745p' klausmate/manage_models.py` to see the exact
current block (account row + status/buttons row, roughly lines 710-739),
then delete that whole block. Leave the `openai_key_edit`/`anthropic_key_edit`
rows that follow it untouched (those survive D1; `anthropic_key_edit` is
removed later, in Cluster D3/D4's config cleanup, not here).

- [ ] **Step 2: Delete the `_plus_base_descs` dict**

Read `sed -n '760,775p' klausmate/manage_models.py`, locate the
`_plus_base_descs` dict literal (around lines 765-771), delete it. If
anything else in the file reads `_plus_base_descs`, grep for it first
(`grep -n "_plus_base_descs" klausmate/manage_models.py`) and remove those
reads too as part of this same step.

- [ ] **Step 3: Delete the "Klaus Plus service" row on the General page**

Read `sed -n '880,905p' klausmate/manage_models.py`, delete the
`plus_base_edit` row block (roughly lines 887-900): the `QLineEdit`
construction, its placeholder/description text, and the `_row(...)` call
that adds it to `general_layout`.

- [ ] **Step 4: Delete every Klaus Plus handler function**

Read `sed -n '1735,1900p' klausmate/manage_models.py` to see the full
contiguous run, then delete `_plus_cfg`, `refresh_plus_status`,
`_prompt_plus_credentials`, `on_plus_sign_in`, `on_plus_sign_out`,
`on_plus_subscribe`, `on_plus_manage`, `on_plus_check` in one pass (they
sit back-to-back, roughly lines 1739-1898).

- [ ] **Step 5: Fix the three surgical single-line references**

- `sync_embed_widgets()` around line 1915: delete the line
  `plus_base_edit.setText(str(cfg.get(plus.BASE) or ""))`.
- `save_general()` around line 2381: delete the line
  `cfg["klaus_plus_base"] = plus_base_edit.text().strip()`.
- `save_embed()` around line 1975: delete the line
  `refresh_plus_status()`.

Confirm each exact line with `grep -n "plus_base_edit\|refresh_plus_status" klausmate/manage_models.py`
before deleting, since line numbers shift after Steps 1-4's deletions.

- [ ] **Step 6: Fix `test_connection()`'s Plus branch**

Read the function (`sed -n '2680,2715p' klausmate/manage_models.py` —
adjust the range once earlier deletions have shifted lines), find the
`if plus.key(cfg): ... return` block (originally lines 2692-2701), delete
it, leaving the OpenAI/Anthropic key-presence checks that make up the rest
of the function.

- [ ] **Step 7: Delete the six standalone Plus signal-wiring lines**

Find (originally around lines 2719-2728, re-locate with
`grep -n "plus_base_edit.textEdited\|plus_.*_btn.clicked" klausmate/manage_models.py`):
one `plus_base_edit.textEdited.connect(...)` line and five
`plus_*_btn.clicked.connect(...)` lines. Delete all six.

- [ ] **Step 8: Grep-confirm zero remaining `plus.` references in this file**

Run: `grep -n "plus\." klausmate/manage_models.py`
Expected: no output (or only unrelated English "plus" — inspect any hit
by hand).

- [ ] **Step 9: Compile check**

Run: `python3 -m py_compile klausmate/manage_models.py`

- [ ] **Step 10: Run the full suite**

Same command as Task 1 Step 4. `tests/test_dialog_logic.py` and
`tests/test_manage_models_assistant.py` likely reference the deleted Plus
widgets/handlers by name — note failures, continue; Task 8 of this
cluster fixes them.

- [ ] **Step 11: Commit**

```bash
git add klausmate/manage_models.py
git commit -m "manage_models: delete the Klaus Plus preferences group and its handlers"
```

---

### Task 6: Delete `service/`; sever `openai_client.py`'s dependency on `plus`

> **Amended during execution (ruling recorded in the SDD ledger,
> 2026-09-19):** `plus.py` itself is NOT deleted by this task, despite
> the original title. `anthropic_client.py` still legitimately calls
> `plus.active(cfg)` (it isn't deleted until Task 14) and
> `openai_client.py` — which is NOT deleted by this plan at all, only by
> a separate future plan — still type-hints `plus.Endpoint`. Deleting
> `plus.py` here would break both. This task instead deletes only
> `service/` (zero dependents, safe regardless) and strips
> `openai_client.py`'s now-dead Plus-endpoint parameters (Tasks 1 and 3
> already removed the only two call sites that ever passed a real
> `endpoint=` argument). `plus.py`/`tests/test_plus.py` move to Task 14,
> which is what actually removes their last real caller.

**Files:**
- Delete: `service/` (entire directory — the FastAPI billing service)
- Modify: `klausmate/openai_client.py` (drop the `plus` import and the
  `endpoint: plus.Endpoint | None = None` parameter from `embed()` and
  `transcribe()`, plus whatever branch inside each function reads it —
  read the live function bodies first, this plan's earlier research
  pass captured them before Tasks 1-5 landed so exact current line
  numbers will differ)

**Interfaces:**
- Consumes: nothing new.
- Produces: `openai_client.embed()`/`transcribe()` no longer accept an
  `endpoint` argument at all — any future caller (including a later,
  separate plan) calls them with just a key. `on_headers` is unrelated
  to Plus and stays untouched — confirm this from the actual code
  before assuming, don't guess from this note.

- [ ] **Step 1: Confirm `service/` has zero klausmate/ dependents**

Run: `grep -rln "service\." klausmate/*.py` and `grep -rln "from service\|import service" klausmate/*.py tests/*.py`.
Expected: no output — `service/` is a separate FastAPI program, never
imported by the add-on (per CLAUDE.md's packaging rules). If anything
prints, stop and report BLOCKED with what you found.

- [ ] **Step 2: Delete `service/`**

```bash
git rm -r service/
```

- [ ] **Step 3: Grep-confirm no remaining caller passes `endpoint=` to `openai_client`**

Run: `grep -rn "openai_client\.\(embed\|transcribe\)(" klausmate/*.py`
and read each call site. Expected: none of them pass an `endpoint=`
keyword argument (Tasks 1 and 3 already removed the only two that did).
If you find one that still does, STOP and report BLOCKED — do not edit
`openai_client.py`'s signatures out from under a real caller.

- [ ] **Step 4: Strip the dead Plus-endpoint parameter from `openai_client.py`**

Read the current `embed()` and `transcribe()` function bodies in full
first (`sed -n '1,160p' klausmate/openai_client.py` or similar — the
file is short). Remove `from . import plus` from the imports. Remove
the `endpoint: plus.Endpoint | None = None` parameter from both
signatures, and whatever code inside each function branches on
`endpoint` being non-`None` (e.g. choosing between the caller's own key
vs. an `Endpoint`'s bearer headers) — collapse each function to the
single remaining (key-based) path. Leave `on_headers` exactly as it is.

- [ ] **Step 5: Compile check**

Run: `python3 -m py_compile klausmate/*.py`

- [ ] **Step 6: Run the full suite**

Same command as Task 1 Step 4, without an early break (see this plan's
Global Constraints and the Task 4 ledger note on why `|| break` hides
downstream failures). `tests/test_openai_client.py` may newly fail if
it has tests that pass `endpoint=` and assert Plus-specific behavior —
that's expected; a later, separate plan finishes cleaning up
`openai_client.py` fully. Note exactly what you see.

- [ ] **Step 7: Commit**

```bash
git add service klausmate/openai_client.py
git commit -m "Delete the never-shipped Klaus Plus service; drop openai_client's now-dead Plus-endpoint params"
```

---

### Task 7: Remove `klaus_plus_*` config keys

**Files:**
- Modify: `klausmate/config.json:8-10`
- Modify: `klausmate/__init__.py` (`_LEGACY_KEYS_DROPPED` tuple, lines 88-128)

**Interfaces:**
- Consumes: nothing new.
- Produces: profiles that still have `klaus_plus_key`/`klaus_plus_cache`/
  `klaus_plus_base` in their stored `meta.json` get them scrubbed on next
  profile open, via the existing `_migrate_config()` loop.

- [ ] **Step 1: Remove the three keys from `config.json`**

Read `sed -n '1,15p' klausmate/config.json` to see the exact current
lines 8-10 (`"klaus_plus_key": ...`, `"klaus_plus_cache": ...`,
`"klaus_plus_base": ...`), delete those three lines, and fix the trailing
comma on whichever line now becomes the last one in that JSON object
(JSON has no trailing commas — verify with
`python3 -c "import json; json.load(open('klausmate/config.json'))"`
after editing, which raises on invalid JSON).

- [ ] **Step 2: Add the three keys to `_LEGACY_KEYS_DROPPED`**

Read the 2026-09-15 dated block inside the tuple (lines 116-126) as the
template — it's a comment-dated group of retired keys in the same tuple.
Append a new dated entry following that exact pattern, e.g.:
```python
    # 2026-09-18: Klaus Plus removed — the subscription service (see
    # docs/superpowers/specs/2026-09-18-local-model-reversion-design.md).
    "klaus_plus_key",
    "klaus_plus_cache",
    "klaus_plus_base",
```
placed as the last entries before the tuple's closing `)` at line 128.
Read `sed -n '85,130p' klausmate/__init__.py` first to match the exact
comment/quoting style used by the neighboring dated blocks.

- [ ] **Step 3: Compile check**

Run: `python3 -m py_compile klausmate/__init__.py`

- [ ] **Step 4: Run the full suite**

Same command as Task 1 Step 4.

- [ ] **Step 5: Commit**

```bash
git add klausmate/config.json klausmate/__init__.py
git commit -m "config: retire the klaus_plus_* keys through the standard migration scrub"
```

---

### Task 8: Fix every remaining Klaus-Plus-aware test, verify D1 clean

**Files:**
- Modify: `tests/test_api_first_config.py`
- Modify: `tests/test_dialog_logic.py`
- Modify: `tests/test_manage_models_assistant.py`
- Modify: `tests/test_index_queue.py`
- Modify: `tests/test_lecture_recorder.py`
- Modify: `tests/test_openai_client.py` (if it references `plus.Endpoint`)
- Modify: `tests/test_setup_crop_theme.py`
- Modify: `tests/test_klausmate.py`
- Modify: `scripts/mutation_audit.py` (remove the deleted service sandbox input)

**Interfaces:**
- Consumes: Tasks 1-7's finished state.
- Produces: a fully green test suite with no obsolete Plus routing assertions.
  Keep retirement/migration coverage, and keep `test_plus.py` and
  `test_anthropic_client.py` until their modules are removed in Task 14.

- [ ] **Step 1: Find every remaining reference**

Run: `grep -rln "klaus_plus\|import plus\|plus\.\(active\|endpoint\|key\|note_quota\|note_refusal\)" tests/*.py`

Expected output: some subset of the files listed above. For each file
that appears:

- [ ] **Step 2: Open the file, remove or rewrite each failing assertion**

For each hit, read the surrounding test function fully. Two shapes will
appear:
- A test whose ENTIRE PURPOSE is Klaus-Plus behavior (e.g.
  `test_lecture_recorder.py`'s "routed through plus.endpoint" and "a 402
  refusal is remembered" sections, `test_api_first_config.py`'s Plus-key
  migration tests) — delete the whole test function.
- A test that incidentally sets a `klaus_plus_*` config key as part of a
  larger fixture unrelated to Plus itself — just remove that one config
  key from the fixture dict, leaving the rest of the test alone.

Do not guess which shape a given hit is — read the test body before
deciding.

Preserve migration tests that prove retired keys are scrubbed. Replace the
recorder test's AST extraction of deleted `service/klausplus/proxy.py`
with stdlib `wave` assertions for the real generated WAV header and
duration. Remove the deleted service tree from the mutation sandbox inputs.

- [ ] **Step 3: Run the full suite until it's fully green**

Run: `PYTHONDONTWRITEBYTECODE=1 bash -c 'status=0; for t in tests/test_*.py; do echo "$t"; python3 "$t" || status=1; done; exit "$status"'`

Expected: every test file prints its section header and no failure output;
the loop reaches the last file.

- [ ] **Step 4: Compile the whole package one more time**

Run: `python3 -m py_compile klausmate/*.py`
Run: `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`

- [ ] **Step 5: Commit**

```bash
git add tests/ scripts/mutation_audit.py
git commit -m "tests: remove every Klaus Plus fixture and assertion — D1 clean"
```

**D1 is now complete.** Do not start Cluster D2 until this task's Step 3
passes with zero failures.

---

# Cluster D2 — Delete the pertinence judge

### Task 9: Collapse `index_queue.py`'s five-phase chain to four

**Files:**
- Modify: `klausmate/index_queue.py`

**Interfaces:**
- Consumes: D1's finished state (this file no longer imports `plus`).
- Produces: the index chain is now `ensure_index` → `ensure_pdf_index` →
  `ensure_matches` → `tag_sync.sync_after_matches`, with no judge phase and
  no `"judge"` value for `RunnerState.phase`. `tag_sync.sync_after_matches`
  is called with no `doubtful` argument (Task 11 removes that parameter
  entirely from `tag_sync.py` — this task must not pass it).

- [ ] **Step 1: Read the current five-phase wiring in full**

Run: `sed -n '580,700p' klausmate/index_queue.py`
This shows `_run()`, `after_pdf_index()` (calling `retention.ensure_matches`),
`after_matches()` (the judge phase — calls `pertinence.ensure_judged`),
and `after_judged()` (the tag-sync phase).

- [ ] **Step 2: Fix the import**

Find (line 598):
```python
from . import curation, pertinence, retention, tag_sync
```
Replace with:
```python
from . import curation, retention, tag_sync
```

- [ ] **Step 3: Delete `after_matches()` and repoint `ensure_matches`'s callback**

`after_matches()` (originally lines 641-663) is the judge phase wrapper —
delete it entirely. Then find the `retention.ensure_matches(...,
on_done=after_matches)` call inside `after_pdf_index()` (originally around
line 676) and change `on_done=after_matches` to `on_done=after_judged`
(reusing the function name from Step 4 below) or to whatever name you give
the renamed function in Step 4 — pick one name and use it consistently in
both places.

- [ ] **Step 4: Simplify `after_judged()` (or rename it) to run straight off `ensure_matches`'s result**

Read the current function (originally lines 624-639):
```python
def after_judged(rejected, matches):
    doubtful = set()
    try:
        doubtful = tag_sync.doubtful_members(_cfg())
    except Exception as exc:
        print(f"[klausmate] index_queue: doubtful_members failed: {exc.__class__.__name__}")
        doubtful = set()
    tag_sync.sync_after_matches(mw, name, matches, doubtful=doubtful)
    ...
```
(Confirm the exact current body with `sed -n '620,645p' klausmate/index_queue.py`
— the snippet above is reconstructed from the research pass's description,
not a verbatim quote, since the doubtful-lookup try/except's exact
variable names weren't captured verbatim.)

Rewrite it to take just `matches` (drop the `rejected` parameter this
function received from the deleted `after_matches`) and drop the
`doubtful_members` lookup entirely:
```python
def after_judged(matches):
    tag_sync.sync_after_matches(mw, name, matches)
    ...
```
Keep whatever code follows the `tag_sync.sync_after_matches(...)` call in
the original function (progress reporting, `RunnerState` updates, etc.) —
only the doubtful-lookup block and the `rejected` parameter are being
removed.

- [ ] **Step 5: Fix the exception fallback that used to call `after_judged(set(), matches)`**

Search for `after_judged(set()` (this was the "whatever escapes
pertinence's own defences" fallback mentioned in the spec) and change the
call to `after_judged(matches)` (dropping the now-nonexistent `rejected`
argument), or delete the fallback entirely if it has no other purpose once
there's no judge phase to fail out of — read the surrounding code to
decide which; if the fallback existed ONLY to recover from a judge
exception, delete it, since `ensure_matches`'s own `on_done` now points
directly at the simplified `after_judged`.

- [ ] **Step 6: Fix `ask_judge()` and `RunnerState`/`status_line()`**

Delete the standalone `ask_judge()` function (originally lines 1061-1088)
in full.

Find `RunnerState`'s `phase` field comment (around line 206) mentioning
`"judge"` and update it to describe only the four remaining phase names.

Find `status_line()`'s ternary (around line 225):
```python
f"{state.done}/{state.total}" if state.phase == "judge" else ...
```
Simplify to always take the non-judge branch (read the full ternary/if
chain with `sed -n '220,235p' klausmate/index_queue.py` first, since the
"else" branch's exact expression wasn't captured verbatim by research —
replace the whole conditional with just that else-branch expression,
unconditionally).

- [ ] **Step 7: Reword the two docstrings describing five phases**

Module docstring (lines 14-24) and `_run`'s docstring (around 592-598) —
rewrite each occurrence of "five phases" / the judge-phase description to
match the new four-phase chain: `ensure_index` → `ensure_pdf_index` →
`ensure_matches` → `tag_sync.sync_after_matches`.

- [ ] **Step 8: Compile check**

Run: `python3 -m py_compile klausmate/index_queue.py`

- [ ] **Step 9: Run the full suite**

Same command as Task 1 Step 4 (Cluster D1). `tests/test_index_queue.py`
has phase-four assertions (lines 326-519, 1461 per the research pass) that
will now fail — note and continue; Task 15 of this cluster is the
test-fixing pass for all of D2.

- [ ] **Step 10: Commit**

```bash
git add klausmate/index_queue.py
git commit -m "index_queue: collapse the index chain from five phases to four, no judge"
```

---

### Task 10: Strip `tag_sync.py`'s doubtful-tag machinery

**Files:**
- Modify: `klausmate/tag_sync.py`

**Interfaces:**
- Consumes: Task 9's finished state.
- Produces: `sync_after_matches`, `sync_after_threshold`, and
  `sync_after_clear_overrides` no longer take a `doubtful` parameter.
  `DOUBTFUL_TAG` and `doubtful_members` no longer exist — Task 13's
  `pdf_map.py`/`pdf_drive.py` fixes and Task 9's `index_queue.py` change
  both depend on this already being done (this task must run before or
  alongside them; per this plan's ordering it runs right after Task 9).

- [ ] **Step 1: Delete `DOUBTFUL_TAG` and its comment block**

Read `sed -n '95,115p' klausmate/tag_sync.py`, delete the `DOUBTFUL_TAG`
constant and its preceding comment (originally lines 101-113). Leave
`RESERVED_LEAVES` — check whether `"doubtful"` is a bare string literal
inside that tuple (line 104 per research) or whether it references
`DOUBTFUL_TAG`; if it's a bare string, leave the tuple entry as-is (a
reserved leaf name costs nothing to keep even with no tag using it); if it
references the now-deleted constant, replace that entry with the literal
string `"Doubtful"`.

- [ ] **Step 2: Strip the `doubtful` parameter from `_do_sync_one`**

Read the full function (`sed -n '450,495p' klausmate/tag_sync.py`).
Remove the `doubtful=None` parameter from its signature, remove the
`doubtful_added`/`doubtful_removed` list-init and the
`apply_membership(col, DOUBTFUL_TAG, doubtful)` call (originally lines
475-483), and remove the two dict keys those variables fed into the
function's return value (originally lines 487-488). Keep every other part
of the function (the per-PDF tag membership diff) untouched.

- [ ] **Step 3: Strip the `doubtful` parameter from the three callers**

For each of `sync_after_matches`, `sync_after_threshold`,
`sync_after_clear_overrides`: read the function fully, remove its
`doubtful` parameter (and, where present, the `doubtful = doubtful_members(cfg)`
try/except block feeding it — originally at lines 743-746 for
`sync_after_threshold` and lines 785-788 for `sync_after_clear_overrides`),
and remove the `doubtful=...` argument from that function's own call into
`_do_sync_one` (originally lines 698, 751, 805 respectively).

Also rewrite `sync_after_matches`'s docstring (originally lines 652-657)
to drop its description of doubtful-tag behavior.

- [ ] **Step 4: Delete `doubtful_members()`**

Read `sed -n '515,565p' klausmate/tag_sync.py`, delete the whole function
(originally lines 518-563).

- [ ] **Step 5: Grep-confirm no remaining reference in this file**

Run: `grep -n "doubtful\|DOUBTFUL" klausmate/tag_sync.py`
Expected: no output, or only the `RESERVED_LEAVES` literal string handled
in Step 1.

- [ ] **Step 6: Compile check**

Run: `python3 -m py_compile klausmate/tag_sync.py`

- [ ] **Step 7: Run the full suite**

Same command as before. `tests/test_klausmate.py`'s doubtful-tag
assertions (lines 1268-1538 per research) will fail — note, continue.

- [ ] **Step 8: Commit**

```bash
git add klausmate/tag_sync.py
git commit -m "tag_sync: remove the Doubtful-tag machinery — no judge to feed it"
```

---

### Task 11: Strip `retention.py`'s `rejected` parameter (breaking return-shape change)

**Files:**
- Modify: `klausmate/retention.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `pdf_retention(matches, threshold, card_r)` drops its
  `rejected` parameter (cosine-threshold-only again).
  `note_card_counts(matches, threshold, queue_map)` drops `rejected` AND
  changes its return shape from a 4-tuple `(notes, viewable, suspended,
  doubtful_count)` to a 3-tuple `(notes, viewable, suspended)` — **every
  caller of `note_card_counts` must be updated in the SAME task or the
  next one immediately following**, since an unpacking mismatch
  (`a, b, c, d = note_card_counts(...)`) raises `ValueError` at runtime,
  not an import-time error. Task 12 fixes the two callers
  (`pdf_drive.py`, `pdf_map.py`) — do not run the full suite as "done"
  between this task and Task 12; run it only to confirm this file's own
  compile+its own direct tests, then proceed straight to Task 12 before
  the broader suite run.

- [ ] **Step 1: Fix `pdf_retention`'s signature and body**

Read `sed -n '218,255p' klausmate/retention.py`. Change the signature from
`def pdf_retention(matches, threshold, card_r, rejected=None):` to
`def pdf_retention(matches, threshold, card_r):`. Find the line
`rejected = rejected or ()` (originally line 246) and delete it. Find the
line `if sim < threshold or nid in rejected:` (originally line 248) and
change it to `if sim < threshold:`.

- [ ] **Step 2: Fix `note_card_counts`'s signature, body, and return shape**

Read `sed -n '272,330p' klausmate/retention.py` in full. Change the
signature from `def note_card_counts(matches, threshold, queue_map,
rejected=None):` to `def note_card_counts(matches, threshold, queue_map):`.
Delete the `doubtful = 0` initializer, the `rejected = rejected or ()`
line, and the `if nid in rejected: doubtful += ...; continue` branch.
Change the function's final `return` statement from a 4-tuple ending in
`doubtful` to a 3-tuple `(notes, viewable, suspended)`.

- [ ] **Step 3: Fix `priority_rows`' judge-lookup block**

Read `sed -n '850,975p' klausmate/retention.py` in full (this function is
long — `priority_rows` starts around line 856). Delete:
- the `"doubtful_count": 0` row-dict initializer (around line 931, right
  after `"card_count": 0"`)
- the guarded `try: from . import pertinence except: ...` block (around
  lines 941-946)
- the per-row `rejected: set[int] = set()` + `judged.json` read (around
  lines 950-956)
- the `rejected=rejected` keyword argument from both the `pdf_retention(...)`
  call and the `note_card_counts(...)` call (around lines 957-960) —
  these calls now take their non-`rejected` positional/keyword arguments
  only, matching Steps 1-2's new signatures
- the `doubtful_count=n_doubtful` keyword in the `row.update(...)` call
  (around line 968)
- fix the unpacking of `note_card_counts`'s result from 4 values to 3
  wherever this function assigns its return (e.g. `notes, viewable,
  suspended, doubtful = note_card_counts(...)` becomes `notes, viewable,
  suspended = note_card_counts(...)`)

- [ ] **Step 4: Grep-confirm no remaining `rejected`/`doubtful` in this file**

Run: `grep -n "rejected\|doubtful" klausmate/retention.py`
Expected: no output.

- [ ] **Step 5: Compile check**

Run: `python3 -m py_compile klausmate/retention.py`

- [ ] **Step 6: Commit**

```bash
git add klausmate/retention.py
git commit -m "retention: drop the rejected/doubtful parameters — cosine threshold only"
```

Do not run the full test suite as a completion gate here — proceed
immediately to Task 12, which fixes the two files whose 4-tuple unpacking
of `note_card_counts` would otherwise crash.

---

### Task 12: Fix `retention.py`'s two callers — `pdf_drive.py` and `pdf_map.py`

**Files:**
- Modify: `klausmate/pdf_drive.py`
- Modify: `klausmate/pdf_map.py`

**Interfaces:**
- Consumes: Task 11's new 3-tuple return shape from `note_card_counts`
  and the `rejected`-free signature of `pdf_retention`.
- Produces: both files compile and run against the new signatures; the
  "Doubtful cards…" UI is fully removed from `pdf_drive.py`.

- [ ] **Step 1: Delete the Cards-cell doubtful suffix in `pdf_drive.py`**

Read `sed -n '2050,2090p' klausmate/pdf_drive.py`. Delete the
`doubtful = int(row.get("doubtful_count") or 0)` line (originally 2062),
the `if doubtful: item.setText(2, f"{item.text(2)} · {doubtful} doubtful")`
block (originally 2069-2074), and the tooltip's
`if doubtful: bits.append(...)` line (originally 2082-2083). Leave the
surrounding suspended/Cards-count rendering untouched.

- [ ] **Step 2: Fix the Match Sensitivity dialog in `pdf_drive.py`**

Read the function in full (`sed -n '2315,2415p' klausmate/pdf_drive.py`).
Delete the `_rejected` computation block (originally 2346-2358), remove
the `rejected=_rejected` keyword from both `retention.pdf_retention(...)`
calls (originally lines 2366, 2390), and fix the
`retention.note_card_counts(...)` call (originally around 2400-2404):
remove its `rejected=_rejected` keyword, change its result-unpacking from
4 values to 3, and remove the `doubtful_count=doubtful` keyword from
whatever dict/call it was feeding.

- [ ] **Step 3: Delete `_on_doubtful` and its menu entry in `pdf_drive.py`**

Delete the `_on_doubtful(self, safe)` method (originally lines 2437-2456)
in full.

Delete the context-menu wiring block (originally lines 2688-2696):
`menu.addAction(DOUBTFUL_MENU_LABEL)...` and its connecting comment.

Delete the `DOUBTFUL_MENU_LABEL = "Doubtful cards…"` constant and its
comment (originally lines 91-96).

- [ ] **Step 4: Grep-confirm no remaining doubtful reference in `pdf_drive.py`**

Run: `grep -n "doubtful\|DOUBTFUL" klausmate/pdf_drive.py`
Expected: no output.

- [ ] **Step 5: Fix `pdf_map.py`'s retention fill**

Read `sed -n '2120,2170p' klausmate/pdf_map.py`. Delete the guarded
`try: from . import pertinence ... except: pertinence = None` block
(originally 2128-2133), delete the per-PDF `rejected: set = set()` +
judged-file read (originally 2156-2163), and remove the `rejected=rejected`
keyword from the `retention.pdf_retention(matches, ..., rejected=rejected)`
call (originally 2164-2166) — leave its other arguments as they are.

- [ ] **Step 6: Grep-confirm no remaining doubtful/rejected reference in `pdf_map.py`**

Run: `grep -n "doubtful\|rejected\|pertinence" klausmate/pdf_map.py`
Expected: no output.

- [ ] **Step 7: Compile check on both files**

Run: `python3 -m py_compile klausmate/pdf_drive.py klausmate/pdf_map.py`

- [ ] **Step 8: Run the full suite**

Same command as before. `tests/test_drive.py`'s Doubtful-menu test (lines
1900-1990 per research) will fail — note, continue; Task 15 fixes it.

- [ ] **Step 9: Commit**

```bash
git add klausmate/pdf_drive.py klausmate/pdf_map.py
git commit -m "pdf_drive, pdf_map: drop the Doubtful-cards UI and the rejected-set retention fill"
```

---

### Task 13: Strip `cost.py`'s judge-pricing

**Files:**
- Modify: `klausmate/cost.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `cost.py` has no `estimate_judge` function and no reasoning-
  model rows in `PRICES`.

- [ ] **Step 1: Delete the two reasoning-model rows from `PRICES`**

Read the full `PRICES` dict (`sed -n '1,30p' klausmate/cost.py`). Delete
the `"claude-sonnet-5": (2.0, 10.0)` (line 16) and `"claude-opus-5": (5.0,
25.0)` (line 17) rows.

- [ ] **Step 2: Delete `estimate_judge` and its constants**

Delete `JUDGE_PROMPT_OVERHEAD_TOKENS` (line 22) and
`JUDGE_OUTPUT_TOKENS_PER_CARD` (line 23). Delete `estimate_judge()` in
full (lines 41-48).

- [ ] **Step 3: Grep-confirm no remaining reference in this file**

Run: `grep -n "judge\|claude-sonnet-5\|claude-opus-5" klausmate/cost.py`
Expected: no output.

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile klausmate/cost.py`

- [ ] **Step 5: Run the full suite**

Same command as before.

- [ ] **Step 6: Commit**

```bash
git add klausmate/cost.py
git commit -m "cost: drop the judge pricing — reasoning-model rows and estimate_judge"
```

---

### Task 14: Delete `pertinence.py`, `anthropic_client.py`, and their tests; delete `plus.py`

> **Amended during Task 6's execution (ruling recorded in the SDD
> ledger, 2026-09-19):** `plus.py` and `tests/test_plus.py` also die
> here, not in Task 6. `anthropic_client.py` is `plus.py`'s last real
> caller (`plus.active(cfg)`) — deleting them together is the point in
> the sequence where `plus.py` genuinely has zero importers.

**Files:**
- Delete: `klausmate/pertinence.py`
- Delete: `klausmate/anthropic_client.py`
- Delete: `klausmate/plus.py`
- Delete: `tests/test_pertinence.py`
- Delete: `tests/test_anthropic_client.py`
- Delete: `tests/test_plus.py`
- Modify: `tests/test_live_api.py` (trim, not delete — it covers more than
  just the Anthropic smoke test)

- Modify: `scripts/mutation_audit.py` (remove deleted module names from the audit roster)

**Interfaces:**
- Consumes: Tasks 9-13's finished state (every real caller of
  `pertinence`/`anthropic_client` already stripped or collapsed) and
  Task 6's finished state (`openai_client.py` no longer depends on
  `plus`, and `service/` is already gone).
- Produces: nothing — pure deletion plus one trim.

- [ ] **Step 1: Grep-confirm no remaining importer of any of the three modules**

Run: `grep -rln "import pertinence\|from \. import pertinence\|import anthropic_client\|from \. import anthropic_client\|import plus\b\|from \. import plus\b" klausmate/*.py`
Expected: no output. If anything prints, stop and fix it before
continuing — if it's `plus` still referenced somewhere other than
`anthropic_client.py` itself, that's a real gap Task 6 should have
caught; investigate before deleting.

- [ ] **Step 2: Delete the three modules and three of their four test files**

```bash
git rm klausmate/pertinence.py klausmate/anthropic_client.py klausmate/plus.py
git rm tests/test_pertinence.py tests/test_anthropic_client.py tests/test_plus.py
```

- [ ] **Step 3: Trim `tests/test_live_api.py`**

Read the whole file (133 lines). It covers live-API smoke tests beyond
just Anthropic (per the research pass, roughly lines 55 and 111-130 are
the Anthropic-specific section). Remove only the Anthropic-specific
test function(s)/section — leave any OpenAI or other live-API coverage
in the file untouched. This file's tests only run under `KLAUS_LIVE_API=1`
per CLAUDE.md's standing rule, so removing the Anthropic section here is
safe to do without a live key.

Remove `pertinence`, `anthropic_client`, `plus` from `scripts/mutation_audit.py`
`AUDIT_MODULES` and adjust the adjacent description. Run the audit selftest
after the final cluster cleanup restores its baseline.

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile klausmate/*.py`

- [ ] **Step 5: Run the full suite**

Same command as before.

- [ ] **Step 6: Commit**

```bash
git add tests/test_live_api.py scripts/mutation_audit.py
git commit -m "Delete pertinence.py and anthropic_client.py — no judge, no Anthropic caller left"
```

(The `git rm` commands from Step 2 are already staged; this commit picks
up both those deletions and the `test_live_api.py` trim together.)

---

### Task 15: Fix every remaining pertinence/judge-aware test, verify D2 clean

**Files:**
- Modify: `tests/test_klausmate.py`
- Modify: `tests/test_index_queue.py`
- Modify: `tests/test_drive.py`
- Modify: `tests/test_cost.py`
- Modify: other test files only when they still assert deleted judge behavior

**Interfaces:**
- Consumes: Tasks 9-14's finished state.
- Produces: a fully green test suite with zero references to
  `pertinence`, `doubtful`, `DOUBTFUL_TAG`, `rejected=`, or judge-phase
  behavior anywhere under `tests/`.

- [ ] **Step 1: Find every remaining reference**

Run: `grep -rln "pertinence\|doubtful\|DOUBTFUL\|rejected=" tests/*.py`

- [ ] **Step 2: Fix each hit**

Same approach as Task 8 Step 2: read the full test function before
deciding whether to delete it wholesale (a test entirely about judge/
doubtful behavior — e.g. `test_klausmate.py`'s doubtful-tag block, lines
1268-1538; `test_index_queue.py`'s phase-four assertions, lines 326-519
and 1461; `test_drive.py`'s Doubtful-menu test, lines 1900-1990) or just
trim one fixture line that happens to set an now-removed field.

- [ ] **Step 3: Run the full suite until fully green**

Run: `PYTHONDONTWRITEBYTECODE=1 bash -c 'status=0; for t in tests/test_*.py; do echo "$t"; python3 "$t" || status=1; done; exit "$status"'`

- [ ] **Step 4: Compile the whole package one more time**

Run: `python3 -m py_compile klausmate/*.py`
Run: `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "tests: remove every pertinence/judge fixture and assertion — D2 clean"
```

**D2 is now complete.** Do not start Cluster D3 until this task's Step 3
passes with zero failures.

---

# Cluster D3 — Delete the embedded assistant dock

### Task 16: Remove the Library toolbar button and its handler from `pdf_drive.py`

**Files:**
- Modify: `klausmate/pdf_drive.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: the Library window's header row has no assistant button; the
  Map button and its neighbors keep working exactly as before.

- [ ] **Step 1: Delete the button construction**

Read `sed -n '1030,1060p' klausmate/pdf_drive.py`. Delete the block from
`assistant_tip = "Klaus Assistant (Ctrl+Shift+K)"` through
`header_row.addWidget(assistant_btn)` (originally lines 1040-1053) —
leave the Map button's own construction, which sits immediately before/
after this block, untouched.

- [ ] **Step 2: Delete `_open_assistant`**

Read `sed -n '2955,2975p' klausmate/pdf_drive.py`. Delete the
`_open_assistant(self)` method in full (originally lines 2962-2972).

- [ ] **Step 3: Grep-confirm no remaining reference**

Run: `grep -n "assistant" klausmate/pdf_drive.py`
Expected: no output (or only unrelated matches — inspect any hit by hand;
none are expected here).

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile klausmate/pdf_drive.py`

- [ ] **Step 5: Run the full suite**

Same command as before.

- [ ] **Step 6: Commit**

```bash
git add klausmate/pdf_drive.py
git commit -m "pdf_drive: remove the Library window's Klaus Assistant toolbar button"
```

---

### Task 17: Fix `__init__.py`'s assistant wiring (surgical — one function partially survives)

**Files:**
- Modify: `klausmate/__init__.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_stop_assistant_on_profile_close()` still exists and still
  calls `anki_endpoint.stop_for_profile()` on `profile_will_close` — only
  its assistant-dock-specific teardown blocks are removed. The Tools-menu
  entry and the `assistant_dock.setup()` startup call are both gone.

- [ ] **Step 1: Delete the Tools-menu entry**

Read `sed -n '615,650p' klausmate/__init__.py`. Delete the block from
`try: from . import assistant_dock; assistant_action = assistant_dock.menu_action()`
through its closing `if assistant_action is not None: ...` (originally
lines 637-648). Reword `install_menu()`'s docstring (originally lines
619-626) to drop its mention of the assistant entry. Leave the
"KlausMate Preferences…" action construction (originally lines 628-636)
untouched.

- [ ] **Step 2: Trim (not delete) `_stop_assistant_on_profile_close`**

Read the full function (`sed -n '1855,1900p' klausmate/__init__.py`).
It has three try/except blocks:
1. assistant_dock teardown (originally ~1878-1882)
2. assistant_dock close (originally ~1883-1886)
3. `anki_endpoint.stop_for_profile()` (originally ~1888-1897)

Delete blocks 1 and 2. **Keep block 3 exactly as it is** — `anki_endpoint`
is not being deleted (D5's plan repurposes it), so this function must
still stop it on profile close. Rename the function if its name no longer
fits after the assistant-specific parts are gone (e.g.
`_stop_endpoint_on_profile_close`), and update its one caller —
`gui_hooks.profile_will_close.append(_stop_assistant_on_profile_close)`
(originally line 2032) — to the new name if you rename it. Keeping the
old name is also acceptable if you'd rather not touch the registration
line; either way, block 3's behavior must be unchanged.

- [ ] **Step 3: Delete the `assistant_dock.setup()` startup call**

Read `sed -n '2015,2028p' klausmate/__init__.py`. Delete the block
`try: from . import assistant_dock; assistant_dock.setup() except: ...`
(originally lines 2019-2024).

- [ ] **Step 4: Reword `_start_assistant_endpoint`'s docstring**

Read `sed -n '1965,1985p' klausmate/__init__.py`. This function (lines
1968-1981) **survives entirely** — it starts `anki_endpoint`, not the
assistant dock — but its docstring (originally lines 1974-1976) mentions
the assistant dock. Reword those lines to describe what the function
actually does now (starts Klaus's MCP/AnkiConnect endpoint on profile
open) without mentioning a dock that no longer exists. Consider renaming
the function itself if `_start_assistant_endpoint` now reads misleadingly
— e.g. `_start_klaus_endpoint` — and update its one call site to match if
you do.

- [ ] **Step 5: Fix the stray comment mentioning `viewer_context.current()`**

Read line 845. It's a comment referencing the assistant's use of
`viewer_context` — reword it, since `viewer_context` is kept but its
consumer here is being described inaccurately once the dock is gone
(the real remaining consumer, per Task 26 in the D5 plan, is
`anki_endpoint.py`).

- [ ] **Step 6: Grep-confirm no remaining `assistant_dock` reference**

Run: `grep -n "assistant_dock" klausmate/__init__.py`
Expected: no output.

- [ ] **Step 7: Compile check**

Run: `python3 -m py_compile klausmate/__init__.py`

- [ ] **Step 8: Run the full suite**

Same command as before.

- [ ] **Step 9: Commit**

```bash
git add klausmate/__init__.py
git commit -m "__init__: remove the assistant dock's menu entry and startup call, keep the endpoint teardown"
```

---

### Task 18: Remove the "Assistant" page and `reasoning_model` from `manage_models.py`

**Files:**
- Modify: `klausmate/manage_models.py`

**Interfaces:**
- Consumes: D1's already-cleaned Klaus Plus state, D2's already-removed
  judge (confirms `reasoning_model` genuinely has zero readers left).
- Produces: no "Assistant" page in the sidebar; no `reasoning_model_edit`
  field on the API-keys page. `anthropic_key_edit` and
  `transcription_model_edit` (both built on the SAME page as
  `reasoning_model_edit`, and both saved by the SAME `save_assistant`/
  `load_assistant` functions) must keep working — this is the one place
  in this task where care is needed, per the research pass's explicit
  warning.

- [ ] **Step 1: Delete the "Assistant" page block**

Read `sed -n '1530,1630p' klausmate/manage_models.py`. Delete the
`_page("Assistant", ...)` call, the `assistant_reopen_cb` row, and the
Clear Sessions button/handler (`_clear_sessions_confirmed`,
`clear_assistant_sessions`) — this whole contiguous block, originally
lines 1533-1626.

- [ ] **Step 2: Delete `reasoning_model_edit`'s row on the API-keys page**

Read `sed -n '780,795p' klausmate/manage_models.py`. Delete the
`reasoning_model_edit` widget construction and its `_row(...)` call
(originally lines 784-791). Leave `transcription_model_edit`'s row (lines
794-802) and `anthropic_key_edit`'s row untouched — they are not part of
this deletion.

- [ ] **Step 3: Split `load_assistant`/`save_assistant` — keep the non-assistant parts**

Read the two functions in full (`sed -n '1622,1655p' klausmate/manage_models.py`).
Per the research pass, these two functions currently do double duty:
they load/save `anthropic_key_edit`, `reasoning_model_edit`, AND
`transcription_model_edit` together, plus the now-deleted
`assistant_reopen_cb`/`assistant_dock_width`/`assistant_dock_open` fields.

Since `reasoning_model_edit` no longer exists (Step 2) and the
`assistant_reopen_cb` etc. fields no longer exist (Step 1), decide one of
two approaches and apply it consistently:
- **(a)** Rename `load_assistant`/`save_assistant` to something reflecting
  their surviving scope (e.g. `load_transcription_settings`/
  `save_transcription_settings`), strip out every line referencing the
  now-deleted widgets, and keep the `transcription_model_edit`/
  `anthropic_key_edit` load/save lines inside them — update the two call
  sites (`save_all()` calls `save_assistant()`, and wherever
  `load_assistant()` is called during dialog population) to the new
  names.
- **(b)** Fold the surviving `transcription_model_edit`/`anthropic_key_edit`
  load/save lines directly into `sync_embed_widgets()`/`save_embed()`
  (which already handle the rest of the API-keys page), and delete
  `load_assistant`/`save_assistant` entirely.

Either is acceptable — pick whichever reads more naturally once you see
the actual current function bodies (read them before deciding; the
research pass flagged this as needing care but did not prescribe which
shape to end with). Whichever you choose, **`transcription_model_edit`
and `anthropic_key_edit` must still be populated on dialog open and
written on Save** — verify this with Step 7's test run, specifically
watching for `tests/test_manage_models_assistant.py` (Task 20 covers
fixing that file's own now-stale assertions, but a genuine functional
regression here — e.g. `transcription_model` silently no longer saving —
would show up as new failures beyond what Task 20 expects to fix).

- [ ] **Step 4: Drop "Assistant" from `_finish_nav`'s page-order call**

Find (originally lines 1658-1659):
```python
_finish_nav("General", "Appearance", "Assistant",
            "API keys & models")
```
Change to:
```python
_finish_nav("General", "Appearance", "API keys & models")
```

- [ ] **Step 5: Delete the two orphaned signal-wiring lines**

Find (originally lines 2737-2738):
```python
assistant_reopen_cb.toggled.connect(lambda _c: mark_dirty())
clear_sessions_btn.clicked.connect(...)
```
Delete both. Also delete line 2735
(`reasoning_model_edit.textEdited.connect(...)`) — confirm exact current
line with `grep -n "reasoning_model_edit\|assistant_reopen_cb\|clear_sessions_btn" klausmate/manage_models.py`
since earlier steps in this task shift line numbers.

- [ ] **Step 6: Grep-confirm no remaining reference**

Run: `grep -n "assistant_reopen\|assistant_dock_width\|assistant_dock_open\|reasoning_model\|clear_sessions_btn\|Clear Sessions" klausmate/manage_models.py`
Expected: no output.

- [ ] **Step 7: Compile check**

Run: `python3 -m py_compile klausmate/manage_models.py`

- [ ] **Step 8: Run the full suite**

Same command as before. `tests/test_manage_models_assistant.py` and
`tests/test_dialog_logic.py` will fail on stale widget-name references —
note, continue; Task 20 fixes them.

- [ ] **Step 9: Commit**

```bash
git add klausmate/manage_models.py
git commit -m "manage_models: delete the Assistant page and reasoning_model, keep transcription/Anthropic-key saves working"
```

---

### Task 19: Delete `agent_host.py`, `assistant_dock.py`, `assistant_sessions.py`, and their tests

**Files:**
- Delete: `klausmate/agent_host.py`
- Delete: `klausmate/assistant_dock.py`
- Delete: `klausmate/assistant_sessions.py`
- Delete: `tests/test_agent_host.py`
- Delete: `tests/test_assistant_dock.py`
- Delete: `tests/test_assistant_sessions.py`

- Modify: `scripts/mutation_audit.py` (remove deleted module names from the audit roster)

**Interfaces:**
- Consumes: Tasks 16-18's finished state (every real caller already
  stripped).
- Produces: nothing — pure deletion. `viewer_context.py` is NOT touched
  by this task (it survives — `pdf_viewer.py` and `anki_endpoint.py` both
  still import it, confirmed by the research pass).

- [ ] **Step 1: Grep-confirm no remaining importer of any of the three modules**

Run: `grep -rln "import agent_host\|from \. import agent_host\|import assistant_dock\|from \. import assistant_dock\|import assistant_sessions\|from \. import assistant_sessions" klausmate/*.py`
Expected: no output.

- [ ] **Step 2: Delete the three modules and their tests**

```bash
git rm klausmate/agent_host.py klausmate/assistant_dock.py klausmate/assistant_sessions.py
git rm tests/test_agent_host.py tests/test_assistant_dock.py tests/test_assistant_sessions.py
```

- [ ] **Step 3: Confirm `viewer_context.py` is untouched and still has its real consumers**

Run: `grep -rln "viewer_context" klausmate/*.py`
Expected: `pdf_viewer.py` and `anki_endpoint.py` (at minimum) still
appear — if either is missing, something in Tasks 16-18 accidentally
touched a live consumer; investigate before proceeding.

Remove `agent_host`, `assistant_sessions` from `scripts/mutation_audit.py`
`AUDIT_MODULES` and adjust the adjacent description. Run the audit selftest
after the final cluster cleanup restores its baseline.

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile klausmate/*.py`

- [ ] **Step 5: Run the full suite**

Same command as before.

- [ ] **Step 6: Commit**

```bash
git add scripts/mutation_audit.py
git commit -m "Delete agent_host.py, assistant_dock.py, assistant_sessions.py — the embedded copilot"
```

---

### Task 20: Remove orphaned config keys, fix every remaining test, final D3 verify

**Files:**
- Modify: `klausmate/config.json`
- Modify: `klausmate/__init__.py` (`_LEGACY_KEYS_DROPPED`)
- Modify: `tests/test_manage_models_assistant.py`
- Modify: `tests/test_dialog_logic.py`
- Modify: `tests/test_api_first_config.py`

**Interfaces:**
- Consumes: Tasks 16-19's finished state.
- Produces: a fully green test suite; `config.json` and
  `_LEGACY_KEYS_DROPPED` both reflect the final, assistant-free,
  judge-free, Plus-free config surface.

- [ ] **Step 1: Remove orphaned assistant-dock config keys from `config.json`**

Run: `grep -n "assistant_reopen\|assistant_dock_width\|assistant_dock_open\|reasoning_model" klausmate/config.json`
Delete each matching line (these were the dock's own persisted
UI-state keys — confirmed dead once Task 18 removed every reader).
Verify JSON validity after editing:
`python3 -c "import json; json.load(open('klausmate/config.json'))"`

- [ ] **Step 2: Add them to `_LEGACY_KEYS_DROPPED`**

Same pattern as Task 7 Step 2 — append a new dated block:
```python
    # 2026-09-18: the embedded assistant dock removed (see
    # docs/superpowers/specs/2026-09-18-local-model-reversion-design.md).
    "assistant_reopen",
    "assistant_dock_width",
    "assistant_dock_open",
    "reasoning_model",
```
placed before the tuple's closing `)`.

- [ ] **Step 3: Find every remaining assistant-aware test reference**

Run: `grep -rln "assistant_dock\|assistant_sessions\|agent_host\|reasoning_model\|assistant_reopen" tests/*.py`

- [ ] **Step 4: Fix each hit**

Same approach as Tasks 8 and 15: read each test fully, delete tests
whose entire purpose was assistant-dock behavior, trim fixtures that
merely set a now-removed config key as an incidental part of a larger
test.

- [ ] **Step 5: Run the full suite until fully green**

Run: `PYTHONDONTWRITEBYTECODE=1 bash -c 'status=0; for t in tests/test_*.py; do echo "$t"; python3 "$t" || status=1; done; exit "$status"'`

Expected: every test file passes, loop reaches the end with no break.

- [ ] **Step 6: Full-package compile check, both paths**

Run: `python3 -m py_compile klausmate/*.py`
Run: `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`

- [ ] **Step 7: Grep-confirm zero dangling references across the whole package**

Run each of these and confirm no output (aside from expected false
positives you've already hand-checked):
```bash
grep -rn "import plus\b" klausmate/*.py
grep -rn "import pertinence\b\|import anthropic_client\b" klausmate/*.py
grep -rn "import agent_host\b\|import assistant_dock\b\|import assistant_sessions\b" klausmate/*.py
grep -rln "klaus_plus_\|assistant_reopen\|assistant_dock_width\|assistant_dock_open" klausmate/config.json
```

- [ ] **Step 8: Commit**

```bash
git add klausmate/config.json klausmate/__init__.py tests/
git commit -m "config, tests: retire assistant-dock keys, D3 clean — demolition complete"
```

**Cluster D3 is now complete, and with it the whole Demolition plan.**
The working tree has no Klaus Plus, no pertinence judge, and no embedded
assistant dock — `anki_endpoint.py` and `viewer_context.py` both survive
untouched, ready for the D5 plan (the MCP bridge) to build on. `CLAUDE.md`
still describes the old, now-removed systems as if they're live — that
doc-inversion pass is its own task in a later plan (per the design spec's
"Doc inversion" section), not part of this one.

---

## Self-Review Notes (for whoever executes this plan)

- **Line numbers throughout this plan are anchors, not guarantees.**
  Every step that references a specific line range was sourced from a
  research pass against the tree as it stood before Task 1 ran. Each
  earlier task in the same cluster shifts line numbers for files touched
  by later tasks in that cluster (most visibly `manage_models.py`, hit by
  both D1 Task 5 and D3 Task 18). Every step says to re-confirm with
  `grep`/`sed -n` before editing for exactly this reason — treat that
  instruction as load-bearing, not decorative.
- **Two spec-vs-code corrections are already folded into this plan**
  (do not re-introduce the spec's original, now-superseded framing):
  the Library toolbar button lives in `pdf_drive.py`, not `__init__.py`
  (Task 16, not part of Task 17); and Klaus Plus's UI is email/password
  sign-in, not a licence-key field (Task 5's steps match the real code).
- **`viewer_context.py` is never touched by this plan.** It is a shared
  module with real consumers beyond the deleted assistant dock
  (`pdf_viewer.py`, `anki_endpoint.py`) — Task 19 Step 3 exists
  specifically to catch an accidental edit to it before it ships.
