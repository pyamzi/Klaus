# Assistant on the Messages API Implementation Plan (API-first Klaus, Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The assistant dock keeps its shell but its engine becomes a Klaus-owned tool loop over the Anthropic Messages API: page context from the page record plus the page image, tools from `anki_tools`, writes behind the existing approval dialog, per-PDF conversations stored as message lists. The Claude Code CLI host, the localhost endpoint and the MCP server are deleted.

**Architecture:** `agent_host.py` is rewritten as `AgentHost.send(...)`: builds the request, streams through `anthropic_client.Client.stream`, executes `tool_use` blocks through `anki_tools._HANDLERS` on the main thread, appends `tool_result` blocks, loops up to 12 rounds, honours a cancel event. `assistant_sessions.py` stores conversations; `assistant_dock.py` drops the process lifecycle and runs a turn on a worker thread whose callbacks emit through the existing `_Bridge`. `anki_tools.py` absorbs the approval dialog and the agent tagging rule from `anki_endpoint.py`.

**Tech Stack:** stdlib, PyQt6 offscreen, the `tests/` harness; `anthropic_client` from Plan 1.

**Spec:** `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md` — decision D7.

## Global Constraints

- Plan 1 and Plan 2 constraints apply verbatim; both plans are committed before this one starts.
- Never `exec()`: the approval dialog stays window-modal `open()` with a `threading.Event` the worker waits on (the `anki_endpoint.qt_approver` shape, moved); Cancel stays the default button.
- Agent-written notes are tagged `klaus::assistant`, `klaus::from::<pdf_safe>`, `klaus::page::<n>` and never a `!Library` tag; `create_note` on the agent path requires a source page.
- `MAX_TOOL_ROUNDS = 12`; Stop is a `threading.Event` checked per SSE line and between rounds; a stopped turn returns its partial text and runs no further tool.
- History sent to the API: the last `HISTORY_MESSAGES = 40` messages after the summary; a conversation file over 80 messages folds its older half into `summary` with one `Client.complete` call.
- Tool results and page text are untrusted content: the tool that reads lecture text returns page records through `page_store`, never a caller-chosen path.
- Every callback into Qt goes through `_Bridge`; nothing touches a widget off the main thread.

---

## File structure

- Modify: `klausmate/agent_host.py` (rewritten), `klausmate/assistant_sessions.py` (conversations), `klausmate/assistant_dock.py` (turn on a worker; no process lifecycle), `klausmate/anki_tools.py` (`confirm_write`, agent tagging, `search_lecture_pdfs` through `page_store`), `klausmate/__init__.py` (no endpoint start/stop; `profile_will_close` order), `klausmate/manage_models.py` (the Assistant page: keep `assistant_reopen` and Clear Sessions; Clear Sessions wipes conversations), `CLAUDE.md`, `AGENTS.md`, `klausmate/config.md`.
- Delete: `klausmate/anki_endpoint.py`, `tests/test_anki_endpoint.py`, `tests/fixtures/claude_stream/`, `scripts/agent_spike.py`, the CLI-related pins in `tests/test_agent_host.py` (rewritten), `tests/test_klausmate.py`'s endpoint sections.
- Tests: `tests/test_agent_host.py` (rewritten against a fake client), `tests/test_assistant_sessions.py`, `tests/test_assistant_dock.py`, `tests/test_anki_tools.py`, `tests/test_klausmate.py`.

Lanes: Task 1 (`anki_tools`: `confirm_write` + tagging + lecture search) ∥ Task 2 (`assistant_sessions` conversations) ∥ Task 3 (`agent_host` loop). Task 4 (`assistant_dock` + `__init__` + `manage_models` wiring, endpoint deletion) after 1–3. Task 5 (docs + integration) last.

---

### Task 1: `anki_tools` owns approval, tagging and lecture-page reads

**Files:**
- Modify: `klausmate/anki_tools.py`, `tests/test_anki_tools.py`

**Interfaces:**
- Consumes: `anki_endpoint.qt_approver` and its `_run_on_main_sync` (moved verbatim, then the module is deleted in Task 4); `page_store.page_texts`; `pdf_index.best_page`.
- Produces: `anki_tools.confirm_write(title: str, sections: list[tuple[str, str]], timeout_s: float = 120.0) -> bool` (window-modal, main-thread dialog; the worker blocks on an Event); `AGENT_TAGS = ("klaus::assistant",)`; `ctx["agent"] = True` and `ctx["pdf_safe"]`, `ctx["page"]` make `_h_create_note` add the three tags and require `args["source_page"]`; `_h_search_lecture_pdfs` returns `[{"pdf", "page", "score", "text"}]` where `text` is the page record's `combined_text` (truncated to 1,200 chars); `_confirm_write_dialog` (the `exec()` one) deleted.

- [ ] **Step 1: Write the failing pins** in `tests/test_anki_tools.py`: `confirm_write` source contains `.open()` and never `.exec(`; its default button is Cancel (source pin on `setDefaultButton(...Cancel)`); `_h_create_note(col, {"deck":…, "model":…, "fields":…, "source_page": 4}, ctx={"agent": True, "pdf_safe": "lec", "confirm": lambda *a: True, ...})` adds a note whose tags include `klaus::assistant`, `klaus::from::lec`, `klaus::page::4` and no `!Library` tag; without `source_page` on the agent path → an error dict, no note; `_h_search_lecture_pdfs` result rows carry `text` from a scratch page record and never a filesystem path key.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Move `qt_approver`'s body into `confirm_write` (a `QMessageBox` built on the main thread via `mw.taskman.run_on_main`, buttons Approve/Cancel, `setDefaultButton(Cancel)`, `theme.dialog_qss`, `finished` sets an `Event` with the answer; the caller thread waits `timeout_s` and treats a timeout as Cancel); `default_ctx()["confirm"] = confirm_write`; in `_h_create_note`, when `ctx.get("agent")`: require `source_page` (else `{"error": "source_page is required"}`), and tags `AGENT_TAGS + (f"klaus::from::{ctx['pdf_safe']}", f"klaus::page::{int(args['source_page'])}")` added after the user's own tags, with any `!Library` tag stripped from the request; `_h_search_lecture_pdfs` maps the best row to its page record text through `page_store` (the PDF path from `pdf_handler.pdf_path_for`). Delete `_confirm_write_dialog`, `run_tool`, `execute_tool`, `_run_on_main_sync`'s duplicate if `anki_endpoint`'s is the one moved.

- [ ] **Step 4: Run to verify it passes.** `tests/test_anki_tools.py` → `0 failed`; compile.

- [ ] **Step 5: Mutate once.** Drop the `!Library` strip → the tag pin fails; restore. Board comment; card stays in Doing.

---

### Task 2: Conversations in `assistant_sessions`

**Files:**
- Modify: `klausmate/assistant_sessions.py`, `tests/test_assistant_sessions.py`

**Interfaces:**
- Produces: `HISTORY_MESSAGES = 40`, `FOLD_AT = 80`; `conversation_path(user_files, pdf_safe) -> str` (`user_files/assistant/conversations/<pdf_safe or "global">.json`); `load_conversation(user_files, pdf_safe) -> dict` (`{"version": 1, "messages": [], "summary": ""}`; corrupt reads empty with a log line); `append_messages(user_files, pdf_safe, messages: list[dict]) -> dict` (atomic); `history_for_request(conv) -> list[dict]` (the last `HISTORY_MESSAGES`, always starting with a `user` message, with the summary prepended as a first user/assistant pair when present); `needs_fold(conv) -> bool`; `fold(conv, summarize: Callable[[list[dict]], str]) -> dict`; `forget(user_files, pdf_safe)` deletes the file; `clear_all(user_files)` deletes the folder. `session_for`/`remember` (Claude Code ids) deleted; slash commands and `ensure_system_prompt` unchanged.

- [ ] **Step 1: Write the failing pins**: round-trip; `history_for_request` on 45 messages returns 40 starting at a `user` turn; `needs_fold` false at 80, true at 81; `fold` with a fake summarizer keeps the newest 40, sets `summary`, and the summarizer received the older ones; corrupt file → empty + no exception; `clear_all` removes the folder; `session_for`/`remember` no longer exist.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement** as specified (atomic writes via the file's existing `_atomic_write_json`). **Step 4:** `0 failed`. **Step 5:** mutate `history_for_request` to slice without the user-turn alignment → the alignment pin fails; restore. Board comment.

---

### Task 3: The tool loop in `agent_host`

**Files:**
- Modify: `klausmate/agent_host.py` (rewritten), `tests/test_agent_host.py` (rewritten), keep `tests/fixtures/anthropic/*.sse` from Plan 1 and add `tool_loop_turn.sse` (a `tool_use` of `search_notes` then, on the second request, a text answer)

**Interfaces:**
- Consumes: `anthropic_client.Client.stream(payload, on_text, on_block_start, cancel)`; `anki_tools.TOOL_SPECS`, `anki_tools._HANDLERS`, `anki_tools.default_ctx()`; `assistant_sessions.history_for_request/append_messages/load_conversation/needs_fold/fold/ensure_system_prompt`; `page_store.load_record/combined_text/render_page_png`.
- Produces: `MAX_TOOL_ROUNDS = 12`; `build_user_content(user_text, view, page_text, selection, png: bytes | None) -> list[dict]` (image block first when `png`, then a text block with the context header and the user's text); `AgentHost(get_config, user_files, client=None, run_tool=None)` with `send(user_text, view, *, on_text, on_tool, on_done, on_error, cancel) -> None` (synchronous; the caller runs it on a worker) where `on_tool(name, args, result_preview: str)` fires per executed tool and `on_done(final_text, stop_reason)`; `run_tool(name, args, ctx) -> dict` defaults to executing `_HANDLERS[name]` on the main thread through `mw.taskman.run_on_main` + an Event (the dock passes the default; tests pass a fake).

- [ ] **Step 1: Write the failing pins** with a fake client whose `stream` returns canned results in sequence and records payloads: a plain text turn → `on_text` deltas, `on_done("Hello", "end_turn")`, the conversation file gained a user and an assistant message; a tool turn → the second request's messages end with an assistant `tool_use` block and a user `tool_result` block whose `tool_use_id` matches, `on_tool` fired once, the tool ran through the injected `run_tool` with `ctx["agent"] is True` and `ctx["pdf_safe"]`; the first request's user content has the image block first and the page text in the text block; `cancel` set before the first stream → `on_done("", "cancelled")` and no tool run; a client that always returns `tool_use` stops after `MAX_TOOL_ROUNDS` requests with `on_error` naming the cap; `LLMError` from the client → `on_error(user_message)`; the system prompt is `ensure_system_prompt`'s text; tools sent are exactly `TOOL_SPECS`.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Delete everything CLI-related (`find_claude*`, `child_env`, `command_line`, `mcp_config`, `decide_permission`, `control_response`, `classify`, `parse_line`, `resume_failed`, the process/reader/stderr code). Keep `build_context_block`'s text shape as the header of the text block. The loop:

```python
    def send(self, user_text, view, *, on_text, on_tool, on_done, on_error, cancel):
        cfg = self._get_config() or {}
        model = str(cfg.get("reasoning_model") or "claude-sonnet-5")
        pdf_safe = getattr(view, "pdf_safe", None) or None
        conv = assistant_sessions.load_conversation(self._user_files, pdf_safe)
        content = build_user_content(user_text, view, *self._page_context(view))
        messages = assistant_sessions.history_for_request(conv) + [{"role": "user", "content": content}]
        new_msgs = [{"role": "user", "content": content}]
        ctx = dict(anki_tools.default_ctx()); ctx.update({"agent": True, "pdf_safe": pdf_safe, "page": getattr(view, "page_index", 0) + 1})
        final_text = ""
        try:
            for round_no in range(MAX_TOOL_ROUNDS + 1):
                if cancel is not None and cancel.is_set():
                    on_done(final_text, "cancelled"); self._persist(pdf_safe, conv, new_msgs); return
                if round_no == MAX_TOOL_ROUNDS:
                    on_error(f"The assistant used more than {MAX_TOOL_ROUNDS} tool calls in one turn and was stopped."); self._persist(pdf_safe, conv, new_msgs); return
                result = self._client.stream({"model": model, "max_tokens": 4096, "system": assistant_sessions.ensure_system_prompt(self._user_files),
                                              "tools": anki_tools.TOOL_SPECS, "messages": messages}, on_text=on_text, cancel=cancel)
                blocks = result.get("content") or []
                final_text += anthropic_client.text_of(result)
                messages.append({"role": "assistant", "content": blocks}); new_msgs.append({"role": "assistant", "content": blocks})
                uses = [b for b in blocks if b.get("type") == "tool_use"]
                if result.get("stop_reason") != "tool_use" or not uses:
                    on_done(final_text, result.get("stop_reason") or "end_turn"); self._persist(pdf_safe, conv, new_msgs); return
                results = []
                for b in uses:
                    if cancel is not None and cancel.is_set():
                        on_done(final_text, "cancelled"); self._persist(pdf_safe, conv, new_msgs); return
                    out = self._run_tool(b["name"], b.get("input") or {}, ctx)
                    on_tool(b["name"], b.get("input") or {}, json.dumps(out)[:200])
                    results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out, ensure_ascii=False), "is_error": bool(out.get("error"))})
                messages.append({"role": "user", "content": results}); new_msgs.append({"role": "user", "content": results})
        except anthropic_client.LLMError as exc:
            on_error(exc.user_message())
```

`_persist` appends `new_msgs`, and folds when `needs_fold` (summarize via `Client.complete` with a short "summarize this conversation for continuity" prompt). `_page_context(view)` returns `(page_text, selection, png)` from `page_store`, guarded.

- [ ] **Step 4: Run to verify it passes.** `tests/test_agent_host.py` → `0 failed`; compile.

- [ ] **Step 5: Mutate once.** Remove the `MAX_TOOL_ROUNDS` check → the cap pin fails (the fake client returns tool_use forever; bound the fake at 20); restore. Board comment.

---

### Task 4: The dock runs turns on a worker; the endpoint and CLI plumbing go

**Files:**
- Modify: `klausmate/assistant_dock.py` (delete `_ensure_child`, `_begin_async_stop`, `_poll_stop`, `_resume_attempt`, `_on_exited`, `_on_init`, session-id handling; `_do_send` starts a `threading.Thread` running `AgentHost.send` with callbacks that `emit` through `_Bridge`; Stop sets the cancel event; New Session calls `assistant_sessions.forget`; the header's "Following:" line unchanged; `find_claude` UI gone), `klausmate/__init__.py` (no `anki_endpoint.start/stop_for_profile`; `profile_will_close` stops nothing but the dock), `klausmate/manage_models.py` (Clear Sessions → `assistant_sessions.clear_all`; copy says conversations)
- Delete: `klausmate/anki_endpoint.py`, `tests/test_anki_endpoint.py`, `tests/fixtures/claude_stream/`, `scripts/agent_spike.py`
- Test: `tests/test_assistant_dock.py` (rewritten around a fake `AgentHost`: Send starts a turn, deltas render, a tool line renders, Stop sets the event and the turn ends "cancelled", New Session forgets the conversation, switching PDFs switches the transcript), `tests/test_klausmate.py` (endpoint pins → absence pins), `tests/test_bridge_reentrancy.py` (only if it names the endpoint)

- [ ] **Step 1: Write the failing pins** (offscreen, the file's `_FakeHost` shape: `send(...)` invokes the callbacks synchronously from a helper thread so `_Bridge`'s queued connection is exercised with `processEvents`).
- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement** as listed; the turn thread is a daemon; `_Bridge` gains `tool_line = pyqtSignal(str, str, str)`; the transcript renders tool lines as the existing muted lines. Delete the four artifacts. `grep -rn "anki_endpoint\|find_claude\|KLAUS_TOKEN\|--mcp-config" klausmate/*.py` → no hits.
- [ ] **Step 4:** full loop `0 failed`; compile every module through the symlink.
- [ ] **Step 5:** mutate: Stop no longer sets the event → the cancelled pin fails; restore. Board comment.

---

### Task 5: Docs and integration (needs-human)

- [ ] **Step 1:** CLAUDE.md's "The assistant" section rewritten: six modules become five (`agent_host` loop, `anki_tools` approval and tagging, `assistant_sessions` conversations, `assistant_dock`, `page_store` as context), the ToolSearch/permission-mode gotchas deleted (they were CLI facts), the endpoint paragraph deleted, the "Deleted" list gains `anki_endpoint.py` and the CLI host with today's date; AGENTS.md's privacy paragraph: OpenAI (embeddings, transcription), Anthropic (pertinence, the assistant — page text, page image, selection and prompt only when the dock is used); `config.md` final pass; `scripts/mutation_audit.py`: `AUDIT_MODULES` drops nothing new but keeps `agent_host`, `anki_tools`, `assistant_sessions`.
- [ ] **Step 2:** Full loop; `python3 scripts/mutation_audit.py --modules all` passes.
- [ ] **Step 3:** Paid smoke behind `KLAUS_LIVE_API=1` + `ANTHROPIC_API_KEY`: one turn "search my notes for 'nephron'" against a stub collection through the real client → a `search_notes` tool call executes and the answer mentions the result; SKIP honestly otherwise.
- [ ] **Step 4:** The live checklist: restart Anki; add the Anthropic key; open a PDF; Ctrl+Shift+K; ask "what is on this slide?" → streamed answer citing the page; "make one card from it" → the approval dialog (Cancel default) → Approve → the card exists in Browse tagged `klaus::assistant`, `klaus::from::<pdf>`, `klaus::page::<n>`; Stop mid-answer then ask again → works; switch PDFs → the conversation switches; New Session → empty; Preferences → Assistant has no binary row; `ps` shows no `claude` process.

## Self-review

**Spec coverage.** D7 in full across Tasks 1–4; docs and privacy in Task 5. Deletions: Task 4. Confinement: Task 1 (`search_lecture_pdfs` through `page_store`).

**Placeholders.** None: the loop is written out; Task 2's and 4's steps name every function and pin.

**Type consistency.** `AgentHost.send`'s callbacks match `_Bridge`'s signals (`on_text: str`, `on_tool: (str, str, str)`, `on_done: (str, str)`, `on_error: str`); `assistant_sessions.history_for_request(conv)` takes the loaded dict; `anki_tools.default_ctx()` still returns the dict `_HANDLERS` expect, extended with `agent`, `pdf_safe`, `page`.
