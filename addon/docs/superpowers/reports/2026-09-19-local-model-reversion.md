# Local-model reversion: completion and verification

2026-09-19. D1-D6 implementation is complete locally through `63e11ce`.
Their task and whole-plan reviews are recorded as complete in the source ledgers.
Integration Task 2 updates actual-state documentation and builds a local package;
its final independent review is controller-owned. Nothing here establishes a push,
merge, publication, live Anki session or working Claude Desktop connection.

## Deliverables and commits

| Deliverable | Commits / reviewed range | Result and historical gate evidence |
| --- | --- | --- |
| D1 subscription removal | Within `a1d56fd..125450f`, service `790aac0`, migration `f1ed8ea`, `bfec471`, `96c9662`, cleanup `c8daa40` | Service and subscription UI/state removed; D1 gate 5,327 custom checks, 50 files, paid smoke skipped. |
| D2 cosine matching | `54e1aea`, `20a51da`, `f1dc9fd`, `c58219a` within demolition range | Reasoning judge removed, cosine matching/duplicates retained, reserved historical tag preserved; D2 gate 5,077 checks, 47 files, paid smoke and historical host fixture skipped. |
| D3 embedded assistant removal | `b2695ff`, `17ac314`, `20bc038`, `9425dc0`, `15795dc`, `2cf81db`, `125450f` | Dock/host/sessions removed, endpoint/context retained. Demolition gate 4,637 checks, 44 files, paid smoke skipped; final review approved `a1d56fd..125450f`. |
| Guidance inversion | `e84663d`, `93bd7b1` | Transitional user/agent guidance inverted before rebuild; this integration task replaces remaining transitional claims with actual controls. Historical spec bodies preserved. |
| D6 local transcription | `e5f9104`, `69a0271`, `ab07c96`, `348f071` | Adapter, recorder and Preferences paths/language; configured-shell discovery correction. Historical aggregate 4,725 checks/46 files; final focused adapter 58 and settings 13. Real sample spike below. |
| D4 Ollama restoration | `b63bfd3`, `651dfd1`, `3dafb28`, `30255fb`, `4b976a4`, `b3633cf` | Managed runtime/local client, config migration, settings inventory and pull/delete, profile lifecycle and automatic port persistence. Runtime/client 35 unittest cases; final focused UI 142, local embeddings 15, setup 33. |
| D5 external MCP | `bac10f9`, `92a99f2`, `735b654`, `63e11ce` | Private discovery, standalone bridge, current_page and config copying; ownership race, missing-fchmod and UTF-8 fixes. Final endpoint 117/bridge 29; current_page 11/settings 18. |

Source implementations: [Ollama client](../../../klausmate/ollama_client.py),
[runtime](../../../klausmate/ollama_runtime.py), [setup](../../../klausmate/ollama_setup.py),
[embeddings](../../../klausmate/embeddings.py), [transcription](../../../klausmate/local_transcription.py),
[recorder](../../../klausmate/lecture_recorder.py), [endpoint](../../../klausmate/anki_endpoint.py),
[bridge](../../../klausmate/scripts/mcp_stdio_bridge.py) and [Preferences](../../../klausmate/manage_models.py).
Prior counts above are historical ledger evidence, not additional final runs.

## Final verification

Code revision tested: `63e11ce` plus the existing unstaged logo work in
`klausmate/manage_models.py`, `klausmate/top_bar.py`, `klausmate/web/klaus-logo.svg`
and `tests/test_top_bar.py`. Existing board changes and the brand SVG deletion
also remained in the checkout. This is a combined working-tree result, not a
claim that the package exactly represents a clean committed tree.

Ran every `tests/test_*.py` independently, without early break:

```sh
env -u KLAUS_LIVE_API PYTHONDONTWRITEBYTECODE=1 python3 .superpowers/sdd/2026-09-19-local-model-integration/run_suite.py .superpowers/sdd/2026-09-19-local-model-integration/final-full
```

Result: **50 files reached, 50 exit zero, 4,858 custom checks plus 35 unittest
cases, zero failures**. No test skip markers were emitted in this final run.
The removed paid API smoke is not a current test file; paid APIs were not run.
The runner supplies `QT_QPA_PLATFORM=offscreen`. No full-suite repeat followed
subsequent documentation-only edits.

Output is not pristine: existing Qt offscreen `propagateSizeHints()` and `raise()`
warnings appear, together with deliberately exercised failure diagnostics
(transcription keeps WAV, failed subscriber/callback, corrupt index/cache,
closed/deleted widgets, bad search and synthetic indexing failures). Existing
incomplete-stub diagnostics include missing `get_config`, `addonManager` and
`run_on_main` in the drive suite. These did not produce failed checks. Full logs
remain under the ignored final-full directory; this report preserves counts.

```sh
env PYTHONDONTWRITEBYTECODE=1 python3 scripts/mutation_audit.py --selftest
```

Mutation **selftest** passed all three cases, 6 test-file executions; 198 working
tree files hashed unchanged. This is not a full all-module mutation campaign.
Recursive `py_compile` passed **105 Python files per path**, including vendored
Python and `scripts/mcp_stdio_bridge.py`, for both the direct `klausmate/` tree
and `/Users/pyamzi/Library/Application Support/Anki2/addons21/klausmate` symlink.
The symlink resolved to the current checkout. All bytecode went to a disposable
temporary directory; `user_files/` was excluded. `git diff --check` is the final
whitespace gate. The K-296 missing-report gate was observed RED (exit 1) before
this report existed, then GREEN (`test -s`); no feature code changed in Task 2.

### Per-file final results

| Test file | Result |
| --- | --- |
| `test_anki_endpoint.py` | 117 checks passed |
| `test_anki_tools.py` | 52 checks passed |
| `test_api_first_config.py` | 14 checks passed |
| `test_background.py` | 111 checks passed |
| `test_board.py` | 83 checks passed |
| `test_board_skill_parity.py` | 8 checks passed |
| `test_bridge_reentrancy.py` | 80 checks passed |
| `test_browse_highlight.py` | 24 checks passed |
| `test_browse_retention.py` | 111 checks passed |
| `test_browse_toggles.py` | 96 checks passed |
| `test_browse_toolkit.py` | 131 checks passed |
| `test_card_forge.py` | 60 checks passed |
| `test_card_index.py` | 3 checks passed |
| `test_current_page.py` | 11 checks passed |
| `test_dashboard.py` | 58 checks passed |
| `test_dialog_logic.py` | 128 checks passed |
| `test_drive.py` | 361 checks passed |
| `test_duplicates.py` | 109 checks passed |
| `test_external_client_settings.py` | 18 checks passed |
| `test_heatmap.py` | 142 checks passed |
| `test_imports.py` | 53 checks passed |
| `test_index_queue.py` | 150 checks passed |
| `test_klausmate.py` | 405 checks passed |
| `test_lecture_recorder.py` | 123 checks passed |
| `test_lecture_view.py` | 122 checks passed |
| `test_library_explorer.py` | 83 checks passed |
| `test_local_embeddings.py` | 15 checks passed |
| `test_local_model_settings.py` | 162 checks passed |
| `test_local_transcription.py` | 58 checks passed |
| `test_local_transcription_settings.py` | 13 checks passed |
| `test_manage_models_assistant.py` | 49 checks passed |
| `test_mcp_stdio_bridge.py` | 29 checks passed |
| `test_md3_switch.py` | 44 checks passed |
| `test_ollama_client.py` | 9 unittest cases passed |
| `test_ollama_runtime.py` | 26 unittest cases passed |
| `test_page_store.py` | 87 checks passed |
| `test_pdf_dock.py` | 107 checks passed |
| `test_pdf_map.py` | 319 checks passed |
| `test_pdf_notes.py` | 99 checks passed |
| `test_pdfjs_viewer.py` | 340 checks passed |
| `test_projection.py` | 85 checks passed |
| `test_retention_history.py` | 70 checks passed |
| `test_setup_crop_theme.py` | 33 checks passed |
| `test_slot_guards.py` | 19 checks passed |
| `test_tag_migrate.py` | 125 checks passed |
| `test_theme.py` | 359 checks passed |
| `test_top_bar.py` | 88 checks passed |
| `test_transcript_strip.py` | 38 checks passed |
| `test_viewer_context.py` | 17 checks passed |
| `test_window_chrome.py` | 49 checks passed |

## Real transcription spike

Earlier in D6, whisper.cpp **v1.9.4**, a CPU-only scratch build using CMake 4.4.3,
transcribed upstream `samples/jfk.wav` with `ggml-tiny.en.bin`. The separate
48 kHz stereo PCM16 fixture also passed the real CLI. The production adapter was
then exercised on the upstream sample and returned nonempty text containing
`country`. This was a scratch sample, not a microphone or a live Anki recording.
The build emitted an upstream `stb_vorbis.c` compiler warning and exited zero.

CLI contract verified: `whisper-cli -m MODEL -f WAV -l en -oj -of PREFIX --prompt TEXT`;
parse `PREFIX.json`, join `transcription[].text`. Diagnostic stdout is not the
parse source. Model SHA256:
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
The spike evidence remains at `/tmp/klaus-whisper-spike/spike-evidence.json` and
D6's ignored `task-1-report.md`. Final integration did not download models,
install runtimes, access a microphone or repeat the spike.

## Package

Command: `bash scripts/package.sh`. The intentional tracked build change is only
`manifest.json`'s `mod` timestamp and the script's normal final newline; no
version or licensing change was invented.
The script's obsolete service deployment/license explanation was replaced with
an accurate staging comment. The local archive includes the checkout's separately
requested, still unstaged logo changes. Those source changes are not staged or
committed by K-296.

- Path: [dist/klausmate.ankiaddon](../../../dist/klausmate.ankiaddon)
- Bytes: **1,406,834**
- SHA256: `bf29d1c8ccb9afde90e3bfcd445005bfa42924312a9ef037856a5ffb302ccff4`
- Archive entries: **147**
- Manifest `mod`: `1789854521`; `human_version`: `0.1.3`.

After the Task 2 punctuation review fix, the archive was rebuilt and its hash,
size and manifest timestamp above refreshed. The full suite, compiles and audit
were not repeated for this documentation-only change.

Independent `zipfile` inspection passed every required assertion: bridge,
local_transcription and ollama_runtime present; all basename `meta.json*` excluded;
`user_files/` contains only its directory entry and README; plus, pertinence,
agent_host, assistant_dock, assistant_sessions, openai_client and anthropic_client
absent. Also checked root `__init__.py`, no wrapper folder or bytecode, and byte
identity of key modules, current logo files, packaged README/config and the storage
README template. No package is uploaded or published.

## Documentation and link checks

Current user docs now describe Ollama runtime/model controls, local whisper.cpp
paths/language, cosine-only matching and external MCP setup with Python 3.9+.
All 38 shipped config keys appear in the reference, with automatic state and
optional overrides distinguished from defaults. Modules and relative source links
were checked against the current tree. Historical specifications remain dated and
superseded; their bodies were not rewritten. Legacy migration literals and dated
architecture history are not live feature claims.

Opened the official [Ollama quickstart](https://docs.ollama.com/quickstart),
[whisper.cpp v1.9.4 CLI guide](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/cli/README.md),
[local MCP setup guide](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers)
and [Anki site](https://apps.ankiweb.net/) on 2026-09-19. Runtime/model downloads use
the network. Inference within Klaus is local; an external client's chosen provider
may receive requested lecture text, transcripts, images and card context. No
external-client configuration was modified. Existing license files are linked,
not replaced with invented terms. The existing support invite is retained;
the browser opener could not access it, while an independent HTTP request returned
200 at its Discord invite URL. That does not prove invite membership or future validity.

## Decision log retained from execution

The ignored ledgers below are the original evidence. Identical rulings repeated
across rebuild plans are deduplicated here; continuation paragraphs were read,
including demolition Task 6. These are execution decisions, not new permissions.

1. Continue the approved D1-D6 scope locally without repeated plan approval; no
   push or merge. Use the existing main checkout after its moves, preserve the
   sequential SDD implementation/review workflow and retrieved helper instructions.
2. Preserve all plan ledgers/reports and this handoff until the whole project has
   final evidence and is merged. No interim cleanup or merge prompt.
3. Run D6 before D4 so transcription moves locally before provider keys disappear;
   retain the OpenAI client only until its final embedding caller is replaced.
4. Demolition Task 4's early-break suite hid new obsolete-Plus setup assertions.
   Correct the report rather than changing intended missing-key behavior. Assign
   `test_setup_crop_theme.py` to Task 8 and always aggregate every test file.
5. Task 5 exposed recorder-test and stale-comment follow-ups. Preserve unrelated
   controls and classify failures by evidence; its original pre-existing recorder
   attribution was later corrected when Task 6 review identified service coupling.
6. **Task 6 plan defect:** `anthropic_client.py` still called `plus.active`, and
   `openai_client.py` retained Plus type dependencies. Delete the zero-dependent
   service and sever unreachable Plus endpoint/header parameters now; defer plus.py
   and its tests until Task 14 deletes the last Anthropic caller. Grep-confirm
   callers before deletion. Low-risk narrow client edits were needed to break the
   otherwise permanent dependency, not to delete a still-used client.
7. Task 6 review assigned recorder tests and mutation sandbox service dependencies
   to Task 8. The original self-report combined incompatible file totals; the
   later verified baseline at `0fb7d6e` was 50 files: 42 pass, 1 skip, 7 fail.
   Task 6 became complete only after review and report/plan correction. D2 waited
   for the D1 green gate. Keep migration and plus/anthropic tests until Task 14.
8. Retire the additional `klaus_plus_email` display-state key with the subscription
   settings; preserve unrelated config and dock-only embedding-decline state.
9. Remove deleted modules from the mutation audit roster at Tasks 14/19 so the
   gate covers live modules. Task 15 also repairs actual cost/judge test failures
   beyond its initial file list.
10. Tasks 11/12 form a linked return-shape producer/consumer change with separate
    commits and combined review. Honor the plan's no-full-suite intermediate
    Task 11 gate; full verification resumes after the caller updates in Task 12.
11. Batch same-shape Tasks 16/17 entry-point removals in one dispatch, keeping
    separate commits and full-suite evidence. Task 19 also deletes the orphaned
    agent_spike probe; historical Claude stream fixtures stay unchanged.
12. Restore surviving reserved `!Library::Doubtful` regression coverage in Task 15.
    Task 20 preserves dock-only decline state plus surviving settings read-back
    and persistence tests. Existing inventoried Qt/stub noise is not broad cleanup.
13. During D6 settings review, fix the new incomplete widget fixture and assert
    empty application diagnostics; retain generic Qt platform warnings. Final D6
    review adds configured login-shell discovery and its behavioral regressions.
14. D4 Task 2 extends ownership to config documentation because config changes
    must ship with their reference. Aggregate-exposed obsolete fixtures and narrow
    Preferences navigation text are repaired; finish the first aggregate, then
    use focused reruns for test/copy-only fixes.
15. D4 runtime review requires tar.zst member/link validation and cancellation
    checks before completion; fake converters with real tar fixtures cover logic.
    Native converter execution remains a separate unverified installation check.
16. D4 Task 3 repairs obsolete assertions forbidding the restored runtime UI.
    Profile close, unlike ordinary Preferences close, cancels runtime work;
    generation/worker coordination must prevent late cleanup stopping a new server.
17. D4 final review persists automatic free-port relocation after dialog close
    using a profile-fenced, endpoint-only compare-and-set. New explicit endpoint
    edits win; manual unsaved endpoint/model values still require Save. Also
    remove the unreachable welcome-ready branch in that scoped fix wave.
18. D5 publication/removal must serialize read/compare/unlink with new publication
    within the endpoint process. Separate-process coordination is not established.
19. D5 final review fixes missing `os.fchmod` on older Windows Python and forces
    UTF-8 stdio framing rather than locale decoding. POSIX 0600 is tested; native
    Windows ACL privacy is not established by the API fallback.
20. The minor D5 current_page collection-access assertion was triaged optional:
    the bare-object fixture/read-only action already supplies indirect coverage.
    Live Anki and Desktop remain explicit verification limits.
21. Use board CLI ownership and exact scoped commits for rebuild work. Preserve
    the unrelated board/logo changes, disclose their presence in verification and
    package outputs, and keep final review under the controller's responsibility.

## Remaining installation limits

- No restarted live Anki UI, native collection, microphone capture or real user
  data was exercised. Automated Qt/stub checks and compilation cannot prove that.
- No real Claude Desktop session or changed external-client settings. Stdio/HTTP,
  clipboard and config paths are covered locally with scratch fixtures.
- No native Windows ACL audit; the chmod fallback is portability coverage only.
- No native Linux zstd/converter/install run or fresh Ollama/model installation
  in final integration. Runtime extraction guards use synthetic/fake fixtures.
- Discovery ownership locking coordinates one process, not competing Anki processes.
- No runtime/model download or paid API request during the final verification.
  The earlier approved whisper spike downloaded/built its scratch dependencies.

Next: install the local package in Anki and restart, follow [setup](../../../README.md),
configure/download the local embedding resources explicitly and point transcription
at installed whisper.cpp/model files. For Desktop, copy the configuration, merge it
manually and keep the Anki profile open. Validate with disposable PDFs/notes before
relying on the live workflow. The handoff/workspaces remain until a future merge.

## Recovery evidence locations

Ignored workspaces retained under `.superpowers/sdd/`:
`2026-09-18-local-model-reversion-demolition`, `2026-09-19-local-transcription`,
`2026-09-19-ollama-restoration`, `2026-09-19-external-mcp-bridge`, and
`2026-09-19-local-model-integration`. Each has progress/task reports; integration
holds `final-full/summary.json`, individual test logs, `final-audit.log`,
`final-compile.json`, `final-package-build.log`, `final-package.json` and
`task-2-report.md`. The tracked report preserves the results even when those
local logs are unavailable to another checkout.
