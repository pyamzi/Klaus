"""Run a user-installed whisper.cpp CLI without importing Anki or native code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


_KNOWN_PATHS = tuple(
    str(Path(directory).expanduser() / name)
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "/usr/bin")
    for name in ("whisper-cli", "whisper-cpp")
)


class TranscriptionError(Exception):
    """A local failure with safe, actionable display text."""

    def user_message(self) -> str:
        return str(self)


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_binary(configured: str = "") -> str | None:
    """Honor an explicit path, then search PATH, a login shell and known paths."""
    if configured:
        path = os.path.abspath(os.path.expanduser(configured))
        return path if _executable(path) else None
    for name in ("whisper-cli", "whisper-cpp"):
        path = shutil.which(name)
        if path and _executable(path):
            return path
    configured_shell = os.environ.get("SHELL", "")
    shell = configured_shell if (
        os.path.isabs(configured_shell)
        and Path(configured_shell).name in ("bash", "fish", "zsh", "sh", "ksh")
        and _executable(configured_shell)
    ) else ("/bin/zsh" if _executable("/bin/zsh") else "/bin/sh")
    try:
        result = subprocess.run(
            [shell, "-lc", "command -v whisper-cli || command -v whisper-cpp"],
            capture_output=True, text=True, timeout=3.0,
        )
        path = result.stdout.strip()
        if result.returncode == 0 and _executable(path):
            return path
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass
    for path in _KNOWN_PATHS:
        if _executable(path):
            return path
    return None


def transcribe(wav: bytes, model_path: str, *, binary: str = "",
               language: str = "en", prompt: str = "", timeout: float = 600.0) -> str:
    """Transcribe private temporary audio and return joined JSON segment text."""
    model = os.path.abspath(os.path.expanduser(model_path))
    if not model_path or not os.path.isfile(model) or not os.access(model, os.R_OK):
        raise TranscriptionError("Select a readable local whisper.cpp model file in Preferences.")
    executable = find_binary(binary)
    if not executable:
        raise TranscriptionError(
            "Install whisper.cpp and select its executable in Preferences."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="klaus-transcription-") as directory:
            audio = Path(directory) / "chunk.wav"
            prefix = Path(directory) / "transcript"
            audio.write_bytes(wav)
            args = [executable, "-m", model, "-f", str(audio), "-l", language,
                    "-oj", "-of", str(prefix)]
            if prompt:
                args.extend(["--prompt", prompt])
            result = subprocess.run(args, capture_output=True, timeout=timeout)
            if result.returncode != 0:
                raise TranscriptionError(
                    "whisper.cpp could not transcribe this audio. Check the model and executable in Preferences."
                )
            try:
                data = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
                segments = data.get("transcription") if isinstance(data, dict) else None
                if not isinstance(segments, list) or any(
                    not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
                    for segment in segments
                ):
                    raise ValueError("invalid transcription shape")
            except (OSError, ValueError, UnicodeError):
                raise TranscriptionError(
                    "whisper.cpp did not produce valid transcription JSON. Check or update the executable in Preferences."
                ) from None
            return " ".join(segment["text"].strip() for segment in segments if segment["text"].strip())
    except subprocess.TimeoutExpired:
        raise TranscriptionError(
            "Local transcription timed out. Try a smaller whisper.cpp model in Preferences."
        ) from None
    except (OSError, subprocess.SubprocessError, ValueError):
        raise TranscriptionError(
            "Could not run local whisper.cpp transcription. Check file permissions and the executable in Preferences."
        ) from None
