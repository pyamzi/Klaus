"""Tests for assistant_sessions — the per-PDF/global session-id store,
the slash-command prompt library, and the versioned system prompt file
(spec docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md
§10).

Everything here is stdlib-only and aqt-free, so the only bootstrap need is
the synthetic ``klausmate`` package stub — no aqt/anki stubs required.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
import importlib

asess = importlib.import_module("klausmate.assistant_sessions")

tmp = tempfile.mkdtemp(prefix="klaus_as_")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------------ paths

section("path helpers")
check("sessions_path lives under <user_files>/assistant/sessions.json",
      asess.sessions_path(tmp) == os.path.join(tmp, "assistant", "sessions.json"))
check("prompts_dir lives under <user_files>/assistant/prompts",
      asess.prompts_dir(tmp) == os.path.join(tmp, "assistant", "prompts"))
check("system_prompt_path lives under <user_files>/assistant/system_prompt.md",
      asess.system_prompt_path(tmp) == os.path.join(tmp, "assistant", "system_prompt.md"))

# --------------------------------------------------------- list_commands (empty)

section("list_commands before anything exists")
check("no prompts folder yet -> empty list, not an error",
      asess.list_commands(tmp) == [])

# ------------------------------------------------------------ ensure_defaults

section("ensure_defaults — seeds exactly three, once, never overwrites")
check("prompts folder does not exist yet", not os.path.isdir(asess.prompts_dir(tmp)))

asess.ensure_defaults(tmp)
pdir = asess.prompts_dir(tmp)
on_disk = sorted(os.listdir(pdir))
check("exactly the three default prompt files are written",
      on_disk == ["cards.md", "explain.md", "quiz.md"], f"got {on_disk}")
for name in ("explain", "cards", "quiz"):
    with open(os.path.join(pdir, f"{name}.md"), encoding="utf-8") as f:
        body = f.read()
    check(f"{name}.md content matches DEFAULT_PROMPTS[{name!r}] verbatim",
          body == asess.DEFAULT_PROMPTS[name], repr(body))

check("DEFAULT_PROMPTS carries exactly explain/cards/quiz",
      set(asess.DEFAULT_PROMPTS) == {"explain", "cards", "quiz"})
check("explain.md text matches spec §10 verbatim",
      asess.DEFAULT_PROMPTS["explain"] == "Explain this page to me as if for "
      "an exam, then list the three facts most likely to be tested.")
check("cards.md text matches spec §10 verbatim",
      asess.DEFAULT_PROMPTS["cards"] == "Propose Anki cards for this page: "
      "one fact per card, front/back, cite the page. Wait for my go-ahead "
      "before adding any.")
check("quiz.md text matches spec §10 verbatim",
      asess.DEFAULT_PROMPTS["quiz"] == "Quiz me on this page, one question "
      "at a time; grade my answer before the next.")

# Edit one file, then call ensure_defaults again — the mutation target:
# an implementation that always (re)writes the three defaults regardless
# of folder state would clobber this back to the canonical text.
_write(os.path.join(pdir, "explain.md"), "MY CUSTOM EXPLAIN PROMPT")
asess.ensure_defaults(tmp)
with open(os.path.join(pdir, "explain.md"), encoding="utf-8") as f:
    edited = f.read()
check("an edited default is never overwritten by a later ensure_defaults call",
      edited == "MY CUSTOM EXPLAIN PROMPT", repr(edited))
check("ensure_defaults re-running also leaves the untouched siblings alone",
      sorted(os.listdir(pdir)) == ["cards.md", "explain.md", "quiz.md"])

# The gate is FOLDER emptiness, not "do explain/cards/quiz exist" — a
# folder holding only an unrelated file must not get the defaults either.
tmp2 = tempfile.mkdtemp(prefix="klaus_as_gate_")
os.makedirs(asess.prompts_dir(tmp2))
_write(os.path.join(asess.prompts_dir(tmp2), "notes.txt"), "not a prompt")
asess.ensure_defaults(tmp2)
check("a non-empty folder holding only an unrelated file stays untouched "
      "(folder-level emptiness, not per-file existence)",
      sorted(os.listdir(asess.prompts_dir(tmp2))) == ["notes.txt"])
shutil.rmtree(tmp2, ignore_errors=True)

# ------------------------------------------------------------- list_commands

section("list_commands — sorted, .md only")
_write(os.path.join(pdir, "zzz-last.md"), "z prompt")
_write(os.path.join(pdir, "aaa-first.md"), "a prompt")
_write(os.path.join(pdir, ".hidden.md"), "should not count")
_write(os.path.join(pdir, "readme.txt"), "not a command")
cmds = asess.list_commands(tmp)
check("list_commands returns every .md stem, sorted, dotfiles/non-.md excluded",
      cmds == ["aaa-first", "cards", "explain", "quiz", "zzz-last"], f"got {cmds}")

# ------------------------------------------------------------------- expand

section("expand — slash commands")
cards_body = asess.DEFAULT_PROMPTS["cards"]
check("/cards with trailing text: file body + blank line + the rest",
      asess.expand("/cards make 3", tmp, {}) == cards_body + "\n\n" + "make 3")
check("/cards alone: just the file body, no trailing blank line appended",
      asess.expand("/cards", tmp, {}) == cards_body)
check("/cards with only whitespace after it behaves like no rest at all",
      asess.expand("/cards   ", tmp, {}) == cards_body)

multiline = asess.expand("/cards line one\nline two", tmp, {})
check("re.S lets a multi-line rest survive whole, embedded newline included",
      multiline == cards_body + "\n\n" + "line one\nline two", repr(multiline))

check("an unknown command passes the whole line through unchanged",
      asess.expand("/nope-such-command do a thing", tmp, {})
      == "/nope-such-command do a thing")
# The negative case above (an unknown HYPHENATED name passes through)
# would pass just as happily if _COMMAND_RE rejected hyphens outright —
# so it proves nothing about them. This is the positive half: a
# hyphenated file the test already wrote IS expanded (final review,
# parked T7 finding).
check("a HYPHENATED command name expands from its file, rest appended",
      asess.expand("/aaa-first go on", tmp, {}) == "a prompt\n\ngo on")

section("expand — $SELECTION/$PAGE/$PDF placeholders")
_write(os.path.join(pdir, "tmpl.md"), "Sel=$SELECTION Page=$PAGE Pdf=$PDF")
filled = asess.expand("/tmpl", tmp, {
    "selection": "SEL_VAL", "page_text": "PAGE_VAL", "pdf": "PDF_VAL",
})
check("all three placeholders are filled from ctx (page_text -> $PAGE)",
      filled == "Sel=SEL_VAL Page=PAGE_VAL Pdf=PDF_VAL", repr(filled))

empty_ctx = asess.expand("/tmpl", tmp, {})
check("missing ctx keys fill in as empty string, never crash or leave the token",
      empty_ctx == "Sel= Page= Pdf=", repr(empty_ctx))

none_ctx = asess.expand("/tmpl", tmp, {"selection": None, "page_text": None, "pdf": None})
check("an explicit None value in ctx also fills in as empty string",
      none_ctx == "Sel= Page= Pdf=", repr(none_ctx))

plain = asess.expand("What is $SELECTION?", tmp, {"selection": "mitosis"})
check("placeholders resolve in plain typed text too, not just command bodies",
      plain == "What is mitosis?", repr(plain))

sel_only = asess.expand("Look at $SELECTION", tmp, {"selection": "loop of Henle"})
check("$SELECTION specifically is substituted (mutation target)",
      sel_only == "Look at loop of Henle", repr(sel_only))

# ------------------------------------------------------------ sessions store

section("sessions store — round trip by PDF and global")
check("no session recorded yet for an unknown pdf_safe -> None",
      asess.session_for(tmp, "lec1") is None)
check("no global session recorded yet -> None",
      asess.session_for(tmp, None) is None)

asess.remember(tmp, "lec1", "sess-lec1-a")
asess.remember(tmp, "lec2", "sess-lec2-a")
asess.remember(tmp, None, "sess-global-a")
check("a PDF-scoped session round-trips under its own pdf_safe",
      asess.session_for(tmp, "lec1") == "sess-lec1-a")
check("a second PDF gets its own independent session",
      asess.session_for(tmp, "lec2") == "sess-lec2-a")
check("the global session round-trips under pdf_safe=None",
      asess.session_for(tmp, None) == "sess-global-a")
check("a PDF-scoped lookup never falls back to the global session",
      asess.session_for(tmp, "lec3") is None)

store = asess.load(tmp)
check("load() exposes exactly the by_pdf/global shape",
      set(store) == {"by_pdf", "global"}
      and set(store["by_pdf"]) == {"lec1", "lec2"}
      and store["global"]["session_id"] == "sess-global-a")

section("sessions store — remember uses the injected clock")
asess.remember(tmp, "lec_clock", "s1", now=lambda: 1_000_000.0)
first_stamp = asess.load(tmp)["by_pdf"]["lec_clock"]["last_used"]
asess.remember(tmp, "lec_clock", "s2", now=lambda: 2_000_000.0)
second_stamp = asess.load(tmp)["by_pdf"]["lec_clock"]["last_used"]
check("last_used is a non-empty, timestamp-shaped string",
      isinstance(first_stamp, str) and first_stamp and "T" in first_stamp,
      repr(first_stamp))
check("two different injected clock values produce two different last_used "
      "stamps — the clock argument is actually used, not ignored",
      first_stamp != second_stamp, f"{first_stamp!r} == {second_stamp!r}")

asess.remember(tmp, None, "sess-global-default-clock")
default_stamp = asess.load(tmp)["global"]["last_used"]
check("remember() also stamps a real timestamp with the default clock "
      "(no now= passed)",
      isinstance(default_stamp, str) and default_stamp)

section("sessions store — corrupt JSON reads as empty")
_write(asess.sessions_path(tmp), "{not valid json at all")
corrupt_load = asess.load(tmp)
check("a corrupt sessions.json loads back as the empty shape",
      corrupt_load == {"by_pdf": {}, "global": {}}, corrupt_load)
check("session_for against a corrupted store returns None, never raises",
      asess.session_for(tmp, "lec1") is None)

_write(asess.sessions_path(tmp), json.dumps(["not", "an", "object"]))
check("a validly-parsed but non-object sessions.json also reads as empty",
      asess.load(tmp) == {"by_pdf": {}, "global": {}})

section("sessions store — forget / clear_all")
asess.remember(tmp, "lecA", "sA")
asess.remember(tmp, "lecB", "sB")
asess.remember(tmp, None, "sG")
asess.forget(tmp, "lecA")
check("forget(pdf_safe) removes only that PDF's mapping",
      asess.session_for(tmp, "lecA") is None
      and asess.session_for(tmp, "lecB") == "sB"
      and asess.session_for(tmp, None) == "sG")
asess.forget(tmp, None)
check("forget(None) removes only the global mapping",
      asess.session_for(tmp, None) is None
      and asess.session_for(tmp, "lecB") == "sB")
asess.forget(tmp, "never-existed")
check("forgetting an unknown pdf_safe is a quiet no-op",
      asess.session_for(tmp, "lecB") == "sB")

asess.clear_all(tmp)
check("clear_all wipes every remembered session back to the empty shape",
      asess.load(tmp) == {"by_pdf": {}, "global": {}})
check("clear_all is safe against an already-empty store (idempotent)",
      (asess.clear_all(tmp), asess.load(tmp))[1] == {"by_pdf": {}, "global": {}})

# ------------------------------------------------------------- system prompt

section("ensure_system_prompt — first write")
# v2 since 2026-09-02 (final review I3): v1's prompt called search_notes
# "semantic" when the handler behind it is Anki's own lexical
# col.find_notes, so the model sent natural-language questions to a
# substring-AND search and read the empty result as "no notes on this".
# v3 since 2026-09-18 (K-207): a real semantic note search
# (search_notes_semantic) exists now, so the prompt names it as THE
# semantic note tool rather than only pointing at search_lecture_pdfs.
# The BUMP is the delivery mechanism — without it a profile that already
# has an older file on disk never sees the correction.
check("SYSTEM_PROMPT_VERSION is the current version",
      asess.SYSTEM_PROMPT_VERSION == 3)
check("no system prompt file exists yet",
      not os.path.isfile(asess.system_prompt_path(tmp)))

sp_path = asess.ensure_system_prompt(tmp)
check("ensure_system_prompt returns system_prompt_path(user_files)",
      sp_path == asess.system_prompt_path(tmp))
check("the file now exists on disk", os.path.isfile(sp_path))

with open(sp_path, encoding="utf-8") as f:
    sp_text = f.read()
check("starts with the current version marker on its own first line",
      sp_text.startswith(f"<!-- klaus-system-prompt v{asess.SYSTEM_PROMPT_VERSION} -->\n"),
      repr(sp_text[:60]))
check("names the [Klaus context] block", "[Klaus context]" in sp_text)
check("tells the model to cite pages as (p. N)", "(p. N)" in sp_text)
check("tells the model about source_page when adding a card",
      "source_page" in sp_text)
check("mentions the mcp__klaus__ tool namespace",
      "mcp__klaus__" in sp_text)
check("warns that a declined/errored tool result means no card was added",
      "NOT added" in sp_text)
# --- I3: the note tools are Anki's own LEXICAL search; only the lecture
# search is semantic. The old prompt said "search_notes (semantic)",
# which is what sent natural-language questions to col.find_notes.
check("the prompt never advertises search_notes as semantic",
      "search_notes (semantic)" not in sp_text)
check("it names Anki's own search syntax for the note tools instead",
      "Anki's own search syntax" in sp_text)
check("it points the model at search_lecture_pdfs as THE semantic tool",
      "search_lecture_pdfs (the SEMANTIC one" in sp_text)

section("ensure_system_prompt — leaves an already-current file alone")
_write(sp_path, sp_text + "CUSTOM_SENTINEL_TAIL")
again_path = asess.ensure_system_prompt(tmp)
with open(again_path, encoding="utf-8") as f:
    still_text = f.read()
check("a file already at the current version is not rewritten",
      still_text == sp_text + "CUSTOM_SENTINEL_TAIL", repr(still_text[-40:]))

section("ensure_system_prompt — rewrites a stale or markerless file")
_write(sp_path, "<!-- klaus-system-prompt v0 -->\nold stale prompt body")
asess.ensure_system_prompt(tmp)
with open(sp_path, encoding="utf-8") as f:
    rewritten = f.read()
check("a v0 marker triggers a rewrite up to the current version",
      rewritten.startswith(f"<!-- klaus-system-prompt v{asess.SYSTEM_PROMPT_VERSION} -->\n")
      and "old stale prompt body" not in rewritten, repr(rewritten[:80]))

_write(sp_path, "no marker at all, just some text a hand edit left behind")
asess.ensure_system_prompt(tmp)
with open(sp_path, encoding="utf-8") as f:
    rewritten2 = f.read()
check("a missing marker also triggers a rewrite",
      rewritten2.startswith(f"<!-- klaus-system-prompt v{asess.SYSTEM_PROMPT_VERSION} -->\n"),
      repr(rewritten2[:60]))

shutil.rmtree(tmp, ignore_errors=True)
raise SystemExit(report())
