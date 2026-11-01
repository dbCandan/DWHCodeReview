#!/usr/bin/env python3
"""Dependency-free, prompt-text-only ingress gate for supported Agent clients."""

from __future__ import annotations

import argparse
import bisect
import contextlib
import getpass
import hashlib
import hmac
import json
import math
import re
import runpy
import secrets
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLIENTS = (
    "claude-code",
    "codex",
    "github-copilot-vscode",
    "cursor",
)
POLICY_RELATIVE_PATH = Path("agent-platform/policies/prompt-ingress/prompt-ingress-policy.json")
STATE_POLICY_RELATIVE_PATH = Path(
    "agent-platform/policies/local-state/local-governance-state-policy.json"
)
PROJECT_MANIFEST_RELATIVE_PATH = Path(".kt-scaffold/project-manifest.json")
FALLBACK_MAX_EVENT_BYTES = 131_072
MAX_POLICY_BYTES = 262_144
MAX_STATE_POLICY_BYTES = 65_536
MAX_PROJECT_MANIFEST_BYTES = 262_144
MAX_NATIVE_CORRELATION_BYTES = 4_096
PROJECT_ID_RE = re.compile(r"^project-(?!0{32}$)[0-9a-f]{32}$")
EVENT_ID_RE = re.compile(r"^event:(?!0{32}$)[0-9a-f]{32}$")
EXPECTED_STATE_LAYOUT = {
    "macos": "/Users/Shared/kt-scaffold/governance/",
    "windows": "%ProgramData%\\kt-scaffold\\governance\\",
    "linux": "/var/lib/kt-scaffold/governance/",
    "prompt_receipts": "{project_id}/prompt-ingress/",
    "authority_pin": "{project_id}/authority-pin/",
    "review_baselines": "{project_id}/review-baseline/",
    "commit_guard_receipts": "{project_id}/commit-governance/",
}
EXPECTED_STATE_LIMITS = {
    "max_prompt_record_bytes": 262_144,
    "max_authority_receipt_bytes": 65_536,
    "max_review_baseline_file_bytes": 2_097_152,
    "max_commit_guard_event_bytes": 65_536,
}
MAX_IDENTITY_FIELD_LENGTHS = {
    "display_name": 200,
    "email": 320,
    "account_id": 200,
}
BLOCK_MESSAGE = (
    "Mesajiniz (prompt) gonderilmedi: icinde paylasilmamasi gereken bilgi bicimine uyan ifade "
    "var: {findings}. Bu ifadeyi cikarip mesaji yeniden gonderin. Ornek ya da test verisiyse "
    "yerine gercek olmadigi acikca anlasilan bir deger yazin."
)
# One finding reads "<label> (<count> adet, satir <line numbers>)"; the matched value never appears.
BLOCK_FINDING = "{label} ({count} adet, satir {lines})"
BLOCK_CLASS_LABELS = {
    "labelled-secret": "parola veya erisim anahtari",
    "cloud-access-key": "bulut erisim anahtari",
    "private-key": "ozel anahtar",
    "email": "e-posta adresi",
    "tckn": "T.C. kimlik numarasi",
    "iban": "IBAN",
    "payment-card": "kart numarasi",
    "phone-number": "telefon numarasi",
    "customer-number": "musteri numarasi",
    "labelled-personal-field": "kisisel bilgi alani (ad, adres veya dogum tarihi)",
    "internal-hostname": "kurum ici sunucu adi",
    "project-codename": "proje kod adi",
}
MAX_REPORTED_LINES = 5
# Each matched detector's reason and basis lines come from the governance client's versioned
# templates; when they cannot be read the block stands and this fixed line says so.
EXPLANATION_UNAVAILABLE = "Neden ve dayanak satirlari okunamadi; engelleme karari degismedi."
INPUT_INVALID_MESSAGE = (
    "Mesajiniz (prompt) gonderilmedi, cunku okunamadi: mesaj cok uzun (en fazla {limit_kb} KB, "
    "yani kabaca {limit_kb} bin harf) ya da bicimi gecersiz. Mesaji kisaltip yeniden gonderin; "
    "uzun bir ciktiyi mesaja yapistirmak yerine dosyaya kaydedip dosyanin yolunu yazin."
)
SAFE_ERROR_MESSAGE = (
    "Mesajiniz (prompt) gonderilmedi, cunku gonderimden once yapilan veri guvenligi denetimi "
    "tamamlanamadi. Proje klasorunde python3 .kt-scaffold/hooks/governance_records.py preflight "
    "komutuyla Python yorumlayicisinin ve denetim kurallarinin (politika) hazir olup olmadigini "
    "kontrol edin; denetim hatasi cozulmeden mesaji yeniden gondermeyin."
)
RECORD_WARNING = "GOVERNANCE_RECORD_UNAVAILABLE: {code}; prompt karari degismedi."
INTERPRETER_MESSAGE = (
    "Mesajiniz (prompt) gonderilmedi, cunku gonderimden once yapilan veri guvenligi denetimi "
    "tamamlanamadi (python-runtime-mismatch): projenin Python ortami (.venv klasoru) yok ya da "
    "Python surumu teknoloji profilinin kabul ettigi en eski surumden eski. .venv hazir olana "
    "kadar her mesaj durdurulur. Terminalde proje klasorunde su komutu calistirip yeniden "
    "deneyin: {command}"
)
EXPECTED_PRIVATE_KEY_BEGIN_PATTERN = (
    r"-----BEGIN (?:[A-Z0-9]{1,24}(?: [A-Z0-9]{1,24}){0,3} )?PRIVATE KEY-----"
)
PRIVATE_KEY_BEGIN_MARKER_RE = re.compile(EXPECTED_PRIVATE_KEY_BEGIN_PATTERN)
PRIVATE_KEY_END_MARKER_RE = re.compile(
    r"-----END (?:[A-Z0-9]{1,24}(?: [A-Z0-9]{1,24}){0,3} )?PRIVATE KEY-----"
)
# A marker is a private key only next to key material: a base64 run this long. A marker that is
# merely quoted or discussed has no such run and stays out of the finding.
PRIVATE_KEY_MATERIAL_RE = re.compile(r"[A-Za-z0-9+/]{40,}")
PRIVATE_KEY_LEADING_MATERIAL_RE = re.compile(r"\s*[A-Za-z0-9+/]{40,}")
PRIVATE_KEY_TRAILING_MATERIAL_RE = re.compile(
    r"[A-Za-z0-9+/]{40,}(?:\s+[A-Za-z0-9+/]+)*={0,2}\s*\Z"
)
PRIVATE_KEY_TRAILING_WINDOW_CHARS = 256
# An email match leaves the email detector only when it is the whole account segment of a home
# directory path and equals the name of the running user's own home directory. The same text
# anywhere else, another account's name and every other detector class stay findings.
HOME_PATH_ROOT_RE = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\{1,2}Users\\{1,2})\Z")
HOME_PATH_ROOT_MAX_CHARS = 12
HOME_ACCOUNT_SEGMENT_END = frozenset("/\\\"'`)]}>,;:")
# A labelled value is a secret candidate unless it is a placeholder, a reference to where the
# secret lives, or text with too little variety to be one.
SECRET_SEPARATOR_RE = re.compile(r"[^:=]*[:=]\s*")
SECRET_PLACEHOLDER_RE = re.compile(
    r"<[^<>]*>|\$\{\{?[^{}]*\}\}?|\$\([^()]*\)|\{\{[^{}]*\}\}|%[A-Za-z_]\w*%"
    r"|[*xX.#_-]+|change[-_]?me|your[-_ ][a-z_ -]*|redacted|placeholder",
    re.IGNORECASE,
)
# A name is a word, a constant or a camel-case identifier without digits; a random letter mix is
# not a name and stays a secret candidate.
SECRET_NAME_RE = re.compile(r"[^\W\d]\w*")
SECRET_CAMEL_CASE_RE = re.compile(
    r"[A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc]?[a-z\u00e7\u011f\u0131\u00f6\u015f\u00fc]+"
    r"(?:[A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc][a-z\u00e7\u011f\u0131\u00f6\u015f\u00fc]{2,})*"
)
SECRET_CALL_OR_INDEX_RE = re.compile(r"(?P<head>[^\W\d][\w.]*)[(\[][\w.,'\"()\[\]=:*/-]*")
SECRET_REFERENCE_ROOTS = frozenset(
    {
        "os", "process", "env", "settings", "config", "cfg", "conf", "self", "this", "args",
        "kwargs", "options", "opts", "params", "props", "state", "secrets", "vars", "values",
        "request", "req", "response", "res", "ctx", "context",
    }
)  # fmt: skip
SECRET_TRAILING_PUNCTUATION = ";,.:"
MIN_SECRET_VALUE_ENTROPY_BITS = 2.0
# An address-shaped match is not a person's address when it is the user part of a URL, a
# transport account, a wildcard, or sits on a domain reserved for documentation and tests.
EMAIL_NON_ADDRESS_LOCAL_PARTS = frozenset({"git", "%"})
EMAIL_RESERVED_DOMAINS = ("example.com", "example.net", "example.org", "users.noreply.github.com")
EMAIL_RESERVED_TOP_LEVEL_DOMAINS = frozenset({"example", "invalid", "localhost", "test"})
URL_PASSWORD_PREFIX_RE = re.compile(r"://[^\s/:@]+:\Z")
URL_PASSWORD_PREFIX_MAX_CHARS = 128
# Issuer prefix and length of the card networks; a digit run outside them is not a card number.
PAYMENT_CARD_ISSUER_RE = re.compile(
    r"4(?:\d{12}|\d{15}|\d{18})"
    r"|(?:5[1-5]\d{2}|222[1-9]|22[3-9]\d|2[3-6]\d{2}|27[01]\d|2720)\d{12}"
    r"|3[47]\d{13}"
    r"|(?:6011|65\d{2}|64[4-9]\d)\d{12,15}"
    r"|62\d{14,17}"
    r"|35(?:2[89]|[3-8]\d)\d{12,15}"
    r"|(?:30[0-5]\d|36\d{2}|3[89]\d{2})\d{10,15}"
    r"|9792\d{12}"
    r"|(?:5018|5020|5038|5893|6304|6759|676[1-3])\d{9,15}"
)
DETECTOR_CLASSES = frozenset(
    {
        "labelled-secret",
        "cloud-access-key",
        "private-key",
        "email",
        "tckn",
        "iban",
        "payment-card",
        "phone-number",
        "customer-number",
        "labelled-personal-field",
        "internal-hostname",
        "project-codename",
    }
)
# What the prompt gets: `block` stops it, `record-mask` lets it through. Every match, whatever its
# action, is masked in the record.
DETECTOR_ACTIONS = ("block", "record-mask")
REGEX_VALIDATORS = frozenset(
    {
        "secret-value-shape",
        "private-key-pem-block",
        "email-address-shape",
        "tckn-checksum",
        "iban-mod97",
        "luhn-checksum",
        "labelled-field-value",
    }
)
EXPECTED_VALIDATORS = {
    "labelled-secret": "secret-value-shape",
    "private-key": "private-key-pem-block",
    "email": "email-address-shape",
    "tckn": "tckn-checksum",
    "iban": "iban-mod97",
    "payment-card": "luhn-checksum",
    "labelled-personal-field": "labelled-field-value",
}
# A term-list class is matched against the keyed digests of a term list, never a pattern.
TERM_LIST_CLASSES = {
    "internal-hostname": "internal-hostnames",
    "project-codename": "project-codenames",
}
TERM_LIST_NAMES = tuple(sorted(TERM_LIST_CLASSES.values()))
TERM_NORMALIZATION = "nfkc-casefold-tr-v1"
TERM_DIGEST = "hmac-sha256"
MAX_TERM_PHRASE_WORDS = 3
INSTITUTION_TERM_LIST_FILE = "institution-terms.json"
EXPECTED_TERM_LIST_POLICY = {
    "normalization": TERM_NORMALIZATION,
    "digest": TERM_DIGEST,
    "max_phrase_words": MAX_TERM_PHRASE_WORDS,
    "institution_list": "shared-governance-root/" + INSTITUTION_TERM_LIST_FILE,
}
MAX_TERM_LIST_BYTES = 4 * 1024 * 1024
MAX_TERM_LIST_ENTRIES = 50_000
TERM_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
TERM_KEY_RE = re.compile(r"(?:[0-9a-f]{2}){32,64}")
TERM_LIST_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
TERM_WORD_RE = re.compile(r"[^\W_]+(?:[-_][^\W_]+)*")
TERM_PHRASE_GAP_RE = re.compile(r"[ \t]+")
HOSTNAME_RE = re.compile(
    r"(?<![\w.-])[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+(?![\w-])"
)
MAX_REPORTED_RECEIPT_LINES = 64
# A labelled personal value is a finding unless it is a placeholder, a code reference, a type name
# or an assignment; unquoted, it needs two words or a digit (a name, an address, a date).
LABELLED_VALUE_WORDS_RE = re.compile(r"[^\W\d_]{2,}\s+[^\W\d_]{2,}")
LABELLED_VALUE_ASSIGNMENT_RE = re.compile(r"[\w.\[\]]+\s*=")
LABELLED_VALUE_DOTTED_RE = re.compile(r"[^\W\d]\w*(?:\.\w+)+")
LABELLED_VALUE_TYPE_WORDS = frozenset(
    {
        "str", "string", "text", "varchar", "nvarchar", "char", "int", "integer", "number",
        "bool", "boolean", "date", "datetime", "timestamp", "any", "object", "none", "null",
        "nil", "optional", "list", "dict", "array", "uuid", "json", "field", "column",
    }
)  # fmt: skip
WHOLE_PROMPT_REDACTION_CLASSES = frozenset({"labelled-secret", "private-key"})
PROMPT_CAPTURE_KEYS = frozenset(
    {
        "mode",
        "text",
        "sha256",
        "redaction_strategy",
        "redaction_count",
        "redacted_classes",
    }
)
DETECTOR_COUNT_KEYS = frozenset(
    {
        "detector_id",
        "class",
        "action",
        "count",
        "lines",
        "lines_truncated",
        "source_ref",
        "legal_refs",
    }
)
PROHIBITED_RECEIPT_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "raw_sha256",
        "input_sha256",
        "input_digest_kind",
    }
)
EXPECTED_PERSISTENCE_POLICY = {
    "capture_scope": "user-prompt-text-only",
    "clean_prompt": "exact",
    "sensitive_prompt": "risk-class-aware-redacted",
    "invalid_prompt": "unavailable",
    "redaction_strategy": "validated-detector-spans-v1",
    "redaction_token_template": "[REDACTED:{class}]",
    "whole_prompt_redaction_classes": ["labelled-secret", "private-key"],
    "whole_prompt_redaction_strategy": "whole-prompt-redacted-v1",
    "whole_prompt_redaction_token": "[REDACTED:high-risk-prompt]",
    "digest_scope": "persisted-prompt-capture-only",
    "raw_sensitive_digest_allowed": False,
    "excluded_content_persistence": False,
}


class GuardError(ValueError):
    """A safe-to-collapse prompt ingress failure."""


def _error_message(_error: BaseException) -> str:
    return SAFE_ERROR_MESSAGE


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _new_nonzero_hex(byte_count: int) -> str:
    while True:
        value = secrets.token_hex(byte_count)
        if int(value, 16) != 0:
            return value


def _safe_identity_field(value: object, *, field: str) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if len(value) > MAX_IDENTITY_FIELD_LENGTHS[field]:
        return None
    if any(
        ord(character) < 32 or 127 <= ord(character) <= 159 or ord(character) in {0x2028, 0x2029}
        for character in value
    ):
        return None
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        return None
    if field == "email":
        if value.count("@") != 1 or any(character.isspace() for character in value):
            return None
        local_part, domain = value.split("@", maxsplit=1)
        if not local_part or not domain:
            return None
    return value


def _identity_reference(client_id: str, event: dict[str, Any] | None) -> tuple[str, str]:
    supplied: dict[str, Any] | None = None
    if event is not None:
        for key in ("audit_identity", "user"):
            candidate = event.get(key)
            if isinstance(candidate, dict):
                supplied = candidate
                break

    display_name = _safe_identity_field(
        supplied.get("display_name", supplied.get("name")) if supplied else None,
        field="display_name",
    )
    email = _safe_identity_field(supplied.get("email") if supplied else None, field="email")
    account_id = _safe_identity_field(
        supplied.get("account_id", supplied.get("id")) if supplied else None,
        field="account_id",
    )
    if any(value is not None for value in (display_name, email, account_id)):
        source = "client-visible"
    else:
        try:
            os_login: object = getpass.getuser()
        except (KeyError, OSError):
            os_login = None
        display_name = _safe_identity_field(os_login, field="display_name")
        email = None
        account_id = None
        source = "os-fallback" if display_name is not None else "unavailable"

    identity = {
        "schema_version": "1.0",
        "kind": "VibecoderIdentity",
        "client_id": client_id,
        "display_name": display_name,
        "email": email,
        "account_id": account_id,
        "source": source,
    }
    canonical = (
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return f"vibecoder-identity:sha256:{_sha256(canonical)}", source


def _native_correlation_value(
    event: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> str | None:
    if event is None:
        return None
    for key in keys:
        value = event.get(key)
        if not isinstance(value, str) or not value or "\x00" in value:
            continue
        encoded = value.encode("utf-8")
        if len(encoded) <= MAX_NATIVE_CORRELATION_BYTES:
            return _sha256(encoded)
    return None


def _prompt_correlation(
    event: dict[str, Any] | None,
    *,
    invocation_token: str,
) -> dict[str, str]:
    session_digest = _native_correlation_value(
        event,
        ("session_id", "conversation_id", "chat_id"),
    )
    turn_digest = _native_correlation_value(
        event,
        ("prompt_id", "turn_id", "request_id", "message_id", "generation_id"),
    )
    return {
        "prompt_session_id": (
            f"session:client.{session_digest}"
            if session_digest is not None
            else f"session:local.{_new_nonzero_hex(16)}"
        ),
        "prompt_session_id_source": (
            "client-envelope"
            if session_digest is not None
            else "local-generated-client-unavailable"
        ),
        "prompt_turn_id": (
            f"turn:client.{turn_digest}"
            if turn_digest is not None
            else f"turn:local.{invocation_token}"
        ),
        "prompt_turn_id_source": (
            "client-envelope" if turn_digest is not None else "local-generated-client-unavailable"
        ),
    }


UNAVAILABLE_MODEL: dict[str, object] = {"source": "unavailable", "id": None, "effort": None}


def _event_normalizer() -> dict[str, Any]:
    path = Path(__file__).resolve().with_name("llm_call_events.py")
    if path.is_symlink() or not path.is_file():
        raise GuardError("event-normalizer-unavailable")
    return runpy.run_path(str(path))


def _observed_model(client_id: str, event: dict[str, Any] | None) -> dict[str, object]:
    """The model and effort the client reports; observation never changes the prompt decision."""
    try:
        model = _event_normalizer()["observed_model"](event, client_id)
    except Exception:
        return dict(UNAVAILABLE_MODEL)
    return model if isinstance(model, dict) else dict(UNAVAILABLE_MODEL)


def _invocation_context(
    client_id: str,
    event: dict[str, Any] | None,
    *,
    project_id: str,
    state_policy: dict[str, Any],
    state_policy_digest: str,
) -> dict[str, object]:
    event_token = _new_nonzero_hex(16)
    invocation_token = _new_nonzero_hex(16)
    occurred_at = datetime.now(timezone.utc)  # noqa: UP017 - generated hook supports Python 3.9.
    audit_identity_ref, audit_identity_source = _identity_reference(client_id, event)
    return {
        "event_id": f"event:{event_token}",
        "invocation_id": f"invocation:{invocation_token}",
        "occurred_at": occurred_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "project_id": project_id,
        "state_policy_version": state_policy["metadata"]["version"],
        "state_policy_sha256": state_policy_digest,
        "storage_authority": "shared-governance-root",
        "immutable_audit_storage_proof": False,
        "run_id": f"run:{_new_nonzero_hex(16)}",
        "trace_context": {
            "schema_version": "1.0",
            "trace_id": _new_nonzero_hex(16),
            "span_id": _new_nonzero_hex(8),
            "parent_span_id": None,
            "trace_flags": "01",
        },
        **_prompt_correlation(event, invocation_token=invocation_token),
        "audit_identity_ref": audit_identity_ref,
        "audit_identity_source": audit_identity_source,
        "model": _observed_model(client_id, event),
    }


def _read_project_id(project_root: Path) -> str:
    manifest_path = project_root / PROJECT_MANIFEST_RELATIVE_PATH
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise GuardError("project-identity-unavailable")
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
        resolved_root = project_root.resolve(strict=True)
        size = manifest_path.stat().st_size
    except OSError as exc:
        raise GuardError("project-identity-unavailable") from exc
    if not resolved_manifest.is_relative_to(resolved_root):
        raise GuardError("project-identity-outside-project")
    if size <= 0 or size > MAX_PROJECT_MANIFEST_BYTES:
        raise GuardError("project-identity-invalid")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError("project-identity-invalid") from exc
    project_id = payload.get("project_id") if isinstance(payload, dict) else None
    if not isinstance(project_id, str) or PROJECT_ID_RE.fullmatch(project_id) is None:
        raise GuardError("project-identity-invalid")
    return project_id


def _read_state_policy(project_root: Path) -> tuple[dict[str, Any], str]:
    policy_path = project_root / STATE_POLICY_RELATIVE_PATH
    if policy_path.is_symlink() or not policy_path.is_file():
        raise GuardError("state-policy-unavailable")
    try:
        resolved_policy = policy_path.resolve(strict=True)
        resolved_root = project_root.resolve(strict=True)
        size = policy_path.stat().st_size
    except OSError as exc:
        raise GuardError("state-policy-unavailable") from exc
    if not resolved_policy.is_relative_to(resolved_root):
        raise GuardError("state-policy-outside-project")
    if size <= 0 or size > MAX_STATE_POLICY_BYTES:
        raise GuardError("state-policy-invalid")
    try:
        raw = policy_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError("state-policy-invalid") from exc
    if not isinstance(payload, dict):
        raise GuardError("state-policy-invalid")
    metadata = payload.get("metadata")
    layout = payload.get("layout")
    limits = payload.get("limits")
    retention = payload.get("retention")
    export = payload.get("export")
    assurance = payload.get("assurance")
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("kind") != "LocalGovernanceStatePolicy"
        or not isinstance(metadata, dict)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(metadata.get("version"))) is None
        or layout != EXPECTED_STATE_LAYOUT
        or retention != {"automatic_delete": False, "delete_requires_export_ack": True}
        or export
        != {
            "enabled": False,
            "endpoint": None,
            "persistent_queue": "collector-file-storage-not-configured",
            "protocol": "otlp/https",
        }
        or assurance
        != {
            "clean_prompt_exact_content_allowed": True,
            "excluded_content_allowed": False,
            "local_spool_immutable": False,
            "production_admission": False,
            "raw_sensitive_content_allowed": False,
        }
    ):
        raise GuardError("state-policy-invalid")
    if limits != EXPECTED_STATE_LIMITS:
        raise GuardError("state-policy-invalid")
    return payload, _sha256(raw)


def _read_policy(project_root: Path) -> tuple[dict[str, Any], str]:
    policy_path = project_root / POLICY_RELATIVE_PATH
    if policy_path.is_symlink() or not policy_path.is_file():
        raise GuardError("policy-unavailable")
    try:
        resolved_policy = policy_path.resolve(strict=True)
        resolved_root = project_root.resolve(strict=True)
    except OSError as exc:
        raise GuardError("policy-unavailable") from exc
    if not resolved_policy.is_relative_to(resolved_root):
        raise GuardError("policy-outside-project")
    try:
        size = policy_path.stat().st_size
    except OSError as exc:
        raise GuardError("policy-unavailable") from exc
    if size <= 0 or size > MAX_POLICY_BYTES:
        raise GuardError("policy-size-invalid")
    try:
        raw = policy_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError("policy-invalid") from exc
    if not isinstance(payload, dict):
        raise GuardError("policy-invalid")
    _validate_policy(payload)
    return payload, _sha256(raw)


def _validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("schema_version") != "2.0" or policy.get("kind") != "PromptIngressPolicy":
        raise GuardError("policy-invalid")
    metadata = policy.get("metadata")
    limits = policy.get("limits")
    persistence = policy.get("persistence")
    detectors = policy.get("detectors")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("version"), str):
        raise GuardError("policy-invalid")
    if not isinstance(limits, dict):
        raise GuardError("policy-invalid")
    if persistence != EXPECTED_PERSISTENCE_POLICY:
        raise GuardError("policy-invalid")
    event_limit = limits.get("max_event_bytes")
    prompt_limit = limits.get("max_prompt_bytes")
    if (
        not isinstance(event_limit, int)
        or isinstance(event_limit, bool)
        or not 1_024 <= event_limit <= 1_048_576
        or not isinstance(prompt_limit, int)
        or isinstance(prompt_limit, bool)
        or not 1 <= prompt_limit <= 524_288
        or prompt_limit > event_limit
    ):
        raise GuardError("policy-invalid")
    if not isinstance(detectors, list) or not detectors:
        raise GuardError("policy-invalid")
    term_lists = policy.get("term_lists")
    if not isinstance(term_lists, dict) or {
        key: term_lists.get(key) for key in EXPECTED_TERM_LIST_POLICY
    } != EXPECTED_TERM_LIST_POLICY or set(term_lists) != {*EXPECTED_TERM_LIST_POLICY, "sample"}:
        raise GuardError("policy-invalid")
    _term_list(term_lists.get("sample"), sample=True)
    seen: set[str] = set()
    for detector in detectors:
        if not isinstance(detector, dict) or set(detector) != {
            "id",
            "class",
            "action",
            "source_ref",
            "implementation",
        }:
            raise GuardError("policy-invalid")
        detector_id = detector.get("id")
        detector_class = detector.get("class")
        action = detector.get("action")
        source_ref = detector.get("source_ref")
        implementation = detector.get("implementation")
        if (
            not isinstance(detector_id, str)
            or detector_id in seen
            or detector_class not in DETECTOR_CLASSES
            or action not in DETECTOR_ACTIONS
            or not isinstance(source_ref, str)
            or len(source_ref) < 8
            or not isinstance(implementation, dict)
        ):
            raise GuardError("policy-invalid")
        # A secret or a private key empties the whole record; such a prompt is never sent.
        if detector_class in WHOLE_PROMPT_REDACTION_CLASSES and action != "block":
            raise GuardError("policy-invalid")
        seen.add(detector_id)
        if detector_class in TERM_LIST_CLASSES:
            if implementation != {
                "kind": "term-list",
                "list": TERM_LIST_CLASSES[str(detector_class)],
            }:
                raise GuardError("policy-invalid")
            continue
        if (
            implementation.get("kind") != "regex"
            or implementation.get("engine") != "python-re"
            or not isinstance(implementation.get("pattern"), str)
            or not isinstance(implementation.get("flags"), list)
            or (
                implementation.get("validator") is not None
                and implementation.get("validator") not in REGEX_VALIDATORS
            )
        ):
            raise GuardError("policy-invalid")
        if implementation.get("validator") != EXPECTED_VALIDATORS.get(str(detector_class)):
            raise GuardError("policy-invalid")
        if detector_class == "private-key" and (
            implementation.get("pattern") != EXPECTED_PRIVATE_KEY_BEGIN_PATTERN
            or implementation.get("flags") != []
        ):
            raise GuardError("policy-invalid")
        pattern = _compile_detector(implementation)
        if pattern.search("") is not None:
            raise GuardError("policy-invalid")


def _term_list(value: object, *, sample: bool) -> dict[str, Any]:
    """A validated term list: its key and the digest set of each list; never a readable term."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "sample",
        "version",
        "key",
        "lists",
    }:
        raise GuardError("term-list-invalid")
    lists = value.get("lists")
    version = value.get("version")
    key = value.get("key")
    if (
        value.get("schema_version") != "1.0"
        or value.get("kind") != "InstitutionTermList"
        or value.get("sample") is not sample
        or not isinstance(version, str)
        or TERM_LIST_VERSION_RE.fullmatch(version) is None
        or not isinstance(key, str)
        or TERM_KEY_RE.fullmatch(key) is None
        or not isinstance(lists, dict)
        or set(lists) != set(TERM_LIST_NAMES)
    ):
        raise GuardError("term-list-invalid")
    digests: dict[str, frozenset[str]] = {}
    total = 0
    for name in TERM_LIST_NAMES:
        entries = lists[name]
        if (
            not isinstance(entries, list)
            or entries != sorted(set(entries))
            or any(
                not isinstance(item, str) or TERM_DIGEST_RE.fullmatch(item) is None
                for item in entries
            )
        ):
            raise GuardError("term-list-invalid")
        total += len(entries)
        digests[name] = frozenset(entries)
    if total > MAX_TERM_LIST_ENTRIES:
        raise GuardError("term-list-invalid")
    return {"key": bytes.fromhex(key), "version": version, "digests": digests}


def normalize_term(value: str) -> str:
    """The one term normalization of the device hook and the factory list tool."""
    folded = unicodedata.normalize("NFKC", value).casefold()
    # Turkish dotted and dotless i fold to the same letter, so `İzmir` and `izmir` match.
    return folded.replace("i̇", "i").replace("ı", "i")


def term_digest(key: bytes, normalized: str) -> str:
    return hmac.digest(key, normalized.encode("utf-8"), "sha256").hex()


def term_list_document(
    terms: dict[str, list[str]], *, key: bytes, version: str, sample: bool
) -> dict[str, object]:
    """Build a term list from readable terms; only the keyed digests leave this function."""
    lists: dict[str, list[str]] = {}
    for name in TERM_LIST_NAMES:
        normalized = {
            " ".join(normalize_term(word) for word in TERM_WORD_RE.findall(term))
            if name == "project-codenames"
            else normalize_term(term.strip()).rstrip(".")
            for term in terms.get(name, [])
        }
        lists[name] = sorted(term_digest(key, item) for item in normalized if item)
    document: dict[str, object] = {
        "schema_version": "1.0",
        "kind": "InstitutionTermList",
        "sample": sample,
        "version": version,
        "key": key.hex(),
        "lists": lists,
    }
    _term_list(document, sample=sample)
    return document


def _canonical_sha256(value: object) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _institution_term_list_path(location: Any = None) -> Path | None:
    """``institution-terms.json`` at the shared governance root the records use."""
    try:
        selected = location if location is not None else _record_location()
        if selected is None:
            selected = _records()["resolve_location"]()
        return Path(selected.root) / INSTITUTION_TERM_LIST_FILE
    except Exception:
        return None


def _load_terms(
    policy: dict[str, Any], location: Any = None
) -> tuple[dict[str, Any], dict[str, object]]:
    """The institution's list when it is present and valid, otherwise the policy's sample list.

    A missing or unreadable institution list never changes the prompt decision; the receipt
    shows which list was applied.
    """
    sample = policy["term_lists"]["sample"]
    path = _institution_term_list_path(location)
    status = "missing"
    if path is not None and (path.exists() or path.is_symlink()):
        status = "invalid"
        try:
            if not path.is_symlink() and path.is_file():
                raw = path.read_bytes()
                if 0 < len(raw) <= MAX_TERM_LIST_BYTES:
                    loaded = _term_list(json.loads(raw.decode("utf-8")), sample=False)
                    return loaded, {
                        "institution_list": "loaded",
                        "applied": "institution",
                        "version": loaded["version"],
                        "sha256": _sha256(raw),
                    }
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    loaded = _term_list(sample, sample=True)
    return loaded, {
        "institution_list": status,
        "applied": "sample",
        "version": loaded["version"],
        "sha256": _canonical_sha256(sample),
    }


def _term_spans(prompt: str, terms: dict[str, Any], list_name: str) -> list[tuple[int, int]]:
    """Spans whose normalized words, phrases or host names are in the keyed digest list."""
    digests = terms["digests"][list_name]
    if not digests:
        return []
    key = terms["key"]
    found: list[tuple[int, int]] = []
    words = [(match.start(), match.end(), match.group(0)) for match in TERM_WORD_RE.finditer(prompt)]
    for index in range(len(words)):
        phrase: list[str] = []
        for offset in range(MAX_TERM_PHRASE_WORDS):
            position = index + offset
            if position >= len(words):
                break
            if offset and TERM_PHRASE_GAP_RE.fullmatch(
                prompt[words[position - 1][1] : words[position][0]]
            ) is None:
                break
            phrase.append(normalize_term(words[position][2]))
            if term_digest(key, " ".join(phrase)) in digests:
                found.append((words[index][0], words[position][1]))
    if list_name == "internal-hostnames":
        for match in HOSTNAME_RE.finditer(prompt):
            labels = normalize_term(match.group(0)).split(".")
            if any(
                term_digest(key, ".".join(labels[start:])) in digests
                for start in range(len(labels))
            ):
                found.append((match.start(), match.end()))
    return sorted(set(found))


def _compile_detector(implementation: dict[str, Any]) -> re.Pattern[str]:
    flag_value = 0
    for flag in implementation["flags"]:
        if flag == "IGNORECASE":
            flag_value |= re.IGNORECASE
        elif flag == "MULTILINE":
            flag_value |= re.MULTILINE
        else:
            raise GuardError("policy-invalid")
    try:
        return re.compile(implementation["pattern"], flag_value)
    except re.error as exc:
        raise GuardError("policy-invalid") from exc


def _read_event(limit: int) -> tuple[bytes, dict[str, Any] | None]:
    raw = sys.stdin.buffer.read(limit + 1)
    if len(raw) > limit:
        return raw, None
    try:
        event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw, None
    return raw, event if isinstance(event, dict) else None


def _valid_tckn(candidate: str) -> bool:
    digits = [int(value) for value in candidate if value.isdigit()]
    if len(digits) != 11 or digits[0] == 0:
        return False
    tenth = ((sum(digits[0:9:2]) * 7) - sum(digits[1:8:2])) % 10
    return digits[9] == tenth and digits[10] == sum(digits[:10]) % 10


def _valid_luhn(candidate: str) -> bool:
    digits = [int(value) for value in candidate if value.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    if PAYMENT_CARD_ISSUER_RE.fullmatch("".join(str(value) for value in digits)) is None:
        return False
    total = 0
    parity = len(digits) % 2
    for index, value in enumerate(digits):
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _valid_iban(candidate: str) -> bool:
    normalized = candidate.replace(" ", "").upper()
    if (
        not normalized.isascii()
        or not normalized.isalnum()
        or not 15 <= len(normalized) <= 34
        or not normalized[:2].isalpha()
        or not normalized[2:4].isdigit()
        or (normalized.startswith("TR") and len(normalized) != 26)
    ):
        return False
    remainder = 0
    for character in normalized[4:] + normalized[:4]:
        expanded = character if character.isdigit() else str(ord(character) - ord("A") + 10)
        for digit in expanded:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _entropy_bits(value: str) -> float:
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    total = len(value)
    return -sum(count / total * math.log2(count / total) for count in counts.values())


def _name_like(value: str) -> bool:
    if SECRET_NAME_RE.fullmatch(value) is None or any(character.isdigit() for character in value):
        return False
    return value.islower() or value.isupper() or SECRET_CAMEL_CASE_RE.fullmatch(value) is not None


def _reference_like(value: str) -> bool:
    """True for a name or a dotted chain of names that points at where a value is kept."""
    segments = value.split(".")
    if len(segments) > 1 and segments[0].lower() in SECRET_REFERENCE_ROOTS:
        return all(SECRET_NAME_RE.fullmatch(segment) is not None for segment in segments[1:])
    return all(_name_like(segment) for segment in segments)


def _secret_value_shape(candidate: str) -> bool:
    """True when the value after the label can be a secret, not a placeholder or a reference."""
    separator = SECRET_SEPARATOR_RE.match(candidate)
    if separator is None:
        return True
    value = candidate[separator.end() :]
    quoted = len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]
    value = value[1:-1] if quoted else value.rstrip(SECRET_TRAILING_PUNCTUATION)
    if not value or SECRET_PLACEHOLDER_RE.fullmatch(value) is not None:
        return False
    if value.startswith("$") and _reference_like(value[1:]):
        return False
    if not quoted:
        if _reference_like(value.lstrip("@")):
            return False
        call = SECRET_CALL_OR_INDEX_RE.fullmatch(value)
        if call is not None and _reference_like(call.group("head")):
            return False
    return _entropy_bits(value) >= MIN_SECRET_VALUE_ENTROPY_BITS


def _email_address_shape(prompt: str, start: int, candidate: str) -> bool:
    """True when the address-shaped match can be a person's address."""
    local_part, _, domain = candidate.rpartition("@")
    preceding = prompt[max(0, start - URL_PASSWORD_PREFIX_MAX_CHARS) : start]
    if URL_PASSWORD_PREFIX_RE.search(preceding) is not None:
        # The password of a URL credential; it stays a finding on any domain.
        return True
    if preceding.endswith("://") or local_part in EMAIL_NON_ADDRESS_LOCAL_PARTS:
        return False
    domain = domain.lower().rstrip(".")
    if domain.rpartition(".")[2] in EMAIL_RESERVED_TOP_LEVEL_DOMAINS:
        return False
    return not any(
        domain == reserved or domain.endswith("." + reserved) for reserved in EMAIL_RESERVED_DOMAINS
    )


def _labelled_field_value(value: str) -> bool:
    """True when the value after a personal-data label can be a person's name, address or date."""
    value = value.strip()
    quoted = len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]
    value = value[1:-1].strip() if quoted else value.rstrip(SECRET_TRAILING_PUNCTUATION).strip()
    if not value or SECRET_PLACEHOLDER_RE.fullmatch(value) is not None:
        return False
    if not any(character.isalnum() for character in value):
        return False
    if quoted:
        return True
    if value[0] in "$@{[(<" or LABELLED_VALUE_ASSIGNMENT_RE.match(value) is not None:
        return False
    # Code followed by prose: a type name or a code reference first is not a person's data.
    first = value.split()[0].rstrip(",;:")
    if (
        first.casefold() in LABELLED_VALUE_TYPE_WORDS
        or "(" in first
        or "[" in first
        or LABELLED_VALUE_DOTTED_RE.fullmatch(first) is not None
    ):
        return False
    if _reference_like(value):
        return False
    call = SECRET_CALL_OR_INDEX_RE.fullmatch(value)
    if call is not None and _reference_like(call.group("head")):
        return False
    return (
        any(character.isdigit() for character in value)
        or LABELLED_VALUE_WORDS_RE.search(value) is not None
    )


def _match_span(match: re.Match[str]) -> tuple[int, int]:
    """A labelled detector masks only its ``value`` group; the label stays readable."""
    if "value" in match.re.groupindex and match.group("value") is not None:
        return match.span("value")
    return match.span()


def _validated_match(validator: str | None, prompt: str, match: re.Match[str]) -> bool:
    candidate = match.group(0)
    if validator == "labelled-field-value":
        start, end = _match_span(match)
        return _labelled_field_value(prompt[start:end])
    if validator == "secret-value-shape":
        return _secret_value_shape(candidate)
    if validator == "email-address-shape":
        return _email_address_shape(prompt, match.start(), candidate)
    if validator == "tckn-checksum":
        return _valid_tckn(candidate)
    if validator == "iban-mod97":
        return _valid_iban(candidate)
    if validator == "luhn-checksum":
        return _valid_luhn(candidate)
    if validator == "private-key-pem-block":
        raise GuardError("private-key-validator-dispatch-invalid")
    return True


def _private_key_pem_spans(prompt: str) -> list[tuple[int, int]]:
    """Spans of private key blocks: complete, cut short or malformed, but with key material."""
    spans: list[tuple[int, int]] = []
    covered_until = 0
    for begin in PRIVATE_KEY_BEGIN_MARKER_RE.finditer(prompt):
        if begin.start() < covered_until:
            continue
        label = begin.group(0)[len("-----BEGIN ") : -len("-----")]
        end_marker = f"-----END {label}-----"
        end_start = prompt.find(end_marker, begin.end())
        if end_start >= 0:
            if PRIVATE_KEY_MATERIAL_RE.search(prompt, begin.end(), end_start) is None:
                continue
            block_end = end_start + len(end_marker)
        else:
            if PRIVATE_KEY_LEADING_MATERIAL_RE.match(prompt, begin.end()) is None:
                continue
            block_end = len(prompt)
        spans.append((begin.start(), block_end))
        covered_until = block_end
    for end in PRIVATE_KEY_END_MARKER_RE.finditer(prompt):
        if any(start <= end.start() and end.end() <= stop for start, stop in spans):
            continue
        window_start = max(0, end.start() - PRIVATE_KEY_TRAILING_WINDOW_CHARS)
        material = PRIVATE_KEY_TRAILING_MATERIAL_RE.search(prompt[window_start : end.start()])
        if material is not None:
            spans.append((window_start + material.start(), end.end()))
    return sorted(spans)


def _home_account_name() -> str | None:
    """Name of the running user's home directory; ``None`` keeps every email match a finding."""
    try:
        name = Path.home().name
    except (RuntimeError, KeyError, OSError):
        return None
    return name or None


def _is_home_account_segment(prompt: str, start: int, end: int, home_account: str) -> bool:
    """True when ``prompt[start:end]`` is the user's own account segment of a home path."""
    if prompt[start:end] != home_account:
        return False
    if end < len(prompt) and not (prompt[end] in HOME_ACCOUNT_SEGMENT_END or prompt[end].isspace()):
        return False
    root = prompt[max(0, start - HOME_PATH_ROOT_MAX_CHARS) : start]
    return HOME_PATH_ROOT_RE.search(root) is not None


def _line_numbers(line_starts: list[int], starts: list[int]) -> list[int]:
    return sorted({bisect.bisect_right(line_starts, start) + 1 for start in starts})


def _scan(
    prompt: str,
    policy: dict[str, Any],
    home_account: str | None,
    terms: dict[str, Any] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Each matched detector with its action, count, lines and source; never the matched value.

    Term-list detectors run only when ``terms`` is given.
    """
    counts: list[dict[str, object]] = []
    spans: list[dict[str, object]] = []
    line_starts = [index + 1 for index, character in enumerate(prompt) if character == "\n"]
    for detector in policy["detectors"]:
        implementation = detector["implementation"]
        if implementation["kind"] == "term-list":
            if terms is None:
                continue
            validated_spans = _term_spans(prompt, terms, str(implementation["list"]))
        elif implementation["validator"] == "private-key-pem-block":
            validated_spans = _private_key_pem_spans(prompt)
        else:
            pattern = _compile_detector(implementation)
            validated_spans = [
                _match_span(match)
                for match in pattern.finditer(prompt)
                if _validated_match(implementation["validator"], prompt, match)
            ]
            validated_spans = [(start, end) for start, end in validated_spans if end > start]
        if detector["class"] == "email" and home_account is not None:
            validated_spans = [
                (start, end)
                for start, end in validated_spans
                if not _is_home_account_segment(prompt, start, end, home_account)
            ]
        count = len(validated_spans)
        if count:
            lines = _line_numbers(line_starts, [start for start, _ in validated_spans])
            counts.append(
                {
                    "detector_id": detector["id"],
                    "class": detector["class"],
                    "action": detector["action"],
                    "count": count,
                    "lines": lines[:MAX_REPORTED_RECEIPT_LINES],
                    "lines_truncated": len(lines) > MAX_REPORTED_RECEIPT_LINES,
                    "source_ref": detector["source_ref"],
                    # No approved ISO or KVKK mapping exists; the factory never invents one.
                    "legal_refs": [],
                }
            )
            spans.extend(
                {
                    "start": start,
                    "end": end,
                    "detector_id": detector["id"],
                    "class": detector["class"],
                    "action": detector["action"],
                }
                for start, end in validated_spans
            )
    return (
        sorted(counts, key=lambda item: (str(item["detector_id"]), str(item["class"]))),
        sorted(
            spans,
            key=lambda item: (
                int(item["start"]),
                -(int(item["end"]) - int(item["start"])),
                str(item["detector_id"]),
                int(item["end"]),
            ),
        ),
    )


def _non_overlapping_spans(spans: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    selected_end = -1
    for span in spans:
        start = int(span["start"])
        end = int(span["end"])
        if start < 0 or end <= start:
            raise GuardError("redaction-span-invalid")
        if start < selected_end:
            continue
        selected.append(span)
        selected_end = end
    return selected


def _sanitize_prompt(
    prompt: str,
    spans: list[dict[str, object]],
    policy: dict[str, Any],
) -> tuple[str, list[dict[str, object]]]:
    selected = _non_overlapping_spans(spans)
    if not selected:
        return prompt, []
    cursor = 0
    parts: list[str] = []
    token_template = str(policy["persistence"]["redaction_token_template"])
    for span in selected:
        start = int(span["start"])
        end = int(span["end"])
        if end > len(prompt):
            raise GuardError("redaction-span-invalid")
        parts.append(prompt[cursor:start])
        parts.append(token_template.format_map({"class": str(span["class"])}))
        cursor = end
    parts.append(prompt[cursor:])
    return "".join(parts), selected


def _unavailable_prompt_capture() -> dict[str, object]:
    return {
        "mode": "unavailable",
        "text": None,
        "sha256": None,
        "redaction_strategy": "none",
        "redaction_count": 0,
        "redacted_classes": [],
    }


def _prompt_capture(
    prompt: str,
    spans: list[dict[str, object]],
    policy: dict[str, Any],
) -> dict[str, object]:
    for span in spans:
        start = int(span["start"])
        end = int(span["end"])
        if start < 0 or end <= start or end > len(prompt):
            raise GuardError("redaction-span-invalid")
    redacted_classes = sorted({str(span["class"]) for span in spans})
    if WHOLE_PROMPT_REDACTION_CLASSES.intersection(redacted_classes):
        sanitized_prompt = str(policy["persistence"]["whole_prompt_redaction_token"])
        return {
            "mode": "sensitive-whole-prompt-redacted",
            "text": sanitized_prompt,
            "sha256": _sha256(sanitized_prompt.encode("utf-8")),
            "redaction_strategy": str(policy["persistence"]["whole_prompt_redaction_strategy"]),
            "redaction_count": 1,
            "redacted_classes": redacted_classes,
        }

    sanitized_prompt, selected = _sanitize_prompt(prompt, spans, policy)
    return {
        "mode": "sensitive-span-redacted" if selected else "clean-exact",
        "text": sanitized_prompt,
        "sha256": _sha256(sanitized_prompt.encode("utf-8")),
        "redaction_strategy": (
            str(policy["persistence"]["redaction_strategy"]) if selected else "none"
        ),
        "redaction_count": len(selected),
        "redacted_classes": sorted({str(span["class"]) for span in selected}),
    }


def _event_name(client_id: str) -> str:
    return "beforeSubmitPrompt" if client_id == "cursor" else "UserPromptSubmit"


def _finding_explanations(project_root: Path, spans: list[dict[str, object]]) -> list[str]:
    """The ASCII reason and basis lines of every blocking detector, in block-message order.

    A ``record-mask`` match lets the prompt through, so it adds no lines.
    """

    detector_ids: list[str] = []
    for detector_class in BLOCK_CLASS_LABELS:
        for span in spans:
            identifier = str(span.get("detector_id"))
            if (
                span.get("class") == detector_class
                and span.get("action", "block") == "block"
                and identifier not in detector_ids
            ):
                detector_ids.append(identifier)
    try:
        client_path = Path(__file__).resolve().with_name("governance_client.py")
        if client_path.is_symlink() or not client_path.is_file():
            return [EXPLANATION_UNAVAILABLE]
        lines = runpy.run_path(str(client_path))["prompt_explanation_lines"](
            project_root, detector_ids
        )
    except Exception:
        return [EXPLANATION_UNAVAILABLE]
    if not isinstance(lines, list) or not all(
        isinstance(line, str) and line.isascii() and line for line in lines
    ):
        return [EXPLANATION_UNAVAILABLE]
    return lines


def _block_message(
    prompt: str, spans: list[dict[str, object]], explanations: list[str] | None = None
) -> str:
    """Name each blocking data class with its count and line numbers; never the matched value.

    A ``record-mask`` match lets the prompt through, so it is not named here. The blocking
    detectors' reason and basis lines follow on their own lines.
    """
    line_starts = [index + 1 for index, character in enumerate(prompt) if character == "\n"]
    findings: list[str] = []
    for detector_class, label in BLOCK_CLASS_LABELS.items():
        starts = [
            int(span["start"])
            for span in spans
            if span["class"] == detector_class and span.get("action", "block") == "block"
        ]
        if not starts:
            continue
        lines = _line_numbers(line_starts, starts)
        shown = ", ".join(str(line) for line in lines[:MAX_REPORTED_LINES])
        if len(lines) > MAX_REPORTED_LINES:
            shown += " ve sonrasi"
        findings.append(BLOCK_FINDING.format(label=label, count=len(starts), lines=shown))
    return "\n".join([BLOCK_MESSAGE.format(findings="; ".join(findings)), *(explanations or [])])


def _decision_output(client_id: str, blocked: bool, *, message: str = "") -> dict[str, object]:
    if client_id == "cursor":
        result: dict[str, object] = {"continue": not blocked}
        if blocked:
            result["user_message"] = message
        return result
    if client_id == "github-copilot-vscode":
        result = {"continue": not blocked}
        if blocked:
            result.update(
                {
                    "stopReason": message,
                    "systemMessage": message,
                }
            )
        return result
    if not blocked:
        return {}
    if client_id == "claude-code":
        # Claude Code otherwise appends "Original prompt:" and the blocked text to the message it
        # shows and writes to the session file on disk.
        return {
            "decision": "block",
            "reason": message,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "suppressOriginalPrompt": True,
            },
        }
    return {"decision": "block", "reason": message}


def _records() -> dict[str, Any]:
    path = Path(__file__).resolve().with_name("governance_records.py")
    if path.is_symlink() or not path.is_file():
        raise GuardError("record-writer-unavailable")
    return runpy.run_path(str(path))


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _managed_preferences() -> Path | None:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


_SYNC_MODULE: list[dict[str, Any]] = []


def _sync_module() -> dict[str, Any]:
    """The periodic sync script, loaded once per prompt for registration and task upkeep."""
    if not _SYNC_MODULE:
        path = Path(__file__).resolve().with_name("authority_sync.py")
        if path.is_symlink() or not path.is_file():
            raise GuardError("authority-sync-unavailable")
        _SYNC_MODULE.append(runpy.run_path(str(path)))
    return _SYNC_MODULE[0]


def _task_scheduler() -> Any:
    """The operating system's per-user task scheduler for the periodic authority sync."""
    return _sync_module()["default_scheduler"](location=_record_location())


def _device_gate() -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Read the local device stop state before any other check; never a network call."""
    try:
        records = _records()
        decision, state = records["device_gate"](
            location=_record_location(), managed_preferences=_managed_preferences()
        )
    except Exception:
        return "allow", None, None
    return decision, state, records


def _sync_notices(
    decision: str, state: dict[str, Any] | None, records: dict[str, Any] | None
) -> list[str]:
    """Register this project for the periodic sync, keep its task installed, collect notices."""
    if records is None:
        return []
    notices: list[str] = []
    try:
        project_root = Path(__file__).resolve(strict=True).parents[2]
        project_id = _read_project_id(project_root)
    except Exception:
        return notices
    if decision == "allow-warn" and records["unsynced_too_long"](
        project_id, location=_record_location()
    ):
        notices.append(str(records["DEVICE_UNVERIFIED_WARNING"]))
    if records["update_pending"](state, project_id):
        notices.append(str(records["UPDATE_PENDING_NOTICE"]))
    try:
        sync = _sync_module()
        notices.extend(
            sync["on_prompt"](
                project_root,
                project_id,
                python=Path(sys.executable),
                location=_record_location(),
                scheduler=_task_scheduler(),
                records=records,
            )
        )
    except Exception:
        notices.append("KT_SYNC_TASK_UNAVAILABLE: Yonetisim esitleme gorevi kurulamadi.")
    return notices


def _native(record: dict[str, object], field: str) -> str | None:
    """A record carries a session or turn only when the client supplied it; never a local one."""
    value = record.get(field)
    if record.get(f"{field}_source") != "client-envelope" or not isinstance(value, str):
        return None
    return value


def _write_receipt(receipt: dict[str, object]) -> str | None:
    """Persist the receipt in the shared root; return a warning code instead of blocking."""

    _validate_receipt_for_persistence(receipt)
    client_id = str(receipt["client_id"])
    event_id = str(receipt["event_id"])
    if client_id not in CLIENTS or EVENT_ID_RE.fullmatch(event_id) is None:
        raise GuardError("receipt-identity-invalid")
    project_id = str(receipt["project_id"])
    context = {
        "client": client_id,
        "client_source": "command",
        "session_hash": _native(receipt, "prompt_session_id"),
        "turn_hash": _native(receipt, "prompt_turn_id"),
        "identity_source": (
            "client-envelope"
            if _native(receipt, "prompt_session_id") and _native(receipt, "prompt_turn_id")
            else "unavailable"
        ),
    }
    try:
        writer = _records()
        location = _record_location()
        writer["write_event"](
            "prompt-ingress",
            project_id,
            receipt,
            record_id=event_id.removeprefix("event:"),
            context=context,
            location=location,
        )
        if receipt["decision"] == "allow":
            normalizer_path = Path(__file__).resolve().with_name("llm_call_events.py")
            record = runpy.run_path(str(normalizer_path))["event_from_prompt_receipt"](receipt)
            if record is not None:
                writer["write_event"](
                    "llm-call-events",
                    project_id,
                    record,
                    record_id=str(record["event_id"]).removeprefix("event:"),
                    context=context,
                    location=location,
                )
    except Exception as exc:  # A missing record never changes the prompt decision.
        code = getattr(exc, "code", None)
        return (
            code
            if isinstance(code, str) and re.fullmatch(r"[a-z-]{1,64}", code)
            else ("record-write-failed")
        )
    return None


def prompt_source_ref(project_id: str, event_token: str) -> str:
    return f"record:v1:{project_id}:prompt-ingress:{event_token}"


def prompt_metadata(record: dict[str, Any]) -> dict[str, object]:
    """Project a stored prompt-ingress record to its content-free metadata; never a verdict."""

    body = record.get("body")
    if not isinstance(body, dict) or record.get("kind") != "prompt-ingress":
        raise GuardError("prompt-record-invalid")
    _validate_receipt_for_persistence(body)
    token = record.get("record_id")
    if (
        not isinstance(token, str)
        or body.get("event_id") != f"event:{token}"
        or body.get("project_id") != record.get("project_id")
    ):
        raise GuardError("prompt-record-invalid")
    capture = body["prompt_capture"]
    payload = (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return {
        "schema_version": "2.0",
        "kind": "PromptIngressMetadata",
        "source_receipt_path": prompt_source_ref(str(body["project_id"]), token),
        "source_receipt_sha256": _sha256(payload),
        "prompt_capture_sha256": capture["sha256"],
        **{
            key: body[key]
            for key in (
                "project_id",
                "client_id",
                "event",
                "event_id",
                "occurred_at",
                "prompt_session_id",
                "prompt_session_id_source",
                "prompt_turn_id",
                "prompt_turn_id_source",
                "decision",
                "outcome",
                "model",
            )
        },
    }


def _validate_receipt_for_persistence(receipt: dict[str, object]) -> None:
    if (
        receipt.get("schema_version") != "2.0"
        or receipt.get("kind") != "PromptIngressReceipt"
        or receipt.get("phase") != "sanitized-user-prompt-audit-phase-1"
        or receipt.get("capture_scope") != "user-prompt-text-only"
        or receipt.get("raw_sensitive_content_recorded") is not False
        or receipt.get("excluded_content_recorded") is not False
        or PROHIBITED_RECEIPT_KEYS.intersection(receipt)
    ):
        raise GuardError("receipt-invalid")

    try:
        _event_normalizer()["validate_model"](receipt.get("model"))
    except Exception:
        raise GuardError("receipt-invalid") from None

    capture = receipt.get("prompt_capture")
    detector_counts = receipt.get("detector_counts")
    if (
        not isinstance(capture, dict)
        or set(capture) != PROMPT_CAPTURE_KEYS
        or not isinstance(detector_counts, list)
    ):
        raise GuardError("receipt-invalid")
    for detector_count in detector_counts:
        if not isinstance(detector_count, dict) or set(detector_count) != DETECTOR_COUNT_KEYS:
            raise GuardError("receipt-invalid")
        number = detector_count.get("count")
        lines = detector_count.get("lines")
        if (
            detector_count.get("class") not in DETECTOR_CLASSES
            or detector_count.get("action") not in DETECTOR_ACTIONS
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            or not isinstance(lines, list)
            or not lines
            or any(not isinstance(line, int) or isinstance(line, bool) or line < 1 for line in lines)
            or lines != sorted(set(lines))
            or len(lines) > min(number, MAX_REPORTED_RECEIPT_LINES)
            or not isinstance(detector_count.get("lines_truncated"), bool)
            or not isinstance(detector_count.get("source_ref"), str)
            or detector_count.get("legal_refs") != []
        ):
            raise GuardError("receipt-invalid")
    _validate_term_list_receipt(receipt.get("term_list"), receipt.get("outcome"))

    outcome = receipt.get("outcome")
    decision = receipt.get("decision")
    mode = capture.get("mode")
    text = capture.get("text")
    digest = capture.get("sha256")
    strategy = capture.get("redaction_strategy")
    count = capture.get("redaction_count")
    classes = capture.get("redacted_classes")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or not isinstance(classes, list)
        or classes != sorted(set(classes))
        or any(item not in DETECTOR_CLASSES for item in classes)
    ):
        raise GuardError("receipt-invalid")

    if isinstance(text, str):
        if digest != _sha256(text.encode("utf-8")):
            raise GuardError("receipt-invalid")
    elif text is not None or digest is not None:
        raise GuardError("receipt-invalid")

    if outcome == "clean":
        valid = (
            decision == "allow"
            and detector_counts == []
            and mode == "clean-exact"
            and isinstance(text, str)
            and strategy == "none"
            and count == 0
            and classes == []
        )
    elif outcome in {"matched", "record-masked"}:
        detector_classes = {str(item["class"]) for item in detector_counts}
        blocking = any(item["action"] == "block" for item in detector_counts)
        # Overlapping matches leave one mask in the text, so a counted class may have no own mask.
        common_valid = (
            decision == ("block" if outcome == "matched" else "allow")
            and blocking is (outcome == "matched")
            and bool(detector_counts)
            and isinstance(text, str)
            and count >= 1
            and bool(classes)
            and set(classes) <= detector_classes
        )
        if mode == "sensitive-span-redacted":
            valid = (
                common_valid
                and strategy == "validated-detector-spans-v1"
                and not WHOLE_PROMPT_REDACTION_CLASSES.intersection(classes)
            )
        elif mode == "sensitive-whole-prompt-redacted":
            valid = (
                common_valid
                and text == "[REDACTED:high-risk-prompt]"
                and strategy == "whole-prompt-redacted-v1"
                and count == 1
                and bool(WHOLE_PROMPT_REDACTION_CLASSES.intersection(classes))
            )
        else:
            valid = False
    elif outcome in {"input-invalid", "guard-error"}:
        valid = (
            decision == "block"
            and detector_counts == []
            and mode == "unavailable"
            and text is None
            and digest is None
            and strategy == "none"
            and count == 0
            and classes == []
        )
    else:
        valid = False
    if not valid:
        raise GuardError("receipt-invalid")


def _validate_term_list_receipt(value: object, outcome: object) -> None:
    """A scanned prompt names the term list applied; an unscanned one carries none."""
    if outcome in {"input-invalid", "guard-error"}:
        if value is not None:
            raise GuardError("receipt-invalid")
        return
    if (
        not isinstance(value, dict)
        or set(value) != {"institution_list", "applied", "version", "sha256"}
        or value.get("institution_list") not in {"loaded", "missing", "invalid"}
        or value.get("applied")
        != ("institution" if value.get("institution_list") == "loaded" else "sample")
        or not isinstance(value.get("version"), str)
        or TERM_LIST_VERSION_RE.fullmatch(str(value.get("version"))) is None
        or not isinstance(value.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256"))) is None
    ):
        raise GuardError("receipt-invalid")


def _receipt(
    *,
    client_id: str,
    policy: dict[str, Any] | None,
    policy_digest: str | None,
    decision: str,
    outcome: str,
    prompt_capture: dict[str, object],
    detector_counts: list[dict[str, object]],
    invocation_context: dict[str, object],
    term_list: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": "PromptIngressReceipt",
        "phase": "sanitized-user-prompt-audit-phase-1",
        **invocation_context,
        "client_id": client_id,
        "event": _event_name(client_id),
        "decision": decision,
        "outcome": outcome,
        "policy_availability": "available" if policy is not None else "unavailable",
        "policy_version": policy["metadata"]["version"] if policy is not None else None,
        "policy_sha256": policy_digest,
        "capture_scope": "user-prompt-text-only",
        "prompt_capture": prompt_capture,
        "detector_counts": detector_counts,
        "term_list": term_list,
        "raw_sensitive_content_recorded": False,
        "excluded_content_recorded": False,
    }


_WARNINGS: list[str | None] = []


def _record_context(project_root: Path) -> tuple[str, dict[str, Any], str] | None:
    """Project identity and state policy only label the record; they never decide the prompt."""
    try:
        project_id = _read_project_id(project_root)
        state_policy, state_policy_digest = _read_state_policy(project_root)
    except GuardError as exc:
        code = str(exc)
        _WARNINGS.append(code if re.fullmatch(r"[a-z-]{1,64}", code) else "record-context-invalid")
        return None
    return project_id, state_policy, state_policy_digest


def _finish(
    client_id: str,
    context: tuple[str, dict[str, Any], str] | None,
    event: dict[str, Any] | None,
    *,
    policy: dict[str, Any] | None,
    policy_digest: str | None,
    outcome: str,
    prompt_capture: dict[str, object],
    detector_counts: list[dict[str, object]],
    message: str = "",
    term_list: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    blocked = outcome not in {"clean", "record-masked"}
    receipt: dict[str, object] | None = None
    if context is not None:
        project_id, state_policy, state_policy_digest = context
        receipt = _receipt(
            client_id=client_id,
            policy=policy,
            policy_digest=policy_digest,
            decision="block" if blocked else "allow",
            outcome=outcome,
            prompt_capture=prompt_capture,
            detector_counts=detector_counts,
            term_list=term_list,
            invocation_context=_invocation_context(
                client_id,
                event,
                project_id=project_id,
                state_policy=state_policy,
                state_policy_digest=state_policy_digest,
            ),
        )
        _WARNINGS.append(_write_receipt(receipt))
    return _decision_output(client_id, blocked, message=message), receipt


def _run(client_id: str) -> tuple[dict[str, object], dict[str, object] | None]:
    script_path = Path(__file__)
    if script_path.is_symlink():
        raise GuardError("script-symlink-rejected")
    project_root = script_path.resolve(strict=True).parents[2]
    context = _record_context(project_root)
    unavailable = _unavailable_prompt_capture()
    try:
        policy, policy_digest = _read_policy(project_root)
    except GuardError:
        _, event = _read_event(FALLBACK_MAX_EVENT_BYTES)
        return _finish(
            client_id,
            context,
            event,
            policy=None,
            policy_digest=None,
            outcome="guard-error",
            prompt_capture=unavailable,
            detector_counts=[],
            message=SAFE_ERROR_MESSAGE,
        )
    _, event = _read_event(policy["limits"]["max_event_bytes"])
    expected_event = _event_name(client_id)
    supplied_event = event.get("hook_event_name") if event is not None else None
    if client_id == "cursor":
        event_name_valid = supplied_event in {None, "beforeSubmitPrompt"}
    else:
        event_name_valid = supplied_event == expected_event
    prompt = event.get("prompt") if event is not None else None
    if (
        event is None
        or not event_name_valid
        or not isinstance(prompt, str)
        or "\x00" in prompt
        or len(prompt.encode("utf-8")) > policy["limits"]["max_prompt_bytes"]
    ):
        return _finish(
            client_id,
            context,
            event,
            policy=policy,
            policy_digest=policy_digest,
            outcome="input-invalid",
            prompt_capture=unavailable,
            detector_counts=[],
            message=INPUT_INVALID_MESSAGE.format(
                limit_kb=max(1, policy["limits"]["max_prompt_bytes"] // 1024)
            ),
        )
    try:
        terms, term_list = _load_terms(policy)
        counts, spans = _scan(prompt, policy, _home_account_name(), terms)
        prompt_capture = _prompt_capture(prompt, spans, policy)
    except GuardError:
        return _finish(
            client_id,
            context,
            event,
            policy=policy,
            policy_digest=policy_digest,
            outcome="guard-error",
            prompt_capture=unavailable,
            detector_counts=[],
            message=SAFE_ERROR_MESSAGE,
        )
    blocking = any(item["action"] == "block" for item in counts)
    return _finish(
        client_id,
        context,
        event,
        policy=policy,
        policy_digest=policy_digest,
        outcome="matched" if blocking else ("record-masked" if counts else "clean"),
        prompt_capture=prompt_capture,
        detector_counts=counts,
        message=(
            _block_message(prompt, spans, _finding_explanations(project_root, spans))
            if blocking
            else ""
        ),
        term_list=term_list,
    )


def record_content_classes(
    project_root: Path, texts: list[str], location: Any = None
) -> list[str]:
    """Data classes the prompt policy finds in record text; the record writer's last gate.

    The same engine as the prompt: the project's validated policy and the applied term list.
    """
    policy, _ = _read_policy(project_root)
    terms, _ = _load_terms(policy, location)
    found: set[str] = set()
    for text in texts:
        counts, _ = _scan(text, policy, None, terms)
        found.update(str(item["class"]) for item in counts)
    return sorted(found)


def _interpreter_status() -> str | None:
    """Move to an accepted Python once; an interpreter below the profile stops the prompt."""
    script = Path(__file__)
    try:
        status: str | None = _records()["ensure_profile_interpreter"](
            script.resolve(strict=True).parents[2], script, sys.argv[1:]
        )
    except Exception:
        return "python-runtime-mismatch"
    return status


def _repair_command() -> str:
    """The distributed `.venv` preparation command on a Python the profile accepts."""
    try:
        records = _records()
        minimum = records["profile_python_minimum"](Path(__file__).resolve().parents[2])
        if isinstance(minimum, str):
            return str(records["repair_command"](minimum))
    except Exception:
        pass
    # Without a readable profile the script itself reports which Python it needs.
    return "python3 .kt-scaffold/hooks/python_environment.py hazirla"


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--client", choices=CLIENTS, required=True)
    arguments = parser.parse_args()
    decision, state, records = _device_gate()
    if records is not None and decision in {"stop", "unverified"}:
        with contextlib.suppress(OSError):
            sys.stdin.buffer.read(FALLBACK_MAX_EVENT_BYTES + 1)
        output = _decision_output(
            arguments.client, True, message=records["gate_message"](decision, marker=False)
        )
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        records["record_refusal"](
            "prompt", decision, client=arguments.client, location=_record_location()
        )
        return 0
    if _interpreter_status() is not None:
        with contextlib.suppress(OSError):
            sys.stdin.buffer.read(FALLBACK_MAX_EVENT_BYTES + 1)
        output = _decision_output(
            arguments.client, True, message=INTERPRETER_MESSAGE.format(command=_repair_command())
        )
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        return 0
    try:
        output, _receipt_payload = _run(arguments.client)
    except Exception as exc:  # The hook must never disclose input or policy internals.
        with contextlib.suppress(OSError):
            sys.stdin.buffer.read(FALLBACK_MAX_EVENT_BYTES + 1)
        output = _decision_output(arguments.client, True, message=_error_message(exc))
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    for code in dict.fromkeys(code for code in _WARNINGS if code is not None):
        print(RECORD_WARNING.format(code=code), file=sys.stderr)
    for notice in dict.fromkeys(_sync_notices(decision, state, records)):
        print(notice, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
