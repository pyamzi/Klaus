"""Managed Ollama runtime for Klausmate.

Lets a user install the add-on and immediately pick a model — no separate
Ollama install. On first run we download the standalone Ollama binary from
the official GitHub release, verify it against the release's sha256sum.txt,
extract it into ``user_files/runtime/<version>/``, and run ``ollama serve``
as a child process whose lifetime we manage.

An Ollama the user installed themselves always wins: if the configured
endpoint is reachable (or a system binary exists), we reuse it and never
touch it on quit. Models are stored in the standard shared ``~/.ollama``
either way (we never set OLLAMA_MODELS), so nothing is duplicated if the
user later installs Ollama proper.

This module must stay import-safe outside Anki: no aqt imports. All UI
work (dialogs, progress bars, main-thread marshalling) lives in
``__init__.py``; progress is reported through callbacks using the same
event dicts Ollama's /api/pull streams, so the existing pull UI renders
runtime downloads unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .ollama_setup import ollama_reachable, platform_kind

# Pinned per add-on release; bump deliberately after testing, never "latest".
OLLAMA_VERSION = "0.31.1"
RELEASE_URL = "https://github.com/ollama/ollama/releases/download/v{version}/{asset}"
CHECKSUM_ASSET = "sha256sum.txt"
DEFAULT_HOST = "127.0.0.1:11434"

_ADDON_DIR = os.path.dirname(__file__)
_USER_FILES = os.path.join(_ADDON_DIR, "user_files")

_CHUNK = 1024 * 1024  # 1 MiB download chunks
_LOG_MAX_BYTES = 1024 * 1024
_DISK_HEADROOM = 500 * 1024 * 1024

ProgressFn = Callable[[dict], None]


class RuntimeProvisionError(Exception):
    """Provisioning failure with a machine-readable kind and a message
    already phrased for the user."""

    Kind = Literal[
        "unsupported_platform", "disk", "network", "checksum", "extract", "cancelled"
    ]

    def __init__(self, kind: "RuntimeProvisionError.Kind", message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class RuntimeAsset:
    """One downloadable release archive for a (platform, arch) pair."""

    name: str
    kind: Literal["tgz", "zip", "tzst"]
    archive_bytes: int  # approximate, for the disk-space check
    extracted_bytes: int


# Sizes are v0.31.1 ballparks; only used for pre-flight disk checks and
# user-facing size hints, so drift across releases is harmless.
_ASSETS: dict[tuple[str, str], RuntimeAsset] = {
    ("macos", "amd64"): RuntimeAsset("ollama-darwin.tgz", "tgz", 130_000_000, 200_000_000),
    ("macos", "arm64"): RuntimeAsset("ollama-darwin.tgz", "tgz", 130_000_000, 200_000_000),
    ("windows", "amd64"): RuntimeAsset(
        "ollama-windows-amd64.zip", "zip", 1_500_000_000, 3_800_000_000
    ),
    ("windows", "arm64"): RuntimeAsset(
        "ollama-windows-arm64.zip", "zip", 20_000_000, 60_000_000
    ),
    ("linux", "amd64"): RuntimeAsset(
        "ollama-linux-amd64.tar.zst", "tzst", 1_450_000_000, 3_600_000_000
    ),
    ("linux", "arm64"): RuntimeAsset(
        "ollama-linux-arm64.tar.zst", "tzst", 1_600_000_000, 4_000_000_000
    ),
}


def detect_arch() -> str | None:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return None


def asset_for_platform() -> RuntimeAsset | None:
    arch = detect_arch()
    if arch is None:
        return None
    return _ASSETS.get((platform_kind(), arch))


def runtime_download_size_hint() -> str:
    """Human size of the runtime download for this machine ('~123 MB')."""
    asset = asset_for_platform()
    if asset is None:
        return "unknown"
    mb = asset.archive_bytes / 1_000_000
    if mb >= 1000:
        return f"~{mb / 1000:.1f} GB"
    return f"~{mb:.0f} MB"


# ----------------------------- paths & state ------------------------------


def runtime_root() -> str:
    return os.path.join(_USER_FILES, "runtime")


def runtime_dir(version: str) -> str:
    return os.path.join(runtime_root(), version)


def _complete_marker(version_dir: str) -> str:
    return os.path.join(version_dir, ".complete")


def _binary_name() -> str:
    return "ollama.exe" if platform_kind() == "windows" else "ollama"


def _find_binary_in(root: str) -> str | None:
    """Locate the ollama binary anywhere under an extracted runtime dir.

    Archive layouts differ per platform (darwin: binary at root; windows:
    ollama.exe + lib/; linux: bin/ollama + lib/), so we search rather than
    hardcode.
    """
    wanted = _binary_name()
    for dirpath, _dirnames, filenames in os.walk(root):
        if wanted in filenames:
            return os.path.join(dirpath, wanted)
    return None


def _parse_version(name: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(\.\d+)*", name):
        return None
    return tuple(int(p) for p in name.split("."))


def find_managed_runtime() -> tuple[str, str] | None:
    """Return ``(version, binary_path)`` for the newest complete managed
    runtime, or None."""
    root = runtime_root()
    if not os.path.isdir(root):
        return None
    candidates: list[tuple[tuple[int, ...], str]] = []
    for entry in os.listdir(root):
        ver = _parse_version(entry)
        if ver is None:
            continue
        vdir = runtime_dir(entry)
        if os.path.isfile(_complete_marker(vdir)):
            candidates.append((ver, entry))
    for _ver, entry in sorted(candidates, reverse=True):
        binary = _find_binary_in(runtime_dir(entry))
        if binary:
            return entry, binary
    return None


def cleanup_old_runtimes(keep: str | None = OLLAMA_VERSION) -> int:
    """Delete managed runtime dirs other than ``keep``; returns bytes freed.

    Skips the directory whose binary is currently being served (upgrade
    flow deletes the old version only after the new server is healthy).
    """
    root = runtime_root()
    if not os.path.isdir(root):
        return 0
    active = server_manager.active_binary()
    freed = 0
    for entry in os.listdir(root):
        if _parse_version(entry) is None or entry == keep:
            continue
        vdir = runtime_dir(entry)
        if active and os.path.commonpath([active, vdir]) == vdir:
            continue
        freed += _dir_size(vdir)
        shutil.rmtree(vdir, ignore_errors=True)
    return freed


def managed_runtime_disk_usage() -> int:
    """Bytes used by managed runtime *versions* only — server.log and
    ollama.pid in runtime_root don't count (they'd keep the settings
    Remove button alive showing 'frees 0.0 GB')."""
    root = runtime_root()
    if not os.path.isdir(root):
        return 0
    return sum(
        _dir_size(runtime_dir(entry))
        for entry in os.listdir(root)
        if _parse_version(entry) is not None
    )


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


# ----------------------------- provisioning -------------------------------


def fetch_expected_sha(version: str, asset_name: str, timeout: float = 30.0) -> str:
    """Download the release's sha256sum.txt and return the hash for one asset."""
    url = RELEASE_URL.format(version=version, asset=CHECKSUM_ASSET)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeProvisionError(
            "network", f"Could not fetch the Ollama release checksums:\n{e}"
        ) from e
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*./") == asset_name:
            return parts[0].lower()
    raise RuntimeProvisionError(
        "network",
        f"Release v{version} does not list {asset_name} in its checksums — "
        "the pinned version may be wrong for this platform.",
    )


def check_disk_space(target_dir: str, asset: RuntimeAsset) -> None:
    needed = asset.archive_bytes + asset.extracted_bytes + _DISK_HEADROOM
    os.makedirs(target_dir, exist_ok=True)
    free = shutil.disk_usage(target_dir).free
    if free < needed:
        raise RuntimeProvisionError(
            "disk",
            "Not enough disk space for the local AI engine.\n\n"
            f"Needed: about {needed / 1_000_000_000:.1f} GB free — "
            f"available: {free / 1_000_000_000:.1f} GB.",
        )


def download_asset(
    url: str,
    dest_path: str,
    expected_sha: str,
    on_progress: ProgressFn | None = None,
    cancel_flag: threading.Event | None = None,
    status_label: str = "Downloading Ollama runtime",
) -> None:
    """Stream ``url`` to ``dest_path`` with sha256 verification.

    Writes to ``<dest>.part`` and renames atomically on success, so a
    half-finished download can never be mistaken for a good archive.
    Progress dicts match Ollama pull events so _format_pull_event works.
    """
    part = dest_path + ".part"
    if os.path.exists(part):
        os.remove(part)
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=60.0) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                while True:
                    if cancel_flag is not None and cancel_flag.is_set():
                        raise RuntimeProvisionError(
                            "cancelled", "Download cancelled."
                        )
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(
                            {"status": status_label, "total": total, "completed": done}
                        )
    except RuntimeProvisionError:
        _remove_quiet(part)
        raise
    except (urllib.error.URLError, OSError) as e:
        _remove_quiet(part)
        raise RuntimeProvisionError(
            "network",
            f"Download failed:\n{e}\n\nCheck your connection and try again.",
        ) from e

    if digest.hexdigest().lower() != expected_sha.lower():
        _remove_quiet(part)
        raise RuntimeProvisionError(
            "checksum",
            "The downloaded file did not match the official checksum and was "
            "discarded. Please try again.",
        )
    os.replace(part, dest_path)


def _remove_quiet(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _check_member_path(name: str, dest_dir: str) -> None:
    """Reject archive members that would escape dest_dir (absolute or ..)."""
    if name.startswith(("/", "\\")) or os.path.isabs(name):
        raise RuntimeProvisionError("extract", f"Unsafe archive member: {name}")
    target = os.path.realpath(os.path.join(dest_dir, name))
    if not target.startswith(os.path.realpath(dest_dir) + os.sep):
        raise RuntimeProvisionError("extract", f"Unsafe archive member: {name}")


def _extract_tgz(archive: str, dest_dir: str) -> None:
    with tarfile.open(archive, mode="r:gz") as tf:
        for member in tf.getmembers():
            _check_member_path(member.name, dest_dir)
        try:
            tf.extractall(dest_dir, filter="data")  # 3.12+: also silences
        except TypeError:  # older Python without the filter kwarg
            tf.extractall(dest_dir)


def _extract_zip(archive: str, dest_dir: str) -> None:
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            _check_member_path(name, dest_dir)
        zf.extractall(dest_dir)


def linux_extract_strategy() -> list[str] | None:
    """Return an argv template for extracting .tar.zst, or None.

    Probed BEFORE downloading ~1.3 GB so unsupported systems fail fast.
    GNU tar shells out to the ``zstd`` program for --zstd, so zstd/unzstd
    on PATH is the primary path; bsdtar links libarchive and usually
    decodes zstd natively. ``{archive}`` / ``{dest}`` are placeholders.
    """
    if shutil.which("unzstd") or shutil.which("zstd"):
        prog = "unzstd" if shutil.which("unzstd") else "zstd -d"
        return [
            "tar", f"--use-compress-program={prog}", "-xf", "{archive}", "-C", "{dest}"
        ]
    if shutil.which("bsdtar"):
        return ["bsdtar", "-xf", "{archive}", "-C", "{dest}"]
    return None


def _extract_tzst(archive: str, dest_dir: str) -> None:
    argv_tpl = linux_extract_strategy()
    if argv_tpl is None:
        raise RuntimeProvisionError(
            "unsupported_platform",
            "Extracting the Linux runtime needs the 'zstd' tool "
            "(e.g. sudo apt install zstd), or install Ollama manually.",
        )
    argv = [a.format(archive=archive, dest=dest_dir) for a in argv_tpl]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeProvisionError(
            "extract",
            f"Archive extraction failed ({' '.join(argv[:2])} exited "
            f"{result.returncode}):\n{(result.stderr or '')[-500:]}",
        )


def extract_asset(archive: str, asset: RuntimeAsset, dest_dir: str) -> str:
    """Extract, chmod, clean up, and return the binary path."""
    os.makedirs(dest_dir, exist_ok=True)
    try:
        if asset.kind == "tgz":
            _extract_tgz(archive, dest_dir)
        elif asset.kind == "zip":
            _extract_zip(archive, dest_dir)
        else:
            _extract_tzst(archive, dest_dir)
    except RuntimeProvisionError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeProvisionError(
            "extract", f"Could not extract the runtime archive:\n{e}"
        ) from e

    binary = _find_binary_in(dest_dir)
    if binary is None:
        raise RuntimeProvisionError(
            "extract", "Extracted archive did not contain an ollama binary."
        )
    if platform_kind() != "windows":
        os.chmod(binary, os.stat(binary).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # urllib doesn't set the quarantine xattr, but strip defensively in
        # case a future macOS version changes that.
        if platform_kind() == "macos":
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", dest_dir],
                capture_output=True,
            )
    _remove_quiet(archive)
    return binary


def provision_runtime(
    on_progress: ProgressFn | None = None,
    cancel_flag: threading.Event | None = None,
    version: str = OLLAMA_VERSION,
) -> str:
    """Download + verify + extract the pinned runtime; return binary path.

    Serialized: a concurrent second call waits, then finds the completed
    runtime and returns without downloading.
    """
    with _provision_lock:
        return _provision_runtime_locked(on_progress, cancel_flag, version)


def _provision_runtime_locked(
    on_progress: ProgressFn | None,
    cancel_flag: threading.Event | None,
    version: str,
) -> str:
    asset = asset_for_platform()
    if asset is None:
        raise RuntimeProvisionError(
            "unsupported_platform",
            "Automatic setup isn't available for this platform — please "
            "install Ollama from https://ollama.com/download instead.",
        )
    if asset.kind == "tzst" and linux_extract_strategy() is None:
        raise RuntimeProvisionError(
            "unsupported_platform",
            "Automatic setup needs the 'zstd' tool on Linux "
            "(e.g. sudo apt install zstd), or install Ollama manually — "
            "https://ollama.com/download",
        )

    vdir = runtime_dir(version)
    existing = _find_binary_in(vdir) if os.path.isfile(_complete_marker(vdir)) else None
    if existing:
        return existing
    # A version dir without its .complete marker is a leftover from an
    # interrupted extract — wipe and start fresh.
    if os.path.isdir(vdir):
        shutil.rmtree(vdir, ignore_errors=True)

    check_disk_space(runtime_root(), asset)
    if on_progress is not None:
        on_progress({"status": "Verifying release checksums"})
    expected_sha = fetch_expected_sha(version, asset.name)

    archive = os.path.join(runtime_root(), asset.name)
    url = RELEASE_URL.format(version=version, asset=asset.name)
    download_asset(url, archive, expected_sha, on_progress, cancel_flag)

    if on_progress is not None:
        on_progress({"status": "Extracting runtime"})
    binary = extract_asset(archive, asset, vdir)
    with open(_complete_marker(vdir), "w", encoding="utf-8") as f:
        f.write(expected_sha + "\n")
    print(f"[klausmate] provisioned managed Ollama {version} at {binary}")
    return binary


# --------------------------- system discovery -----------------------------


def find_system_ollama() -> str | None:
    """A user-installed ollama binary, if any (PATH first, then known spots)."""
    found = shutil.which("ollama")
    if found:
        return found
    kind = platform_kind()
    candidates: list[str] = []
    if kind == "windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(os.path.join(local, "Programs", "Ollama", "ollama.exe"))
    elif kind == "macos":
        candidates += [
            "/opt/homebrew/bin/ollama",
            "/usr/local/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama",
        ]
    elif kind == "linux":
        candidates += ["/usr/local/bin/ollama", "/usr/bin/ollama"]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# ----------------------------- server manager -----------------------------


def _pidfile_path() -> str:
    return os.path.join(runtime_root(), "ollama.pid")


def _server_log_path() -> str:
    return os.path.join(runtime_root(), "server.log")


def _pid_alive(pid: int) -> bool:
    """Non-destructive liveness probe.

    On Windows ``os.kill(pid, 0)`` is NOT a probe: for console-less
    processes CPython falls through to TerminateProcess (bpo-42962), so it
    would kill the very process it is checking. Use OpenProcess +
    GetExitCodeProcess there instead.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            # Access denied → the process exists but belongs to someone
            # else; anything else → treat as dead.
            return kernel32.GetLastError() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _process_exe(pid: int) -> str | None:
    """Best-effort full path of the executable behind ``pid``.

    Used to prove a pidfile pid still belongs to OUR ollama binary before
    adopting it — pids get recycled across reboots. Returns None when the
    platform gives no reliable answer; callers must then refuse to adopt
    rather than risk killing an unrelated process at quit.
    """
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return None
            try:
                buf = ctypes.create_unicode_buffer(4096)
                size = ctypes.c_ulong(len(buf))
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)
                ):
                    return buf.value or None
                return None
            finally:
                kernel32.CloseHandle(handle)
        proc_exe = f"/proc/{pid}/exe"  # Linux
        if os.path.islink(proc_exe):
            return os.path.realpath(proc_exe)
        # macOS/BSD: comm= is the full executable path.
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _endpoint_for_host(host: str) -> str:
    return f"http://{host}"


def _host_from_endpoint(endpoint: str) -> tuple[str, int] | None:
    """(hostname, port) if endpoint is loopback http, else None."""
    m = re.match(r"https?://(\[[^\]]+\]|[^/:]+)(?::(\d+))?/?$", endpoint.strip())
    if not m:
        return None
    hostname = m.group(1).lower()
    if hostname not in ("localhost", "127.0.0.1", "[::1]"):
        return None
    return hostname, int(m.group(2) or 11434)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class EnsureResult:
    status: Literal["reachable", "started", "needs_provision", "failed"]
    endpoint: str
    detail: str = ""
    port_moved: bool = False  # spawned on a non-default port; config rewritten

    @property
    def ok(self) -> bool:
        """True when the server is actually usable (reachable or just
        started). The single source of truth for this check — it used to
        be copy-pasted as ``status in ("reachable", "started")`` at four
        call sites (__init__.py, setup_flow.py, manage_models.py, and the
        one below); adding a fifth status value now only means updating
        this property, not hunting down every copy."""
        return self.status in ("reachable", "started")


class ServerManager:
    """Owns at most one `ollama serve` child. App-lifetime singleton.

    Kill discipline: we only ever stop a server we spawned this session or
    adopted via our own pidfile (crash leftover). A reachable endpoint with
    no pidfile is the user's own Ollama and is never touched.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._adopted_pid: int | None = None
        self._binary: str | None = None
        self._host: str | None = None
        self._log_handle: Any = None
        self._checked_pidfile = False
        self._lock = threading.Lock()

    def active_binary(self) -> str | None:
        return self._binary

    def spawned_or_adopted(self) -> bool:
        """True only while the server we own is actually ALIVE.

        A handle to a dead child must not count — otherwise a crashed or
        user-killed managed server could never be respawned in-session
        (every ensure_server would bail with 'not responding'). Dead state
        is cleared here so the ladder can spawn again.
        """
        with self._lock:
            if self._proc is not None:
                if self._proc.poll() is None:
                    return True
                print("[klausmate] managed ollama serve died; clearing for respawn")
                self._proc = None
                self._binary = None
                _remove_quiet(_pidfile_path())
                if self._log_handle is not None:
                    try:
                        self._log_handle.close()
                    except OSError:
                        pass
                    self._log_handle = None
                return False
            if self._adopted_pid is not None:
                if _pid_alive(self._adopted_pid):
                    return True
                self._adopted_pid = None
                self._binary = None
                _remove_quiet(_pidfile_path())
                return False
            return False

    # -- lifecycle ---------------------------------------------------------

    def adopt_orphan_if_any(self, endpoint: str) -> bool:
        """Once per app run: claim a server left by a crashed session.

        Adoption requires PROOF of identity: the pidfile pid must still map
        to the exact binary we recorded at spawn time. Pids are recycled
        across reboots — without this check a stale pidfile could make us
        SIGTERM an unrelated process (or the user's own Ollama) at quit.
        When identity can't be proven, we do NOT adopt: the reachable
        server is treated as user-owned (reused, never killed) and the
        pidfile is discarded.
        """
        if self._proc is not None or self._checked_pidfile:
            return self._adopted_pid is not None
        self._checked_pidfile = True
        path = _pidfile_path()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.loads(f.read())
            pid = int(data.get("pid") or 0)
            host = str(data.get("host") or DEFAULT_HOST)
            binary = str(data.get("binary") or "")
        except (OSError, ValueError):
            return False
        if _pid_alive(pid) and ollama_reachable(_endpoint_for_host(host)):
            exe = _process_exe(pid)
            if (
                binary
                and exe
                and os.path.realpath(exe) == os.path.realpath(binary)
            ):
                self._adopted_pid = pid
                self._host = host
                self._binary = binary
                print(f"[klausmate] adopted orphan ollama serve (pid {pid})")
                return True
            print(
                "[klausmate] pidfile pid no longer maps to our binary — "
                "treating the running server as user-owned"
            )
        _remove_quiet(path)
        return False

    def spawn(self, binary: str, host: str) -> None:
        os.makedirs(runtime_root(), exist_ok=True)
        log_path = _server_log_path()
        try:
            if os.path.getsize(log_path) > _LOG_MAX_BYTES:
                os.remove(log_path)
        except OSError:
            pass
        self._log_handle = open(log_path, "ab")
        env = os.environ.copy()
        env["OLLAMA_HOST"] = host
        kwargs: dict[str, Any] = {}
        if platform_kind() == "windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        else:
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(
            [binary, "serve"],
            stdout=self._log_handle,
            stderr=self._log_handle,
            stdin=subprocess.DEVNULL,
            env=env,
            **kwargs,
        )
        self._binary = binary
        self._host = host
        try:
            with open(_pidfile_path(), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "pid": self._proc.pid,
                        "host": host,
                        "binary": binary,
                        "spawned_at": time.time(),
                    },
                    f,
                )
        except OSError:
            pass
        print(f"[klausmate] spawned ollama serve pid={self._proc.pid} host={host}")

    def poll_ready(self, endpoint: str, timeout: float = 20.0) -> tuple[bool, str]:
        """Wait for the spawned server to answer /api/tags.

        Returns (ok, detail); detail carries the log tail when the process
        died so error dialogs can show the real cause.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False, self._log_tail()
            if ollama_reachable(endpoint):
                return True, ""
            time.sleep(0.3)
        return False, f"Server did not respond within {int(timeout)}s.\n" + self._log_tail()

    def _log_tail(self, limit: int = 600) -> str:
        try:
            with open(_server_log_path(), "rb") as f:
                f.seek(max(0, os.path.getsize(_server_log_path()) - 4096))
                return f.read().decode("utf-8", "replace")[-limit:]
        except OSError:
            return ""

    def stop(self) -> None:
        """Terminate the server we own (spawned or adopted). Never a reused one."""
        with self._lock:
            proc, self._proc = self._proc, None
            adopted, self._adopted_pid = self._adopted_pid, None
            if proc is not None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except OSError:
                    pass
            elif adopted is not None and _pid_alive(adopted):
                try:
                    import signal

                    os.kill(adopted, signal.SIGTERM)
                except OSError:
                    pass
            if proc is not None or adopted is not None:
                _remove_quiet(_pidfile_path())
                print("[klausmate] stopped managed ollama serve")
            if self._log_handle is not None:
                try:
                    self._log_handle.close()
                except OSError:
                    pass
                self._log_handle = None
            self._binary = None


server_manager = ServerManager()


# ----------------------------- orchestration ------------------------------

# Serialize the check-then-spawn ladder: concurrent QueryOp workers
# (profile-open readiness vs error-path autostart vs one-click setup) must
# never both pass the "nothing running" check and double-spawn — the loser
# of the port-bind race would leak an untracked `ollama serve`.
_ensure_lock = threading.Lock()

# One runtime download at a time: two provision calls share .part paths.
_provision_lock = threading.Lock()


def ensure_server(
    cfg: dict[str, Any],
    save_config: Callable[[dict[str, Any]], None] | None = None,
) -> EnsureResult:
    """Silent decision ladder — never downloads anything.

    1. endpoint reachable → reuse (adopting a crash orphan if it's ours)
    2. managed runtime present → spawn it
    3. system ollama binary → spawn it
    4. → needs_provision

    Serialized: a second caller blocks until the first finishes, then sees
    the freshly started server as "reachable".
    """
    with _ensure_lock:
        return _ensure_server_locked(cfg, save_config)


def _ensure_server_locked(
    cfg: dict[str, Any],
    save_config: Callable[[dict[str, Any]], None] | None,
) -> EnsureResult:
    endpoint = str(cfg.get("endpoint") or _endpoint_for_host(DEFAULT_HOST)).rstrip("/")

    if ollama_reachable(endpoint):
        server_manager.adopt_orphan_if_any(endpoint)
        return EnsureResult("reachable", endpoint)

    host_port = _host_from_endpoint(endpoint)
    if host_port is None:
        return EnsureResult(
            "failed",
            endpoint,
            "Configured endpoint is not local — Klaus won't manage a remote "
            "Ollama. Fix the endpoint in Klaus settings or start the remote "
            "server.",
        )

    managed = find_managed_runtime()
    binary = managed[1] if managed else find_system_ollama()
    if binary is None:
        return EnsureResult("needs_provision", endpoint)

    if server_manager.spawned_or_adopted():
        # We already own a server this session; if it isn't answering at
        # the configured endpoint something is genuinely wrong.
        return EnsureResult("failed", endpoint, "Managed server is not responding.")

    configured_port = host_port[1]
    port = configured_port
    if _port_in_use(port):
        # Port is taken but /api/tags didn't answer: not an Ollama. Move to
        # a free port and persist the endpoint so every client follows.
        port = _free_port()
    host = f"127.0.0.1:{port}"
    new_endpoint = _endpoint_for_host(host)

    server_manager.spawn(binary, host)
    ok, detail = server_manager.poll_ready(new_endpoint)
    if not ok:
        server_manager.stop()
        return EnsureResult("failed", endpoint, detail)

    port_moved = port != configured_port
    if port_moved:
        if save_config is not None:
            cfg["endpoint"] = new_endpoint
            save_config(cfg)
    else:
        # Same port the config already points at — keep the user's spelling
        # (localhost vs 127.0.0.1) rather than churning the config file.
        new_endpoint = endpoint
    upgrade = ""
    if managed and managed[0] != OLLAMA_VERSION:
        upgrade = "update_available"
    return EnsureResult("started", new_endpoint, upgrade, port_moved)


def full_setup(
    cfg: dict[str, Any],
    on_progress: ProgressFn | None = None,
    cancel_flag: threading.Event | None = None,
    save_config: Callable[[dict[str, Any]], None] | None = None,
) -> EnsureResult:
    """One-click path: ensure, and provision when nothing exists.

    Runs on a background thread (QueryOp). On Windows we prefer a silent
    winget install of the official app (auto-updates, login autostart, no
    duplicate storage) and fall back to the standalone zip.
    """
    res = ensure_server(cfg, save_config)
    if res.status != "needs_provision":
        return res

    if platform_kind() == "windows":
        binary = _try_winget(on_progress)
        if binary is not None:
            return ensure_server(cfg, save_config)

    provision_runtime(on_progress, cancel_flag)
    return ensure_server(cfg, save_config)


def update_runtime(
    cfg: dict[str, Any],
    on_progress: ProgressFn | None = None,
    cancel_flag: threading.Event | None = None,
    save_config: Callable[[dict[str, Any]], None] | None = None,
) -> EnsureResult:
    """Move a managed server onto the pinned OLLAMA_VERSION.

    Downloads the new version first (old server keeps working), then
    restarts onto it and removes older managed versions only after the
    new server is healthy. Never touches a user-owned Ollama.
    """
    provision_runtime(on_progress, cancel_flag)
    if server_manager.spawned_or_adopted():
        server_manager.stop()
    res = ensure_server(cfg, save_config)
    if res.ok:
        cleanup_old_runtimes(keep=OLLAMA_VERSION)
    return res


def _try_winget(on_progress: ProgressFn | None) -> str | None:
    from .ollama_setup import install_methods, run_install_method

    method = next((m for m in install_methods() if m.id == "winget"), None)
    if method is None:
        return None
    if on_progress is not None:
        on_progress(
            {"status": "Installing Ollama via winget (may take several minutes)"}
        )
    code, output = run_install_method(method, timeout=1200.0)
    if code != 0:
        print(f"[klausmate] winget install failed ({code}); falling back to zip:\n{output}")
        return None
    return find_system_ollama()
