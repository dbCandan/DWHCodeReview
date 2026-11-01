#!/usr/bin/env python3
"""Write governance records to the shared, repository-free governance root.

Records live outside the consumer repository and the user's home directory, under one
operating-system root shared by every local user, keyed by ``project_id``. Each record is written
once and never changed, so a collector can pick up new files incrementally. The storage location
is visible and user-writable by design: it is not an integrity boundary. Trust comes from the
specialist agents and from the hooks that enforce their evidence on the agent path.

Every dated, content-addressed and publication record also carries a ``chain`` link: a per
``(project_id, os_user)`` stream sequence and the SHA-256 of the previous record's exact bytes. The
link makes later deletion, insertion or rewriting visible to the central collector once the
forwarder has sealed the stream head; it proves nothing on the device itself.

This module is dependency-free. Hooks load it with ``runpy``; the factory package reuses the same
file through ``kt_scaffold.governance_records``.
"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import runpy
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

# Hooks may start on the host's python3 before moving to the project's `.venv`; keep 3.9 syntax.
UTC = timezone.utc  # noqa: UP017
SCHEMA = "kt-governance-record/v1"
SHARED_DIRECTORY_MODE = 0o1777
RECORD_FILE_MODE = 0o644

DATED_KINDS = frozenset(
    {
        "prompt-ingress",
        "llm-call-events",
        "commit-governance",
        "agent-consultation",
        "review-decision",
    }
)
ADDRESSED_KINDS = frozenset({"review-baseline", "authority-pin"})
REVIEW_RUN_KIND = "governed-review"
MAX_RECORD_BYTES = {
    "llm-call-events": 16 * 1024,
    "prompt-ingress": 256 * 1024,
    "commit-governance": 64 * 1024,
    "agent-consultation": 512 * 1024,
    "review-decision": 128 * 1024,
    "authority-pin": 64 * 1024,
    "review-baseline": 2 * 1024 * 1024,
}
MAX_REVIEW_RUN_BYTES = {
    "snapshot": 4 * 1024 * 1024,
    "reports": 512 * 1024,
}
DEFAULT_REVIEW_RUN_BYTES = 1024 * 1024
CONTEXT_FIELDS = (
    "client",
    "client_source",
    "session_hash",
    "turn_hash",
    "identity_source",
)
CLIENT_SOURCES = frozenset({"envelope", "command"})
MAX_CONTEXT_CHARACTERS = 256

PROJECT_ID_RE = re.compile(r"^project-[0-9a-f]{32}$")
RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ADDRESS_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^run-[A-Za-z0-9][A-Za-z0-9._-]{3,119}$")
RUN_FILE_RE = re.compile(r"^(?:snapshot|decision|receipt|audit|lease|reports/[a-z0-9-]{1,64})$")
# Canonical run artifacts the governance client writes as raw bytes: the run inputs, the
# rule-based scan record, the decision and the receipt.  Specialist reports have their own writer;
# the audit is an enveloped record.
RUN_ARTIFACT_RE = re.compile(
    r"^(?:inputs/(?:snapshot|run|[a-z][a-z0-9]*(?:-[a-z0-9]+)*\.bindings)"
    r"|reports/deterministic-scan|decision|receipt)$"
)
AGENT_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_IDENTITY_CHARACTERS = 256
# Variables that could point Git at a different repository than the project.
GIT_LOCATION_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)
GIT_TIMEOUT_SECONDS = 30

# Chain streams: one directory per (project_id, os_user), owned by that user and closed to others.
CHAIN_DIRECTORY = "chain"
STREAM_DIRECTORY_MODE = 0o755
STREAM_PRIVATE_FILE_MODE = 0o600
CHAIN_LOCK_TIMEOUT_SECONDS = 2.0
ZERO_DIGEST = "0" * 64
CHAIN_HEAD_SCHEMA = "kt-governance-chain-head/v1"
CHAIN_ENTRY_SCHEMA = "kt-governance-chain-entry/v1"
CHAIN_HEAD_FILE = "head.json"
CHAIN_ENTRY_DIRECTORY = "entries"
CHAIN_LOCK_FILE = "lock"
STREAM_ID_RE = re.compile(r"^stream-[0-9a-f]{32}$")
CHAIN_ENTRY_RE = re.compile(r"^([0-9]{6})-([0-9]{12})\.json$")
MAX_CHAIN_STATE_BYTES = 4096
# Run files that are working state, never evidence: the lease and the specialists' scratch area.
UNBOUND_RUN_PARTS = frozenset({"work", "lease.json"})
# A link of the largest shape, so size limits are checked before any directory is created.
SIZE_PROBE_CHAIN = {
    "status": "linked",
    "stream_id": "stream-" + "0" * 32,
    "epoch": 999999,
    "sequence": 999999999999,
    "previous_sha256": ZERO_DIGEST,
    "epoch_reason": "head-unreadable",
}


class RecordError(Exception):
    """A record could not be written; ``code`` is a stable, content-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# The last gate (Agent Platform capability 011): every text value of these kinds is scanned with
# the prompt policy's engine before it is written. Identifier and digest values are left out: a
# run of hexadecimal digits can match a checksum by chance.
CONTENT_GATED_KINDS = frozenset({"llm-call-events"})
GATE_IDENTIFIER_RE = re.compile(r"(?:[a-z][a-z0-9-]*[:.])*[0-9a-f]{16,}")
PROMPT_GUARD_FILE = "prompt_ingress_guard.py"


def _gate_texts(value: object, texts: list[str]) -> None:
    if isinstance(value, str):
        if GATE_IDENTIFIER_RE.fullmatch(value) is None:
            texts.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _gate_texts(key, texts)
            _gate_texts(item, texts)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _gate_texts(item, texts)


def _content_gate(body: Mapping[str, Any], location: GovernanceLocation | None) -> None:
    """Refuse a gated record that carries a data class the prompt policy finds.

    The engine is the prompt hook beside this file with the project's own policy; when it cannot
    run, the record is refused too.
    """

    texts: list[str] = []
    _gate_texts(body, texts)
    if not texts:
        return
    try:
        here = Path(__file__).resolve()
        guard = here.with_name(PROMPT_GUARD_FILE)
        if guard.is_symlink() or not guard.is_file():
            raise RecordError("record-content-gate-unavailable")
        found = runpy.run_path(str(guard))["record_content_classes"](
            here.parents[2], texts, location
        )
    except Exception:
        raise RecordError("record-content-gate-unavailable") from None
    if found:
        raise RecordError("record-content-sensitive")


@dataclass(frozen=True)
class GovernanceLocation:
    """The provisioned ``anchor`` must already exist; ``root`` is created below it on demand."""

    anchor: Path
    root: Path


def resolve_location(
    platform_name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> GovernanceLocation:
    """Return the fixed shared root for this operating system; no variable can relocate it."""

    selected = sys.platform if platform_name is None else platform_name
    values = os.environ if environment is None else environment
    if selected == "darwin":
        anchor = Path("/Users/Shared")
        return GovernanceLocation(anchor, anchor / "kt-scaffold" / "governance")
    if selected == "win32":
        program_data = values.get("ProgramData") or values.get("PROGRAMDATA")
        if not program_data:
            raise RecordError("root-unavailable")
        windows_anchor = PureWindowsPath(program_data)
        if not windows_anchor.is_absolute() or ".." in windows_anchor.parts:
            raise RecordError("root-unavailable")
        anchor = Path(str(windows_anchor))
        return GovernanceLocation(anchor, anchor / "kt-scaffold" / "governance")
    linux_root = Path(str(PurePosixPath("/var/lib/kt-scaffold/governance")))
    return GovernanceLocation(linux_root, linux_root)


def device_name() -> str:
    return _bounded_identity(socket.gethostname())


def os_user() -> str:
    if os.name == "posix":
        import pwd

        with contextlib.suppress(KeyError):
            return _bounded_identity(pwd.getpwuid(os.geteuid()).pw_name)
    return _bounded_identity(getpass.getuser())


def _bounded_identity(value: str) -> str:
    cleaned = "".join(character for character in value if character.isprintable()).strip()
    if not cleaned:
        return "unavailable"
    return cleaned[:MAX_IDENTITY_CHARACTERS]


def _now() -> datetime:
    return datetime.now(UTC)


def _require_project_id(project_id: str) -> None:
    if not isinstance(project_id, str) or PROJECT_ID_RE.fullmatch(project_id) is None:
        raise RecordError("project-id-invalid")


def _is_windows() -> bool:
    return os.name == "nt"


def _checked_directory(path: Path) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        raise RecordError("root-unavailable") from None
    except OSError as exc:
        raise RecordError("root-unavailable") from exc
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise RecordError("root-path-unsafe")


def _shared_directory(path: Path) -> None:
    """Create ``path`` as a shared directory, or accept an existing real directory."""

    try:
        path.mkdir(mode=SHARED_DIRECTORY_MODE)
    except FileExistsError:
        _checked_directory(path)
        return
    except OSError as exc:
        raise RecordError("root-not-writable") from exc
    _checked_directory(path)
    if not _is_windows():
        try:
            # Contract 1777: all users write, sticky bit; the rule flags every usable directory.
            os.chmod(path, SHARED_DIRECTORY_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        except OSError as exc:
            raise RecordError("root-not-writable") from exc


def _prepare_directory(location: GovernanceLocation, parts: tuple[str, ...]) -> Path:
    _checked_directory(location.anchor)
    relative = location.root.relative_to(location.anchor).parts
    current = location.anchor
    for part in (*relative, *parts):
        current = current / part
        _shared_directory(current)
    return current


def _fsync_directory(path: Path) -> None:
    if _is_windows():
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(destination: Path, payload: bytes) -> bool:
    """Atomically publish ``payload``; return False when the destination already exists."""

    temporary = destination.parent / f".{destination.name}.{secrets.token_hex(16)}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, RECORD_FILE_MODE)
    except OSError as exc:
        raise RecordError("root-not-writable") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            if not _is_windows():
                os.fchmod(handle.fileno(), RECORD_FILE_MODE)
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            return False
        _fsync_directory(destination.parent)
        return True
    except OSError as exc:
        raise RecordError("record-write-failed") from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _encode(record: Mapping[str, Any], limit: int) -> bytes:
    try:
        payload = (
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecordError("record-invalid") from exc
    if len(payload) > limit:
        raise RecordError("record-too-large")
    return payload


def _context(context: Mapping[str, object] | None) -> dict[str, object]:
    supplied = {} if context is None else dict(context)
    if set(supplied) - set(CONTEXT_FIELDS):
        raise RecordError("record-context-invalid")
    result: dict[str, object] = {}
    for field in CONTEXT_FIELDS:
        value = supplied.get(field)
        if value is not None and (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_CONTEXT_CHARACTERS
            or not value.isprintable()
        ):
            raise RecordError("record-context-invalid")
        result[field] = value
    if result["client_source"] is not None and result["client_source"] not in CLIENT_SOURCES:
        raise RecordError("record-context-invalid")
    return result


def _envelope(
    kind: str,
    project_id: str,
    record_id: str,
    body: Mapping[str, Any],
    recorded_at: datetime,
    context: Mapping[str, object] | None,
    chain: Mapping[str, object] | None = None,
    bound_files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Wrap ``body`` unchanged; identity fields come from this process, never from the caller."""

    if not isinstance(body, Mapping):
        raise RecordError("record-invalid")
    envelope: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": kind,
        "record_id": record_id,
        "project_id": project_id,
        "device_name": device_name(),
        "os_user": os_user(),
        "recorded_at": recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        **_context(context),
        "body": dict(body),
    }
    if chain is not None:
        envelope["chain"] = dict(chain)
    if bound_files is not None:
        envelope["bound_files"] = bound_files
    return envelope


def stream_id(project_id: str, user: str | None = None) -> str:
    """The chain stream of one ``(project_id, os_user)`` pair on this device."""

    _require_project_id(project_id)
    selected = os_user() if user is None else user
    digest = hashlib.sha256(f"{project_id}\n{selected}".encode()).hexdigest()
    return f"stream-{digest[:32]}"


def _owned_private_directory(path: Path) -> None:
    """Accept only a real directory this user owns and nobody else can write."""

    try:
        status = path.lstat()
    except OSError:
        raise RecordError("chain-path-unsafe") from None
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise RecordError("chain-path-unsafe")
    if not _is_windows() and (
        status.st_uid != os.geteuid() or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RecordError("chain-path-unsafe")


def _owned_directory(path: Path) -> None:
    try:
        path.mkdir(mode=STREAM_DIRECTORY_MODE)
    except FileExistsError:
        pass
    except OSError:
        raise RecordError("chain-path-unsafe") from None
    else:
        if not _is_windows():
            with contextlib.suppress(OSError):
                # Contract mode 0755: only the owner writes; the rule flags every usable directory.
                os.chmod(path, STREAM_DIRECTORY_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    _owned_private_directory(path)


def stream_directory(project_id: str, *, location: GovernanceLocation | None = None) -> Path:
    """Create or accept ``<root>/<project_id>/chain/<stream_id>``; anything foreign is unsafe."""

    _require_project_id(project_id)
    selected = resolve_location() if location is None else location
    try:
        parent = _prepare_directory(selected, (project_id, CHAIN_DIRECTORY))
    except RecordError:
        raise RecordError("chain-path-unsafe") from None
    stream = parent / stream_id(project_id)
    _owned_directory(stream)
    return stream


def _acquire_stream_lock(stream: Path) -> int:
    """Hold the stream's exclusive lock; give up after two seconds with a stable code."""

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(stream / CHAIN_LOCK_FILE, flags, STREAM_PRIVATE_FILE_MODE)
    except OSError:
        raise RecordError("chain-path-unsafe") from None
    deadline = time.monotonic() + CHAIN_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            if _is_windows():
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except OSError:
            if time.monotonic() >= deadline:
                os.close(descriptor)
                raise RecordError("chain-lock-timeout") from None
            time.sleep(0.01)


def _release_stream_lock(descriptor: int) -> None:
    try:
        if _is_windows():
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _small_json(path: Path) -> dict[str, Any] | None:
    """Read a small working-state JSON object; ``None`` when absent, an error when unusable."""

    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise RecordError("chain-state-unreadable") from None
    if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_CHAIN_STATE_BYTES:
        raise RecordError("chain-state-unreadable")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecordError("chain-state-unreadable") from None
    if not isinstance(value, dict):
        raise RecordError("chain-state-unreadable")
    return value


def _is_count(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _valid_position(value: Mapping[str, Any], schema: str, stream: str) -> bool:
    digest = value.get("last_sha256" if schema == CHAIN_HEAD_SCHEMA else "sha256")
    return (
        value.get("schema") == schema
        and value.get("stream_id") == stream
        and _is_count(value.get("epoch"), 1)
        and _is_count(value.get("sequence"), 0)
        and isinstance(digest, str)
        and ADDRESS_RE.fullmatch(digest) is not None
    )


def chain_entries(stream: Path) -> list[tuple[int, int, Path]]:
    """Return the stream's index entries as ``(epoch, sequence, path)`` in chain order."""

    directory = stream / CHAIN_ENTRY_DIRECTORY
    if directory.is_symlink() or not directory.is_dir():
        return []
    found = []
    for candidate in directory.iterdir():
        match = CHAIN_ENTRY_RE.fullmatch(candidate.name)
        if match is not None:
            found.append((int(match.group(1)), int(match.group(2)), candidate))
    found.sort()
    return found


def read_chain_entry(
    stream: Path, entry: Path, location: GovernanceLocation
) -> tuple[dict[str, Any], Path, bytes | None] | None:
    """Return an index entry, the record path it names and that record's current bytes.

    ``None`` means the entry itself is unusable; missing record bytes are ``None`` so a caller
    can still report the position.
    """

    try:
        value = _small_json(entry)
    except RecordError:
        return None
    if value is None or not _valid_position(value, CHAIN_ENTRY_SCHEMA, stream.name):
        return None
    relative = value.get("path")
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        return None
    record = location.root.joinpath(*relative.split("/"))
    payload = None
    with contextlib.suppress(OSError):
        if not record.is_symlink() and record.is_file():
            payload = record.read_bytes()
    return value, record, payload


def _recovered_position(
    stream: Path, location: GovernanceLocation
) -> tuple[int, int, str, str | None]:
    """Continue from the highest entry whose record still matches; else open a new epoch."""

    entries = chain_entries(stream)
    for epoch, sequence, entry in reversed(entries):
        found = read_chain_entry(stream, entry, location)
        if found is None or found[2] is None:
            continue
        value, _, payload = found
        if hashlib.sha256(payload).hexdigest() == value.get("sha256"):
            return epoch, sequence, str(value["sha256"]), None
    if entries:
        return max(epoch for epoch, _, _ in entries) + 1, 0, ZERO_DIGEST, "head-unreadable"
    return 1, 0, ZERO_DIGEST, None


def _chain_position(
    stream: Path, location: GovernanceLocation
) -> tuple[int, int, str, str | None]:
    try:
        head = _small_json(stream / CHAIN_HEAD_FILE)
    except RecordError:
        head = {}
    if head is None:
        return _recovered_position(stream, location)
    if not _valid_position(head, CHAIN_HEAD_SCHEMA, stream.name):
        epochs = [epoch for epoch, _, _ in chain_entries(stream)]
        return max([1, *epochs]) + 1, 0, ZERO_DIGEST, "head-unreadable"
    return int(head["epoch"]), int(head["sequence"]), str(head["last_sha256"]), None


def read_chain_head(stream: Path) -> dict[str, Any] | None:
    """Return the stream head when it is readable and well formed; ``None`` otherwise."""

    try:
        head = _small_json(stream / CHAIN_HEAD_FILE)
    except RecordError:
        return None
    if head is None or not _valid_position(head, CHAIN_HEAD_SCHEMA, stream.name):
        return None
    return head


def _replace_private(path: Path, payload: bytes, mode: int) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            if not _is_windows():
                os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _record_position(
    stream: Path,
    location: GovernanceLocation,
    destination: Path,
    chain: Mapping[str, Any],
    digest: str,
) -> None:
    """Leave the index entry and the new head; both are working state beside the record."""

    entries = stream / CHAIN_ENTRY_DIRECTORY
    _owned_directory(entries)
    position = {
        "stream_id": stream.name,
        "epoch": chain["epoch"],
        "sequence": chain["sequence"],
    }
    entry = {
        "schema": CHAIN_ENTRY_SCHEMA,
        **position,
        "path": destination.relative_to(location.root).as_posix(),
        "sha256": digest,
    }
    name = f"{int(chain['epoch']):06d}-{int(chain['sequence']):012d}.json"
    _write_once(entries / name, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
    head = {"schema": CHAIN_HEAD_SCHEMA, **position, "last_sha256": digest}
    _replace_private(
        stream / CHAIN_HEAD_FILE,
        (json.dumps(head, sort_keys=True) + "\n").encode("utf-8"),
        RECORD_FILE_MODE,
    )


def _publish_chained(
    location: GovernanceLocation,
    project_id: str,
    destination: Path,
    build: Callable[[dict[str, Any]], bytes],
) -> bool:
    """Write one record with the next link of this user's stream, or with an unavailable link.

    A stream that cannot be used never stops the record: it is written with ``status:
    unavailable`` and a stable reason so the collector can show it.
    """

    identifier = stream_id(project_id)
    try:
        stream = stream_directory(project_id, location=location)
        descriptor = _acquire_stream_lock(stream)
    except RecordError as exc:
        unavailable = {"status": "unavailable", "stream_id": identifier, "reason": exc.code}
        return _write_once(destination, build(unavailable))
    try:
        epoch, sequence, previous, reason = _chain_position(stream, location)
        chain: dict[str, Any] = {
            "status": "linked",
            "stream_id": identifier,
            "epoch": epoch,
            "sequence": sequence + 1,
            "previous_sha256": previous,
        }
        if reason is not None:
            chain["epoch_reason"] = reason
        payload = build(chain)
        if not _write_once(destination, payload):
            return False
        with contextlib.suppress(RecordError, OSError, ValueError):
            _record_position(
                stream, location, destination, chain, hashlib.sha256(payload).hexdigest()
            )
        return True
    finally:
        _release_stream_lock(descriptor)


def _bound_files(run: Path) -> list[dict[str, str]]:
    """Name and digest every evidence file of a run, leaving its working state out."""

    bound = []
    for path in sorted(run.rglob("*.json")):
        relative = path.relative_to(run)
        if (
            relative.parts[0] in UNBOUND_RUN_PARTS
            or any(part.startswith(".") for part in relative.parts)
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RecordError("review-run-file-unreadable") from exc
        bound.append({"name": relative.as_posix(), "sha256": digest})
    return bound


def write_event(
    kind: str,
    project_id: str,
    body: Mapping[str, Any],
    *,
    record_id: str | None = None,
    context: Mapping[str, object] | None = None,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> Path:
    """Write one dated event record under ``<root>/<project_id>/<kind>/<YYYY-MM-DD>/``.

    ``record_id`` lets a producer reuse its own random event token so the record can be found
    again; it must be 32 lowercase hex characters.
    """

    if kind not in DATED_KINDS:
        raise RecordError("record-kind-invalid")
    _require_project_id(project_id)
    if record_id is None:
        record_id = secrets.token_hex(16)
    elif not isinstance(record_id, str) or RECORD_ID_RE.fullmatch(record_id) is None:
        raise RecordError("record-id-invalid")
    moment = _now() if now is None else now
    identifier = record_id

    def build(chain: dict[str, Any]) -> bytes:
        return _encode(
            _envelope(kind, project_id, identifier, body, moment, context, chain),
            MAX_RECORD_BYTES[kind],
        )

    build(dict(SIZE_PROBE_CHAIN))
    selected = resolve_location() if location is None else location
    if kind in CONTENT_GATED_KINDS:
        _content_gate(body, selected)
    day = moment.astimezone(UTC).strftime("%Y-%m-%d")
    directory = _prepare_directory(selected, (project_id, kind, day))
    destination = directory / f"{record_id}.json"
    if not _publish_chained(selected, project_id, destination, build):
        raise RecordError("record-id-collision")
    return destination


def write_addressed(
    kind: str,
    project_id: str,
    address: str,
    body: Mapping[str, Any],
    *,
    context: Mapping[str, object] | None = None,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> tuple[Path, bool]:
    """Publish a content-addressed record; an existing address is kept, never overwritten."""

    if kind not in ADDRESSED_KINDS:
        raise RecordError("record-kind-invalid")
    _require_project_id(project_id)
    if not isinstance(address, str) or ADDRESS_RE.fullmatch(address) is None:
        raise RecordError("record-address-invalid")
    moment = _now() if now is None else now

    def build(chain: dict[str, Any]) -> bytes:
        return _encode(
            _envelope(kind, project_id, address, body, moment, context, chain),
            MAX_RECORD_BYTES[kind],
        )

    build(dict(SIZE_PROBE_CHAIN))
    selected = resolve_location() if location is None else location
    directory = _prepare_directory(selected, (project_id, kind))
    destination = directory / f"{address}.json"
    if destination.exists() or destination.is_symlink():
        return destination, False
    return destination, _publish_chained(selected, project_id, destination, build)


def write_review_run_file(
    project_id: str,
    run_id: str,
    name: str,
    body: Mapping[str, Any],
    *,
    context: Mapping[str, object] | None = None,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> Path:
    """Write one immutable file of a governed-review run under ``governed-review/<run_id>/``."""

    _require_project_id(project_id)
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise RecordError("review-run-id-invalid")
    if not isinstance(name, str) or RUN_FILE_RE.fullmatch(name) is None:
        raise RecordError("review-run-file-invalid")
    moment = _now() if now is None else now
    group = name.split("/", 1)[0]
    limit = MAX_REVIEW_RUN_BYTES.get(group, DEFAULT_REVIEW_RUN_BYTES)
    record_id = f"{run_id}/{name}"
    payload = _encode(
        _envelope(REVIEW_RUN_KIND, project_id, record_id, body, moment, context), limit
    )
    selected = resolve_location() if location is None else location
    parts = (project_id, REVIEW_RUN_KIND, run_id, *name.split("/")[:-1])
    directory = _prepare_directory(selected, parts)
    destination = directory / f"{name.rsplit('/', 1)[-1]}.json"
    if not _write_once(destination, payload):
        raise RecordError("review-run-file-exists")
    return destination


def _read_file(path: Path, limit: int) -> dict[str, Any]:
    try:
        status = path.lstat()
    except FileNotFoundError:
        raise RecordError("record-not-found") from None
    except OSError as exc:
        raise RecordError("record-unreadable") from exc
    if not stat.S_ISREG(status.st_mode) or status.st_size > limit:
        raise RecordError("record-unreadable")
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        record = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordError("record-unreadable") from exc
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise RecordError("record-unreadable")
    return record


def _kind_directory(kind: str, project_id: str, location: GovernanceLocation | None) -> Path:
    _require_project_id(project_id)
    selected = resolve_location() if location is None else location
    directory = selected.root / project_id / kind
    for candidate in (selected.anchor, selected.root, selected.root / project_id, directory):
        if candidate.exists() or candidate.is_symlink():
            _checked_directory(candidate)
    return directory


def read_event(
    kind: str,
    project_id: str,
    record_id: str,
    *,
    location: GovernanceLocation | None = None,
) -> dict[str, Any]:
    """Return one dated event record by its identifier, whatever day it was written."""

    if kind not in DATED_KINDS:
        raise RecordError("record-kind-invalid")
    if not isinstance(record_id, str) or RECORD_ID_RE.fullmatch(record_id) is None:
        raise RecordError("record-id-invalid")
    directory = _kind_directory(kind, project_id, location)
    if not directory.is_dir():
        raise RecordError("record-not-found")
    for day in sorted(directory.iterdir(), reverse=True):
        candidate = day / f"{record_id}.json"
        if not day.is_symlink() and day.is_dir() and (candidate.exists() or candidate.is_symlink()):
            record = _read_file(candidate, MAX_RECORD_BYTES[kind])
            if record.get("record_id") != record_id or record.get("project_id") != project_id:
                raise RecordError("record-unreadable")
            return record
    raise RecordError("record-not-found")


def recent_events(
    kind: str,
    project_id: str,
    *,
    limit: int,
    location: GovernanceLocation | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` readable records, newest first; unreadable files are skipped."""

    if kind not in DATED_KINDS:
        raise RecordError("record-kind-invalid")
    directory = _kind_directory(kind, project_id, location)
    if not directory.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for day in sorted(directory.iterdir(), reverse=True):
        if day.is_symlink() or not day.is_dir():
            continue
        records = []
        for candidate in day.glob("*.json"):
            with contextlib.suppress(RecordError):
                record = _read_file(candidate, MAX_RECORD_BYTES[kind])
                if record.get("project_id") == project_id and record.get("kind") == kind:
                    records.append(record)
        records.sort(key=lambda record: str(record.get("recorded_at")), reverse=True)
        found.extend(records)
        if len(found) >= limit:
            break
    return found[:limit]


def read_addressed(
    kind: str,
    project_id: str,
    address: str,
    *,
    location: GovernanceLocation | None = None,
) -> dict[str, Any]:
    if kind not in ADDRESSED_KINDS:
        raise RecordError("record-kind-invalid")
    if not isinstance(address, str) or ADDRESS_RE.fullmatch(address) is None:
        raise RecordError("record-address-invalid")
    directory = _kind_directory(kind, project_id, location)
    record = _read_file(directory / f"{address}.json", MAX_RECORD_BYTES[kind])
    if record.get("record_id") != address or record.get("project_id") != project_id:
        raise RecordError("record-unreadable")
    return record


STATE_DIRECTORY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def prepare_directory(
    project_id: str, *parts: str, location: GovernanceLocation | None = None
) -> Path:
    """Create ``<root>/<project_id>/<parts...>`` with shared modes for working state files."""

    _require_project_id(project_id)
    if not parts or any(STATE_DIRECTORY_RE.fullmatch(part) is None for part in parts):
        raise RecordError("state-directory-invalid")
    selected = resolve_location() if location is None else location
    return _prepare_directory(selected, (project_id, *parts))


def addressed_records(
    kind: str,
    project_id: str,
    *,
    location: GovernanceLocation | None = None,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Return the content-addressed records of ``kind``; ``strict`` fails on any unreadable one."""

    if kind not in ADDRESSED_KINDS:
        raise RecordError("record-kind-invalid")
    directory = _kind_directory(kind, project_id, location)
    if not directory.is_dir():
        return []
    records = []
    for candidate in sorted(directory.iterdir()):
        if candidate.name.startswith("."):
            continue
        try:
            record = _read_file(candidate, MAX_RECORD_BYTES[kind])
            if (
                candidate.suffix != ".json"
                or record.get("project_id") != project_id
                or record.get("record_id") != candidate.stem
            ):
                raise RecordError("record-unreadable")
        except RecordError:
            if strict:
                raise
            continue
        records.append(record)
    return records


REVIEW_INPUT_DIRECTORIES = ("inputs", "reports", "work")
PUBLICATION_DIRECTORY = "published"


def _require_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise RecordError("review-run-id-invalid")


def review_area(project_id: str, *, location: GovernanceLocation | None = None) -> Path:
    """Return ``<root>/<project_id>/governed-review`` after checking every existing component."""

    return _kind_directory(REVIEW_RUN_KIND, project_id, location)


def prepare_review_run(
    project_id: str, run_id: str, *, location: GovernanceLocation | None = None
) -> Path:
    """Create the run directory; its inputs, reports, decision and receipt come from commands."""

    _require_project_id(project_id)
    _require_run_id(run_id)
    selected = resolve_location() if location is None else location
    run = _prepare_directory(selected, (project_id, REVIEW_RUN_KIND, run_id))
    for name in REVIEW_INPUT_DIRECTORIES:
        _shared_directory(run / name)
    return run


def write_review_report(
    project_id: str,
    run_id: str,
    agent_slug: str,
    payload: bytes,
    *,
    location: GovernanceLocation | None = None,
) -> tuple[Path, bool]:
    """Write one specialist report of a run once; return its path and whether it was created."""

    _require_project_id(project_id)
    _require_run_id(run_id)
    if not isinstance(agent_slug, str) or AGENT_SLUG_RE.fullmatch(agent_slug) is None:
        raise RecordError("review-run-file-invalid")
    if len(payload) > MAX_REVIEW_RUN_BYTES["reports"]:
        raise RecordError("record-too-large")
    selected = resolve_location() if location is None else location
    directory = _prepare_directory(selected, (project_id, REVIEW_RUN_KIND, run_id, "reports"))
    destination = directory / f"{agent_slug}.json"
    return destination, _write_once(destination, payload)


def write_review_artifact(
    project_id: str,
    run_id: str,
    name: str,
    payload: bytes,
    *,
    location: GovernanceLocation | None = None,
) -> tuple[Path, bool]:
    """Write one run input, scan record, decision or receipt once; return path and creation."""

    _require_project_id(project_id)
    _require_run_id(run_id)
    if not isinstance(name, str) or RUN_ARTIFACT_RE.fullmatch(name) is None:
        raise RecordError("review-run-file-invalid")
    if len(payload) > DEFAULT_REVIEW_RUN_BYTES:
        raise RecordError("record-too-large")
    selected = resolve_location() if location is None else location
    parts = (project_id, REVIEW_RUN_KIND, run_id, *name.split("/")[:-1])
    directory = _prepare_directory(selected, parts)
    destination = directory / f"{name.rsplit('/', 1)[-1]}.json"
    return destination, _write_once(destination, payload)


def read_review_run_file(
    project_id: str,
    run_id: str,
    name: str,
    *,
    location: GovernanceLocation | None = None,
) -> tuple[Path, dict[str, Any]]:
    _require_run_id(run_id)
    if not isinstance(name, str) or RUN_FILE_RE.fullmatch(name) is None:
        raise RecordError("review-run-file-invalid")
    group = name.split("/", 1)[0]
    limit = MAX_REVIEW_RUN_BYTES.get(group, DEFAULT_REVIEW_RUN_BYTES)
    path = review_area(project_id, location=location) / run_id / f"{name}.json"
    record = _read_file(path, limit)
    if record.get("record_id") != f"{run_id}/{name}" or record.get("project_id") != project_id:
        raise RecordError("record-unreadable")
    return path, record


def publish_review(
    project_id: str,
    snapshot_sha256: str,
    run_id: str,
    receipt_sha256: str,
    *,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> tuple[Path, bool]:
    """Mark a finalized PASS run as the review of one staged snapshot; never overwrite a mark."""

    _require_project_id(project_id)
    _require_run_id(run_id)
    for value in (snapshot_sha256, receipt_sha256):
        if not isinstance(value, str) or ADDRESS_RE.fullmatch(value) is None:
            raise RecordError("record-address-invalid")
    moment = _now() if now is None else now
    record_id = f"{PUBLICATION_DIRECTORY}/{snapshot_sha256}/{run_id}"
    body = {"run_id": run_id, "snapshot_sha256": snapshot_sha256, "receipt_sha256": receipt_sha256}
    selected = resolve_location() if location is None else location
    run = review_area(project_id, location=selected) / run_id
    bound = _bound_files(run) if run.is_dir() and not run.is_symlink() else []

    def build(chain: dict[str, Any]) -> bytes:
        return _encode(
            _envelope(REVIEW_RUN_KIND, project_id, record_id, body, moment, None, chain, bound),
            DEFAULT_REVIEW_RUN_BYTES,
        )

    build(dict(SIZE_PROBE_CHAIN))
    directory = _prepare_directory(
        selected, (project_id, REVIEW_RUN_KIND, PUBLICATION_DIRECTORY, snapshot_sha256)
    )
    destination = directory / f"{run_id}.json"
    if destination.exists() or destination.is_symlink():
        return destination, False
    return destination, _publish_chained(selected, project_id, destination, build)


def published_reviews(
    project_id: str,
    snapshot_sha256: str,
    *,
    location: GovernanceLocation | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    """Return the publication marks of one staged snapshot, newest first."""

    if not isinstance(snapshot_sha256, str) or ADDRESS_RE.fullmatch(snapshot_sha256) is None:
        raise RecordError("record-address-invalid")
    directory = review_area(project_id, location=location) / PUBLICATION_DIRECTORY / snapshot_sha256
    if directory.is_symlink() or not directory.is_dir():
        return []
    marks = []
    for candidate in directory.glob("*.json"):
        with contextlib.suppress(RecordError):
            record = _read_file(candidate, DEFAULT_REVIEW_RUN_BYTES)
            body = record.get("body")
            if (
                record.get("project_id") == project_id
                and isinstance(body, dict)
                and body.get("snapshot_sha256") == snapshot_sha256
                and body.get("run_id") == candidate.stem
            ):
                marks.append((candidate, record))
    marks.sort(key=lambda item: str(item[1].get("recorded_at")), reverse=True)
    return marks


# Periodic authority sync and device stop (Engineering Governance capability 003).  One directory
# per operating-system user holds the projects the prompt hook registered, the device stop state
# the hooks read before any other check, and the write-once events of the sync script and of
# refusing hooks.  Other users can read it but not write into it.
SYNC_DIRECTORY = "authority-sync"
SYNC_KIND = "authority-sync"
SYNC_STATE_SCHEMA = "kt-authority-sync-state/v1"
SYNC_PROJECT_SCHEMA = "kt-authority-sync-project/v1"
USER_DIRECTORY_MODE = 0o755
MAX_SYNC_STATE_BYTES = 64 * 1024
MAX_SYNC_PROJECT_BYTES = 8 * 1024
MAX_SYNC_EVENT_BYTES = 64 * 1024
MAX_SYNC_PROJECTS = 256
DEVICE_STATES = ("running", "stopped", "unknown")
# Jamf deploys this managed preference file; its presence marks a managed AI Lab Mac.
MANAGED_PREFERENCES = Path("/Library/Managed Preferences/com.kuveytturk.kt-scaffold.plist")
SYNC_EVENT_KEYS = frozenset(
    {
        "event",
        "hook",
        "client",
        "device_id",
        "state",
        "previous_state",
        "reason_code",
        "generation",
        "outcome",
        "paths",
        "authority_generation",
        "local_authority_generation",
    }
)
SYNC_PATH_KEYS = frozenset({"path", "sha256", "source", "result"})
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
DEVICE_STOP_MARKER = "KT_DEVICE_STOPPED"
DEVICE_UNVERIFIED_MARKER = "KT_DEVICE_STATE_UNVERIFIED"
# Person-facing refusals follow rules/02-iletisim-tarzi.md: no path, mechanism or reason code.
DEVICE_STOP_MESSAGE = (
    "Bu bilgisayarda yapay zekâ asistanıyla çalışma kurum tarafından durduruldu. Yeni mesaj "
    "gönderilemez, komut çalıştırılamaz ve dosya yazılamaz. Bilgi için bilgi güvenliği ekibine "
    "başvurun."
)
DEVICE_UNVERIFIED_MESSAGE = (
    "Bu bilgisayarda yapay zekâ asistanıyla çalışmanın açık olduğu şu an doğrulanamadı. Birkaç "
    "dakika içinde kendiliğinden yeniden denenir; sorun sürerse bilgi güvenliği ekibine başvurun."
)
DEVICE_UNVERIFIED_WARNING = (
    "KT_DEVICE_STATE_UNVERIFIED: Bu bilgisayarın kurum durdurma durumu bir süredir denetlenemedi; "
    "mesaj gönderildi. Sorun sürerse proje fabrikası ekibine bildirin."
)
# An unmanaged device warns only when the periodic sync has not written a state this long after
# the project was registered, which means the scheduled task is not running.
UNSYNCED_WARNING_AFTER_SECONDS = 15 * 60
UPDATE_PENDING_NOTICE = (
    "KT_GOVERNANCE_UPDATE_PENDING: Bu proje için yönetişim kurallarının yeni sürümü yayımlandı. "
    "Asistandan projeyi proje fabrikası bağlantısındaki proje_iskelesini_esitle aracıyla "
    "güncellemesini isteyin."
)


def user_identity() -> str:
    """The operating-system user: the numeric uid, or the Windows ``domain\\user`` account."""

    if os.name == "posix":
        return f"uid:{os.geteuid()}"
    domain = os.environ.get("USERDOMAIN", "")
    return "account:" + f"{domain}\\{getpass.getuser()}".casefold()


def user_key() -> str:
    """A path-safe digest of the user; the raw name never appears in a path."""

    return hashlib.sha256(f"kt-scaffold-user\0{user_identity()}".encode()).hexdigest()


def _owned_by_user(status: os.stat_result) -> bool:
    return _is_windows() or status.st_uid == os.geteuid()


def _user_directory(path: Path) -> None:
    """Create ``path`` for this user only, or accept an existing real directory the user owns."""

    try:
        path.mkdir(mode=USER_DIRECTORY_MODE)
    except FileExistsError:
        pass
    except OSError as exc:
        raise RecordError("root-not-writable") from exc
    try:
        status = path.lstat()
    except OSError as exc:
        raise RecordError("root-unavailable") from exc
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise RecordError("root-path-unsafe")
    if not _owned_by_user(status):
        raise RecordError("sync-directory-foreign")
    if not _is_windows() and stat.S_IMODE(status.st_mode) != USER_DIRECTORY_MODE:
        try:
            # Contract mode 0755: only the owner writes; the rule flags every usable directory.
            os.chmod(path, USER_DIRECTORY_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        except OSError as exc:
            raise RecordError("root-not-writable") from exc


def sync_directory(
    *parts: str, location: GovernanceLocation | None = None, create: bool = True
) -> Path:
    """Return ``<root>/authority-sync/<user-key>/<parts...>``, created for this user on demand."""

    selected = resolve_location() if location is None else location
    if any(STATE_DIRECTORY_RE.fullmatch(part) is None for part in parts):
        raise RecordError("state-directory-invalid")
    base = selected.root / SYNC_DIRECTORY / user_key()
    if not create:
        return base.joinpath(*parts)
    shared = _prepare_directory(selected, (SYNC_DIRECTORY,))
    current = shared / user_key()
    _user_directory(current)
    for part in parts:
        current = current / part
        _user_directory(current)
    return current


def _replace_owned(destination: Path, payload: bytes) -> None:
    """Atomically replace a working state file inside this user's sync directory."""

    temporary = destination.parent / f".{destination.name}.{secrets.token_hex(16)}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, RECORD_FILE_MODE)
    except OSError as exc:
        raise RecordError("root-not-writable") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise RecordError("root-path-unsafe")
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except OSError as exc:
        raise RecordError("record-write-failed") from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _read_owned_json(path: Path, limit: int) -> dict[str, Any] | None:
    """A regular JSON object file owned by this user, or ``None`` for anything else."""

    try:
        status = path.lstat()
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_size > limit
            or not _owned_by_user(status)
            or not _owned_by_user(path.parent.lstat())
        ):
            return None
        with path.open("rb") as handle:
            value = json.loads(handle.read(limit + 1).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _utc_text(moment: datetime | None = None) -> str:
    selected = _now() if moment is None else moment
    return selected.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _valid_sync_state(state: object) -> bool:
    if not isinstance(state, dict) or state.get("schema") != SYNC_STATE_SCHEMA:
        return False
    authority = state.get("authority")
    projects = state.get("projects")
    reason = state.get("reason_code")
    return (
        state.get("state") in DEVICE_STATES
        and (reason is None or (isinstance(reason, str) and bool(REASON_CODE_RE.match(reason))))
        and isinstance(authority, dict)
        and authority.get("state") in DEVICE_STATES
        and isinstance(authority.get("generation"), int)
        and not isinstance(authority.get("generation"), bool)
        and authority["generation"] >= 0
        and isinstance(projects, dict)
        and len(projects) <= MAX_SYNC_PROJECTS
        and all(PROJECT_ID_RE.fullmatch(str(key)) for key in projects)
        and all(isinstance(value, dict) for value in projects.values())
    )


def read_sync_state(*, location: GovernanceLocation | None = None) -> dict[str, Any] | None:
    """This user's sync state, or ``None`` when it is missing, unreadable, foreign or malformed."""

    try:
        path = sync_directory(location=location, create=False) / "state.json"
    except RecordError:
        return None
    state = _read_owned_json(path, MAX_SYNC_STATE_BYTES)
    return state if _valid_sync_state(state) else None


def write_sync_state(state: Mapping[str, Any], *, location: GovernanceLocation | None = None) -> Path:
    candidate = dict(state)
    candidate["schema"] = SYNC_STATE_SCHEMA
    if not _valid_sync_state(candidate):
        raise RecordError("record-invalid")
    payload = _encode(candidate, MAX_SYNC_STATE_BYTES)
    destination = sync_directory(location=location) / "state.json"
    _replace_owned(destination, payload)
    return destination


def device_gate(
    *,
    location: GovernanceLocation | None = None,
    managed_preferences: Path | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Decide from the local state alone: ``stop``, ``unverified``, ``allow-warn`` or ``allow``.

    A managed (Jamf) device without a readable state refuses; any other device only warns.  No
    network, model or authority call happens here.
    """

    state = read_sync_state(location=location)
    if state is not None:
        return ("stop" if state["state"] == "stopped" else "allow"), state
    return ("unverified" if managed_device(managed_preferences) else "allow-warn"), None


def managed_device(managed_preferences: Path | None = None) -> bool:
    """Whether this is a Jamf-managed AI Lab Mac: the one device test every gate shares.

    Jamf deploys the managed preference file only there; a file that cannot even be checked counts
    as managed so the stricter decision applies.
    """

    managed = MANAGED_PREFERENCES if managed_preferences is None else managed_preferences
    try:
        return managed.is_file()
    except OSError:
        return True


def gate_message(decision: str, *, marker: bool) -> str:
    """The fixed person-facing refusal; hooks speaking to an Agent prefix the stable marker."""

    if decision == "stop":
        prefix, text = DEVICE_STOP_MARKER, DEVICE_STOP_MESSAGE
    else:
        prefix, text = DEVICE_UNVERIFIED_MARKER, DEVICE_UNVERIFIED_MESSAGE
    return f"{prefix}: {text}" if marker else text


# A client-local file can switch off or relocate the project's hooks and rules, or add an
# instruction file the generator does not own, without touching any recorded managed file.  The
# commit gate and the governed review check these files; a managed device stops, any other device
# only warns.  The project's CI stops on any device: a committed file reaches every developer.
LOCAL_OVERRIDE_MARKER = "LOCAL_CLIENT_OVERRIDE"
LOCAL_OVERRIDE_WARNING_MARKER = "LOCAL_CLIENT_OVERRIDE_WARNING"
MAX_LOCAL_SETTINGS_BYTES = 1024 * 1024
MAX_LOCAL_OVERRIDE_LINES = 10
# Instruction files the clients load from any directory: Codex and VS Code nested AGENTS.md and
# AGENTS.override.md, Claude Code nested CLAUDE.md and CLAUDE.local.md.
INSTRUCTION_FILE_NAMES = frozenset({"agents.md", "agents.override.md", "claude.md", "claude.local.md"})
# Instruction files and folders the clients load only from the project root.
ROOT_INSTRUCTION_FILES = (".cursorrules", ".claude/CLAUDE.md", ".github/copilot-instructions.md")
ROOT_INSTRUCTION_DIRECTORIES = (".claude/output-styles", ".github/prompts", ".github/chatmodes")
# Client folders: at the root they are governed or checked file by file; below it a session
# started there reads them instead of the project's hooks and rules.
CLIENT_DIRECTORY_NAMES = frozenset({".agents", ".claude", ".codex", ".cursor"})
ROOT_CHECKED_DIRECTORY_NAMES = CLIENT_DIRECTORY_NAMES.union({".github", ".vscode"})
# Dependency and tool caches are never a client's working directory.
LOCAL_SCAN_SKIPPED_NAMES = frozenset(
    {
        ".git",
        ".kt-scaffold",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
CLAUDE_LOCAL_SETTINGS = ".claude/settings.local.json"
COPILOT_SETTINGS_FILES = (".github/copilot/settings.json", ".github/copilot/settings.local.json")
VSCODE_SETTINGS = ".vscode/settings.json"
# Claude Code: hooks that only announce something cannot approve, deny or rewrite a step.
CLAUDE_NOTICE_HOOK_EVENTS = frozenset({"Notification"})
CLAUDE_BUILT_IN_OUTPUT_STYLES = frozenset({"default", "explanatory", "learning"})
CLAUDE_BYPASS_PERMISSION_MODES = frozenset({"auto", "bypassPermissions"})
# Variables that decide which interpreter, project, home folder or Git hooks a hook sees.
HOOK_ENVIRONMENT_NAMES = frozenset(
    {"claude_config_dir", "claude_project_dir", "home", "path", "userprofile"}
)
HOOK_ENVIRONMENT_PREFIXES = ("git_", "kt_", "python")
VSCODE_LOCATION_SETTINGS = (
    "chat.agentFilesLocations",
    "chat.agentSkillsLocations",
    "chat.hookFilesLocations",
    "chat.instructionsFilesLocations",
    "chat.modeFilesLocations",
    "chat.promptFilesLocations",
)
VSCODE_INLINE_INSTRUCTION_SETTINGS = (
    "github.copilot.chat.codeGeneration.instructions",
    "github.copilot.chat.testGeneration.instructions",
)

LOCAL_REASON_UNREADABLE = (
    "dosya okunamıyor ya da biçimi bozuk; içeriği denetlenemediği için yönetişimi atlatan ayar "
    "sayılır"
)
LOCAL_REASON_LINK = "sembolik bağlantı; gösterdiği içerik denetlenemez"
LOCAL_REASON_INSTRUCTION = "projenin yönetmediği talimat dosyası; asistan bunu proje kuralı gibi okur"
LOCAL_REASON_NESTED_CLIENT = (
    "alt klasördeki asistan ayar klasörü; asistan bu klasörden başlatılırsa projenin kuralları ve "
    "kancaları yerine bunlar kullanılır"
)


def _child(directory: Path, name: str) -> Path | None:
    """The entry named ``name`` in any letter case: macOS and Windows open it under either case."""

    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    wanted = name.casefold()
    for entry in sorted(entries):
        if entry.casefold() == wanted:
            return directory / entry
    return None


def _project_entry(root: Path, relative: str) -> Path | None:
    """The existing entry at ``relative``; a symbolic link on the way is returned in its place."""

    current = root
    for part in relative.split("/"):
        if current != root and current.is_symlink():
            return current
        if current != root and not current.is_dir():
            return None
        child = _child(current, part)
        if child is None:
            return None
        current = child
    return current


def _owned_paths(root: Path) -> set[str] | None:
    """Every path the generator writes: managed files and recorded application seeds."""

    try:
        manifest = root / ".kt-scaffold" / "manifest.json"
        if manifest.is_symlink():
            return None
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("managed"), dict):
        return None
    seed = payload.get("application_seed")
    return set(payload["managed"]) | (set(seed) if isinstance(seed, dict) else set())


def _without_json_comments(text: str) -> str:
    """VS Code settings allow comments and trailing commas; strip both outside strings."""

    output: list[str] = []
    index, length, in_string = 0, len(text), False
    while index < length:
        character = text[index]
        if in_string:
            output.append(character)
            if character == "\\" and index + 1 < length:
                output.append(text[index + 1])
                index += 1
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
            output.append(character)
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end < 0 else end
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        else:
            output.append(character)
        index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(output))


def _settings_object(path: Path, *, comments: bool) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_LOCAL_SETTINGS_BYTES:
            return None
        text = path.read_text(encoding="utf-8-sig")
        payload = json.loads(_without_json_comments(text) if comments else text)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _hook_environment_name(name: object) -> bool:
    folded = str(name).casefold()
    return folded in HOOK_ENVIRONMENT_NAMES or folded.startswith(HOOK_ENVIRONMENT_PREFIXES)


def _claude_settings_reasons(settings: Mapping[str, Any]) -> list[str]:
    """Keys of a Claude Code local settings file that weaken the project's hooks or rules.

    Local settings win over the project file for single values and add to lists.  A permission
    ``allow`` list stays harmless because project ``ask`` and ``deny`` rules still win over it.
    """

    reasons: list[str] = []
    if "disableAllHooks" in settings and settings["disableAllHooks"] is not False:
        reasons.append("disableAllHooks bütün kancaları (kendiliğinden çalışan denetimleri) kapatıyor")
    hooks = settings.get("hooks")
    if "hooks" in settings and (
        not isinstance(hooks, dict) or any(event not in CLAUDE_NOTICE_HOOK_EVENTS for event in hooks)
    ):
        reasons.append("hooks projenin yönetmediği bir kanca ekliyor ya da değiştiriyor")
    if settings.get("claudeMdExcludes"):
        reasons.append("claudeMdExcludes proje kurallarının bir kısmının yüklenmesini engelliyor")
    plugins = settings.get("enabledPlugins")
    if plugins and (not isinstance(plugins, dict) or any(plugins.values())):
        reasons.append("enabledPlugins projenin yönetmediği eklenti açıyor")
    if settings.get("skillOverrides"):
        reasons.append("skillOverrides proje becerilerini gizliyor ya da değiştiriyor")
    if settings.get("agent"):
        reasons.append("agent asistanı projenin yönetmediği bir ajan talimatıyla başlatıyor")
    style = settings.get("outputStyle")
    if "outputStyle" in settings and (
        not isinstance(style, str) or style.casefold() not in CLAUDE_BUILT_IN_OUTPUT_STYLES
    ):
        reasons.append("outputStyle asistanın talimatını projenin yönetmediği bir biçimle değiştiriyor")
    permissions = settings.get("permissions")
    if isinstance(permissions, dict) and permissions.get("defaultMode") in CLAUDE_BYPASS_PERMISSION_MODES:
        reasons.append("permissions.defaultMode izin sorularını atlayan bir çalışma kipi açıyor")
    elif "permissions" in settings and not isinstance(permissions, dict):
        reasons.append("permissions alanının biçimi bozuk")
    reasons.extend(_environment_reasons(settings))
    return reasons


def _environment_reasons(settings: Mapping[str, Any]) -> list[str]:
    environment = settings.get("env")
    if "env" not in settings:
        return []
    if not isinstance(environment, dict):
        return ["env alanının biçimi bozuk"]
    names = sorted(str(name) for name in environment if _hook_environment_name(name))
    if not names:
        return []
    return [f"env kancaların çalıştığı ortamı değiştiriyor: {', '.join(names)}"]


def _copilot_settings_reasons(settings: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if "disableAllHooks" in settings and settings["disableAllHooks"] is not False:
        reasons.append("disableAllHooks bütün kancaları (kendiliğinden çalışan denetimleri) kapatıyor")
    if settings.get("hooks") or ("hooks" in settings and not isinstance(settings["hooks"], dict)):
        reasons.append("hooks projenin yönetmediği bir kanca ekliyor ya da değiştiriyor")
    return reasons


def _vscode_settings_reasons(settings: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if "chat.useHooks" in settings and settings["chat.useHooks"] is not True:
        reasons.append("chat.useHooks VS Code'da kancaları kapatıyor")
    if "chat.useAgentsMdFile" in settings and settings["chat.useAgentsMdFile"] is not True:
        reasons.append("chat.useAgentsMdFile AGENTS.md proje kurallarının yüklenmesini kapatıyor")
    for key in VSCODE_LOCATION_SETTINGS:
        if key in settings:
            reasons.append(f"{key} kanca ya da talimat dosyalarının yerini değiştiriyor")
    if settings.get("chat.useCustomizationsInParentRepositories"):
        reasons.append(
            "chat.useCustomizationsInParentRepositories üst depodan talimat ve kanca yüklüyor"
        )
    for key in VSCODE_INLINE_INSTRUCTION_SETTINGS:
        if settings.get(key):
            reasons.append(f"{key} ayar içinde projenin yönetmediği talimat ekliyor")
    return reasons


def _settings_findings(
    root: Path, relative: str, check: Callable[[Mapping[str, Any]], list[str]], *, comments: bool
) -> list[tuple[str, str]]:
    path = _project_entry(root, relative)
    if path is None:
        return []
    shown = path.relative_to(root).as_posix()
    if path.is_symlink():
        return [(shown, LOCAL_REASON_LINK)]
    settings = _settings_object(path, comments=comments)
    if settings is None:
        return [(shown, LOCAL_REASON_UNREADABLE)]
    return [(shown, reason) for reason in check(settings)]


def _workspace_findings(root: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return [(".", LOCAL_REASON_UNREADABLE)]
    for name in names:
        if not name.casefold().endswith(".code-workspace"):
            continue
        path = root / name
        if path.is_symlink():
            findings.append((name, LOCAL_REASON_LINK))
            continue
        workspace = _settings_object(path, comments=True)
        settings = workspace.get("settings", {}) if workspace is not None else None
        if not isinstance(settings, dict):
            findings.append((name, LOCAL_REASON_UNREADABLE))
            continue
        findings.extend((name, reason) for reason in _vscode_settings_reasons(settings))
    return findings


def _unowned_files(root: Path, directory: Path, owned: set[str]) -> list[str]:
    found: list[str] = []
    for current, directories, files in os.walk(directory):
        directories.sort()
        for name in sorted(files) + [entry for entry in directories if (Path(current) / entry).is_symlink()]:
            relative = (Path(current) / name).relative_to(root).as_posix()
            if relative not in owned:
                found.append(relative)
    return found


def _tree_findings(root: Path, owned: set[str]) -> list[tuple[str, str]]:
    """Instruction files anywhere and client folders below the root that the generator does not own."""

    findings: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root):
        here = Path(current)
        at_root = here == root
        kept: list[str] = []
        for name in sorted(directories):
            folded = name.casefold()
            if folded in LOCAL_SCAN_SKIPPED_NAMES or (at_root and folded in ROOT_CHECKED_DIRECTORY_NAMES):
                continue
            path = here / name
            if folded in CLIENT_DIRECTORY_NAMES:
                if path.is_symlink() or _unowned_files(root, path, owned):
                    findings.append((path.relative_to(root).as_posix(), LOCAL_REASON_NESTED_CLIENT))
                continue
            kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            if name.casefold() not in INSTRUCTION_FILE_NAMES:
                continue
            relative = (here / name).relative_to(root).as_posix()
            if relative not in owned:
                findings.append((relative, LOCAL_REASON_INSTRUCTION))
    return findings


def local_client_overrides(root: Path) -> list[tuple[str, str]]:
    """Client-local files of this project that bypass governance, as ``(path, reason)`` pairs.

    Reads only the project tree: no network, model or authority call.  Root client folders are
    governed by the drift check; here they are checked only for the files it does not cover.
    """

    owned = _owned_paths(root)
    if owned is None:
        return [(".kt-scaffold/manifest.json", LOCAL_REASON_UNREADABLE)]
    findings = _tree_findings(root, owned)
    for relative in ROOT_INSTRUCTION_FILES:
        path = _project_entry(root, relative)
        if path is not None and path.relative_to(root).as_posix() not in owned:
            reason = LOCAL_REASON_LINK if path.is_symlink() else LOCAL_REASON_INSTRUCTION
            findings.append((path.relative_to(root).as_posix(), reason))
    for relative in ROOT_INSTRUCTION_DIRECTORIES:
        path = _project_entry(root, relative)
        if path is None:
            continue
        if path.is_symlink() or not path.is_dir():
            reason = LOCAL_REASON_LINK if path.is_symlink() else LOCAL_REASON_INSTRUCTION
            findings.append((path.relative_to(root).as_posix(), reason))
            continue
        findings.extend((item, LOCAL_REASON_INSTRUCTION) for item in _unowned_files(root, path, owned))
    findings.extend(
        _settings_findings(root, CLAUDE_LOCAL_SETTINGS, _claude_settings_reasons, comments=False)
    )
    for relative in COPILOT_SETTINGS_FILES:
        findings.extend(
            _settings_findings(root, relative, _copilot_settings_reasons, comments=False)
        )
    findings.extend(
        _settings_findings(root, VSCODE_SETTINGS, _vscode_settings_reasons, comments=True)
    )
    findings.extend(_workspace_findings(root))
    return sorted(set(findings))


def local_override_message(
    findings: list[tuple[str, str]], *, blocking: bool, ci: bool = False
) -> str:
    """The person-facing notice: what was found, and how to remove it.

    ``ci`` names the project's CI check, which stops whatever the device is.
    """

    if ci:
        head = (
            f"{LOCAL_OVERRIDE_MARKER}: yapay zekâ asistanının yerel ayarı proje yönetişimini "
            "(kuralları ve kancaları, yani kendiliğinden çalışan denetimleri) atlatıyor ve bu "
            "ayar projeye kaydedilmiş (commit edilmiş). Kaydedilen dosya projenin bütün "
            "geliştiricilerine ulaştığı için CI denetimi (her değişiklikte projeyi sunucuda "
            "kendiliğinden denetleyen iş) durduruldu."
        )
    elif blocking:
        head = (
            f"{LOCAL_OVERRIDE_MARKER}: yapay zekâ asistanının bu projedeki yerel ayarı proje "
            "yönetişimini (kuralları ve kancaları, yani kendiliğinden çalışan denetimleri) "
            "atlatıyor. Bu bilgisayar kurum tarafından yönetildiği için commit (değişikliği "
            "proje geçmişine kaydetme) ve yönetilen inceleme durduruldu."
        )
    else:
        head = (
            f"{LOCAL_OVERRIDE_WARNING_MARKER}: yapay zekâ asistanının bu projedeki yerel ayarı "
            "proje yönetişimini (kuralları ve kancaları, yani kendiliğinden çalışan denetimleri) "
            "atlatıyor. Bu bilgisayar kurum tarafından yönetilmediği için yalnız uyarılıyor; "
            "kurumun yönettiği bilgisayarda aynı durum commit'i ve yönetilen incelemeyi durdurur. "
            "Dosya projeye kaydedilirse (commit edilirse) projenin CI denetimi (her değişiklikte "
            "projeyi sunucuda kendiliğinden denetleyen iş) de durur."
        )
    lines = [head]
    lines.extend(f"- {path}: {reason}" for path, reason in findings[:MAX_LOCAL_OVERRIDE_LINES])
    if len(findings) > MAX_LOCAL_OVERRIDE_LINES:
        lines.append(f"- ve {len(findings) - MAX_LOCAL_OVERRIDE_LINES} bulgu daha")
    lines.append(
        "Ne yapmalı: listelenen dosyayı sil ya da dosyada adı geçen ayarı çıkar; bu değişikliği "
        "asistana değil kendin yap. Yönetişime dokunmayan kişisel ayarlar (ör. izin listesi, model "
        "seçimi, bildirim) kalabilir. Kalıcı bir talimat gerekiyorsa proje kuralı olarak "
        "eklenmesini fabrika ekibinden iste. Denetimi silerek ya da --no-verify ile atlayarak "
        "bulgu kapatılmaz."
    )
    return "\n".join(lines)


def update_pending(state: Mapping[str, Any] | None, project_id: str) -> bool:
    if state is None:
        return False
    project = state.get("projects", {}).get(project_id)
    return isinstance(project, dict) and project.get("update_pending") is True


def _sync_body(body: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the bounded metadata fields only: paths, digests and outcomes, never file content."""

    if not isinstance(body, Mapping) or set(body) - SYNC_EVENT_KEYS:
        raise RecordError("record-invalid")
    paths = body.get("paths")
    if paths is not None and (
        not isinstance(paths, list)
        or any(not isinstance(item, Mapping) or set(item) - SYNC_PATH_KEYS for item in paths)
    ):
        raise RecordError("record-invalid")
    return dict(body)


def write_sync_event(
    body: Mapping[str, Any],
    *,
    project_id: str | None = None,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> Path:
    """Write one sync, restore, device-state or hook-refusal event once under ``events/<day>/``."""

    if project_id is not None:
        _require_project_id(project_id)
    moment = _now() if now is None else now
    record_id = secrets.token_hex(16)
    envelope = _envelope(SYNC_KIND, "", record_id, _sync_body(body), moment, None)
    envelope["project_id"] = project_id
    payload = _encode(envelope, MAX_SYNC_EVENT_BYTES)
    day = moment.astimezone(UTC).strftime("%Y-%m-%d")
    directory = sync_directory("events", day, location=location)
    destination = directory / f"{record_id}.json"
    if not _write_once(destination, payload):
        raise RecordError("record-id-collision")
    return destination


def record_refusal(
    hook: str,
    decision: str,
    *,
    client: str | None = None,
    project_id: str | None = None,
    location: GovernanceLocation | None = None,
) -> str | None:
    """Record a stop refusal; return a warning code instead of failing the refusal itself."""

    try:
        write_sync_event(
            {
                "event": "hook-refused",
                "hook": hook,
                "client": client,
                "outcome": "stopped" if decision == "stop" else "unverified",
            },
            project_id=project_id,
            location=location,
        )
    except RecordError as exc:
        return exc.code
    except Exception:
        return "record-write-failed"
    return None


def register_project(
    project_id: str, workspace_root: Path, *, location: GovernanceLocation | None = None
) -> bool:
    """Name this project's root for the sync script; rewrite only when the record changes."""

    _require_project_id(project_id)
    record = {
        "schema": SYNC_PROJECT_SCHEMA,
        "project_id": project_id,
        "workspace_root": str(workspace_root),
    }
    current = registered_project(project_id, location=location)
    if current is not None and current == Path(record["workspace_root"]):
        return False
    payload = _encode(record, MAX_SYNC_PROJECT_BYTES)
    destination = sync_directory("projects", location=location) / f"{project_id}.json"
    _replace_owned(destination, payload)
    return True


def registered_project(
    project_id: str, *, location: GovernanceLocation | None = None
) -> Path | None:
    try:
        path = sync_directory("projects", location=location, create=False) / f"{project_id}.json"
    except RecordError:
        return None
    record = _read_owned_json(path, MAX_SYNC_PROJECT_BYTES)
    if (
        record is None
        or record.get("schema") != SYNC_PROJECT_SCHEMA
        or record.get("project_id") != project_id
        or not isinstance(record.get("workspace_root"), str)
    ):
        return None
    root = Path(record["workspace_root"])
    return root if root.is_absolute() else None


def registered_projects(*, location: GovernanceLocation | None = None) -> list[tuple[str, Path]]:
    """The projects this user registered, in name order; unreadable records are skipped."""

    directory = sync_directory("projects", location=location, create=False)
    if directory.is_symlink() or not directory.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for candidate in sorted(directory.glob("project-*.json"))[:MAX_SYNC_PROJECTS]:
        project_id = candidate.name[: -len(".json")]
        if PROJECT_ID_RE.fullmatch(project_id) is None:
            continue
        root = registered_project(project_id, location=location)
        if root is not None:
            found.append((project_id, root))
    return found


def unsynced_too_long(
    project_id: str,
    *,
    location: GovernanceLocation | None = None,
    now: datetime | None = None,
) -> bool:
    """Whether the project was registered long enough ago that a sync state should exist."""

    try:
        path = sync_directory("projects", location=location, create=False) / f"{project_id}.json"
        status = path.lstat()
    except (RecordError, OSError):
        return False
    moment = (_now() if now is None else now).timestamp()
    return moment - status.st_mtime > UNSYNCED_WARNING_AFTER_SECONDS


def forget_project(project_id: str, *, location: GovernanceLocation | None = None) -> None:
    _require_project_id(project_id)
    path = sync_directory("projects", location=location, create=False) / f"{project_id}.json"
    with contextlib.suppress(FileNotFoundError):
        if not path.is_symlink() and path.is_file():
            path.unlink()


def profile_python_minimum(project_root: Path) -> str | None:
    """The oldest `major.minor` Python series the technology profile accepts.

    Every later release, including a later series, is accepted; the profile names no patch floor
    and no upper bound.
    """
    profile = project_root / "technology-profile.yml"
    try:
        if profile.is_symlink() or not profile.is_file():
            return None
        text = profile.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    in_backend = False
    for line in text.splitlines():
        if line and not line[0].isspace():
            in_backend = line.rstrip() == "backend:"
            continue
        match = re.fullmatch(r"\s+minimum_language_version:\s*\"(\d+\.\d+)\"\s*", line)
        if in_backend and match:
            return match.group(1)
    return None


def python_meets_minimum(series: tuple[int, int], minimum: str) -> bool:
    """Whether an interpreter's `(major, minor)` is at or above the profile's oldest series."""
    major, minor = (int(part) for part in minimum.split("."))
    return series >= (major, minor)


PYTHON_ENVIRONMENT_SCRIPT = ".kt-scaffold/hooks/python_environment.py"


def repair_command(minimum: str) -> str:
    """The one project-root command that prepares `.venv` on an accepted Python."""
    script = PYTHON_ENVIRONMENT_SCRIPT
    return (
        f"python3 {script} hazirla (Python {minimum} veya daha yenisi; "
        f"Windows: py -3 {script} hazirla)"
    )


def venv_interpreter(project_root: Path) -> Path:
    if _is_windows():
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


REEXEC_MARKER = "KT_SCAFFOLD_PROFILE_INTERPRETER"
# Variables that make an interpreter load code or a standard library from outside the project's
# `.venv`, or run code the hook did not ask for; the profile interpreter starts without them.
INTERPRETER_STEERING_VARIABLES = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTHONPLATLIBDIR",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONEXECUTABLE",
        "__PYVENV_LAUNCHER__",
    }
)


def profile_interpreter_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """The client's environment for the ``.venv`` interpreter, without interpreter steering.

    Every other variable, including the client's hook context, passes unchanged; the marker stops
    a second move.
    """

    selected = {
        key: value
        for key, value in environment.items()
        if key.upper() not in INTERPRETER_STEERING_VARIABLES
    }
    selected[REEXEC_MARKER] = "1"
    return selected


def ensure_profile_interpreter(
    project_root: Path, script: Path, arguments: list[str]
) -> str | None:
    """Run the entry point on an accepted Python, moving once into the project's ``.venv``.

    Returns ``None`` when the running interpreter is at or above the technology profile's oldest
    accepted series. Otherwise it replaces the process with ``.venv`` when that exists, or
    returns ``python-runtime-mismatch`` so a gate can refuse and an observation hook can warn.
    """

    minimum = profile_python_minimum(project_root)
    running = (sys.version_info.major, sys.version_info.minor)
    if minimum is not None and python_meets_minimum(running, minimum):
        return None
    interpreter = venv_interpreter(project_root)
    # A POSIX `.venv` interpreter is normally a link to its base Python; follow it once.
    if minimum is not None and os.environ.get(REEXEC_MARKER) != "1" and interpreter.is_file():
        environment = profile_interpreter_environment(os.environ)
        # Same script on the profile Python: fixed program and argv, the client's hook environment.
        os.execve(  # noqa: S606  # nosemgrep: python.lang.security.audit.dangerous-os-exec-tainted-env-args.dangerous-os-exec-tainted-env-args
            str(interpreter), [str(interpreter), str(script), *arguments], environment
        )
    return "python-runtime-mismatch"


def repository_status(project_root: Path) -> str:
    """Report whether the project sits in a Git work tree with a commit; change nothing."""

    executable = shutil.which("git")
    if executable is None:
        return "git-unavailable"
    environment = {
        key: value for key, value in os.environ.items() if key not in GIT_LOCATION_VARIABLES
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"

    def succeeds(*arguments: str) -> bool:
        completed = subprocess.run(
            [executable, "-C", str(project_root), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
        return completed.returncode == 0 and completed.stdout.strip() != b"false"

    try:
        if not succeeds("rev-parse", "--is-inside-work-tree"):
            return "not-a-repository"
        if not succeeds("rev-parse", "--verify", "--quiet", "HEAD"):
            return "no-commit"
    except (OSError, subprocess.SubprocessError):
        return "git-unavailable"
    return "ok"


def preflight(project_root: Path, location: GovernanceLocation | None = None) -> dict[str, Any]:
    """Report the root, its writability, the interpreter match and the project's Git state.

    It reads no record and changes nothing.
    """

    try:
        selected = resolve_location() if location is None else location
    except RecordError as exc:
        return {"ok": False, "root": None, "root_status": exc.code}
    root_status = "ok"
    try:
        _checked_directory(selected.anchor)
        if selected.root.exists() or selected.root.is_symlink():
            _checked_directory(selected.root)
            if not os.access(selected.root, os.W_OK | os.X_OK):
                root_status = "root-not-writable"
        elif not os.access(selected.anchor, os.W_OK | os.X_OK):
            root_status = "root-not-writable"
    except RecordError as exc:
        root_status = exc.code
    minimum = profile_python_minimum(project_root)
    series = (sys.version_info.major, sys.version_info.minor)
    running = f"{series[0]}.{series[1]}"
    interpreter = venv_interpreter(project_root)
    interpreter_status = "ok"
    if minimum is None:
        interpreter_status = "profile-unavailable"
    elif not interpreter.is_file():
        interpreter_status = "venv-missing"
    elif not python_meets_minimum(series, minimum):
        interpreter_status = "python-runtime-mismatch"
    repository = repository_status(project_root)
    return {
        "ok": root_status == "ok" and interpreter_status == "ok" and repository == "ok",
        "root": str(selected.root),
        "root_status": root_status,
        "profile_python_minimum": minimum,
        "running_python": running,
        "venv_interpreter": str(interpreter),
        "interpreter_status": interpreter_status,
        "repository_status": repository,
    }


def main(arguments: list[str] | None = None) -> int:
    selected = sys.argv[1:] if arguments is None else arguments
    if selected != ["preflight"]:
        print("usage: governance_records.py preflight", file=sys.stderr)
        return 2
    result = preflight(Path.cwd())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
