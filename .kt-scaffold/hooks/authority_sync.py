#!/usr/bin/env python3
"""The one periodic client script: authority sync and device stop.

The operating system runs ``authority_sync.py calistir`` at login and every five minutes for the
signed-in user (Engineering Governance capability 003).  One run executes the tasks of ``TASKS``
in order: the device stop, record forwarding (Agent Platform capability 010) and the governance
restore.  Each task receives the same ``RunContext``, bounds itself by ``ctx.remaining()`` and
never stops the next task by failing.

Extension point: a later client capability adds one ``(name, function)`` entry to ``TASKS`` in
its own accepted PRD instead of a new scheduled script.
A task may read ``ctx.records`` (the shared governance records module), ``ctx.location``,
``ctx.address``, ``ctx.device_id`` and call ``ctx.post``; it keeps its own working state under its
own key of ``ctx.state`` and writes events through ``ctx.event``.

Integrity today is TLS certificate verification plus SHA-256 equality, checked only in
``verify_authority_response``.  The authority signature of the versioning step is added there and
nowhere else.  The script never commits, never touches the Git index or ``.git`` and writes only
the governance-surface files the scaffold ownership manifest records, with their recorded bytes.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import json
import os
import plistlib
import re
import runpy
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Tuple

# Started by launchd, Task Scheduler or a hook on the host's python3; keep 3.9 syntax.
UTC = timezone.utc  # noqa: UP017
RUN_BUDGET_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 10.0
RUN_INTERVAL_SECONDS = 300
AUTHORITY_CHECK_INTERVAL = timedelta(hours=1)
ACTIVE_RUN_WINDOW = timedelta(hours=2)
DEVICE_STATE_PATH = "/cihaz-durumu/v1/sorgu"
GOVERNED_BODIES_PATH = "/yonetisim-esitleme/v1/govdeler"
DEVICE_STATE_SCHEMA = "kt-device-state/v1"
GOVERNED_BODIES_SCHEMA = "kt-governed-bodies/v1"
TASK_LABEL = "com.kuveytturk.kt-scaffold.yonetisim-esitleme"
WINDOWS_TASK_NAME = "\\KT\\YonetisimEsitleme"
SYSTEM_LAUNCH_AGENT = Path("/Library/LaunchAgents") / f"{TASK_LABEL}.plist"
MANIFEST_PATH = ".kt-scaffold/manifest.json"
PROJECT_MANIFEST_PATH = ".kt-scaffold/project-manifest.json"
ANSWERS_PATH = ".kt-scaffold/answers.yml"
SURFACE_GUARD = "governance_surface_guard.py"
FORWARDER = "governance_forwarder.py"
FORWARDER_STATE_FILE = "log-forwarder.json"
# The managed preference keys the forwarder's settings come from (Agent Platform capability 010).
FORWARDER_PREFERENCES = {
    "collector_url": "LogCollectorURL",
    "ca_file": "LogCollectorCAFile",
    "device_key_file": "LogDeviceKeyFile",
}
MAX_BODIES_PER_REQUEST = 64
MAX_RESPONSE_BYTES = 4 * 1024 * 1024 + 64 * 1024
MAX_STATE_RESPONSE_BYTES = 4 * 1024
MAX_ANSWERS_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RESTORE_BYTES = 16 * 1024 * 1024
MAX_SETTINGS_BYTES = 16 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 30
FILE_MODES = {"100644": 0o644, "100755": 0o755}
GIT_OPERATION_MARKERS = (
    "MERGE_HEAD",
    "rebase-merge",
    "rebase-apply",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "index.lock",
)
TERMINAL_RUN_STATES = frozenset({"completed", "stopped", "failed"})
DEVICE_ID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_ID_RE = re.compile(r"^project-(?!0{32}$)[0-9a-f]{32}$")
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
TASK_UNAVAILABLE_WARNING = (
    "KT_SYNC_TASK_UNAVAILABLE: Yönetişim eşitleme görevi bu bilgisayara kurulamadı; mesaj "
    "gönderildi. Sorun sürerse proje fabrikası ekibine bildirin."
)


class SyncError(Exception):
    """A content-free reason code; never a path, a response body or a raw exception text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_arguments: Any, **_keywords: Any) -> None:
        return None


# --- seams: the operating system's defaults; tests replace these module globals -------------


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _managed_preferences() -> Optional[Path]:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


def _settings_home() -> Path:
    return Path.home()


def _now() -> datetime:
    return datetime.now(UTC)


_TLS_CONTEXTS: List[ssl.SSLContext] = []


def _tls_context() -> ssl.SSLContext:
    """Verified TLS only: the interpreter's trust store plus the macOS system keychains."""

    if _TLS_CONTEXTS:
        return _TLS_CONTEXTS[0]
    context = ssl.create_default_context()
    if sys.platform == "darwin":
        for keychain in (
            "/System/Library/Keychains/SystemRootCertificates.keychain",
            "/Library/Keychains/System.keychain",
        ):
            with contextlib.suppress(OSError, subprocess.SubprocessError, ssl.SSLError):
                exported = subprocess.run(
                    ["/usr/bin/security", "find-certificate", "-a", "-p", keychain],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if exported.returncode == 0 and b"BEGIN CERTIFICATE" in exported.stdout:
                    context.load_verify_locations(cadata=exported.stdout.decode("ascii", "ignore"))
    _TLS_CONTEXTS.append(context)
    return context


def _transport(url: str, body: bytes, timeout: float) -> Tuple[int, bytes]:
    """POST ``body`` over verified HTTPS without following redirects."""

    if urllib.parse.urlsplit(url).scheme != "https":
        raise SyncError("ADDRESS_INSECURE")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "Content-Type": "application/json",
            "User-Agent": "kt-scaffold-authority-sync",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_tls_context()), _NoRedirect()
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with contextlib.suppress(OSError):
            exc.read(4096)
        return int(exc.code), b""
    except (OSError, ValueError, ssl.SSLError):
        raise SyncError("AUTHORITY_UNREACHABLE") from None


def _hardware_device_id() -> Optional[str]:
    """The hardware UUID Jamf shows as UDID (macOS) or the SMBIOS UUID (Windows)."""

    try:
        if sys.platform == "darwin":
            completed = subprocess.run(
                ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10,
                check=False,
            )
            match = re.search(rb'"IOPlatformUUID" = "([0-9A-Fa-f-]{36})"', completed.stdout)
            value = match.group(1).decode("ascii") if match else ""
        elif os.name == "nt":
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=20,
                check=False,
            )
            value = completed.stdout.decode("ascii", "ignore").strip()
        else:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return normalized_device_id(value)


def _task_scheduler() -> Any:
    return default_scheduler()


# --- small helpers ---------------------------------------------------------------------------


def normalized_device_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper()
    return candidate if DEVICE_ID_RE.fullmatch(candidate) else None


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _records() -> Dict[str, Any]:
    path = Path(__file__).resolve().with_name("governance_records.py")
    if path.is_symlink() or not path.is_file():
        raise SyncError("RECORDS_UNAVAILABLE")
    return runpy.run_path(str(path))


def _governed_classifier() -> Callable[[str], bool]:
    """The governance surface list has one owner: the generated surface guard."""

    path = Path(__file__).resolve().with_name(SURFACE_GUARD)
    if path.is_symlink() or not path.is_file():
        raise SyncError("CLASSIFIER_UNAVAILABLE")
    classify = runpy.run_path(str(path))["classify"]

    def governed(relative: str) -> bool:
        return classify(relative) in {"authority", "governed"}

    return governed


def _read_regular(path: Path, limit: int) -> Optional[bytes]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _read_json(path: Path, limit: int) -> Optional[Dict[str, Any]]:
    raw = _read_regular(path, limit)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def safe_relative(value: object) -> str:
    """A project-relative POSIX path without escapes; Windows separators are not accepted."""

    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise SyncError("UNSAFE_PATH")
    parts = value.split("/")
    windows = PureWindowsPath(value)
    if value.startswith("/") or windows.drive or any(part in {"", ".", ".."} for part in parts):
        raise SyncError("UNSAFE_PATH")
    return value


def safe_destination(project_root: Path, relative: str) -> Path:
    """The project path of ``relative`` when no component is a link and it stays inside."""

    current = project_root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise SyncError("LINKED_PATH")
    try:
        current.resolve(strict=False).relative_to(project_root.resolve(strict=True))
    except (OSError, ValueError):
        raise SyncError("LINKED_PATH") from None
    if current.exists() and not current.is_file():
        raise SyncError("LINKED_PATH")
    return current


def _replace_file(destination: Path, content: bytes, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".kt-sync-{os.getpid()}-{time.monotonic_ns()}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        with contextlib.suppress(OSError):
            if os.path.lexists(temporary):
                os.unlink(temporary)


# --- the single verification step ------------------------------------------------------------


def verify_authority_response(
    kind: str,
    status: int,
    raw: bytes,
    *,
    device_id: Optional[str] = None,
    expected: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Accept an authority response only after TLS (in ``_transport``), shape and digests.

    ``expected`` maps each requested path to the digest the project's manifest records; a body
    whose SHA-256 differs is refused.  The versioning step adds the authority signature here.
    """

    if status == 503 or status >= 500 or status == 404:
        raise SyncError("AUTHORITY_UNAVAILABLE")
    if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        raise SyncError("AUTHORITY_RESPONSE_INVALID")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SyncError("AUTHORITY_RESPONSE_INVALID") from None
    if not isinstance(payload, dict):
        raise SyncError("AUTHORITY_RESPONSE_INVALID")
    if kind == "device-state":
        generation = payload.get("generation")
        reason = payload.get("reason_code")
        if (
            set(payload) != {"schema", "device_id", "state", "reason_code", "generation"}
            or payload.get("schema") != DEVICE_STATE_SCHEMA
            or payload.get("device_id") != device_id
            or payload.get("state") not in {"running", "stopped"}
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or (reason is not None and (not isinstance(reason, str) or not REASON_CODE_RE.match(reason)))
        ):
            raise SyncError("AUTHORITY_RESPONSE_INVALID")
        return payload
    generation = payload.get("authority_generation")
    files = payload.get("files")
    if (
        payload.get("schema") != GOVERNED_BODIES_SCHEMA
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or not isinstance(payload.get("governance_digest"), str)
        or not DIGEST_RE.fullmatch(payload["governance_digest"])
        or not isinstance(files, list)
    ):
        raise SyncError("AUTHORITY_RESPONSE_INVALID")
    wanted = expected or {}
    verified: Dict[str, Tuple[bytes, int]] = {}
    for item in files:
        if not isinstance(item, dict) or item.get("path") not in wanted:
            raise SyncError("AUTHORITY_RESPONSE_INVALID")
        relative = item["path"]
        try:
            if item.get("encoding") == "base64":
                content = base64.b64decode(str(item.get("content")), validate=True)
            elif item.get("encoding") == "utf-8" and isinstance(item.get("content"), str):
                content = item["content"].encode("utf-8")
            else:
                raise ValueError("encoding")
        except ValueError:
            raise SyncError("AUTHORITY_RESPONSE_INVALID") from None
        if item.get("mode") not in FILE_MODES or len(content) > MAX_RESTORE_BYTES:
            raise SyncError("AUTHORITY_RESPONSE_INVALID")
        if hashlib.sha256(content).hexdigest() != wanted[relative]:
            raise SyncError("DIGEST_MISMATCH")
        verified[relative] = (content, FILE_MODES[item["mode"]])
    return {
        "authority_generation": generation,
        "governance_digest": payload["governance_digest"],
        "files": verified,
    }


# --- authority address and managed preferences -----------------------------------------------


def read_managed_preferences(path: Path) -> Optional[Dict[str, Any]]:
    """Jamf's managed preferences, or ``None`` on a device that has none."""

    raw = _read_regular(path, 64 * 1024)
    if raw is None:
        return None
    try:
        value = plistlib.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _base_url(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parts = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        return None
    return f"https://{parts.netloc}"


def _kt_url(document: object, table: str) -> object:
    if not isinstance(document, dict):
        return None
    servers = document.get(table)
    entry = servers.get("kt") if isinstance(servers, dict) else None
    return entry.get("url") if isinstance(entry, dict) else None


def client_registration_url(home: Optional[Path] = None) -> Optional[str]:
    """The first HTTPS ``kt`` registration of this user's coding clients."""

    selected = _settings_home() if home is None else home
    if sys.platform == "darwin":
        vscode = selected / "Library/Application Support/Code/User/mcp.json"
    elif os.name == "nt":
        vscode = Path(os.environ.get("APPDATA", str(selected))) / "Code/User/mcp.json"
    else:
        vscode = selected / ".config/Code/User/mcp.json"
    candidates = (
        (selected / ".claude.json", "mcpServers"),
        (selected / ".cursor/mcp.json", "mcpServers"),
        (vscode, "servers"),
    )
    for path, table in candidates:
        url = _base_url(_kt_url(_read_json(path, MAX_SETTINGS_BYTES), table))
        if url is not None:
            return url
    codex_home = Path(os.environ.get("CODEX_HOME") or (selected / ".codex"))
    raw = _read_regular(codex_home / "config.toml", MAX_SETTINGS_BYTES)
    if raw is not None:
        try:
            import tomllib  # Python 3.11 and later; older interpreters skip Codex.

            return _base_url(_kt_url(tomllib.loads(raw.decode("utf-8")), "mcp_servers"))
        except Exception:
            return None
    return None


# --- run context and state -------------------------------------------------------------------


def _fresh_state() -> Dict[str, Any]:
    return {
        "state": "unknown",
        "reason_code": None,
        "authority": {"state": "unknown", "reason_code": None, "generation": 0, "checked_at": None},
        "device_id": None,
        "last_check": None,
        "projects": {},
    }


class RunContext:
    """What every task of one run shares; tasks never keep state outside ``state``."""

    def __init__(
        self,
        records: Dict[str, Any],
        location: Any,
        managed: Optional[Dict[str, Any]],
        address: Optional[str],
        device_id: Optional[str],
        budget: float = RUN_BUDGET_SECONDS,
    ) -> None:
        self.records = records
        self.location = location
        self.managed = managed
        self.address = address
        self.device_id = device_id
        self.deadline = time.monotonic() + budget
        self.state = records["read_sync_state"](location=location) or _fresh_state()
        self.events: List[str] = []

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, bytes]:
        if self.address is None:
            raise SyncError("ADDRESS_UNAVAILABLE")
        timeout = min(REQUEST_TIMEOUT_SECONDS, self.remaining())
        if timeout <= 0:
            raise SyncError("RUN_BUDGET_EXHAUSTED")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return _transport(self.address + path, body, timeout)

    def event(self, body: Dict[str, Any], project_id: Optional[str] = None) -> None:
        with contextlib.suppress(Exception):
            self.records["write_sync_event"](body, project_id=project_id, location=self.location)
            self.events.append(str(body.get("event")))

    def save(self) -> None:
        self.state["updated_at"] = _utc_text(_now())
        self.records["write_sync_state"](self.state, location=self.location)


# --- task: device stop -----------------------------------------------------------------------


def device_stop_task(ctx: RunContext) -> None:
    """Read this device's line of the stop list and keep a stopped device stopped offline."""

    state = ctx.state
    authority = state["authority"]
    previous = state["state"]
    managed_id = normalized_device_id((ctx.managed or {}).get("DeviceID"))
    mismatch = bool(
        ctx.device_id is not None
        and ctx.managed
        and ctx.managed.get("DeviceID") is not None
        and managed_id != ctx.device_id
    )
    outcome = "ok"
    if ctx.device_id is None:
        outcome = "device-id-unavailable"
    elif mismatch:
        outcome = "device-id-mismatch"
    elif ctx.address is None:
        outcome = "address-unavailable"
    else:
        try:
            status, raw = ctx.post(DEVICE_STATE_PATH, {"device_id": ctx.device_id})
            answer = verify_authority_response(
                "device-state", status, raw, device_id=ctx.device_id
            )
        except SyncError as exc:
            outcome = (
                "unreachable"
                if exc.code in {"AUTHORITY_UNREACHABLE", "AUTHORITY_UNAVAILABLE"}
                else "invalid-response"
            )
        else:
            generation = int(answer["generation"])
            current = int(authority["generation"])
            accepted = (
                generation >= current
                if authority["state"] == "unknown"
                else generation > current
                or (generation == current and answer["state"] == authority["state"])
            )
            if accepted:
                authority.update(
                    {
                        "state": answer["state"],
                        "reason_code": answer["reason_code"],
                        "generation": generation,
                        "checked_at": _utc_text(_now()),
                    }
                )
            else:
                outcome = "stale-response"
    if mismatch:
        state["state"], state["reason_code"] = "stopped", "DEVICE_ID_MISMATCH"
    else:
        state["state"], state["reason_code"] = authority["state"], authority["reason_code"]
    state["device_id"] = ctx.device_id
    state["last_check"] = {"at": _utc_text(_now()), "outcome": outcome}
    if state["state"] != previous:
        ctx.event(
            {
                "event": "device-state-changed",
                "device_id": ctx.device_id,
                "previous_state": previous,
                "state": state["state"],
                "reason_code": state["reason_code"],
                "generation": authority["generation"],
                "outcome": outcome,
            }
        )


# --- task: governance restore ----------------------------------------------------------------


class _Git:
    """Read the project's object store only: commit trees and blobs, never the index."""

    def __init__(self, project_root: Path, records: Dict[str, Any]) -> None:
        executable = shutil.which("git")
        if executable is None:
            raise SyncError("GIT_UNAVAILABLE")
        self.command = [executable, "-C", str(project_root), "--literal-pathspecs"]
        excluded = records["GIT_LOCATION_VARIABLES"]
        self.environment = {key: value for key, value in os.environ.items() if key not in excluded}
        self.environment["GIT_OPTIONAL_LOCKS"] = "0"
        self.environment["GIT_TERMINAL_PROMPT"] = "0"

    def __call__(self, *arguments: str) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(
            [*self.command, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=self.environment,
        )


def history_bytes(git: _Git, relative: str, expected: str) -> Optional[Tuple[bytes, int]]:
    """The recorded bytes of ``relative`` in ``HEAD``, then in its history, newest first."""

    checked = set()

    def search(commits: List[str]) -> Optional[Tuple[bytes, int]]:
        for commit in commits:
            listed = git("ls-tree", "-l", "-z", commit, "--", relative)
            if listed.returncode != 0:
                continue
            for record in listed.stdout.split(b"\0"):
                metadata, _, name = record.partition(b"\t")
                fields = metadata.decode("ascii", "replace").split()
                if len(fields) != 4 or name.decode("utf-8", "surrogateescape") != relative:
                    continue
                mode, kind, object_id, size = fields
                if (
                    kind != "blob"
                    or mode not in FILE_MODES
                    or object_id in checked
                    or not size.isdigit()
                    or int(size) > MAX_RESTORE_BYTES
                ):
                    continue
                checked.add(object_id)
                blob = git("cat-file", "blob", object_id)
                if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == expected:
                    return blob.stdout, FILE_MODES[mode]
        return None

    found = search(["HEAD"])
    if found is not None:
        return found
    history = git("rev-list", "--full-history", "HEAD", "--", relative)
    if history.returncode != 0:
        return None
    return search(history.stdout.decode("ascii", "replace").split())


def _git_directory(project_root: Path) -> Optional[Path]:
    dot_git = project_root / ".git"
    if dot_git.is_dir() and not dot_git.is_symlink():
        return dot_git
    raw = _read_regular(dot_git, 4096)
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace").strip()
    if not text.startswith("gitdir:"):
        return None
    target = Path(text[len("gitdir:") :].strip())
    return target if target.is_absolute() else (project_root / target)


def project_busy(ctx: RunContext, project_id: str, project_root: Path) -> Optional[str]:
    """A reason to leave the project alone this run, or ``None``."""

    git_directory = _git_directory(project_root)
    if git_directory is not None and any(
        os.path.lexists(git_directory / marker) for marker in GIT_OPERATION_MARKERS
    ):
        return "GIT_OPERATION_IN_PROGRESS"
    try:
        area = ctx.records["review_area"](project_id, location=ctx.location)
    except Exception:
        return None
    if area.is_symlink() or not area.is_dir():
        return None
    now = _now()
    leases = area / "leases"
    if leases.is_dir() and not leases.is_symlink():
        for candidate in leases.glob("*.json"):
            lease = _read_json(candidate, 64 * 1024)
            run = lease.get("run") if lease else None
            expires = _parse_utc(run.get("lease_expires_at")) if isinstance(run, dict) else None
            if (
                isinstance(run, dict)
                and run.get("state") not in TERMINAL_RUN_STATES
                and expires is not None
                and expires > now
            ):
                return "REVIEW_RUN_ACTIVE"
    for run_directory in area.glob("run-*"):
        started = run_directory / "inputs" / "run.json"
        try:
            if (
                not run_directory.is_symlink()
                and started.is_file()
                and not (run_directory / "receipt.json").exists()
                and now - datetime.fromtimestamp(started.stat().st_mtime, UTC) < ACTIVE_RUN_WINDOW
            ):
                return "REVIEW_RUN_ACTIVE"
        except OSError:
            continue
    return None


def _managed_digests(project_root: Path) -> Dict[str, str]:
    manifest = _read_json(project_root / MANIFEST_PATH, MAX_MANIFEST_BYTES)
    managed = manifest.get("managed") if manifest else None
    if not isinstance(managed, dict) or any(
        not isinstance(path, str) or not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest)
        for path, digest in managed.items()
    ):
        raise SyncError("MANIFEST_INVALID")
    return dict(managed)


def _project_identity(project_root: Path) -> Optional[Dict[str, Any]]:
    try:
        if project_root.is_symlink() or not project_root.is_dir():
            return None
    except OSError:
        return None
    return _read_json(project_root / PROJECT_MANIFEST_PATH, 256 * 1024)


def _drifted(
    project_root: Path, managed: Dict[str, str], governed: Callable[[str], bool]
) -> Tuple[Dict[str, str], Dict[str, Path]]:
    """Governed managed paths whose bytes differ from the record, with checked destinations."""

    drifted: Dict[str, str] = {}
    destinations: Dict[str, Path] = {}
    for relative in sorted(managed):
        if not governed(relative):
            continue
        safe_relative(relative)
        destination = safe_destination(project_root, relative)
        current = _read_regular(destination, MAX_RESTORE_BYTES)
        if current is None or hashlib.sha256(current).hexdigest() != managed[relative]:
            drifted[relative] = managed[relative]
            destinations[relative] = destination
    return drifted, destinations


def _authority_bodies(
    ctx: RunContext, project_root: Path, wanted: Dict[str, str]
) -> Dict[str, Any]:
    answers = _read_regular(project_root / ANSWERS_PATH, MAX_ANSWERS_BYTES)
    if answers is None:
        raise SyncError("AUTHORITY_UNAVAILABLE")
    try:
        answers_text = answers.decode("utf-8")
    except UnicodeDecodeError:
        raise SyncError("AUTHORITY_UNAVAILABLE") from None
    found: Dict[str, Tuple[bytes, int]] = {}
    summary: Dict[str, Any] = {}
    paths = sorted(wanted)
    for start in range(0, max(len(paths), 1), MAX_BODIES_PER_REQUEST):
        batch = paths[start : start + MAX_BODIES_PER_REQUEST]
        status, raw = ctx.post(GOVERNED_BODIES_PATH, {"answers_yaml": answers_text, "paths": batch})
        answer = verify_authority_response(
            "governed-bodies", status, raw, expected={path: wanted[path] for path in batch}
        )
        found.update(answer["files"])
        summary = answer
    return {
        "authority_generation": summary.get("authority_generation"),
        "governance_digest": summary.get("governance_digest"),
        "files": found,
    }


def _restore_project(
    ctx: RunContext, project_id: str, project_root: Path, governed: Callable[[str], bool]
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Validate the whole project first; write nothing unless every drifted file is planned."""

    try:
        managed = _managed_digests(project_root)
        drifted, destinations = _drifted(project_root, managed, governed)
    except SyncError as exc:
        return "refused", {"event": "restore", "outcome": "refused", "reason_code": exc.code}
    if not drifted:
        return "current", None
    planned: Dict[str, Tuple[bytes, int, str]] = {}
    if ctx.records["repository_status"](project_root) == "ok":
        try:
            git = _Git(project_root, ctx.records)
            for relative, digest in drifted.items():
                found = history_bytes(git, relative, digest)
                if found is not None:
                    planned[relative] = (found[0], found[1], "git-history")
        except (SyncError, OSError, subprocess.SubprocessError):
            pass
    missing = {path: digest for path, digest in drifted.items() if path not in planned}
    reason = None
    if missing:
        try:
            answer = _authority_bodies(ctx, project_root, missing)
            for relative, (content, mode) in answer["files"].items():
                planned[relative] = (content, mode, "authority")
        except SyncError as exc:
            reason = exc.code
    unplanned = [path for path in drifted if path not in planned]
    if unplanned:
        code = reason or "NOT_AVAILABLE"
        return "refused", {
            "event": "restore",
            "outcome": "refused",
            "reason_code": code,
            "paths": [
                {"path": path, "sha256": drifted[path], "result": "refused"} for path in unplanned
            ],
        }
    if ctx.expired() or project_busy(ctx, project_id, project_root) is not None:
        return "skipped", None
    written = []
    for relative in sorted(planned):
        content, mode, source = planned[relative]
        try:
            destination = safe_destination(project_root, relative)
            if destination != destinations[relative]:
                raise SyncError("LINKED_PATH")
            _replace_file(destination, content, mode)
        except (SyncError, OSError):
            return "refused", {
                "event": "restore",
                "outcome": "write-failed",
                "reason_code": "WRITE_FAILED",
                "paths": written,
            }
        written.append(
            {"path": relative, "sha256": drifted[relative], "source": source, "result": "restored"}
        )
    return "restored", {"event": "restore", "outcome": "restored", "paths": written}


def _authority_generation_check(
    ctx: RunContext, project_id: str, project_root: Path, summary: Dict[str, Any]
) -> None:
    """Note a newer authority generation; the update itself stays the Agent-led sync."""

    last = _parse_utc(summary.get("authority_checked_at"))
    if ctx.address is None or (last is not None and _now() - last < AUTHORITY_CHECK_INTERVAL):
        return
    identity = _project_identity(project_root) or {}
    local = identity.get("authority_generation")
    if not isinstance(local, int) or isinstance(local, bool):
        return
    try:
        answer = _authority_bodies(ctx, project_root, {})
    except SyncError:
        return
    remote = answer.get("authority_generation")
    if not isinstance(remote, int):
        return
    summary["authority_checked_at"] = _utc_text(_now())
    pending = remote > local
    if pending and summary.get("update_pending") is not True:
        ctx.event(
            {
                "event": "update-pending",
                "authority_generation": remote,
                "local_authority_generation": local,
                "device_id": ctx.device_id,
            },
            project_id=project_id,
        )
    summary["update_pending"] = pending


def governance_restore_task(ctx: RunContext) -> None:
    """Put drifted governance files of every registered project back to their recorded bytes."""

    governed = _governed_classifier()
    projects = ctx.state.setdefault("projects", {})
    registered = ctx.records["registered_projects"](location=ctx.location)
    known = {project_id for project_id, _ in registered}
    for project_id in list(projects):
        if project_id not in known:
            del projects[project_id]
    for project_id, project_root in registered:
        if ctx.expired():
            break
        identity = _project_identity(project_root)
        if identity is None or identity.get("project_id") != project_id:
            ctx.records["forget_project"](project_id, location=ctx.location)
            projects.pop(project_id, None)
            continue
        summary = projects.setdefault(project_id, {})
        busy = project_busy(ctx, project_id, project_root)
        if busy is not None:
            outcome, event = "skipped", None
        else:
            outcome, event = _restore_project(ctx, project_id, project_root, governed)
        if event is not None and (outcome == "restored" or summary.get("outcome") != outcome):
            event["device_id"] = ctx.device_id
            ctx.event(event, project_id=project_id)
        summary["outcome"] = outcome
        summary["at"] = _utc_text(_now())
        _authority_generation_check(ctx, project_id, project_root, summary)


# --- task: record forwarding (Agent Platform capability 010) ---------------------------------


def _forwarder() -> Dict[str, Any]:
    path = Path(__file__).resolve().with_name(FORWARDER)
    if path.is_symlink() or not path.is_file():
        raise SyncError("FORWARDER_UNAVAILABLE")
    return runpy.run_path(str(path))


def log_forwarding_task(ctx: RunContext) -> None:
    """Forward this user's chained records with the run's device identity, as this user.

    The collector address, the institution's root CA file and the MDM-written device key file
    come from the managed preferences; a device without them forwards nothing and keeps its
    records.  The acknowledgement state stays in this user's sync directory.
    """

    managed = ctx.managed or {}
    settings: Dict[str, object] = {
        name: managed.get(key) for name, key in FORWARDER_PREFERENCES.items()
    }
    forwarder = _forwarder()
    if ctx.remaining() < float(forwarder["REQUEST_TIMEOUT_SECONDS"]):
        code = "run-budget-exhausted"
    else:
        state_file = ctx.records["sync_directory"](location=ctx.location) / FORWARDER_STATE_FILE
        settings["state_file"] = str(state_file)
        code = str(
            forwarder["forward"](settings, device_id=ctx.device_id, location=ctx.location)["code"]
        )
    previous = ctx.state.get("log_forwarding")
    ctx.state["log_forwarding"] = {"code": code, "at": _utc_text(_now())}
    if not isinstance(previous, dict) or previous.get("code") != code:
        ctx.event({"event": "log-forwarding-changed", "device_id": ctx.device_id, "outcome": code})


TASKS: Tuple[Tuple[str, Callable[[RunContext], None]], ...] = (
    ("cihaz-durdurma", device_stop_task),
    ("kayit-aktarimi", log_forwarding_task),
    ("yonetisim-geri-alma", governance_restore_task),
)


# --- one run ---------------------------------------------------------------------------------


def _privileged() -> bool:
    if os.name == "posix":
        return os.geteuid() == 0
    user = getpass.getuser()
    return user.upper() == "SYSTEM" or user.endswith("$")


@contextlib.contextmanager
def _single_run(records: Dict[str, Any], location: Any) -> Any:
    """Hold this user's run lock; yield ``False`` when another run already holds it."""

    path = records["sync_directory"](location=location) / "run.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            acquired = False
        yield acquired
    finally:
        os.close(descriptor)


def run_once(budget: float = RUN_BUDGET_SECONDS) -> Dict[str, Any]:
    """Run every task once for the signed-in user and save the state."""

    if _privileged():
        return {"status": "refused-privileged"}
    records = _records()
    location = _record_location()
    with _single_run(records, location) as acquired:
        if not acquired:
            return {"status": "busy"}
        managed = read_managed_preferences(
            _managed_preferences() or records["MANAGED_PREFERENCES"]
        )
        address = _base_url((managed or {}).get("AuthorityURL")) if managed else None
        if address is None and not managed:
            address = client_registration_url()
        ctx = RunContext(records, location, managed, address, _hardware_device_id(), budget)
        failed: List[str] = []
        for name, task in TASKS:
            try:
                task(ctx)
            except Exception:
                failed.append(name)
            with contextlib.suppress(Exception):
                ctx.save()
        return {
            "status": "ran",
            "state": ctx.state["state"],
            "failed_tasks": failed,
            "events": ctx.events,
            "projects": {key: value.get("outcome") for key, value in ctx.state["projects"].items()},
        }


# --- the hooks' side: gate, project registration and task installation ----------------------


def gate(hook: str, client: Optional[str] = None, project_id: Optional[str] = None) -> int:
    """The Git pre-commit side of the device stop; prints the fixed refusal and returns 1."""

    try:
        records = _records()
    except SyncError:
        return 0
    location = _record_location()
    decision, _ = records["device_gate"](
        location=location, managed_preferences=_managed_preferences()
    )
    if decision not in {"stop", "unverified"}:
        return 0
    print(records["gate_message"](decision, marker=True), file=sys.stderr)
    records["record_refusal"](hook, decision, client=client, project_id=project_id, location=location)
    return 1


class LaunchdScheduler:
    """A per-user LaunchAgent; skipped where Jamf installed the system-wide one."""

    def __init__(
        self,
        home: Path,
        runner: Optional[Callable[[List[str]], int]] = None,
        system_agent: Path = SYSTEM_LAUNCH_AGENT,
    ) -> None:
        self.agent = home / "Library/LaunchAgents" / f"{TASK_LABEL}.plist"
        self.system_agent = system_agent
        self.runner = runner or _run_quietly

    @staticmethod
    def definition(python: Path, script: Path) -> bytes:
        return plistlib.dumps(
            {
                "Label": TASK_LABEL,
                "ProgramArguments": [str(python), str(script), "calistir"],
                "RunAtLoad": True,
                "StartInterval": RUN_INTERVAL_SECONDS,
                "ProcessType": "Background",
                "LowPriorityIO": True,
                "LimitLoadToSessionType": "Aqua",
                "StandardOutPath": "/dev/null",
                "StandardErrorPath": "/dev/null",
            }
        )

    def ensure(self, python: Path, script: Path) -> str:
        if self.system_agent.is_file():
            return "managed"
        current = _read_regular(self.agent, 64 * 1024)
        if current is not None:
            try:
                arguments = plistlib.loads(current).get("ProgramArguments")
            except Exception:
                arguments = None
            if (
                isinstance(arguments, list)
                and len(arguments) == 3
                and all(isinstance(item, str) and Path(item).is_file() for item in arguments[:2])
            ):
                return "current"
        self.agent.parent.mkdir(parents=True, exist_ok=True)
        _replace_file(self.agent, self.definition(python, script), 0o644)
        domain = f"gui/{os.getuid()}"
        self.runner(["/bin/launchctl", "bootout", f"{domain}/{TASK_LABEL}"])
        if self.runner(["/bin/launchctl", "bootstrap", domain, str(self.agent)]) != 0:
            return "failed"
        return "installed"


class WindowsScheduler:
    """A user task that runs every five minutes only while the user is signed in."""

    def __init__(self, marker: Path, runner: Optional[Callable[[List[str]], int]] = None) -> None:
        self.marker = marker
        self.runner = runner or _run_quietly

    def ensure(self, python: Path, script: Path) -> str:
        windowless = python.with_name("pythonw.exe")
        interpreter = windowless if windowless.is_file() else python
        recorded = _read_json(self.marker, 4096) or {}
        checked = _parse_utc(recorded.get("checked_at"))
        targets = [recorded.get("python"), recorded.get("script")]
        if (
            all(isinstance(item, str) and Path(item).is_file() for item in targets)
            and checked is not None
            and _now() - checked < AUTHORITY_CHECK_INTERVAL
        ):
            return "current"
        status = "current"
        if self.runner(["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME]) != 0:
            command = f'"{interpreter}" "{script}" calistir'
            created = self.runner(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    WINDOWS_TASK_NAME,
                    "/SC",
                    "MINUTE",
                    "/MO",
                    "5",
                    "/IT",
                    "/F",
                    "/TR",
                    command,
                ]
            )
            if created != 0:
                return "failed"
            status = "installed"
            targets = [str(interpreter), str(script)]
        marker = {"python": targets[0], "script": targets[1], "checked_at": _utc_text(_now())}
        _replace_file(self.marker, json.dumps(marker).encode("utf-8"), 0o644)
        return status


def _run_quietly(command: List[str]) -> int:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def default_scheduler(location: Any = None) -> Any:
    if sys.platform == "darwin":
        return LaunchdScheduler(Path.home())
    if os.name == "nt":
        records = _records()
        return WindowsScheduler(records["sync_directory"](location=location) / "windows-task.json")
    return None


def on_prompt(
    project_root: Path,
    project_id: str,
    *,
    python: Path,
    location: Any = None,
    scheduler: Any = None,
    records: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Register the project and keep the periodic task installed; return warnings only."""

    warnings: List[str] = []
    records = records if records is not None else _records()
    try:
        records["register_project"](project_id, project_root, location=location)
    except Exception:
        # An unusable shared root is already reported by the prompt record warning.
        return warnings
    if scheduler is None:
        return warnings
    script = project_root / ".kt-scaffold/hooks/authority_sync.py"
    try:
        status = scheduler.ensure(python, script)
    except Exception:
        status = "failed"
    if status == "failed":
        warnings.append(TASK_UNAVAILABLE_WARNING)
    return warnings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Periyodik yönetişim eşitlemesi ve cihaz durdurma.")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("calistir", help="Görevleri bu kullanıcı için bir kez çalıştır.")
    gate_parser = commands.add_parser("kapi", help="Cihaz durdurulmuşsa sıfır dışı kodla çık.")
    gate_parser.add_argument("--kanca", default="pre-commit", choices=("pre-commit",))
    arguments = parser.parse_args(argv)
    if arguments.operation == "kapi":
        return gate(arguments.kanca)
    try:
        result = run_once()
    except Exception:
        result = {"status": "failed"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] in {"ran", "busy"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
