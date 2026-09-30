# Local-model documentation and final integration plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repository guidance match the approved reversion, then verify and package the complete local add-on after D4-D6.

**Architecture:** First update agent-facing guidance so rebuild workers do not follow obsolete cloud-only instructions. Execute the independent transcription, Ollama and MCP plans in that order. Finally update user documentation from actual implemented behavior and run the release checks without publishing.

**Tech Stack:** Markdown, existing Python headless suite, existing package.sh.

**Spec:** `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`, Doc inversion and D1-D6.

## Global Constraints

- Main checkout and existing branch; no push, merge, live Anki, microphone or real profile-data access.
- Preserve unrelated logo edits. All claims distinguish implemented, planned, tested headlessly and real-device-unverified behavior.
- Keep historical design documents with a superseded header. No invented cloud support, price, provider guarantee or live external-client test.
- New prose contains no em dash. Check cited local paths and external links.
- Keep ignored reports/ledger until the entire authorized project is recorded; do not erase recovery evidence between subsystem plans.

## Review Focus

- An agent reads old cloud-only guidance: current approved architecture must be explicit before rebuild starts.
- A user follows setup from scratch: actual executable/model requirements and Preferences names must match shipped code.
- A package leaks local data: zip contains no meta.json, credentials, runtime install, PDFs or recordings.
- A user assumes a tested UI means live-device verification: report offscreen/subprocess evidence and remaining live Anki/Claude Desktop limits explicitly.
- Another task's logo changes are in the checkout: commits must exclude them and test reports must disclose the combined working tree.

### Task 1: Invert agent guidance before rebuild

**Files:** Modify `AGENTS.md`, `CLAUDE.md`, the active local-model spec only for the two verified identifier corrections, and the three superseded specs `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md`, `2026-09-16-klaus-plus-subscription-design.md`, `2026-09-01-klaus-assistant-claude-code-design.md`.

**Interfaces:** Current architectural authority is the approved local-model spec; behavioral/safety rules still apply. D1-D3 are implemented at this point; D4-D6 are approved rebuild work, not yet complete.

- [ ] **Step 1: Locate every conflicting architecture instruction with `rg -n 'API.first|Ollama|Klaus Plus|assistant_dock|agent_host|pertinence|Anthropic|OpenAI' AGENTS.md CLAUDE.md`.** Read each affected section, preserving unrelated editor/library/Qt/test conventions.
- [ ] **Step 2: Replace affected dated narratives in place with short history notes.** Example exact new opening:

```markdown
## Current architecture: local-model reversion

The approved architecture is [the local-model reversion](docs/superpowers/specs/2026-09-18-local-model-reversion-design.md). D1-D3 have removed Klaus Plus, the pertinence judge and the embedded assistant. The next implementation plans restore managed Ollama embeddings, local whisper.cpp transcription and an external MCP bridge. Follow those plans for the rebuild; older cloud-only instructions below are historical where explicitly marked.
```

Remove live module-map entries and command examples for deleted code; retain `anki_endpoint.py`, `viewer_context.py`, recorder/page storage and their real responsibilities. Mark restored/new module entries as planned until implementation. Replace assistant teardown order instructions with actual retained endpoint profile hooks. Preserve permissions, main-thread rules, no real user-data testing, write approvals and unrelated UI gotchas. Do not describe API-key fields as the future design even while the intermediate code still has them.
- [ ] **Step 3: Add exactly one superseded header to each historical spec.** Use:

```markdown
> Superseded by [Local-model reversion](2026-09-18-local-model-reversion-design.md). Retained as historical design, not current implementation guidance.
```

Preserve the remainder of those specs byte-for-byte. Correct only factual identifiers in the active spec if needed, with a dated note: actual class is Endpoint and current_view already consumes viewer_context. Do not re-litigate approved scope.
- [ ] **Step 4: Check local links, review changed paragraphs against actual modules and `git diff --check`, then commit owned docs only.** No code tests needed for this doc-only change. Report affected sections and any guidance intentionally left historical.

### Task 2: Final user docs, package and verification

**Prerequisite:** All tasks and reviews in `2026-09-19-local-transcription.md`, `2026-09-19-ollama-restoration.md`, `2026-09-19-external-mcp-bridge.md` complete.

**Files:** Modify `README.md`, `klausmate/README.md`, `klausmate/config.md`, `PRODUCT.md`, `ANKIWEB.md`, `AGENTS.md`, `CLAUDE.md`, `klausmate/user_files_README.txt`, `scripts/package.sh` only its obsolete Plus exclusion explanation, `docs/superpowers/plans/2026-09-19-HANDOFF-local-model-reversion.md`; package manifest timestamp only if build changes it. Create a tracked completion/verification report under `docs/superpowers/reports/2026-09-19-local-model-reversion.md`.

**Interfaces:** Documentation derives from the actual config defaults, Preferences text, local adapters and bridge. The package is local, not published.

- [ ] **Step 1: Read actual implemented controls/config and list remaining cloud/subscription/assistant claims in user-facing docs.** Replace current-feature claims with Ollama setup and management, local whisper.cpp executable/model setup, cosine-only matching, and external MCP configuration. State model/runtime downloads use the network; inference is local; the external client's chosen provider may receive requested context. Do not claim all external-client processing is local.
- [ ] **Step 2: Update agent-facing module maps from planned to actual and remove transition wording.** Keep short dated history notes. Update configuration reference keys/defaults to exactly match config.json plus documented automatic state. Preserve unrelated features. Update storage README for recordings/page records/runtime/discovery and token lifecycle. Remove obsolete service deployment/license language without inventing new licensing terms.
- [ ] **Step 3: Validate docs and links against the current tree.** Each named module/config key/control must exist or be clearly historical. Search tracked current product/code docs for paid-provider key prompts, Plus sign-in, judge/Doubtful UI and embedded dock entry points; distinguish migration keys and history from live features. Check external install/documentation URLs by opening them, use official sources. No broad unrelated doc rewrite.
- [ ] **Step 4: Run the aggregate full suite, mutation selftest, direct and symlink compile checks.** Include new standalone script recursively in compile check. Record actual counts, skips and existing diagnostics. Do not repeat the full suite after doc-only adjustments. Use scratch tests only.
- [ ] **Step 5: Build with `bash scripts/package.sh` and inspect the zip manifest.** The script stages only klausmate with meta.json/user_files excluded; verify independently with `zipfile`:

```python
with zipfile.ZipFile("dist/klausmate.ankiaddon") as z:
    names = z.namelist()
    assert "scripts/mcp_stdio_bridge.py" in names
    assert "local_transcription.py" in names
    assert "ollama_runtime.py" in names
    assert not any(n.rsplit("/", 1)[-1].startswith("meta.json") for n in names)
    assert all(n in ("user_files/", "user_files/README.txt") for n in names if n.startswith("user_files/"))
    assert not any(n in names for n in ("plus.py", "pertinence.py", "agent_host.py", "assistant_dock.py", "assistant_sessions.py", "openai_client.py", "anthropic_client.py"))
```

Record package SHA256 and bytes. Treat tracked manifest timestamp change as intentional build metadata, include it in the scoped commit. Disclose that the package uses the combined current checkout including the separately requested logo changes, while those changes remain uncommitted here.
- [ ] **Step 6: Write the completion report with commits, exact test evidence, spike results, package path/hash and remaining real-device limits.** Update the handoff from in-progress demolition to completed local work and installation verification next steps. Do not delete the handoff because its own rule requires the entire project merged first and no merge is authorized.
- [ ] **Step 7: Commit exact owned documentation/build metadata and complete final whole-change review.** Do not stage the unrelated logo files/hunks or publish. Final response links the local package/report and states restart/configuration steps and unverified live-app limits.

## Self-review

Doc inversion precedes rebuilding and final docs describe actual code afterward. Package and report cover all D1-D6 deliverables. Explicit evidence checks cover the five review conditions. No deployment, external messaging or real user-data test is included.
