"""Ollama installation helpers for KlausMate.

Detects platform, lists optional package-manager install commands, and runs
them via subprocess when the user confirms.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

from .ollama_client import OllamaClient

PlatformKind = Literal["macos", "windows", "linux", "other"]

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


@dataclass(frozen=True)
class InstallMethod:
    """A package-manager install option (not the browser download)."""

    id: str
    label: str
    description: str
    command_display: str
    argv: list[str]


def platform_kind() -> PlatformKind:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def ollama_reachable(endpoint: str, timeout: float = 5.0) -> bool:
    """Short local health probe for a background worker."""
    try:
        return OllamaClient(endpoint.rstrip("/"), timeout=timeout).health()
    except Exception:
        return False


def install_methods() -> list[InstallMethod]:
    """Return package-manager install options for the current OS (may be empty)."""
    kind = platform_kind()
    methods: list[InstallMethod] = []

    if kind == "macos" and command_available("brew"):
        methods.append(
            InstallMethod(
                id="brew",
                label="Install with Homebrew",
                description="Runs: brew install ollama",
                command_display="brew install ollama",
                argv=["brew", "install", "ollama"],
            )
        )

    if kind == "windows" and command_available("winget"):
        methods.append(
            InstallMethod(
                id="winget",
                label="Install with winget",
                description="Runs: winget install -e --id Ollama.Ollama",
                command_display="winget install -e --id Ollama.Ollama",
                argv=[
                    "winget",
                    "install",
                    "-e",
                    "--id",
                    "Ollama.Ollama",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
            )
        )

    return methods


def run_install_method(method: InstallMethod, timeout: float = 600.0) -> tuple[int, str]:
    """Run an install command; return (exit_code, combined output snippet)."""
    try:
        result = subprocess.run(
            method.argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, f"Install timed out after {int(timeout)} seconds."
    except FileNotFoundError:
        return -1, f"Command not found: {method.argv[0]}"
    except OSError as e:
        return -1, f"{type(e).__name__}: {e}"

    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout.strip())
    if result.stderr:
        parts.append(result.stderr.strip())
    combined = "\n".join(parts).strip()
    if len(combined) > 2000:
        combined = "…\n" + combined[-2000:]
    if not combined:
        combined = "(no output)"
    return result.returncode, combined
