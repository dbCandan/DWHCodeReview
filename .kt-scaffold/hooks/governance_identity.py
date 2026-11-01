#!/usr/bin/env python3
"""Read the signed-in user's corporate account (UPN) for the collector-side fingerprint.

The device never computes the fingerprint: the fingerprint key stays with the institution. The
observation hook reads the account at most once a UTC day from sources the device already knows,
in a fixed order, and leaves it in an owner-only binding file inside this user's chain stream. The
file is working state, not a record: it is never chained and only the forwarder sends it, inside
a sealed HTTPS request. Nothing here contacts the network or the directory, needs administrator
rights or invents a value; Git e-mail and client accounts never stand in for the corporate one.

This module keeps Python 3.9 syntax and uses only the standard library. Hooks load it with
``runpy``.
"""

from __future__ import annotations

import contextlib
import json
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

UTC = timezone.utc  # noqa: UP017
IDENTITY_SCHEMA = "kt-governance-identity-binding/v1"
IDENTITY_FILE = "identity.json"
IDENTITY_FILE_MODE = 0o600
MAX_IDENTITY_BYTES = 4096
READ_BUDGET_SECONDS = 0.5
MANAGED_PREFERENCES_ROOT = Path("/Library/Managed Preferences")
MANAGED_PREFERENCES_DOMAIN = "com.kuveytturk.kt-scaffold.plist"
MANAGED_UPN_KEY = "UserPrincipalName"
SOURCES = ("mdm-managed", "sso-extension", "directory-binding", "windows-logon", "unavailable")
UPN_RE = re.compile(r"^[a-z0-9._%+'-]{1,128}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+$")
UPN_TOKEN_RE = re.compile(r"[A-Za-z0-9._%+'-]{1,128}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
SSO_UPN_LINE_RE = re.compile(r"(?i)\b(?:upn|userprincipalname|loginusername)\b")
# A Kerberos authority of an AD-bound account; the local KDC (LKDC:) of every Mac is not one.
KERBEROS_AUTHORITY_RE = re.compile(r";Kerberosv5;[^;]*;([^;@]+@[^;]+);([^;]+);")
NAME_USER_PRINCIPAL = 8

Runner = Callable[[list[str], float], Optional[str]]


def normalize_upn(value: object) -> str | None:
    """NFKC, trimmed and lower-cased ``user@domain``; anything else is not an account."""

    if not isinstance(value, str):
        return None
    cleaned = unicodedata.normalize("NFKC", value).strip().lower()
    if UPN_RE.fullmatch(cleaned) is None:
        return None
    return cleaned


def _run(command: list[str], timeout: float) -> str | None:
    """Run a fixed local program with a bounded wait; any failure is simply no answer."""

    if timeout <= 0 or shutil.which(command[0]) is None and not Path(command[0]).is_file():
        return None
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _managed_preference(user: str, root: Path) -> str | None:
    path = root / user / MANAGED_PREFERENCES_DOMAIN
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            return None
        with path.open("rb") as handle:
            values = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    if not isinstance(values, dict):
        return None
    return normalize_upn(values.get(MANAGED_UPN_KEY))


def _sso_extension(output: str | None) -> str | None:
    if output is None:
        return None
    for line in output.splitlines():
        if SSO_UPN_LINE_RE.search(line) is None:
            continue
        match = UPN_TOKEN_RE.search(line)
        if match is not None:
            return normalize_upn(match.group(0))
    return None


def _directory_binding(output: str | None) -> str | None:
    if output is None:
        return None
    for match in KERBEROS_AUTHORITY_RE.finditer(output):
        principal, realm = match.group(1), match.group(2)
        if realm.upper().startswith("LKDC:") or "LKDC:" in principal.upper():
            continue
        return normalize_upn(principal)
    return None


def _windows_logon() -> str | None:
    try:
        import ctypes

        secur32 = ctypes.WinDLL("secur32")  # type: ignore[attr-defined]
        size = ctypes.c_ulong(0)
        secur32.GetUserNameExW(NAME_USER_PRINCIPAL, None, ctypes.byref(size))
        if not 0 < size.value <= 1024:
            return None
        buffer = ctypes.create_unicode_buffer(size.value)
        if not secur32.GetUserNameExW(NAME_USER_PRINCIPAL, buffer, ctypes.byref(size)):
            return None
        return normalize_upn(buffer.value)
    except (AttributeError, OSError, ValueError):
        return None


def read_account(
    user: str,
    *,
    platform_name: str | None = None,
    runner: Runner | None = None,
    managed_root: Path | None = None,
    budget: float = READ_BUDGET_SECONDS,
) -> tuple[str | None, str]:
    """Return ``(upn, source)`` from the first source that answers within the budget."""

    selected = sys.platform if platform_name is None else platform_name
    run = _run if runner is None else runner
    deadline = time.monotonic() + budget

    def remaining() -> float:
        return deadline - time.monotonic()

    if selected == "win32":
        account = _windows_logon()
        return (account, "windows-logon") if account else (None, "unavailable")
    if selected != "darwin" or not user or "/" in user or user.startswith("."):
        return None, "unavailable"
    preferences = MANAGED_PREFERENCES_ROOT if managed_root is None else managed_root
    account = _managed_preference(user, preferences)
    if account:
        return account, "mdm-managed"
    if remaining() > 0:
        account = _sso_extension(run(["/usr/bin/app-sso", "platform", "-s"], remaining()))
        if account:
            return account, "sso-extension"
    if remaining() > 0:
        output = run(
            ["/usr/bin/dscl", ".", "-read", f"/Users/{user}", "AuthenticationAuthority"],
            remaining(),
        )
        account = _directory_binding(output)
        if account:
            return account, "directory-binding"
    return None, "unavailable"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def read_binding(stream: Path) -> dict[str, Any] | None:
    """Return the stream's identity binding when it is a valid owner-only file."""

    path = stream / IDENTITY_FILE
    try:
        status = path.lstat()
        if not os.path.isfile(path) or path.is_symlink() or status.st_size > MAX_IDENTITY_BYTES:
            return None
        if os.name == "posix" and status.st_mode & 0o077:
            return None
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema") != IDENTITY_SCHEMA
        or value.get("source") not in SOURCES
        or not isinstance(value.get("observed_at"), str)
    ):
        return None
    account = value.get("upn")
    if value["source"] == "unavailable":
        if account is not None:
            return None
    elif normalize_upn(account) != account:
        return None
    return value


def _write_binding(stream: Path, binding: Mapping[str, Any]) -> None:
    payload = (json.dumps(dict(binding), sort_keys=True) + "\n").encode("utf-8")
    temporary = stream / f".{IDENTITY_FILE}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, IDENTITY_FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            if os.name == "posix":
                os.fchmod(handle.fileno(), IDENTITY_FILE_MODE)
            os.fsync(handle.fileno())
        os.replace(temporary, stream / IDENTITY_FILE)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def refresh_binding(
    stream: Path,
    user: str,
    *,
    now: datetime | None = None,
    reader: Callable[[str], tuple[str | None, str]] | None = None,
) -> str:
    """Refresh the binding at most once per UTC day; return ``fresh`` or the source written."""

    moment = datetime.now(UTC) if now is None else now
    current = read_binding(stream)
    today = moment.astimezone(UTC).strftime("%Y-%m-%d")
    if current is not None and str(current["observed_at"]).startswith(today):
        return "fresh"
    account, source = (read_account if reader is None else reader)(user)
    if source not in SOURCES or (source == "unavailable") != (account is None):
        account, source = None, "unavailable"
    _write_binding(
        stream,
        {"schema": IDENTITY_SCHEMA, "upn": account, "source": source, "observed_at": _iso(moment)},
    )
    return source
