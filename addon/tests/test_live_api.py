"""Live smoke tests against the real hosted OpenAI API. PAID. Opt-in only.

K-239: the spec/testing plan calls for two cheap, real smokes proving the
wire-level integration actually works end to end — not correctness of any
AI output, just "the request left the process and a sane response came
back" — against ``klausmate.openai_client`` (embeddings + audio
transcription). Each hits a real paid endpoint, so the whole file is a
no-op unless a developer deliberately opts in.

Gate: nothing below this module's docstring runs a single line of
klausmate-import or network code unless ``KLAUS_LIVE_API=1`` is set in the
environment — that is checked, and can exit the process, before
``install_package_stub()`` or any ``klausmate.*`` import happens. A normal
`for t in tests/test_*.py` sweep (or CI) always takes the early SKIP exit
and touches no network, no matter how the client modules change shape.

Credentials come from the standard SDK-style environment variables, never
from klausmate's own ``meta.json`` (this repo's tooling denies reading that
file on purpose, and a headless test has no business opening a user's live
Anki config anyway):

    KLAUS_LIVE_API=1 OPENAI_API_KEY=sk-... \\
        python3 tests/test_live_api.py

Each section below additionally SKIPs itself (not a FAIL) if the key is
missing.

Run: KLAUS_LIVE_API=1 python3 tests/test_live_api.py
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install_package_stub, report, section  # noqa: E402

if os.environ.get("KLAUS_LIVE_API") != "1":
    print("SKIP tests/test_live_api.py: set KLAUS_LIVE_API=1 to run these "
          "paid live-API smokes (needs OPENAI_API_KEY too)")
    raise SystemExit(0)

# openai_client is aqt-free at module load time. No aqt stub needed.
install_package_stub()
openai_client = importlib.import_module("klausmate.openai_client")


def _say_wav(text: str) -> bytes:
    """~3s of REAL speech via macOS's built-in `say`, so the transcription
    smoke gets actual words back instead of gambling on whether a model
    hallucinates non-empty text for silence or a bare tone. Native platform
    feature: no vendored TTS, no fixture file that could go stale/missing.
    """
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            ["say", "-o", path, "--data-format=LEI16@16000",
             "--file-format=WAVE", text],
            check=True, capture_output=True, timeout=30,
        )
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


section("smoke: OpenAI embeddings (klausmate.openai_client.embed)")
openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
if not openai_key:
    print("  SKIP no OPENAI_API_KEY in environment")
else:
    try:
        # 256 dims: cheap, deterministic to assert on, and the exact
        # truncation embeddings.py's own docstring cites as still beating
        # the old ada-002 at 1536 — a realistic call, not an edge case.
        vecs = openai_client.embed(
            openai_key, ["klaus live-api smoke test"], "text-embedding-3-small", 256,
        )
        check("one vector back for one input", len(vecs) == 1, f"got {len(vecs)}")
        check("vector has the requested 256 dimensions",
              len(vecs[0]) == 256, f"got {len(vecs[0])}")
        check("vector entries are real numbers",
              all(isinstance(x, float) for x in vecs[0]))
    except openai_client.OpenAIError as e:
        check("embeddings call succeeded", False, str(e))

section("smoke: OpenAI audio transcription (klausmate.openai_client.transcribe)")
if not openai_key:
    print("  SKIP no OPENAI_API_KEY in environment")
else:
    try:
        wav = _say_wav("Testing one two three, this is a live smoke test.")
        text = openai_client.transcribe(openai_key, wav, "gpt-4o-mini-transcribe")
        check("transcription returned non-empty text", bool(text.strip()), repr(text))
    except FileNotFoundError:
        print("  SKIP macOS `say` not available to synthesize speech audio")
    except openai_client.OpenAIError as e:
        check("transcription call succeeded", False, str(e))

raise SystemExit(report())
