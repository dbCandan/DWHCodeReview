#!/usr/bin/env python3
"""Forward chained governance records to the central Log Collector, byte for byte.

This module is not a daemon or a scheduler. The single periodic sync script
(``authority_sync.py``, Engineering Governance) runs it as one task of its task list, once per
run, for the signed-in user::

    forwarder = runpy.run_path(".kt-scaffold/hooks/governance_forwarder.py")
    result = forwarder["forward"](settings, device_id=ctx.device_id)

``settings`` is a mapping with four required values: ``collector_url`` (``https`` only),
``ca_file`` (the institution's root CA bundle), ``device_key_file`` (the MDM-written device key,
64 lowercase hex characters) and ``state_file`` (where acknowledgements are kept). The sync
script reads the first three from its managed preferences and keeps the state file in this
user's sync directory. A missing value sends and writes nothing and returns ``not-configured``.
``device_id`` is the hardware UUID the sync script already reads for the device stop; the
forwarder never reads a second device identifier. The result is a small mapping with a stable
``code``, a plain Turkish ``message`` and counts; it never carries record content, the account
or the key.

The forwarder runs with the signed-in user's privilege only; a run as root or as the Windows
system account sends nothing. Each run scans this user's chain streams, sends the records after
the collector's last acknowledgement, every stream head (also the device's liveness signal), the
bound files of governed-review publication marks, unchained records and the owner-only identity
binding. The request and every head are sealed with HMAC-SHA256 under the device key. Only a
sealed acknowledgement for this request moves the saved position; nothing on the device is ever
deleted.

The seal and key-derivation functions here are the single definition the collector also loads.
Python 3.9 syntax and the standard library only.
"""

from __future__ import annotations

import base64
import contextlib
import getpass
import hashlib
import hmac
import json
import os
import re
import runpy
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

UTC = timezone.utc  # noqa: UP017
FORWARD_SCHEMA = "kt-log-forward/v1"
ACK_SCHEMA = "kt-log-ack/v1"
STATE_SCHEMA = "kt-log-forwarder-state/v1"
DEVICE_KEY_LABEL = b"kt-log-device-key/v1\n"
REQUEST_SEAL_LABEL = "kt-log-request/v1"
HEAD_SEAL_LABEL = "kt-log-head/v1"
ACK_SEAL_LABEL = "kt-log-ack/v1"
SEAL_HEADER = "X-KT-Seal"
INGEST_PATH = "/v1/kayitlar"
REQUIRED_SETTINGS = ("collector_url", "ca_file", "device_key_file", "state_file")
RUNNER = "user"
# The hardware UUID the sync script reads (``IOPlatformUUID`` or the SMBIOS UUID), upper case.
DEVICE_ID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DEVICE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_ACK_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20.0
RESCAN_MARGIN_SECONDS = 86400.0
STATE_FILE_MODE = 0o600
STATE_DIRECTORY_MODE = 0o700
DATED_KINDS = (
    "prompt-ingress",
    "llm-call-events",
    "commit-governance",
    "agent-consultation",
    "review-decision",
)
ADDRESSED_KINDS = ("review-baseline", "authority-pin")
PROJECT_RE = re.compile(r"^project-[0-9a-f]{32}$")
RUN_RE = re.compile(r"^run-[A-Za-z0-9][A-Za-z0-9._-]{3,119}$")

MESSAGES = {
    "sent": "Kayıtlar kayıt toplayıcısına gönderildi ve onaylandı.",
    "not-configured": "Kayıt aktarımı için ayarlar eksik; kayıtlar cihazda bekliyor.",
    "collector-url-invalid": "Kayıt toplayıcısının adresi geçersiz; kayıtlar cihazda bekliyor.",
    "ca-unavailable": "Kurum kök sertifikası okunamadı; kayıtlar cihazda bekliyor.",
    "device-key-unavailable": "Cihaz anahtarı okunamadı; kayıtlar cihazda bekliyor.",
    "device-id-unavailable": "Cihaz kimliği okunamadı; kayıtlar cihazda bekliyor.",
    "privileged-run-refused": (
        "Kayıt aktarımı yönetici hesabıyla çalışmaz; kayıtlar cihazda bekliyor."
    ),
    "collector-unreachable": (
        "Kayıt toplayıcısına ulaşılamadı; kayıtlar cihazda kaldı, sonraki çalışmada yeniden "
        "denenecek."
    ),
    "collector-rejected": (
        "Kayıt toplayıcısı gönderimi kabul etmedi; kayıtlar cihazda kaldı."
    ),
    "ack-invalid": (
        "Kayıt toplayıcısının onayı doğrulanamadı; kayıtlar cihazda kaldı ve yeniden gönderilecek."
    ),
    "state-unwritable": (
        "Aktarım durumu kaydedilemedi; kayıtlar cihazda kaldı ve yeniden gönderilecek."
    ),
}

Transport = Callable[
    [str, bytes, Mapping[str, str], ssl.SSLContext], "tuple[int, dict[str, str], bytes]"
]


class ForwardError(Exception):
    """A run stopped before anything was acknowledged; ``code`` is stable and content-free."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _hex_hmac(key: bytes, message: str) -> str:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def derive_device_key(master_key: bytes, device_id: str) -> bytes:
    """The device key the collector derives from the institution's master key and the UUID."""

    return hmac.new(
        master_key, DEVICE_KEY_LABEL + device_id.encode("utf-8"), hashlib.sha256
    ).digest()


def request_seal(key: bytes, device_id: str, nonce: str, sent_at: str, body_sha256: str) -> str:
    return _hex_hmac(key, "\n".join((REQUEST_SEAL_LABEL, device_id, nonce, sent_at, body_sha256)))


def head_seal(
    key: bytes,
    device_id: str,
    stream: str,
    epoch: int,
    sequence: int,
    last_sha256: str,
    sent_at: str,
) -> str:
    fields = (HEAD_SEAL_LABEL, device_id, stream, str(epoch), str(sequence), last_sha256, sent_at)
    return _hex_hmac(key, "\n".join(fields))


def ack_seal(key: bytes, device_id: str, nonce: str, body_sha256: str) -> str:
    return _hex_hmac(key, "\n".join((ACK_SEAL_LABEL, device_id, nonce, body_sha256)))


def encode_body(value: Mapping[str, Any]) -> bytes:
    """The exact request and acknowledgement bytes both sides seal."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _result(code: str, **counts: object) -> dict[str, Any]:
    return {"code": code, "message": MESSAGES[code], **counts}


def _hooks() -> Path:
    return Path(__file__).resolve().parent


def _records() -> dict[str, Any]:
    return runpy.run_path(str(_hooks() / "governance_records.py"))


def _identity() -> dict[str, Any]:
    return runpy.run_path(str(_hooks() / "governance_identity.py"))


def privileged() -> bool:
    """Root or the Windows system account; the forwarder runs only as the signed-in user."""

    if os.name == "posix":
        return os.geteuid() == 0
    name = getpass.getuser().upper()
    return name == "SYSTEM" or name.endswith("$")


def _validated_settings(settings: Mapping[str, object] | None) -> dict[str, str]:
    values = {} if settings is None else dict(settings)
    selected: dict[str, str] = {}
    for name in REQUIRED_SETTINGS:
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ForwardError("not-configured")
        selected[name] = value.strip()
    parsed = urllib.parse.urlsplit(selected["collector_url"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ForwardError("collector-url-invalid")
    return selected


def _tls_context(ca_file: str) -> ssl.SSLContext:
    path = Path(ca_file)
    if not path.is_file():
        raise ForwardError("ca-unavailable")
    try:
        context = ssl.create_default_context(cafile=str(path))
    except (OSError, ssl.SSLError, ValueError):
        raise ForwardError("ca-unavailable") from None
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def read_device_key(path_text: str) -> bytes:
    path = Path(path_text)
    try:
        if path.is_symlink() or not path.is_file() or path.lstat().st_size > 1024:
            raise ForwardError("device-key-unavailable")
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        raise ForwardError("device-key-unavailable") from None
    if DEVICE_KEY_RE.fullmatch(text) is None:
        raise ForwardError("device-key-unavailable")
    return bytes.fromhex(text)


def _empty_state() -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "streams": {},
        "unchained_sent": [],
        "scan_watermark": 0.0,
        "unreachable_since": None,
        "last_success_at": None,
    }


def load_state(path: Path) -> dict[str, Any]:
    """Read the acknowledgement state; an unusable file restarts from nothing, which only resends."""

    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
            return _empty_state()
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_state()
    state = _empty_state()
    if not isinstance(value, dict) or value.get("schema") != STATE_SCHEMA:
        return state
    streams = value.get("streams")
    if isinstance(streams, dict):
        for stream, position in streams.items():
            if (
                isinstance(position, dict)
                and type(position.get("epoch")) is int
                and type(position.get("sequence")) is int
            ):
                state["streams"][str(stream)] = {
                    "epoch": position["epoch"],
                    "sequence": position["sequence"],
                }
    sent = value.get("unchained_sent")
    if isinstance(sent, list):
        state["unchained_sent"] = [
            item for item in sent if isinstance(item, str) and DIGEST_RE.fullmatch(item)
        ]
    if isinstance(value.get("scan_watermark"), (int, float)):
        state["scan_watermark"] = float(value["scan_watermark"])
    for field in ("unreachable_since", "last_success_at"):
        if isinstance(value.get(field), str):
            state[field] = value[field]
    return state


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=STATE_DIRECTORY_MODE)
        temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(temporary, flags, STATE_FILE_MODE)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write((json.dumps(dict(state), sort_keys=True) + "\n").encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
    except OSError:
        raise ForwardError("state-unwritable") from None


def _owned(path: Path) -> bool:
    if os.name != "posix":
        return True
    try:
        return path.lstat().st_uid == os.geteuid()
    except OSError:
        return False


def _projects(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if PROJECT_RE.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
    )


def _streams(root: Path, writer: Mapping[str, Any]) -> list[tuple[str, Path]]:
    """This user's streams: owned by the user on POSIX, named after the user on Windows."""

    found = []
    own = writer["os_user"]()
    for project in _projects(root):
        chain = project / writer["CHAIN_DIRECTORY"]
        if chain.is_symlink() or not chain.is_dir():
            continue
        for stream in sorted(chain.iterdir()):
            if writer["STREAM_ID_RE"].fullmatch(stream.name) is None:
                continue
            if stream.is_symlink() or not stream.is_dir() or not _owned(stream):
                continue
            if os.name != "posix" and stream.name != writer["stream_id"](project.name, own):
                continue
            found.append((project.name, stream))
    return found


def _bounded_bytes(path: Path) -> bytes | None:
    with contextlib.suppress(OSError):
        if not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_RECORD_BYTES:
            return path.read_bytes()
    return None


def _encoded(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _attachments(root: Path, project: str, payload: bytes) -> list[dict[str, str]]:
    """The bound files a publication mark names, read as they are now on the device."""

    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    bound = record.get("bound_files") if isinstance(record, dict) else None
    body = record.get("body") if isinstance(record, dict) else None
    if not isinstance(bound, list) or not isinstance(body, dict):
        return []
    run = body.get("run_id")
    if not isinstance(run, str) or RUN_RE.fullmatch(run) is None:
        return []
    directory = root / project / "governed-review" / run
    found = []
    for item in bound:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or any(part in {"", ".", ".."} for part in name.split("/")):
            continue
        content = _bounded_bytes(directory.joinpath(*name.split("/")))
        if content is not None:
            found.append({"run_id": run, "name": name, "content": _encoded(content)})
    return found


def _position_after(position: Mapping[str, int] | None, epoch: int, sequence: int) -> bool:
    if position is None:
        return True
    return (epoch, sequence) > (int(position["epoch"]), int(position["sequence"]))


def _unchained(
    root: Path, state: Mapping[str, Any], scan_started: float
) -> list[tuple[str, bytes]]:
    """Records written without a link (unsafe or locked stream) that were not sent yet."""

    sent = set(state["unchained_sent"])
    since = float(state["scan_watermark"]) - RESCAN_MARGIN_SECONDS
    found = []
    for project in _projects(root):
        candidates: list[Path] = []
        for kind in DATED_KINDS:
            candidates.extend((project / kind).glob("*/*.json"))
        for kind in ADDRESSED_KINDS:
            candidates.extend((project / kind).glob("*.json"))
        candidates.extend((project / "governed-review" / "published").glob("*/*.json"))
        for candidate in sorted(candidates):
            try:
                status = candidate.lstat()
            except OSError:
                continue
            if status.st_mtime < since or not _owned(candidate):
                continue
            payload = _bounded_bytes(candidate)
            if payload is None:
                continue
            digest = hashlib.sha256(payload).hexdigest()
            if digest in sent:
                continue
            with contextlib.suppress(UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                chain = json.loads(payload.decode("utf-8")).get("chain")
                if isinstance(chain, dict) and chain.get("status") == "unavailable":
                    found.append((project.name, payload))
    return found


def _collector_opener(context: ssl.SSLContext) -> urllib.request.OpenerDirector:
    """An opener that can only reach an ``https`` address with the verified TLS context.

    It has no ``file:``, ``data:``, ``ftp:`` or ``http:`` handler and no redirect handler, so the
    sealed request can never be read from a local file, sent in clear text or re-sent to a
    different address. The proxy handler keeps the system proxy settings the default opener uses;
    any other scheme fails as an unknown URL type and a redirect is returned as an HTTP error.
    """

    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _default_transport(
    url: str, body: bytes, headers: Mapping[str, str], context: ssl.SSLContext
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310
    try:
        with _collector_opener(context).open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, dict(response.headers.items()), response.read(MAX_ACK_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), b""


def build_request(
    *,
    key: bytes,
    device_id: str,
    root: Path,
    state: Mapping[str, Any],
    writer: Mapping[str, Any],
    location: Any,
    now: datetime,
    scan_started: float,
) -> tuple[dict[str, Any], list[str]]:
    """Assemble one bounded request; return it and the unchained digests it carries."""

    sent_at = _iso(now)
    budget = {"records": 0, "bytes": 0}
    streams = []
    identity = _identity()
    os_user = str(writer["os_user"]())
    for project, stream in _streams(root, writer):
        acknowledged = state["streams"].get(stream.name)
        records = []
        attachments: list[dict[str, str]] = []
        for epoch, sequence, entry in writer["chain_entries"](stream):
            if not _position_after(acknowledged, epoch, sequence):
                continue
            if budget["records"] >= MAX_BATCH_RECORDS or budget["bytes"] >= MAX_BATCH_BYTES:
                break
            found = writer["read_chain_entry"](stream, entry, location)
            if found is None or found[2] is None:
                continue
            payload = found[2]
            budget["records"] += 1
            budget["bytes"] += len(payload)
            records.append({"epoch": epoch, "sequence": sequence, "content": _encoded(payload)})
            attachments.extend(_attachments(root, project, payload))
        head_value = None
        head = writer["read_chain_head"](stream)
        if head is not None:
            epoch, sequence = int(head["epoch"]), int(head["sequence"])
            last = str(head["last_sha256"])
            head_value = {
                "epoch": epoch,
                "sequence": sequence,
                "last_sha256": last,
                "seal": head_seal(key, device_id, stream.name, epoch, sequence, last, sent_at),
            }
        binding = identity["read_binding"](stream)
        streams.append(
            {
                "stream_id": stream.name,
                "project_id": project,
                "os_user": os_user,
                "head": head_value,
                "records": records,
                "attachments": attachments,
                "identity": None
                if binding is None
                else {
                    "upn": binding.get("upn"),
                    "source": binding["source"],
                    "observed_at": binding["observed_at"],
                },
            }
        )
    unchained = _unchained(root, state, scan_started)
    request = {
        "schema": FORWARD_SCHEMA,
        "device_id": device_id,
        "runner": RUNNER,
        "nonce": secrets.token_hex(16),
        "sent_at": sent_at,
        "streams": streams,
        "unchained": [
            {"project_id": project, "content": _encoded(payload)} for project, payload in unchained
        ],
    }
    return request, [hashlib.sha256(payload).hexdigest() for _, payload in unchained]


def _verified_ack(
    key: bytes, device_id: str, request: Mapping[str, Any], headers: Mapping[str, str], raw: bytes
) -> dict[str, Any]:
    if len(raw) > MAX_ACK_BYTES:
        raise ForwardError("ack-invalid")
    seal = {name.lower(): value for name, value in headers.items()}.get(SEAL_HEADER.lower(), "")
    expected = ack_seal(key, device_id, str(request["nonce"]), hashlib.sha256(raw).hexdigest())
    if not hmac.compare_digest(seal, expected):
        raise ForwardError("ack-invalid")
    try:
        ack = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ForwardError("ack-invalid") from None
    if (
        not isinstance(ack, dict)
        or ack.get("schema") != ACK_SCHEMA
        or ack.get("nonce") != request["nonce"]
        or ack.get("device_id") != device_id
        or not isinstance(ack.get("streams"), list)
        or not isinstance(ack.get("unchained"), list)
    ):
        raise ForwardError("ack-invalid")
    return ack


def forward(
    settings: Mapping[str, object] | None,
    *,
    device_id: object,
    location: Any = None,
    now: datetime | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Run one forwarding pass; see the module docstring for the call contract."""

    if privileged():
        return _result("privileged-run-refused")
    try:
        selected = _validated_settings(settings)
        context = _tls_context(selected["ca_file"])
        key = read_device_key(selected["device_key_file"])
    except ForwardError as exc:
        return _result(exc.code)
    if not isinstance(device_id, str) or DEVICE_ID_RE.fullmatch(device_id) is None:
        return _result("device-id-unavailable")
    writer = _records()
    chosen = writer["resolve_location"]() if location is None else location
    state_path = Path(selected["state_file"])
    state = load_state(state_path)
    moment = datetime.now(UTC) if now is None else now
    scan_started = moment.timestamp()
    request, unchained = build_request(
        key=key,
        device_id=device_id,
        root=Path(chosen.root),
        state=state,
        writer=writer,
        location=chosen,
        now=moment,
        scan_started=scan_started,
    )
    body = encode_body(request)
    headers = {
        "Content-Type": "application/json",
        SEAL_HEADER: request_seal(
            key, device_id, request["nonce"], request["sent_at"], hashlib.sha256(body).hexdigest()
        ),
    }
    url = selected["collector_url"].rstrip("/") + INGEST_PATH
    try:
        status, response_headers, raw = (
            _default_transport if transport is None else transport
        )(url, body, headers, context)
    except (OSError, ssl.SSLError, ValueError):
        status, response_headers, raw = 0, {}, b""
    if status != 200:
        if state["unreachable_since"] is None:
            state["unreachable_since"] = _iso(moment)
        with contextlib.suppress(ForwardError):
            save_state(state_path, state)
        return _result("collector-unreachable" if status == 0 else "collector-rejected")
    try:
        ack = _verified_ack(key, device_id, request, response_headers, raw)
    except ForwardError as exc:
        return _result(exc.code)
    for item in ack["streams"]:
        if not isinstance(item, dict):
            continue
        stream = item.get("stream_id")
        epoch, sequence = item.get("epoch"), item.get("sequence")
        if not isinstance(stream, str) or type(epoch) is not int or type(sequence) is not int:
            continue
        if _position_after(state["streams"].get(stream), epoch, sequence):
            state["streams"][stream] = {"epoch": epoch, "sequence": sequence}
    acknowledged = {item for item in ack["unchained"] if isinstance(item, str)}
    state["unchained_sent"] = sorted(
        set(state["unchained_sent"]) | (acknowledged & set(unchained))
    )
    state["scan_watermark"] = scan_started
    state["unreachable_since"] = None
    state["last_success_at"] = _iso(moment)
    try:
        save_state(state_path, state)
    except ForwardError as exc:
        return _result(exc.code)
    return _result(
        "sent",
        streams=len(request["streams"]),
        records=sum(len(item["records"]) for item in request["streams"]),
        unchained=len(request["unchained"]),
    )
