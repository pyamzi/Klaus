# Ollama embeddings restoration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore fully local embeddings with managed Ollama installation, server lifecycle and model inventory in the current Preferences shell.

**Architecture:** Restore the three historical stdlib runtime modules, then replace the cloud embedding adapter and setup gates without changing page-level storage or matching. Add runtime/model controls as a separate UI task. Local transcription lands first, so the OpenAI client can be removed when embeddings stops using it.

**Tech Stack:** Python with postponed annotations, stdlib urllib/subprocess, Ollama 0.31.1, existing Anki/PyQt6 shell.

**Spec:** `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`, D4.

## Global Constraints

- Restore full runtime management, not only a client. No Voyage, cloud fallback, OCR, chat UI or provider picker.
- Restore from `git show 1b6fccd^:klausmate/ollama_client.py`, `ollama_runtime.py`, `ollama_setup.py`; historical adapter at `f74a09e^:klausmate/embeddings.py`.
- Default provider `ollama`, model `nomic-embed-text`, endpoint `http://127.0.0.1:11434`, native dimensions `0`.
- No third-party Python dependencies. Never exercise actual profile data, credentials, microphone or Anki during tests.
- Profile-open readiness may start an existing runtime in a background operation; it must never download/install a runtime or model without the user's explicit Preferences action.
- Preserve main checkout/symlink, unrelated logo edits, collection ownership and current Preferences shell. No push or merge. No em dash in new prose.
- Pin/version archive already verified in scratch: `/tmp/klaus-ollama-smoke/ollama --version` reports 0.31.1; archive SHA checked against upstream sha256sum. Tests still use fake servers and scratch assets.

## Review Focus

- Existing cloud profile with merged defaults: one-time migration resets its model to the local default, retires credentials, then preserves later user choices.
- GUI PATH or unavailable runtime: readiness reports configuration needs without silently downloading or blocking Qt.
- Occupied port and concurrent config saves: moved endpoint is patched narrowly on the main thread without replacing unrelated settings.
- Existing user-managed Ollama: reuse it and never stop it when Klaus closes or a user presses Stop.
- Corrupt archive, failed pull, dialog closed during progress: actionable error, safe temporary cleanup, no stale widget callback or false success.

### Task 1: Restore and verify the runtime modules

**Files:** Create `klausmate/ollama_client.py`, `klausmate/ollama_runtime.py`, `klausmate/ollama_setup.py`, `tests/test_ollama_client.py`, `tests/test_ollama_runtime.py`.

**Interfaces:** Preserve historical `OllamaClient(endpoint, timeout=30)`, `.embed(model,texts)`, `.health()`, `.list_models()`, `.pull(model,on_event)`, `.delete(model)`; `ensure_server(cfg,save_config=None) -> EnsureResult`, `full_setup(cfg,on_progress=None,cancel_flag=None,save_config=None)`, `update_runtime(...)`, `server_manager.stop()`. Add no parallel alternate manager.

- [ ] **Step 1: Add failing import/behavior tests with the klaus-test bootstrap.** Fake stdlib HTTP server routes return `/api/tags`, `/api/embed`, streaming `/api/pull` and `/api/delete` responses. Assert ordered vectors, wrong response count rejection, server error, refused connection, model list and progress events. Example core assertion:

```python
client = OllamaClient(fake_server_url)
check("vectors preserve order", client.embed("nomic-embed-text", ["a", "b"]) == [[1, 0], [0, 1]])
check("model inventory", client.list_models() == ["nomic-embed-text:latest"])
```

`fake_server_url` is the test's loopback `ThreadingHTTPServer` fixture, with recorded request bodies; assert the real request uses `/api/embed`, the selected model, and the input list.

For runtime tests, override `_USER_FILES` before any path call, and fake download/process/probe functions. Assert missing runtime returns `needs_provision` without invoking `provision_runtime`; remote endpoint is rejected before any request; external reachable process is not killed; owned process is stopped; occupied port yields a saved new endpoint; invalid SHA and path traversal fail without completion marker. Check cancellation cleanup and platform asset selection.

- [ ] **Step 2: Run both new files and record the missing-module RED result.**
- [ ] **Step 3: Restore the historical source with exact git-show commands.** Retain the module boundaries and public interfaces. Make only necessary local-mode fixes: validate loopback endpoint before probing or sending embeddings, bypass proxies/redirects for local content, set `OLLAMA_NO_CLOUD=1` for owned processes, retain safe extraction and PID ownership checks. A user-owned process is never adopted merely because it listens on the port. Do not restore OCR callers. Keep existing download/checksum/disk-space/cancellation/platform behavior.
- [ ] **Step 4: Run focused tests and compile the three files through both paths.** No real server spawn, model pull or system install in automatic tests. Use fake archives to cover successful extraction and failed SHA, and verify saved config callback receives the moved endpoint.
- [ ] **Step 5: Commit only the three modules and two test files.**

### Task 2: Convert embedding, config and readiness behavior

**Files:** Modify `klausmate/embeddings.py`, `klausmate/__init__.py`, `klausmate/config.json`, `klausmate/setup_flow.py`, `klausmate/index_queue.py`, `klausmate/manage_models.py`, affected tests, `scripts/mutation_audit.py`; delete `klausmate/openai_client.py`, `tests/test_openai_client.py`, `tests/test_live_api.py` once no caller remains; delete `cost.py` and its test only after verifying no live estimator caller.

**Interfaces:** `provider_name(cfg) -> "ollama"`, `embedding_model(cfg) -> configured name or nomic-embed-text`, `index_signature(cfg) -> ("ollama",model,0)`, `OllamaEmbeddings(get_config).embed(texts,kind="document")`. Preserve `signature_matches`, batching, normalization, page index format and cancellation. Use `patch_config({"endpoint": updated["endpoint"]})` as the runtime save callback rather than writing a captured whole config.

- [ ] **Step 1: Add failing behavioral local-provider/config tests.** Stub the real Ollama client, assert selected model and endpoint, unchanged input ordering and normalized output through `embed_batches`. A cloud signature must fail `signature_matches` against the new local signature; later model changes invalidate it. Use the real migration harness with defaults merged under an old OpenAI profile. Assert credentials disappear, first migration sets nomic-embed-text and native dimensions, a saved local custom model survives the second migration, and unrelated appearance/library settings survive.
- [ ] **Step 2: Run the relevant focused files and record RED.**
- [ ] **Step 3: Replace the cloud adapter and defaults.** Translate `OllamaError` into `EmbeddingError` with local actionable wording. Remove obsolete Plus/key/rate-limit copy. Preserve current vector/storage APIs. Unretire `embedding_provider`, `endpoint`, `runtime_auto_setup` (default true, silent existing-runtime startup only); retire all provider credentials and `_embed_key_setup_declined`. Add a one-time `_local_embeddings_migrated` marker written by migration, never defaulted to true. On first transition set the model to nomic-embed-text and dimensions0; later migrations never reset user choice. Remove the former OpenAI rename/model-reset migration, while preserving unrelated legacy-key scrubbing.

```python
if not cfg.get("_local_embeddings_migrated"):
    cfg.update(embedding_provider="ollama", embedding_model="nomic-embed-text",
               embedding_dimensions=0, _local_embeddings_migrated=True)
    changed = True
```

- [ ] **Step 4: Rewire readiness and indexing.** Remove API-key gates and paid-price calculations, retain queue cancellation/locking and model-change confirmation with No as default. Text describes local work and re-indexing, never a bill. Welcome and readiness direct users to Local models. Run `ensure_server` in a collection-free background operation when automatic management is enabled; no provisioning at profile open. Stop only the owned runtime on profile close. Preserve library-folder prompt ordering and stale-index sweep behavior. Fresh settings writes read current config or use narrow patches.
- [ ] **Step 5: Convert the basic Preferences page.** Rename API keys & models to Local models, remove both credential fields and save paths, use free-text local model plus endpoint, and preserve local transcription rows from D6. Replace Check Keys with a background local connection check. The detailed inventory/installation controls arrive in Task3; basic user-installed Ollama must already be configurable and usable here. Preserve current layout/search/navigation and index button behavior.
- [ ] **Step 6: Remove final cloud code and obsolete tests only after a focused import/caller scan.** D6 has removed the recorder import. Remove OpenAI client/tests and paid smoke file. Remove cost module/test if every caller is gone. Update mutation roster for deleted/restored modules. Convert obsolete API-first tests to local migration/readiness behavior rather than deleting mixed coverage. No old prices or API keys remain in product controls.
- [ ] **Step 7: Run focused tests, full aggregate suite, audit selftest and both compile paths, then commit exact files.** Exclude the unrelated Preferences logo hunk. Record all test counts/skips/diagnostics.

### Task 3: Build runtime and model controls in Preferences

**Files:** Modify `klausmate/manage_models.py`, its relevant tests and `klausmate/config.md`; create `tests/test_local_model_settings.py` for meaningful offscreen UI coverage if current fixtures cannot exercise the wiring.

**Interfaces:** Consume Task1 `ensure_server`, `full_setup`, `update_runtime`, `server_manager.stop`, and `OllamaClient` inventory/pull/delete methods. Use current `_page`, `_row`, `_finish_nav`, dirty/save and dialog-liveness patterns. No alternate dialog shell.

- [ ] **Step 1: Write failing offscreen UI tests with fake task manager/runtime/client.** Instantiate the actual Preferences dialog, locate the Local models page and controls, and assert user actions call the expected provider method. Pin model path/name save and reload, no install on page open, progress delivered on main thread, close-during-progress safely ignored, and Stop disabled or informative for an external process.
- [ ] **Step 2: Run focused tests and record RED.**
- [ ] **Step 3: Add runtime health/status, Install/start, Stop managed server, update when available, and automatic management toggle.** All network/process work goes through collection-free background operations. The installation button is the explicit consent to download; show estimated download size before starting using the runtime helper. Reuse error and progress callbacks, do not add a second process manager. Disabled/busy controls return to usable state on every success/failure path.
- [ ] **Step 4: Add installed model list, Refresh, free-text pull name, Pull progress and Delete with a confirmation.** Selecting an installed model can populate the existing embedding model field, with Save and its ordinary re-index confirmation owning changes. Inventory refresh does not silently change configured model. Stream pull progress into a label/progress bar on the main thread, retain dialog-liveness guards, and display actionable failures. No automatic model download on startup.
- [ ] **Step 5: Update the local-model section of config.md with actual control names and paths, including managed vs external stop ownership.**
- [ ] **Step 6: Run focused UI tests, full aggregate suite, both compile paths, inspect actual offscreen rendered dialog for clipped controls, and commit only owned changes.** No live Anki or actual downloads needed to prove UI mechanics. Preserve logo edit unstaged. Record remaining real-device verification limits.

## Self-review

Full runtime restore, local provider, credentials retirement, setup/index gate inversion and separate current-shell UI work are each assigned. D6-first ordering removes the last cloud caller in Task2. The five review conditions have direct tests. No new cloud provider, OCR or assistant surface is introduced.
