#!/usr/bin/env python3
"""Dependency-free governance commands over the shared, repository-free governance root.

`restore` is the one command that writes project files: it puts drifted scaffold-managed files
back to the bytes the scaffold recorded for them, taken only from the project's commit history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PureWindowsPath
from typing import Any, NoReturn, cast

# Started with the host's python3 before moving to the project's `.venv`; keep 3.9 syntax.
UTC = timezone.utc  # noqa: UP017
MAX_REQUEST_BYTES = 16 * 1024 * 1024 + 4096
PROMPT_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "source_receipt_path",
        "source_receipt_sha256",
        "prompt_capture_sha256",
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
    }
)
CLIENT_SESSION_ENVIRONMENT = {
    "claude-code": ("CLAUDE_CODE_SESSION_ID",),
    "codex": ("CODEX_SESSION_ID", "CODEX_THREAD_ID"),
    "cursor": ("CURSOR_SESSION_ID", "CURSOR_CONVERSATION_ID"),
    "github-copilot-vscode": ("VSCODE_SESSION_ID",),
}
# Codex runs a project hook only after the user trusts its exact definition. Project creation and
# a hook-changing update record that trust; a copied project or an edited hook file needs the
# user's own step on the VS Code extension's Hooks settings page, which has no `/hooks` command.
PROMPT_HOOK_TRUST_GUIDANCE = {
    "codex": (
        "Codex bu projenin kancalarını (mesaj gönderince kendiliğinden çalışan denetimler) büyük "
        "olasılıkla onaylı bulmadığı için çalıştırmadı. Proje bu bilgisayarda proje fabrikasıyla "
        "oluşturulduysa veya güncellendiyse onay kendiliğinden yazılmıştır; bu projede yeni bir "
        "sohbet açıp isteğinizi orada gönderin. Proje başka yerden kopyalandıysa ya da kancalar "
        "sonradan değiştiyse onayı bir kez siz verin: VS Code'da Codex kenar çubuğundaki dişli "
        "simgesinden Codex Settings'i açın; Hooks bölümünde bu projenin kancalarını tek tek Trust "
        "ile onaylayın. Liste boşsa önce bu projede bir sohbet açın, sonra Reload hooks'a basın. "
        "Onaydan sonra isteğinizi yeni bir mesajla gönderin."
    ),
}
PROJECT_ID_RE = re.compile(r"project-(?!0{32}$)[0-9a-f]{32}")
SESSION_ID_RE = re.compile(r"session:client\.[0-9a-f]{64}")
TURN_ID_RE = re.compile(r"turn:(?:client\.[0-9a-f]{64}|local\.(?!0{32}$)[0-9a-f]{32})")
EVENT_ID_RE = re.compile(r"event:(?!0{32}$)[0-9a-f]{32}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
MAX_PROMPT_METADATA_BYTES = 16 * 1024
MAX_PROMPT_METADATA_FILES = 512
MAX_REVIEW_ARTIFACT_BYTES = 16 * 1024 * 1024
# Mirrors policies/aggregation/governed-review.yml#security_critical_veto; a factory parity
# test binds both.  A covered Agent's accepted critical finding removes PASS whatever the
# weighted score is.
SECURITY_CRITICAL_VETO_AGENTS = frozenset(
    {"agent:bilgi-guvenligi", "agent:uygulama-guvenligi", "agent:gizlilik-kvkk"}
)
RUN_ID_RE = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]{3,119}")
AGENT_SLUG_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
# The only observation fields a specialist evaluates; every other field comes from the run's
# bindings input, so no Agent transcribes identifiers or digests.
EVALUATED_FIELDS = (
    "agent_id",
    "candidate_responses",
    "error_code",
    "error_summary",
    "findings",
    "scanned_files",
    "status",
)
CANDIDATE_GUIDANCE = {
    "CANDIDATE_RESPONSE_MISSING": (
        "Uzman, bağlama dosyasındaki `deterministic_candidates` listesinin her adayına "
        "`candidate_responses` içinde bir yanıt vermedi. Kural tabanlı taramanın bulduğu her "
        "eşleşme yanıtlanmalıdır: `confirmed` (gerçek sorun) ya da gerekçeli `dismissed` "
        "(gerçek sorun değil)."
    ),
    "CANDIDATE_RESPONSE_DUPLICATE": (
        "Aynı aday için birden fazla yanıt var; her aday kimliğine tek yanıt verilir."
    ),
    "CANDIDATE_UNKNOWN": (
        "Yanıttaki aday kimliği bu uzmanın bağlama dosyasında yok; yalnız "
        "`deterministic_candidates` listesindeki kimlikler yanıtlanır."
    ),
    "CANDIDATE_REASON_MISSING": (
        "Reddedilen (`dismissed`) adayın gerekçesi eksik veya 20 karakterden kısa. Eşleşmenin "
        "neden gerçek bir sorun olmadığını sade dille yaz; eşleşen değeri yazma."
    ),
}
GUARD_REASON_RE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
GIT_TIMEOUT_SECONDS = 30
MAX_JSON_BYTES = 4 * 1024 * 1024
CLIENT_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}")
TEST_AUTOMATION_AGENT = "agent:test-otomasyonu"
RUN_CONTEXT_CANONICALIZATION = "kt-governed-review-run-context-json-v1"
RULE_PATH = "rules/13-tamamlanma-tanimi.md"
ORCHESTRATION_PATH = "agent-platform/orchestrations/governed-review.yml"
AGGREGATION_POLICY_PATH = "agent-platform/policies/aggregation/governed-review.yml"
AGGREGATION_INSTRUCTIONS_PATH = (
    "agent-platform/policies/aggregation/governed-review-instructions.md"
)
EVALUATOR_POLICY_PATH = "agent-platform/policies/aggregation/governed-review-agentic-evaluation.yml"
EXPLANATION_TEMPLATES_PATH = (
    "agent-platform/policies/aggregation/decision-explanation-templates.yml"
)
# `restore` takes a file's recorded digest from the scaffold ownership manifest that the drift
# check trusts and its bytes only from commit trees, never from the Git index.
MANAGED_MANIFEST_PATH = ".kt-scaffold/manifest.json"
MAX_RESTORE_BLOB_BYTES = 16 * 1024 * 1024
RESTORE_FILE_MODES = {"100644": 0o644, "100755": 0o755}
RESTORE_GUIDANCE = {
    "UNSAFE_PATH": "Yol, proje klasörü içinde göreli bir dosya yolu olmalı.",
    "UNMANAGED_PATH": (
        "Yalnız proje iskeletinin yönettiği, .kt-scaffold/manifest.json kaydındaki dosyalar geri "
        "alınır."
    ),
    "LINKED_PATH": (
        "Yolda sembolik bağlantı (başka bir yeri gösteren kısayol) var veya yol normal bir dosyayı "
        "göstermiyor."
    ),
    "NOT_IN_HISTORY": (
        "Dosyanın kaydedilmiş doğru hâli (kayıttaki parmak izine uyan içerik) bu projenin commit "
        "geçmişinde yok. Dosyayı elle yazma; projeyi fabrika güncellemesiyle güncelle: asistanın "
        "proje fabrikası bağlantısındaki (MCP) proje_iskelesini_esitle aracı veya kt-iskelet "
        "guncelle komutu."
    ),
    "WRITE_FAILED": "Dosya yazılamadı; yazma izni olmayabilir.",
}


class GovernanceClientError(ValueError):
    """A fixed public error code, never a filesystem path or raw exception text."""

    def __init__(
        self,
        code: str,
        *,
        reason_code: str | None = None,
        violation: dict[str, object] | None = None,
        guidance: str | None = None,
    ) -> None:
        super().__init__(code)
        self.reason_code = (
            reason_code
            if reason_code is not None and GUARD_REASON_RE.fullmatch(reason_code)
            else None
        )
        self.violation = violation
        # A fixed hook remedy for the reason code, such as the draft PRD version line.
        self.guidance = guidance or None


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise GovernanceClientError("invalid-request")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GovernanceClientError("invalid-request")
        result[key] = value
    return result


def _invalid_constant(_: str) -> object:
    raise GovernanceClientError("invalid-request")


def _decode(payload: bytes) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise GovernanceClientError("invalid-request") from None


def preflight() -> dict[str, object]:
    """Report the shared root and interpreter readiness; read and write no record."""
    try:
        result = _hook_module("governance_records.py")["preflight"](Path.cwd(), _record_location())
    except Exception:
        return {"ok": False, "root_status": "record-writer-unavailable"}
    return cast(dict[str, object], result)


def record_consultation(raw: bytes) -> dict[str, object]:
    """Store one advisory single-agent consultation; it never carries a decision or permission."""

    if len(raw) > MAX_REQUEST_BYTES:
        raise GovernanceClientError("request-too-large")
    project_root = Path.cwd().resolve(strict=True)
    record = _decode(raw)
    guard = _hook_module("agentic_review_receipt_guard.py")
    try:
        guard["_validate_against_schema"](
            record,
            "agentic-agent-consultation.schema.json",
            guard["_schema_registry"](project_root),
        )
    except Exception:
        raise GovernanceClientError("consultation-invalid") from None
    if not isinstance(record, dict) or record.get("project_id") != _project_id(project_root):
        raise GovernanceClientError("consultation-invalid")
    writer = _hook_module("governance_records.py")
    try:
        path = writer["write_event"](
            "agent-consultation",
            record["project_id"],
            record,
            context={"client_source": "command"},
            location=_record_location(),
        )
    except writer["RecordError"]:
        raise GovernanceClientError("consultation-unrecorded") from None
    return {"status": "recorded", "record_id": Path(path).stem, "commit_authority": False}


def _read_regular_json(path: Path, *, maximum: int) -> dict[str, object]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_size > maximum
            ):
                raise GovernanceClientError("prompt-metadata-invalid")
            raw = handle.read(maximum + 1)
        value = _decode(raw)
    except GovernanceClientError:
        raise
    except OSError:
        raise GovernanceClientError("prompt-metadata-invalid") from None
    if not isinstance(value, dict):
        raise GovernanceClientError("prompt-metadata-invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GovernanceClientError("review-artifact-invalid") from None


def _canonical_sha256(value: object, *, excluding: str | None = None) -> str:
    if excluding is not None:
        if not isinstance(value, dict) or excluding not in value:
            raise GovernanceClientError("review-artifact-invalid")
        value = {key: item for key, item in value.items() if key != excluding}
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _read_review_json(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        if path.is_symlink():
            raise GovernanceClientError("review-artifact-invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_size > MAX_REVIEW_ARTIFACT_BYTES
            ):
                raise GovernanceClientError("review-artifact-invalid")
            raw = handle.read(MAX_REVIEW_ARTIFACT_BYTES + 1)
        value = _decode(raw)
    except GovernanceClientError:
        raise
    except OSError:
        raise GovernanceClientError("review-artifact-invalid") from None
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise GovernanceClientError("review-artifact-invalid")
    return raw, value


def _utc_second(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GovernanceClientError("review-artifact-invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise GovernanceClientError("review-artifact-invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise GovernanceClientError("review-artifact-invalid")
    return parsed


def _mtime_second(path: Path) -> datetime:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        raise GovernanceClientError("review-artifact-invalid") from None
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise GovernanceClientError("review-artifact-invalid")
    return datetime.fromtimestamp(info.st_mtime_ns // 1_000_000_000, UTC)


def _iso_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _review_event(
    *,
    receipt: dict[str, object],
    decision: dict[str, object],
    position: int,
    observed_at: datetime,
    previous_sha256: str,
    result: dict[str, object] | None,
) -> dict[str, object]:
    execution = receipt.get("execution")
    evidence = receipt.get("decision_evidence")
    snapshot = receipt.get("snapshot")
    if not all(isinstance(value, dict) for value in (execution, evidence, snapshot)):
        raise GovernanceClientError("review-artifact-invalid")
    client = execution.get("client")
    audit_replay = evidence.get("audit_replay")
    if not isinstance(client, dict) or not isinstance(audit_replay, dict):
        raise GovernanceClientError("review-artifact-invalid")
    prompt_binding = audit_replay.get("prompt_binding")
    if not isinstance(prompt_binding, dict) or not isinstance(prompt_binding.get("envelope"), dict):
        raise GovernanceClientError("review-artifact-invalid")
    envelope = prompt_binding["envelope"]
    if not isinstance(envelope, dict):
        raise GovernanceClientError("review-artifact-invalid")
    if position == 0:
        event_name, reason_code = "review_started", "REVIEW_STARTED"
    elif position == 13:
        reasons = decision.get("reason_codes")
        if not isinstance(reasons, list) or not reasons or not isinstance(reasons[0], str):
            raise GovernanceClientError("review-artifact-invalid")
        event_name, reason_code = "review_completed", reasons[0]
    else:
        event_name, reason_code = "agent_completed", "AGENT_OK"
    event: dict[str, object] = {
        "schema_version": "1.1",
        "kind": "AgenticGovernedReviewAuditEvent",
        "evidence_profile": "phase1-agentic-advisory",
        "receipt_id": receipt.get("receipt_id"),
        "project_id": receipt.get("project_id"),
        "client_id": client.get("id"),
        "prompt_session_id": execution.get("session_id"),
        "prompt_turn_id": envelope.get("source_prompt_turn_id"),
        "event": event_name,
        "chain_position": position,
        "event_canonicalization": "kt-agentic-review-audit-event-json-v1",
        "run_id": receipt.get("run_id"),
        "trace_id": receipt.get("trace_id"),
        "span_id": (
            decision.get("span_id")
            if position == 13
            else result.get("span_id")
            if result is not None
            else receipt.get("trace_id", "")[:16]
        ),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "agentic_evaluator": receipt.get("agentic_evaluator"),
        "agent_id": result.get("agent_id") if result is not None else None,
        "invocation_id": result.get("invocation_id") if result is not None else None,
        "status": result.get("status") if result is not None else None,
        "decision": decision.get("decision") if position == 13 else None,
        "reason_code": reason_code,
        "report_sha256": result.get("report_sha256") if result is not None else None,
        "decision_sha256": receipt.get("decision_sha256") if position == 13 else None,
        "decision_evidence_sha256": evidence.get("evidence_sha256"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "previous_event_sha256": previous_sha256,
        "event_sha256": "0" * 64,
        "native_result": None,
        "claim_boundary": {
            "immutable_audit": False,
            "otel_exported": False,
            "production_authority": False,
            "native_hook_result_recorded": False,
            "commit_retry_recorded": False,
        },
        "data_handling": {
            "raw_prompt_stored": False,
            "source_content_stored": False,
            "pii_stored": False,
            "secret_stored": False,
        },
        "observed_at": _iso_utc(observed_at),
    }
    event["event_sha256"] = _canonical_sha256(event, excluding="event_sha256")
    return event


def _build_review_audit_events(
    run_root: Path,
    receipt_path: Path,
    receipt: dict[str, object],
    decision_raw: bytes,
    decision: dict[str, object],
) -> list[dict[str, object]]:
    if (
        receipt.get("decision") != "PASS"
        or decision.get("decision") != "PASS"
        or receipt.get("run_id") != run_root.name
        or receipt.get("decision_sha256") != hashlib.sha256(decision_raw).hexdigest()
        or receipt.get("receipt_sha256") != _canonical_sha256(receipt, excluding="receipt_sha256")
    ):
        raise GovernanceClientError("review-artifact-invalid")
    results = receipt.get("agent_results")
    evidence = receipt.get("decision_evidence")
    if not isinstance(results, list) or len(results) != 12 or not isinstance(evidence, dict):
        raise GovernanceClientError("review-artifact-invalid")
    audit_replay = evidence.get("audit_replay")
    if not isinstance(audit_replay, dict) or not isinstance(
        audit_replay.get("primary_evaluation"), dict
    ):
        raise GovernanceClientError("review-artifact-invalid")
    primary_started = _utc_second(audit_replay["primary_evaluation"].get("started_at"))
    timed_results: list[tuple[datetime, str, dict[str, object]]] = []
    report_root = run_root / "reports"
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("agent_id"), str):
            raise GovernanceClientError("review-artifact-invalid")
        slug = item["agent_id"].removeprefix("agent:")
        expected_relative = f"governed-review/{run_root.name}/reports/{slug}.json"
        if item.get("report_path") != expected_relative or item.get("status") != "ok":
            raise GovernanceClientError("review-artifact-invalid")
        report_path = report_root / f"{slug}.json"
        report_raw, _ = _read_review_json(report_path)
        if item.get("report_sha256") != hashlib.sha256(report_raw).hexdigest():
            raise GovernanceClientError("review-artifact-invalid")
        timed_results.append((_mtime_second(report_path), item["agent_id"], item))
    timed_results.sort(key=lambda item: (item[0], item[1]))
    if timed_results[-1][0] > primary_started:
        raise GovernanceClientError("artifact-chronology-invalid")
    receipt_created = _utc_second(receipt.get("created_at"))
    completed = _mtime_second(receipt_path)
    if completed < receipt_created or completed > datetime.now(UTC):
        raise GovernanceClientError("artifact-chronology-invalid")
    previous = str(receipt["receipt_sha256"])
    events = [
        _review_event(
            receipt=receipt,
            decision=decision,
            position=0,
            observed_at=timed_results[0][0],
            previous_sha256=previous,
            result=None,
        )
    ]
    previous = str(events[-1]["event_sha256"])
    for position, (observed_at, _agent_id, result) in enumerate(timed_results, start=1):
        event = _review_event(
            receipt=receipt,
            decision=decision,
            position=position,
            observed_at=observed_at,
            previous_sha256=previous,
            result=result,
        )
        events.append(event)
        previous = str(event["event_sha256"])
    events.append(
        _review_event(
            receipt=receipt,
            decision=decision,
            position=13,
            observed_at=completed,
            previous_sha256=previous,
            result=None,
        )
    )
    return events


def _review_run(project_root: Path, run_id: str) -> tuple[str, Path]:
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise GovernanceClientError("invalid-request")
    project_id = _project_id(project_root)
    writer = _hook_module("governance_records.py")
    try:
        run_root = writer["review_area"](project_id, location=_record_location()) / run_id
    except writer["RecordError"]:
        raise GovernanceClientError("review-artifact-invalid") from None
    if run_root.is_symlink() or not run_root.is_dir():
        raise GovernanceClientError("review-artifact-invalid")
    return project_id, run_root


def _read_run_input(path: Path) -> dict[str, object]:
    """One run input or evaluation: a regular, unlinked JSON object owned by this user."""

    try:
        if path.is_symlink():
            raise GovernanceClientError("review-artifact-invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_size > MAX_REVIEW_ARTIFACT_BYTES
            ):
                raise GovernanceClientError("review-artifact-invalid")
            raw = handle.read(MAX_REVIEW_ARTIFACT_BYTES + 1)
    except GovernanceClientError:
        raise
    except OSError:
        raise GovernanceClientError("review-artifact-invalid") from None
    value = _decode(raw)
    if not isinstance(value, dict):
        raise GovernanceClientError("review-artifact-invalid")
    return value


def _staged_paths(project_root: Path, error: str = "evaluation-invalid") -> set[str]:
    """Repository-relative paths the staged candidate adds, changes or deletes."""

    executable = shutil.which("git")
    if executable is None:
        raise GovernanceClientError(error, reason_code="CANDIDATE_UNAVAILABLE")
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            [
                executable,
                "-C",
                str(project_root),
                "diff",
                "--cached",
                "--name-only",
                "--no-renames",
                "-z",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
        if completed.returncode != 0:
            raise GovernanceClientError(error, reason_code="CANDIDATE_UNAVAILABLE")
        return {item for item in completed.stdout.decode("utf-8").split("\0") if item}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise GovernanceClientError(error, reason_code="CANDIDATE_UNAVAILABLE") from None


def _validate_evaluation_scope(project_root: Path, evaluation: dict[str, object]) -> None:
    """Mechanically bind a specialist answer to the staged candidate.

    A rejected answer writes no report, so the main Agent asks the same specialist again with
    the returned reason instead of repeating the whole review.
    """

    findings = evaluation.get("findings")
    scanned = evaluation.get("scanned_files")
    if not isinstance(findings, list) or not isinstance(scanned, list):
        raise GovernanceClientError("evaluation-invalid")
    if scanned:
        candidate = _staged_paths(project_root)
        if any(path not in candidate for path in scanned):
            raise GovernanceClientError("evaluation-invalid", reason_code="SCANNED_FILE_NOT_STAGED")
    covered = set(scanned)
    for finding in findings:
        locations = finding.get("locations") if isinstance(finding, dict) else None
        if isinstance(locations, list) and any(
            isinstance(location, dict) and location.get("path") not in covered
            for location in locations
        ):
            raise GovernanceClientError("evaluation-invalid", reason_code="LOCATION_NOT_SCANNED")


# The governed-review scan: the regex detectors with hard-fail authority, run by code on the
# staged blobs.  The patterns are the packs' own; compilation and checksum validators are the
# prompt-ingress hook's functions, so there is one engine.
SCAN_EXECUTOR_REF = "executor:governance-client/deterministic-scan"
SCAN_MODE = "governed-review-scan"
SCAN_GROUPS = ("blocking", "adjudication")
SCAN_VALIDATORS = ("tckn-checksum", "iban-mod97", "luhn-checksum")
SCAN_RECORD_NAME = "reports/deterministic-scan"
SCAN_CANONICALIZATION = "kt-governed-review-deterministic-scan-json-v1"
MAX_SCAN_TEXT_BYTES = 8 * 1024 * 1024
MAX_SCAN_MATCHES = 512
# Matches past the record limit are counted, not kept; the run is then incomplete anyway.
MAX_SCAN_COLLECTED = 50_000
# A large candidate is matched in worker processes of this same file.  Each loads the packs itself
# and returns their identity, which must equal the parent's; the result never depends on how many
# workers ran.
PARALLEL_SCAN_MIN_CHARACTERS = 2 * 1024 * 1024
PARALLEL_SCAN_CHUNK_CHARACTERS = 2 * 1024 * 1024
MAX_SCAN_WORKERS = 8
SCAN_WORKER_TIMEOUT_SECONDS = 120
# Git checks only the first 8000 bytes to call a file binary; a larger file is never read whole.
BINARY_PROBE_BYTES = 8000
SCAN_BLOB_MODES = frozenset({"100644", "100755", "120000"})
SCAN_GITLINK_MODE = "160000"
SCAN_FILE_SUMMARIES = {
    "binary": "`{path}` taranmadı: ikili dosya (metin değil); karar değişmez.",
    "submodule": (
        "`{path}` taranmadı: alt modül bağı (başka bir deponun commit kimliği); içeriği bu "
        "depoda değil, karar değişmez."
    ),
    "too-large": (
        "`{path}` taranamadı: dosya 8 MiB metin sınırını aşıyor. İnceleme bu yüzden "
        "tamamlanamaz (BLOCKED_INCOMPLETE)."
    ),
    "not-utf8": (
        "`{path}` taranamadı: dosya UTF-8 metin olarak okunamadı. İnceleme bu yüzden "
        "tamamlanamaz (BLOCKED_INCOMPLETE)."
    ),
}
# Blocks of a pack entry read as lists: the detector's own controls and every entry's standard
# references.  Other blocks (source lineage, detector lists) are not needed by the client.
PACK_LIST_BLOCKS = frozenset({"control_refs", "standard_refs"})
SCAN_MATCH_SUMMARIES = {
    "blocking": (
        "`{detector}` kuralı `{path}` dosyasının {lines} eşleşti; eşleşen değer kayda "
        "yazılmadı. Bu kesin kuraldır: eşleşme bulgu sayılır."
    ),
    "adjudication": (
        "`{detector}` kuralı `{path}` dosyasının {lines} eşleşti; eşleşen değer kayda "
        "yazılmadı. Uzman ajan bu eşleşmenin gerçek bir sorun olup olmadığını yanıtlar."
    ),
}


def _scan_failure(reason: str) -> GovernanceClientError:
    return GovernanceClientError("deterministic-scan-invalid", reason_code=reason)


def _pack_scalar(value: str) -> object:
    """One scalar of the factory-written pack: JSON-quoted, single-quoted, `null`, `[]` or plain."""

    value = value.strip()
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except ValueError:
            raise _scan_failure("DETECTOR_PACK_INVALID") from None
        if not isinstance(decoded, str):
            raise _scan_failure("DETECTOR_PACK_INVALID")
        return decoded
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise _scan_failure("DETECTOR_PACK_INVALID")
        return value[1:-1].replace("''", "'")
    if value in {"null", "~"}:
        return None
    if value == "[]":
        return []
    return value


def _pack_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")):
            key = line.split(":", 1)[0]
            if key in sections:
                raise _scan_failure("DETECTOR_PACK_INVALID")
            current = key
            sections[key] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _pack_entries(lines: list[str]) -> list[dict[str, Any]]:
    """Each list entry's direct fields, `implementation` mapping, `control_refs` and
    `standard_refs`; other blocks are skipped.

    The detector and policy packs share this layout, so one reader gives both the detectors and the
    policy controls.
    """

    entries: list[dict[str, Any]] = []
    entry: dict[str, Any] | None = None
    block: str | None = None
    listing: str | None = None
    reference: dict[str, object] | None = None
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("  - id: "):
            entry = {"id": _pack_scalar(line[len("  - id: ") :]), "implementation": {}}
            entries.append(entry)
            block = listing = None
            continue
        if entry is None:
            raise _scan_failure("DETECTOR_PACK_INVALID")
        field = re.fullmatch(r"    ([a-z_]+):(?: (.*))?", line)
        if field is not None:
            key, value = field.group(1), field.group(2)
            block = key if value is None else None
            listing = None
            reference = None
            if value is not None or key in PACK_LIST_BLOCKS:
                if key in entry:
                    raise _scan_failure("DETECTOR_PACK_INVALID")
                entry[key] = _pack_scalar(value) if value is not None else []
            continue
        if block == "control_refs":
            item = re.fullmatch(r"      - (.+)", line)
            if item is None:
                raise _scan_failure("DETECTOR_PACK_INVALID")
            entry[block].append(_pack_scalar(item.group(1)))
            continue
        if block == "standard_refs":
            item = re.fullmatch(r"      - ([a-z_]+): (.+)", line)
            if item is not None:
                reference = {item.group(1): _pack_scalar(item.group(2))}
                entry[block].append(reference)
                continue
            item = re.fullmatch(r"        ([a-z_]+): (.+)", line)
            if item is None or reference is None or item.group(1) in reference:
                raise _scan_failure("DETECTOR_PACK_INVALID")
            reference[item.group(1)] = _pack_scalar(item.group(2))
            continue
        if block != "implementation":
            continue
        implementation = entry["implementation"]
        field = re.fullmatch(r"      ([a-z_]+):(?: (.*))?", line)
        if field is not None:
            key, value = field.group(1), field.group(2)
            if key in implementation:
                raise _scan_failure("DETECTOR_PACK_INVALID")
            implementation[key] = [] if value is None else _pack_scalar(value)
            listing = key if value is None else None
            continue
        item = re.fullmatch(r"        - (.+)", line)
        if item is None or listing is None:
            raise _scan_failure("DETECTOR_PACK_INVALID")
        implementation[listing].append(_pack_scalar(item.group(1)))
    return entries


def _scan_pack(
    raw: bytes, agent_id: str, guard: dict[str, Any], prompt: dict[str, Any]
) -> list[dict[str, Any]]:
    """The scanned detectors of one pack; a missing group or wrong boundary refuses the pack."""

    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise _scan_failure("DETECTOR_PACK_INVALID") from None
    sections = _pack_sections(text)
    boundary: dict[str, object] = {}
    for line in sections.get("execution_boundary", []):
        field = re.fullmatch(r"  ([a-z_]+): (.+)", line)
        if field is not None:
            boundary[field.group(1)] = _pack_scalar(field.group(2))
    try:
        authoritative, unresolved = guard["detector_hard_fail_lists"](raw)
    except guard["GuardError"]:
        raise _scan_failure("DETECTOR_PACK_INVALID") from None
    conflicts = {
        _pack_scalar(line.split(":", 1)[1])
        for line in sections.get("decision_metadata", [])
        if line.startswith("    - detector_id: ")
    }
    detectors = _pack_entries(sections.get("detectors", []))
    identifiers = [item.get("id") for item in detectors]
    if len(set(identifiers)) != len(identifiers) or not set(authoritative | unresolved) <= set(
        identifiers
    ):
        raise _scan_failure("DETECTOR_PACK_INVALID")
    pack_sha256 = hashlib.sha256(raw).hexdigest()
    scanned: list[dict[str, Any]] = []
    for detector in detectors:
        implementation = detector["implementation"]
        selected = (
            implementation.get("kind") == "regex"
            and implementation.get("engine") == "python-re"
            and detector["id"] in authoritative | unresolved
        )
        if not selected:
            if "scan_group" in detector or "validator" in implementation:
                raise _scan_failure("DETECTOR_PACK_INVALID")
            continue
        validator = implementation.get("validator")
        pattern = implementation.get("pattern")
        flags = implementation.get("flags")
        if (
            detector.get("scan_group") not in SCAN_GROUPS
            or detector.get("severity") not in guard["SEVERITIES"]
            or (validator is not None and validator not in SCAN_VALIDATORS)
            or not isinstance(pattern, str)
            or not isinstance(flags, list)
            or not isinstance(detector.get("reason"), str)
            or not str(detector["reason"]).strip()
        ):
            raise _scan_failure("DETECTOR_PACK_INVALID")
        try:
            compiled = prompt["_compile_detector"]({"pattern": pattern, "flags": flags})
        except prompt["GuardError"]:
            raise _scan_failure("DETECTOR_PACK_INVALID") from None
        if compiled.search("") is not None:
            raise _scan_failure("DETECTOR_PACK_INVALID")
        scanned.append(
            {
                "detector_id": detector["id"],
                "agent_id": agent_id,
                "scan_group": detector["scan_group"],
                "severity": detector["severity"],
                "validator": validator,
                "hard_fail_list": "authoritative"
                if detector["id"] in authoritative
                else "unresolved",
                "decision_effect": (
                    "hard-fail"
                    if detector["id"] in authoritative and detector["id"] not in conflicts
                    else "blocked-incomplete"
                ),
                "detector_pack_sha256": pack_sha256,
                "pattern": compiled,
            }
        )
    expected = (SCAN_MODE, SCAN_EXECUTOR_REF) if scanned else ("specification-only", None)
    if (boundary.get("mode"), boundary.get("executor_ref")) != expected:
        raise _scan_failure("DETECTOR_PACK_INVALID")
    return scanned


def _scan_git(
    project_root: Path, executable: str | None, arguments: list[str], payload: bytes | None = None
) -> bytes:
    resolved = shutil.which("git") if executable in {None, "git"} else executable
    if resolved is None:
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            [resolved, "-C", str(project_root), *arguments],
            input=payload,
            stdin=None if payload is not None else subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        raise _scan_failure("CANDIDATE_UNAVAILABLE") from None
    if completed.returncode != 0:
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    return completed.stdout


def _staged_blobs(project_root: Path, executable: str | None) -> list[tuple[str, str, str]]:
    """``(path, mode, object id)`` of every added or changed index entry; deletions are skipped."""

    raw = _scan_git(
        project_root,
        executable,
        ["diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev"],
    )
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    if len(tokens) % 2:
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    entries: list[tuple[str, str, str]] = []
    for index in range(0, len(tokens), 2):
        fields = tokens[index].decode("ascii", "replace").split()
        try:
            path = tokens[index + 1].decode("utf-8")
        except UnicodeError:
            raise _scan_failure("SCAN_PATH_INVALID") from None
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise _scan_failure("CANDIDATE_UNAVAILABLE")
        status = fields[4][:1]
        if status == "D":
            continue
        if status not in {"A", "M", "T"}:
            raise _scan_failure("CANDIDATE_UNAVAILABLE")
        entries.append((path, fields[1], fields[3]))
    return sorted(entries)


def _blob_sizes(project_root: Path, executable: str | None, oids: list[str]) -> dict[str, int]:
    if not oids:
        return {}
    output = _scan_git(
        project_root,
        executable,
        ["cat-file", "--batch-check"],
        "".join(f"{oid}\n" for oid in oids).encode("ascii"),
    )
    sizes: dict[str, int] = {}
    for line in output.decode("ascii", "replace").splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[1] != "blob" or not fields[2].isdigit():
            raise _scan_failure("CANDIDATE_UNAVAILABLE")
        sizes[fields[0]] = int(fields[2])
    if set(sizes) != set(oids):
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    return sizes


def _blob_contents(project_root: Path, executable: str | None, oids: list[str]) -> dict[str, bytes]:
    if not oids:
        return {}
    output = _scan_git(
        project_root,
        executable,
        ["cat-file", "--batch"],
        "".join(f"{oid}\n" for oid in oids).encode("ascii"),
    )
    contents: dict[str, bytes] = {}
    position = 0
    for oid in oids:
        header_end = output.find(b"\n", position)
        fields = output[position:header_end].decode("ascii", "replace").split()
        if header_end < 0 or len(fields) != 3 or fields[0] != oid or not fields[2].isdigit():
            raise _scan_failure("CANDIDATE_UNAVAILABLE")
        start = header_end + 1
        end = start + int(fields[2])
        if output[end : end + 1] != b"\n":
            raise _scan_failure("CANDIDATE_UNAVAILABLE")
        contents[oid] = output[start:end]
        position = end + 1
    return contents


def _blob_head(project_root: Path, executable: str | None, oid: str) -> bytes:
    """The first bytes of an oversized blob, read without loading the rest."""

    resolved = shutil.which("git") if executable in {None, "git"} else executable
    if resolved is None:
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        with subprocess.Popen(
            [resolved, "-C", str(project_root), "cat-file", "blob", oid],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        ) as process:
            stream = process.stdout
            head = stream.read(BINARY_PROBE_BYTES) if stream is not None else b""
            process.kill()
    except (OSError, subprocess.SubprocessError):
        raise _scan_failure("CANDIDATE_UNAVAILABLE") from None
    return head


def _managed_digests(raw: bytes | None) -> dict[str, str] | None:
    """The ``managed`` path to SHA-256 map of one scaffold ownership manifest, if it is valid."""

    if raw is None:
        return None
    try:
        payload = _decode(raw)
    except GovernanceClientError:
        return None
    managed = payload.get("managed") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("format") != 1
        or not isinstance(managed, dict)
        or any(
            not isinstance(path, str)
            or not isinstance(digest, str)
            or DIGEST_RE.fullmatch(digest) is None
            for path, digest in managed.items()
        )
    ):
        return None
    return cast(dict[str, str], managed)


def _authority_digests(project_root: Path, executable: str | None) -> dict[str, str]:
    """Digests of the scaffold-managed files the scan may leave out as identical to the authority.

    The source is the scaffold ownership manifest the drift check and `restore` already trust:
    its staged bytes give the digest, and only paths its committed (`HEAD`) version already
    manages qualify, so a candidate cannot add a path to the exclusion.  Without both versions
    nothing is left out.
    """

    def blob(revision: str) -> bytes | None:
        try:
            return _scan_git(project_root, executable, ["cat-file", "blob", revision])
        except GovernanceClientError:
            return None

    staged = _managed_digests(blob(f":{MANAGED_MANIFEST_PATH}"))
    committed = _managed_digests(blob(f"HEAD:{MANAGED_MANIFEST_PATH}"))
    if staged is None or committed is None:
        return {}
    return {path: digest for path, digest in staged.items() if path in committed}


def _line_phrase(start: int, end: int) -> str:
    return f"{start}. satırında" if start == end else f"{start}–{end}. satırlarında"


def scan_detectors(project_root: Path) -> list[dict[str, Any]]:
    """The scanned detectors of the twelve review Agents' packs, in Agent and pack order."""

    guard = _hook_module("agentic_review_receipt_guard.py")
    prompt = _hook_module("prompt_ingress_guard.py")
    detectors: list[dict[str, Any]] = []
    for agent_id in guard["AGENTS"]:
        relative = f"agent-platform/agents/{agent_id.removeprefix('agent:')}/detectors.yml"
        try:
            raw = guard["_regular_file"](project_root, relative, limit=MAX_JSON_BYTES)[1]
        except guard["GuardError"]:
            raise _scan_failure("DETECTOR_PACK_INVALID") from None
        detectors.extend(_scan_pack(raw, agent_id, guard, prompt))
    return detectors


def scan_text(
    detectors: list[dict[str, Any]], prompt: dict[str, Any], text: str
) -> list[tuple[int, int, int]]:
    """``(start, end, detector index)`` of every validated, non-empty match in ``text``."""

    located: list[tuple[int, int, int]] = []
    for index, detector in enumerate(detectors):
        for match in detector["pattern"].finditer(text):
            if match.end() == match.start() or (
                detector["validator"] is not None
                and not prompt["_validated_match"](detector["validator"], text, match)
            ):
                continue
            located.append((match.start(), match.end(), index))
    return located


def _detector_identity(detectors: list[dict[str, Any]]) -> list[list[object]]:
    return [
        [
            item["detector_id"],
            item["detector_pack_sha256"],
            item["scan_group"],
            item["validator"],
            item["pattern"].pattern,
            item["pattern"].flags,
        ]
        for item in detectors
    ]


def _match_texts(
    project_root: Path,
    detectors: list[dict[str, Any]],
    prompt: dict[str, Any],
    texts: list[tuple[str, str]],
) -> list[list[tuple[int, int, int]]]:
    """Each text's matches; a large candidate is split over parallel worker processes."""

    total = sum(len(text) for _, text in texts)
    workers = min(
        MAX_SCAN_WORKERS,
        os.cpu_count() or 1,
        -(-total // PARALLEL_SCAN_CHUNK_CHARACTERS),
    )
    if total < PARALLEL_SCAN_MIN_CHARACTERS or workers < 2 or not sys.executable:
        return [scan_text(detectors, prompt, text) for _, text in texts]
    buckets: list[list[int]] = [[] for _ in range(workers)]
    loads = [0] * workers
    for index in sorted(range(len(texts)), key=lambda item: (-len(texts[item][1]), item)):
        lightest = loads.index(min(loads))
        buckets[lightest].append(index)
        loads[lightest] += len(texts[index][1])
    expected = _detector_identity(detectors)
    results: list[list[tuple[int, int, int]]] = [[] for _ in texts]
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for bucket in buckets:
            payload = json.dumps(
                {"project_root": str(project_root), "texts": [texts[item][1] for item in bucket]}
            ).encode("ascii")
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "scan-worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(project_root),
            )
            processes.append(process)
            if process.stdin is None:
                raise OSError("worker-input-unavailable")
            process.stdin.write(payload)
            process.stdin.close()
        for position, process in enumerate(processes):
            bucket = buckets[position]
            output = process.stdout.read() if process.stdout is not None else b""
            if process.wait(timeout=SCAN_WORKER_TIMEOUT_SECONDS) != 0:
                raise OSError("worker-failed")
            value = json.loads(output.decode("ascii"))
            located = value.get("located") if isinstance(value, dict) else None
            if (
                value.get("detectors") != expected
                or not isinstance(located, list)
                or len(located) != len(bucket)
            ):
                raise OSError("worker-result-invalid")
            for offset, matches in enumerate(located):
                results[bucket[offset]] = [
                    (int(start), int(end), int(index)) for start, end, index in matches
                ]
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        raise _scan_failure("SCAN_WORKER_FAILED") from None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
    return results


def scan_worker(raw: bytes) -> dict[str, object]:
    """Match the given texts for a parent scan; it returns the pack identity it used."""

    payload = _decode(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("texts"), list):
        raise _scan_failure("SCAN_WORKER_FAILED")
    detectors = scan_detectors(Path(str(payload.get("project_root"))))
    prompt = _hook_module("prompt_ingress_guard.py")
    return {
        "detectors": _detector_identity(detectors),
        "located": [
            [list(item) for item in scan_text(detectors, prompt, str(text))]
            for text in payload["texts"]
        ],
    }


def deterministic_scan(project_root: Path, executable: str | None = None) -> dict[str, object]:
    """Scan every added or changed staged file with the governed-review detectors.

    The result holds file lists, per-detector counts and each match's detector, path and line
    range; never the matched value, its digest or the line text.  The same index and the same
    packs give the same bytes, so `finalize-review` and the commit hook rerun it and compare.
    """

    guard = _hook_module("agentic_review_receipt_guard.py")
    prompt = _hook_module("prompt_ingress_guard.py")
    detectors = scan_detectors(project_root)
    entries = _staged_blobs(project_root, executable)
    blobs = [(path, oid) for path, mode, oid in entries if mode in SCAN_BLOB_MODES]
    unknown = [
        path for path, mode, _ in entries if mode not in SCAN_BLOB_MODES | {SCAN_GITLINK_MODE}
    ]
    if unknown:
        raise _scan_failure("CANDIDATE_UNAVAILABLE")
    sizes = _blob_sizes(project_root, executable, sorted({oid for _, oid in blobs}))
    small = sorted({oid for _, oid in blobs if sizes[oid] <= MAX_SCAN_TEXT_BYTES})
    contents = _blob_contents(project_root, executable, small)
    scanned: list[str] = []
    skipped: list[dict[str, object]] = []
    unscannable: list[dict[str, object]] = []
    texts: list[tuple[str, str]] = []
    authority = _authority_digests(project_root, executable)
    authority_matched: list[str] = []
    found: list[tuple[int, int, str, int, int, int, int]] = []
    counts = [0] * len(detectors)
    agent_order = {agent_id: position for position, agent_id in enumerate(guard["AGENTS"])}

    def note(target: list[dict[str, object]], path: str, reason: str) -> None:
        target.append(
            {
                "path": path,
                "reason": reason,
                "summary": SCAN_FILE_SUMMARIES[reason].format(path=path),
            }
        )

    for path, mode, oid in entries:
        if mode == SCAN_GITLINK_MODE:
            note(skipped, path, "submodule")
            continue
        content = contents.get(oid)
        if (
            content is not None
            and path in authority
            and hashlib.sha256(content).hexdigest() == authority[path]
        ):
            authority_matched.append(path)
            continue
        if content is None:
            head = _blob_head(project_root, executable, oid)
            note(
                skipped if b"\0" in head else unscannable,
                path,
                "binary" if b"\0" in head else "too-large",
            )
            continue
        if b"\0" in content:
            note(skipped, path, "binary")
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeError:
            note(unscannable, path, "not-utf8")
            continue
        scanned.append(path)
        texts.append((path, text))
    matched = _match_texts(project_root, detectors, prompt, texts)
    for position, (path, text) in enumerate(texts):
        located = matched[position]
        for _, _, index in located:
            counts[index] += 1
        line, position = 1, 0
        for start, end, index in sorted(located)[: max(0, MAX_SCAN_COLLECTED - len(found))]:
            line += text.count("\n", position, start)
            position = start
            end_line = line + text.count("\n", start, max(start, end - 1))
            found.append(
                (agent_order[detectors[index]["agent_id"]], index, path, start, end, line, end_line)
            )
    found.sort()
    matches: list[dict[str, object]] = []
    ordinals: dict[tuple[int, str], int] = {}
    for _, index, path, _, _, start_line, end_line in found[:MAX_SCAN_MATCHES]:
        detector = detectors[index]
        ordinal = ordinals.get((index, path), 0)
        ordinals[(index, path)] = ordinal + 1
        identity = {
            "detector_id": detector["detector_id"],
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "ordinal": ordinal,
        }
        matches.append(
            {
                "candidate_id": f"candidate:{_canonical_sha256(identity)[:32]}",
                "detector_id": detector["detector_id"],
                "agent_id": detector["agent_id"],
                "scan_group": detector["scan_group"],
                "severity": detector["severity"],
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "summary": SCAN_MATCH_SUMMARIES[detector["scan_group"]].format(
                    detector=detector["detector_id"],
                    path=path,
                    lines=_line_phrase(start_line, end_line),
                ),
            }
        )
    reasons = []
    if sum(counts) > MAX_SCAN_MATCHES:
        reasons.append("MATCH_LIMIT_EXCEEDED")
    if unscannable:
        reasons.append("UNSCANNABLE_FILE")
    return {
        "executor_ref": SCAN_EXECUTOR_REF,
        "limits": {"max_text_file_bytes": MAX_SCAN_TEXT_BYTES, "max_matches": MAX_SCAN_MATCHES},
        "status": "incomplete" if reasons else "complete",
        "incomplete_reasons": reasons,
        "files": {
            "scanned": scanned,
            "authority_matched": authority_matched,
            "skipped": skipped,
            "unscannable": unscannable,
        },
        "detectors": [
            {
                **{key: value for key, value in detector.items() if key != "pattern"},
                "match_count": counts[index],
            }
            for index, detector in enumerate(detectors)
        ],
        "matches": matches,
    }


def _scan_record(
    project_id: str, run_id: str, snapshot_sha256: str, body: dict[str, object]
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "kind": "GovernedReviewDeterministicScan",
        "canonicalization": SCAN_CANONICALIZATION,
        "project_id": project_id,
        "run_id": run_id,
        "snapshot_sha256": snapshot_sha256,
        **body,
        "claim_boundary": {
            "runtime_admission": False,
            "production_decision": False,
            "calibration_complete": False,
        },
        "data_handling": {
            "matched_value_stored": False,
            "matched_value_digest_stored": False,
            "line_text_stored": False,
            "source_content_stored": False,
        },
    }


# A finding's reason and basis: read from the packs by their structure, checked against the shared
# standard-reference schema and written from the versioned explanation catalog.  A reference that
# fails the schema stops the run; a detector with no ISO/KVKK reference says so in its basis line.
STANDARD_REFERENCE_SCHEMA = "standard-reference.schema.json"
INSTITUTIONAL_STANDARD = "KT-AGENT-POLICY"
BASIS_STANDARDS = ("ISO-IEC-27001", "KVKK-6698")
BASIS_STATUSES = ("unit-verified", "baseline-unverified")
STANDARD_ORDER = (
    "ISO-IEC-27001",
    "KVKK-6698",
    "CWE",
    "OWASP-TOP-10",
    "PCI-DSS",
    "SLSA",
    INSTITUTIONAL_STANDARD,
)
FINDING_TEMPLATE_NAMES = (
    "reason",
    "basis",
    "basis_unmapped",
    "source_stated",
    "institutional",
)
FINDING_LABEL_GROUPS = ("statuses", "formats", "titles")
# Prompt hook messages stay ASCII; Turkish letters become their nearest ASCII letter.
ASCII_FOLD = str.maketrans("çÇğĞıİöÖşŞüÜâÂîÎûÛ", "cCgGiIoOsSuUaAiIuU")


def _basis_failure() -> GovernanceClientError:
    return GovernanceClientError("finding-basis-invalid", reason_code="FINDING_BASIS_INVALID")


def _pack_text(project_root: Path, guard: dict[str, Any], relative: str) -> str:
    try:
        raw = guard["_regular_file"](project_root, relative, limit=MAX_JSON_BYTES)[1]
        return cast(bytes, raw).decode("utf-8")
    except (guard["GuardError"], UnicodeError):
        raise _basis_failure() from None


def _ordered_references(references: list[dict[str, object]]) -> list[dict[str, object]]:
    """Catalog order (ISO, KVKK, CWE, OWASP, PCI, SLSA, institutional), each reference once."""

    unique: list[dict[str, object]] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return sorted(unique, key=lambda item: STANDARD_ORDER.index(str(item["standard_id"])))


def finding_basis(project_root: Path) -> dict[str, dict[str, Any]]:
    """Every review Agent detector's reason and references, keyed by detector id.

    A detector's references are its own `standard_refs` and those of the policy controls its
    `control_refs` names.  Every reference must match the shared standard-reference schema;
    otherwise no explanation is given and the caller stops the run.
    """

    guard = _hook_module("agentic_review_receipt_guard.py")
    try:
        schemas = guard["_schema_registry"](project_root)
    except guard["GuardError"]:
        raise _basis_failure() from None

    def checked(references: object) -> list[dict[str, object]]:
        if not isinstance(references, list):
            raise _basis_failure()
        for reference in references:
            try:
                guard["_validate_against_schema"](reference, STANDARD_REFERENCE_SCHEMA, schemas)
            except guard["GuardError"]:
                raise _basis_failure() from None
        return cast(list[dict[str, object]], references)

    detectors: dict[str, Any] = {}
    for agent_id in guard["AGENTS"]:
        slug = agent_id.removeprefix("agent:")
        try:
            policy = _pack_sections(
                _pack_text(project_root, guard, f"agent-platform/agents/{slug}/policy.yml")
            )
            controls = {
                str(control["id"]): checked(control.get("standard_refs", []))
                for control in _pack_entries(policy.get("controls", []))
            }
            pack = _pack_sections(
                _pack_text(project_root, guard, f"agent-platform/agents/{slug}/detectors.yml")
            )
            entries = _pack_entries(pack.get("detectors", []))
        except GovernanceClientError:
            raise _basis_failure() from None
        for detector in entries:
            references = list(checked(detector.get("standard_refs", [])))
            control_refs = detector.get("control_refs", [])
            if not isinstance(control_refs, list):
                raise _basis_failure()
            for control_ref in control_refs:
                control_id = str(control_ref).removeprefix("control:")
                if control_id not in controls:
                    raise _basis_failure()
                references.extend(controls[control_id])
            reason = detector.get("reason")
            detectors[str(detector["id"])] = {
                "agent_id": agent_id,
                "reason": reason if isinstance(reason, str) and reason.strip() else None,
                "references": _ordered_references(references),
            }
    return {"detectors": detectors}


def _catalog_string(value: str) -> str:
    try:
        decoded = json.loads(value)
    except ValueError:
        raise _basis_failure() from None
    if not isinstance(decoded, str):
        raise _basis_failure()
    return decoded


def finding_catalog(raw: bytes) -> dict[str, dict[str, str]]:
    """`finding_templates` and `finding_labels` of the versioned explanation catalog."""

    try:
        lines = raw.decode("utf-8").splitlines()
        templates_start = lines.index("finding_templates:") + 1
        labels_start = lines.index("finding_labels:") + 1
    except (UnicodeError, ValueError):
        raise _basis_failure() from None
    catalog: dict[str, dict[str, str]] = {"templates": {}}
    catalog.update({group: {} for group in FINDING_LABEL_GROUPS})
    name: str | None = None
    for line in lines[templates_start:]:
        if line and not line.startswith(" "):
            break
        matched = re.fullmatch(r"  ([a-z_]+):", line)
        if matched is not None:
            name = matched.group(1)
            continue
        matched = re.fullmatch(r"    text: (\".*\")", line)
        if matched is not None and name is not None:
            catalog["templates"][name] = _catalog_string(matched.group(1))
    group: str | None = None
    for line in lines[labels_start:]:
        if line and not line.startswith(" "):
            break
        matched = re.fullmatch(r"  ([a-z_]+):", line)
        if matched is not None:
            group = matched.group(1)
            continue
        matched = re.fullmatch(r"    (\"[^\"]+\"): (\".*\")", line)
        if matched is not None and group in catalog:
            catalog[group][_catalog_string(matched.group(1))] = _catalog_string(matched.group(2))
    if set(catalog["templates"]) != set(FINDING_TEMPLATE_NAMES) or any(
        not catalog[group] for group in FINDING_LABEL_GROUPS
    ):
        raise _basis_failure()
    return catalog


def _reference_text(reference: dict[str, object], catalog: dict[str, dict[str, str]]) -> str:
    standard = str(reference["standard_id"])
    control = str(reference["control_id"])
    pattern = catalog["formats"].get(standard)
    if pattern is None:
        raise _basis_failure()
    title = ""
    if "{title}" in pattern:
        title_key = f"{standard} {control.split('/')[0]}"
        if title_key not in catalog["titles"]:
            raise _basis_failure()
        title = catalog["titles"][title_key]
    try:
        return pattern.format(control=control, version=reference.get("version") or "", title=title)
    except (KeyError, IndexError, ValueError):
        raise _basis_failure() from None


def reason_line(reason: str, catalog: dict[str, dict[str, str]]) -> str:
    return catalog["templates"]["reason"].format(reason=reason)


def basis_lines(
    references: list[dict[str, object]], catalog: dict[str, dict[str, str]]
) -> list[str]:
    """The `Dayanak:` lines of one finding, then its unverified source and policy lines."""

    templates = catalog["templates"]

    def joined(items: list[dict[str, object]]) -> str:
        return "; ".join(_reference_text(item, catalog) for item in items)

    lines: list[str] = []
    basis = [item for item in references if item["standard_id"] in BASIS_STANDARDS]
    if not basis:
        lines.append(templates["basis_unmapped"])
    for status in BASIS_STATUSES:
        group = [item for item in basis if item["mapping_status"] == status]
        if group:
            label = catalog["statuses"].get(status)
            if label is None:
                raise _basis_failure()
            lines.append(templates["basis"].format(references=joined(group), status=label))
    stated = [item for item in references if item["mapping_status"] == "source-stated-unverified"]
    if stated:
        lines.append(templates["source_stated"].format(references=joined(stated)))
    institutional = [item for item in references if item["standard_id"] == INSTITUTIONAL_STANDARD]
    if institutional:
        lines.append(templates["institutional"].format(references=joined(institutional)))
    return lines


def detector_explanation(
    detector_id: str, basis: dict[str, dict[str, Any]], catalog: dict[str, dict[str, str]]
) -> dict[str, object]:
    """`reason_line` and `basis_lines` of a code finding; a detector without a reason refuses."""

    entry = basis["detectors"].get(detector_id)
    if entry is None or entry["reason"] is None:
        raise _basis_failure()
    return {
        "reason_line": reason_line(str(entry["reason"]), catalog),
        "basis_lines": basis_lines(entry["references"], catalog),
    }


def prompt_explanation_lines(project_root: Path, detector_ids: list[str]) -> list[str]:
    """The ASCII reason and basis lines the prompt hook adds for each matched detector."""

    basis = finding_basis(project_root)
    guard = _hook_module("agentic_review_receipt_guard.py")
    try:
        raw = guard["_regular_file"](project_root, EXPLANATION_TEMPLATES_PATH, limit=MAX_JSON_BYTES)
    except guard["GuardError"]:
        raise _basis_failure() from None
    catalog = finding_catalog(cast(bytes, raw[1]))
    lines: list[str] = []
    for detector_id in detector_ids:
        explanation = detector_explanation(detector_id, basis, catalog)
        lines.append(str(explanation["reason_line"]))
        lines.extend(cast(list[str], explanation["basis_lines"]))
    return [ascii_folded(line) for line in lines]


def ascii_folded(text: str) -> str:
    return text.translate(ASCII_FOLD).encode("ascii", "replace").decode("ascii")


def record_observation(run_id: str, agent: str) -> dict[str, object]:
    """Write one specialist report from its bindings input and its returned evaluation.

    The specialist evaluates; this command copies every identifier and digest byte for byte
    from the bindings input `review-start` wrote and binds the Agent's policy controls to every
    finding, so no specialist chooses a control identifier. A rejected evaluation writes no
    report; a schema violation names its JSON pointer, keyword and schema constraint, and a
    wrong `agent_id` names the exact expected identity, so the main Agent can return it to the
    same specialist once.
    """

    if AGENT_SLUG_RE.fullmatch(agent) is None:
        raise GovernanceClientError("invalid-request")
    project_root = Path.cwd().resolve(strict=True)
    project_id, run_root = _review_run(project_root, run_id)
    guard = _hook_module("agentic_review_receipt_guard.py")
    agent_id = f"agent:{agent}"
    if agent_id not in guard["AGENTS"]:
        raise GovernanceClientError("invalid-request")
    bindings = _read_run_input(run_root / "inputs" / f"{agent}.bindings.json")
    evaluation = _read_run_input(run_root / "work" / f"{agent}-evaluation.json")
    candidates = bindings.get("deterministic_candidates")
    if "candidate_responses" not in evaluation:
        # An absent list answers no candidate: it is complete only when there is none to answer.
        evaluation = {**evaluation, "candidate_responses": []}
    missing = sorted(set(EVALUATED_FIELDS) - set(evaluation))
    unexpected = sorted(set(evaluation) - set(EVALUATED_FIELDS))
    if missing or unexpected:
        raise GovernanceClientError(
            "evaluation-invalid",
            reason_code="EVALUATION_SCHEMA_INVALID",
            violation={
                "pointer": "",
                "keyword": "required" if missing else "additionalProperties",
                "constraint": missing or unexpected,
            },
        )
    if evaluation.get("agent_id") != agent_id:
        # Never normalized or accepted for another Agent: the rejection names only the exact
        # identity this specialist may return, so the same specialist can answer once more.
        raise GovernanceClientError(
            "evaluation-invalid",
            reason_code="AGENT_ID_MISMATCH",
            violation={"pointer": "/agent_id", "keyword": "const", "constraint": agent_id},
        )
    problem = guard["candidate_response_problem"](
        candidates, evaluation.get("candidate_responses"), evaluation.get("status")
    )
    if problem is not None:
        # Every rule-based scan candidate needs one answer from its own specialist; a
        # rejection names the candidate field so the same specialist answers once more.
        raise GovernanceClientError(
            "evaluation-invalid",
            reason_code=problem[0],
            violation=problem[1],
            guidance=CANDIDATE_GUIDANCE[problem[0]],
        )
    findings = evaluation.get("findings")
    if isinstance(findings, list):
        for index, finding in enumerate(findings):
            if isinstance(finding, dict) and "controls" in finding:
                # Code binds the policy controls; a specialist that cites its own control
                # identifier is returned once instead of having the identifier replaced.
                raise GovernanceClientError(
                    "evaluation-invalid",
                    reason_code="EVALUATION_SCHEMA_INVALID",
                    violation={
                        "pointer": f"/findings/{index}",
                        "keyword": "additionalProperties",
                        "constraint": ["controls"],
                    },
                )
        if findings:
            controls = _policy_standard_refs(project_root, agent, "evaluation-invalid")
            if not controls:
                raise GovernanceClientError("evaluation-invalid", reason_code="POLICY_UNAVAILABLE")
            evaluation = {
                **evaluation,
                "findings": [
                    {**finding, "controls": controls} if isinstance(finding, dict) else finding
                    for finding in findings
                ],
            }
    bound_fields = set(guard["OBSERVATION_KEYS"]) - set(EVALUATED_FIELDS) | {"agent_id"}
    if (
        set(bindings) != bound_fields
        or bindings.get("agent_id") != agent_id
        or bindings.get("run_id") != run_id
        or bindings.get("project_id") != project_id
    ):
        raise GovernanceClientError("bindings-invalid")
    schemas = guard["_schema_registry"](project_root)
    schema = "agentic-governance-observation.schema.json"
    # A clean evaluation separates a bindings fault from the specialist's answer, which only the
    # specialist corrects.
    clean = {
        "agent_id": agent_id,
        "candidate_responses": [],
        "error_code": None,
        "error_summary": None,
        "findings": [],
        "scanned_files": [],
        "status": "ok",
    }
    try:
        guard["_validate_against_schema"]({**bindings, **clean}, schema, schemas)
    except Exception:
        raise GovernanceClientError("bindings-invalid") from None
    observation = {**bindings, **evaluation}
    try:
        guard["_validate_against_schema"](observation, schema, schemas)
    except Exception:
        raise GovernanceClientError(
            "evaluation-invalid",
            reason_code="EVALUATION_SCHEMA_INVALID",
            violation=guard["schema_violation"](observation, schema, schemas),
        ) from None
    _validate_evaluation_scope(project_root, evaluation)
    payload = _canonical_bytes(observation)
    writer = _hook_module("governance_records.py")
    try:
        path, created = writer["write_review_report"](
            project_id, run_id, agent, payload, location=_record_location()
        )
    except writer["RecordError"]:
        raise GovernanceClientError("report-write-failed") from None
    if not created and _read_review_json(path)[0] != payload:
        raise GovernanceClientError("report-exists")
    findings = observation["findings"]
    return {
        "agent_id": agent_id,
        "finding_count": len(findings) if isinstance(findings, list) else 0,
        "report": "written" if created else "reused",
        "report_path": f"governed-review/{run_id}/reports/{agent}.json",
        "report_sha256": hashlib.sha256(payload).hexdigest(),
        "status": observation["status"],
    }


def _policy_standard_refs(project_root: Path, agent: str, error: str) -> list[dict[str, str]]:
    """The institutional policy bindings (`KT-AGENT-POLICY`) of the Agent, in file order.

    Code binds these to every specialist finding; a finding's ISO/KVKK basis comes only from a
    detector, so another standard in a policy control never enters a specialist report.
    """

    path = project_root / "agent-platform" / "agents" / agent / "policy.yml"
    try:
        if path.is_symlink() or not path.is_file():
            raise GovernanceClientError(error, reason_code="POLICY_UNAVAILABLE")
        sections = _pack_sections(path.read_text(encoding="utf-8"))
        controls = _pack_entries(sections.get("controls", []))
    except (OSError, UnicodeError, GovernanceClientError):
        raise GovernanceClientError(error, reason_code="POLICY_UNAVAILABLE") from None
    references: list[dict[str, str]] = []
    for control in controls:
        items = control.get("standard_refs", [])
        if not isinstance(items, list):
            raise GovernanceClientError(error, reason_code="POLICY_UNAVAILABLE")
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("standard_id") != INSTITUTIONAL_STANDARD
                or item.get("mapping_status") != "institutional-policy-binding"
            ):
                continue
            reference = {
                "standard_id": INSTITUTIONAL_STANDARD,
                "control_id": str(item.get("control_id")),
                "version": str(item.get("version")),
            }
            if reference not in references:
                references.append(reference)
    return references


def _component_bindings(
    project_root: Path, guard: dict[str, Any], client_id: str
) -> dict[str, Any]:
    """Every authority, policy, harness and Agent binding of a run, read from the project files."""

    def read(relative: str) -> bytes:
        return cast(bytes, guard["_regular_file"](project_root, relative, limit=MAX_JSON_BYTES)[1])

    def digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    version = guard["_yaml_metadata_version"]
    mapping = guard["_yaml_direct_mapping"]
    manifest_raw = read(".kt-scaffold/project-manifest.json")
    manifest = _decode(manifest_raw)
    if not isinstance(manifest, dict):
        raise GovernanceClientError("review-start-invalid", reason_code="PROJECT_MANIFEST_INVALID")
    orchestration_raw = read(ORCHESTRATION_PATH)
    aggregation_raw = read(AGGREGATION_POLICY_PATH)
    evaluator_raw = read(EVALUATOR_POLICY_PATH)
    lineage = mapping(aggregation_raw, "lineage")
    evaluation = mapping(evaluator_raw, "evaluation")
    evaluator_metadata = mapping(evaluator_raw, "metadata")
    blueprint_version = manifest.get("blueprint_version")
    harness: dict[str, Any] = {
        "protocol_id": "protocol:mandatory-governed-execution-phase1",
        "version": "1.3.0",
        "canonicalization": "kt-mandatory-governed-execution-json-v1",
        "sha256": "",
        "mandatory": True,
        "rule": {
            "ref": RULE_PATH,
            "version_source": "project-manifest.blueprint_version",
            "version": blueprint_version,
            "sha256": digest(read(RULE_PATH)),
        },
        "skill": {
            "ref": guard["CLIENT_SKILLS"][client_id],
            "version_source": "project-manifest.blueprint_version",
            "version": blueprint_version,
            "sha256": digest(read(guard["CLIENT_SKILLS"][client_id])),
        },
        "stage_order": list(guard["STAGE_ORDER"]),
        "missing_or_stale_result": "BLOCKED_INCOMPLETE",
    }
    harness["sha256"] = _canonical_sha256(harness, excluding="sha256")
    agents: dict[str, Any] = {}
    for agent_id in guard["AGENTS"]:
        slug = agent_id.removeprefix("agent:")
        component: dict[str, Any] = {}
        for name, filename in (
            ("agent", "agent.yml"),
            ("policy", "policy.yml"),
            ("detectors", "detectors.yml"),
            ("instructions", "instructions.md"),
        ):
            raw = read(f"agent-platform/agents/{slug}/{filename}")
            component[name] = {
                "version": "unavailable" if name == "instructions" else version(raw),
                "sha256": digest(raw),
            }
        projection_path = guard["CLIENT_PROJECTION_PATHS"][client_id].format(agent=slug)
        component["projection"] = {
            "client_id": client_id,
            "path": projection_path,
            "version": "unavailable",
            "sha256": digest(read(projection_path)),
        }
        agents[agent_id] = component
    return {
        "authority": {
            "authority_generation": manifest.get("authority_generation"),
            "version": manifest.get("governance_version"),
            "sha256": manifest.get("governance_digest"),
            "manifest_sha256": digest(manifest_raw),
        },
        "orchestration": {
            "ref": "orchestration:governed-review",
            "version": version(orchestration_raw),
            "sha256": digest(orchestration_raw),
            "required_agents": list(guard["AGENTS"]),
            "separate_invocations_observed": True,
        },
        "aggregation_policy": {
            "ref": "policy:governed-review-aggregation",
            "version": version(aggregation_raw),
            "sha256": digest(aggregation_raw),
            "instructions_ref": guard["_yaml_top_level_scalar"](
                aggregation_raw, "instructions_ref"
            ),
            "instructions_sha256": digest(read(AGGREGATION_INSTRUCTIONS_PATH)),
            "weights": mapping(aggregation_raw, "weights"),
            "thresholds": mapping(aggregation_raw, "thresholds"),
            "calibration_status": lineage.get("calibration_status"),
            "runtime_admission": lineage.get("runtime_admission"),
        },
        "agentic_evaluator": {
            "policy_ref": evaluator_metadata.get("id"),
            "evaluator_id": evaluator_metadata.get("evaluator_id"),
            "version": version(evaluator_raw),
            "sha256": digest(evaluator_raw),
            "mode": evaluation.get("mode"),
            "authority": evaluation.get("authority"),
            "runtime_admission": False,
            "deterministic": False,
            "production_authority": False,
        },
        "mandatory_governed_execution": harness,
        "agents": agents,
        "severity_scores": guard["severity_scores"](aggregation_raw),
        "explanations": read(EXPLANATION_TEMPLATES_PATH),
    }


def _observation_bindings(
    context: dict[str, Any],
    components: dict[str, Any],
    agent_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, object]:
    """Every observation field of one specialist report except the ones it evaluates.

    ``candidates`` are the Agent's adjudication matches of the run's rule-based scan record.
    """

    identity = context["agents"][agent_id]
    return {
        "schema_version": "1.1",
        "kind": "AgenticGovernanceObservation",
        "evidence_profile": "phase1-agentic-advisory",
        "receipt_id": context["receipt_id"],
        "project_id": context["project_id"],
        "agent_id": agent_id,
        "run_id": context["run_id"],
        "trace_id": context["trace_id"],
        "span_id": identity["span_id"],
        "invocation_id": identity["invocation_id"],
        "snapshot_sha256": context["snapshot_sha256"],
        "agentic_evaluator": components["agentic_evaluator"],
        "component_binding": components["agents"][agent_id],
        "acceptance_criteria": (
            context["acceptance_criteria"] if agent_id == TEST_AUTOMATION_AGENT else None
        ),
        "deterministic_candidates": candidates,
        "claim_boundary": {
            "deterministic_evidence": False,
            "canonical_conformance": False,
            "runtime_admission": False,
            "production_decision": False,
            "immutable_audit": False,
        },
        "data_handling": _data_handling(),
    }


def _data_handling() -> dict[str, bool]:
    return {
        "raw_prompt_stored": False,
        "source_content_stored": False,
        "pii_stored": False,
        "secret_stored": False,
    }


def _identity(prefix: str, used: set[str]) -> dict[str, str]:
    """A fresh invocation id and a 16-hex span id no other call of the run carries."""

    while True:
        span_id = secrets.token_hex(8)
        if span_id not in used:
            used.add(span_id)
            return {
                "invocation_id": f"invocation:{prefix}:{secrets.token_hex(6)}",
                "span_id": span_id,
            }


def _write_artifact(
    project_id: str, run_id: str, name: str, value: object
) -> tuple[Path, bytes, bool]:
    """Write one canonical run artifact once; an existing one must hold the same bytes."""

    payload = _canonical_bytes(value)
    writer = _hook_module("governance_records.py")
    try:
        path, created = writer["write_review_artifact"](
            project_id, run_id, name, payload, location=_record_location()
        )
    except writer["RecordError"]:
        raise GovernanceClientError("review-artifact-write-failed") from None
    if not created and _read_review_json(path)[0] != payload:
        raise GovernanceClientError("run-conflict")
    return path, payload, created


def _scan_incomplete_guidance(record: dict[str, object]) -> str:
    """Plain-language reason a scan could not finish; it names files, never their content."""

    files = cast(dict[str, list[dict[str, object]]], record["files"])
    lines = [str(item["summary"]) for item in files["unscannable"][:5]]
    if len(files["unscannable"]) > 5:
        lines.append(f"Taranamayan {len(files['unscannable']) - 5} dosya daha kayıtta listeli.")
    if "MATCH_LIMIT_EXCEEDED" in cast(list[str], record["incomplete_reasons"]):
        lines.append(
            f"Kural tabanlı tarama {MAX_SCAN_MATCHES} eşleşme sınırını aştı; eşleşmeler kayıtta "
            "sayıldı ama hepsi listelenemedi."
        )
    lines.append(
        "Kural tabanlı tarama (kesin kuralları kodla denetleyen adım) tamamlanamadığı için "
        "inceleme BLOCKED_INCOMPLETE ile durdu. Dosyayı düzeltip yeniden stage et ve yeni bir "
        "koşum başlat."
    )
    return " ".join(lines)


def _scan_summary(run_id: str, record: dict[str, object]) -> dict[str, object]:
    """What the main Agent reports: blocking matches, candidate counts and skipped files."""

    files = cast(dict[str, list[Any]], record["files"])
    matches = cast(list[dict[str, object]], record["matches"])
    return {
        "record_path": f"governed-review/{run_id}/{SCAN_RECORD_NAME}.json",
        "status": record["status"],
        "scanned_file_count": len(files["scanned"]),
        "authority_matched_files": (
            f"{len(files['authority_matched'])} dosya taranmadı: otoriteyle birebir"
        ),
        "skipped_files": [item["summary"] for item in files["skipped"]],
        "blocking_matches": [
            item["summary"] for item in matches if item["scan_group"] == "blocking"
        ],
        "candidate_count": sum(1 for item in matches if item["scan_group"] == "adjudication"),
    }


def review_start(
    run_id: str, client_id: str, client_version: str, criteria_path: str
) -> dict[str, object]:
    """Open or resume a governed-review run: snapshot, run context and twelve bindings inputs.

    The main Agent supplies only what it observes or judges: the running client's version and
    the accepted or draft PRD that frames the Test Automation Agent.  Every identifier, digest,
    binding and the PRD's lifecycle come from the project files, the staged index and the prompt
    record.
    """

    if (
        RUN_ID_RE.fullmatch(run_id) is None
        or client_id not in CLIENT_SESSION_ENVIRONMENT
        or CLIENT_VERSION_RE.fullmatch(client_version) is None
    ):
        raise GovernanceClientError("invalid-request")
    project_root = Path.cwd().resolve(strict=True)
    _local_override_gate(project_root)
    project_id = _project_id(project_root)
    guard = _hook_module("agentic_review_receipt_guard.py")
    try:
        snapshot = guard["_capture_snapshot"](project_root, "git")
        components = _component_bindings(project_root, guard, client_id)
        criteria = guard["acceptance_criteria"](project_root, criteria_path, "git")
    except guard["GuardError"] as exc:
        raise GovernanceClientError(
            "review-start-invalid", reason_code=exc.code, guidance=exc.diagnostic
        ) from None
    try:
        scan = deterministic_scan(project_root)
        # The packs' references and the explanation catalog are checked before any specialist
        # runs, so a run never reaches a decision it cannot explain.
        finding_basis(project_root)
        finding_catalog(components["explanations"])
    except GovernanceClientError as exc:
        raise GovernanceClientError("review-start-invalid", reason_code=exc.reason_code) from None
    writer = _hook_module("governance_records.py")
    try:
        run_root = writer["prepare_review_run"](project_id, run_id, location=_record_location())
    except writer["RecordError"]:
        raise GovernanceClientError("review-directory-unavailable") from None
    context_path = run_root / "inputs" / "run.json"
    identity = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    if context_path.exists() or context_path.is_symlink():
        _, context = _read_review_json(context_path)
        if (
            context.get("snapshot_sha256") != snapshot["snapshot_sha256"]
            or cast(dict[str, object], context.get("client", {})).get("id") != client_id
            or cast(dict[str, object], context.get("client", {})).get("version") != client_version
            or context.get("acceptance_criteria") != criteria
        ):
            raise GovernanceClientError("run-conflict")
        status = "resumed"
    else:
        metadata = current_prompt_metadata(client_id)
        used: set[str] = set()
        client = {
            "source": "native-event-observed" if client_id == "cursor" else "agent-self-observed",
            "id": client_id,
            "version": client_version,
            "sha256": _canonical_sha256({"id": client_id, "version": client_version}),
        }
        context = {
            "canonicalization": RUN_CONTEXT_CANONICALIZATION,
            "project_id": project_id,
            "run_id": run_id,
            "receipt_id": f"receipt:{run_id}",
            "trace_id": secrets.token_hex(16),
            "started_at": _iso_utc(datetime.now(UTC)),
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "client": client,
            "session_id": metadata["prompt_session_id"],
            "model": metadata["model"],
            "prompt_source_ref": metadata["source_receipt_path"],
            "acceptance_criteria": criteria,
            "evaluator": _identity("evaluator-primary", used),
            "second_pass": _identity("evaluator-second-pass", used),
            "agents": {
                agent_id: _identity(agent_id.removeprefix("agent:"), used)
                for agent_id in guard["AGENTS"]
            },
        }
        status = "started"
    _write_artifact(project_id, run_id, "inputs/snapshot", identity)
    _write_artifact(project_id, run_id, "inputs/run", context)
    schemas = guard["_schema_registry"](project_root)
    record = _scan_record(project_id, run_id, str(snapshot["snapshot_sha256"]), scan)
    try:
        guard["_validate_against_schema"](record, guard["SCAN_RECORD_SCHEMA"], schemas)
    except guard["GuardError"]:
        raise GovernanceClientError(
            "review-start-invalid", reason_code="DETERMINISTIC_SCAN_INVALID"
        ) from None
    _write_artifact(project_id, run_id, SCAN_RECORD_NAME, record)
    if record["status"] != "complete":
        # The record lists what could not be scanned; no specialist is asked to review it.
        raise GovernanceClientError(
            "review-start-invalid",
            reason_code="DETERMINISTIC_SCAN_INCOMPLETE",
            guidance=_scan_incomplete_guidance(record),
        )
    agents: list[dict[str, object]] = []
    for agent_id in guard["AGENTS"]:
        slug = agent_id.removeprefix("agent:")
        candidates = guard["deterministic_candidates"](record, agent_id)
        bindings = _observation_bindings(context, components, agent_id, candidates)
        clean = {
            "candidate_responses": [],
            "error_code": None,
            "error_summary": None,
            "findings": [],
            "scanned_files": [],
            "status": "ok",
        }
        try:
            guard["_validate_against_schema"](
                {**bindings, **clean}, "agentic-governance-observation.schema.json", schemas
            )
        except guard["GuardError"]:
            raise GovernanceClientError("bindings-invalid") from None
        path, _, _ = _write_artifact(project_id, run_id, f"inputs/{slug}.bindings", bindings)
        agents.append(
            {
                "agent_id": agent_id,
                "bindings_path": str(path),
                "candidate_count": len(candidates),
                "report": "written"
                if (run_root / "reports" / f"{slug}.json").exists()
                else "missing",
            }
        )
    return {
        "status": status,
        "run_id": run_id,
        "review_directory": str(run_root),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "staged_paths": sorted(_staged_paths(project_root, "review-start-invalid")),
        "acceptance_criteria": criteria,
        "deterministic_scan": _scan_summary(run_id, record),
        "agents": agents,
        "next_action": (
            "finalize-review"
            if all(item["report"] == "written" for item in agents)
            else "dispatch-specialists"
        ),
    }


def _verify_review_run(
    project_root: Path,
    receipt_raw: bytes,
    receipt: dict[str, object],
    events: list[dict[str, object]],
) -> None:
    """Run every commit-hook check on the run before its audit is written or it is published.

    A rejection names the hook's reason code, writes nothing and leaves the agent's decision and
    receipt correctable; a published run is never corrected in place.
    """

    guard = _hook_module("agentic_review_receipt_guard.py")
    validate = guard["validate_review_run"]
    # The hook resolves the shared root through its own module; use the client's location.
    validate.__globals__["_record_location"] = _record_location
    execution = receipt.get("execution")
    client = execution.get("client") if isinstance(execution, dict) else None
    client_id = client.get("id") if isinstance(client, dict) else None
    if client_id not in guard["CLIENTS"]:
        raise GovernanceClientError("review-artifact-invalid")
    try:
        validate(
            project_root,
            client_id,
            receipt_raw,
            receipt,
            datetime.now(UTC),
            "git",
            audit_raw=_audit_bytes(events),
        )
    except guard["GuardError"] as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.code) from None
    except Exception:
        raise GovernanceClientError("review-run-invalid") from None


def _audit_bytes(events: list[dict[str, object]]) -> bytes:
    return "".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for event in events
    ).encode("utf-8")


def _weight_micros(value: object) -> int:
    if type(value) not in {int, float}:
        raise GovernanceClientError("review-artifact-invalid")
    try:
        scaled = Decimal(str(value)) * 1_000_000
    except (InvalidOperation, ValueError):
        raise GovernanceClientError("review-artifact-invalid") from None
    if scaled != scaled.to_integral_value() or scaled <= 0:
        raise GovernanceClientError("review-artifact-invalid")
    return int(scaled)


def _percent_basis_points(value: object) -> int:
    if type(value) not in {int, float}:
        raise GovernanceClientError("review-artifact-invalid")
    scaled = Decimal(str(value)) * 100
    if scaled != scaled.to_integral_value() or scaled < 0:
        raise GovernanceClientError("review-artifact-invalid")
    return int(scaled)


def _policy_outcome(
    components: dict[str, Any],
    observations: list[dict[str, object]],
    code_findings: list[dict[str, Any]],
) -> tuple[dict[str, object], list[int]]:
    """Apply the versioned aggregation policy to the twelve reports; return outcome and scores.

    Specialists classify their findings; this code maps severities to the policy's score bands,
    takes each Agent's maximum, applies the weights and thresholds and resolves precedence
    ``BLOCKED_INCOMPLETE > HARD-FAIL > FAIL > PASS``.  The rule-based scan's code findings enter
    their Agent's score the same way; only they can yield ``HARD-FAIL``, and one of an unresolved
    or conflicting detector blocks instead.
    """

    policy = components["aggregation_policy"]
    thresholds = policy["thresholds"]
    floor = thresholds.get("confidence_floor")
    if type(floor) not in {int, float}:
        raise GovernanceClientError("review-artifact-invalid")
    scores = components["severity_scores"]
    blocking: set[str] = set()
    hard_fail = False
    vetoed = False
    agent_scores: list[int] = []
    weighted_sum = 0
    total_weight = 0
    status_reasons = {"failed": "AGG_AGENT_FAILED", "timeout": "AGG_TIMEOUT"}
    for observation in observations:
        agent_id = str(observation["agent_id"])
        if observation.get("status") != "ok":
            blocking.add(status_reasons.get(str(observation.get("status")), "AGG_INVALID_SCHEMA"))
        maximum = 0
        for finding in cast(list[dict[str, object]], observation.get("findings", [])):
            severity = str(finding.get("severity"))
            confidence = finding.get("confidence")
            if severity not in scores or type(confidence) not in {int, float}:
                raise GovernanceClientError("review-artifact-invalid")
            maximum = max(maximum, int(scores[severity]))
            if cast(float, confidence) < floor:
                blocking.add("AGG_LOW_CONFIDENCE")
            if str(finding.get("source", "")).startswith("source-conflict:"):
                blocking.add("AGG_AUTHORITATIVE_CONFLICT")
            if (
                agent_id in SECURITY_CRITICAL_VETO_AGENTS
                and severity == "critical"
                and cast(float, confidence) >= floor
            ):
                vetoed = True
        for code_finding in code_findings:
            if code_finding.get("agent_id") != agent_id:
                continue
            severity = str(code_finding.get("severity"))
            if severity not in scores:
                raise GovernanceClientError("review-artifact-invalid")
            maximum = max(maximum, int(scores[severity]))
            effect = code_finding.get("decision_effect")
            if effect == "hard-fail":
                hard_fail = True
            elif effect == "blocked-incomplete":
                blocking.add("AGG_AUTHORITATIVE_CONFLICT")
            else:
                raise GovernanceClientError("review-artifact-invalid")
            if agent_id in SECURITY_CRITICAL_VETO_AGENTS and severity == "critical":
                vetoed = True
        agent_scores.append(maximum)
        weight = _weight_micros(policy["weights"].get(agent_id))
        weighted_sum += maximum * weight
        total_weight += weight
    risk = (weighted_sum + total_weight // 2) // total_weight
    compliance = max(0, _percent_basis_points(thresholds.get("compliance_baseline")) - risk)
    if blocking:
        verdict, reasons = "BLOCKED_INCOMPLETE", sorted(blocking)
    elif hard_fail:
        verdict, reasons = "HARD-FAIL", ["AGG_HARD_FAIL"]
    elif vetoed:
        verdict, reasons = "FAIL", ["AGG_SECURITY_CRITICAL_VETO"]
    elif risk >= _percent_basis_points(thresholds.get("fail_score")):
        verdict, reasons = "FAIL", ["AGG_THRESHOLD_FAIL"]
    elif risk >= _percent_basis_points(thresholds.get("warning_score")):
        verdict, reasons = "PASS", ["AGG_THRESHOLD_WARNING"]
    else:
        verdict, reasons = "PASS", ["AGG_THRESHOLD_PASS"]
    outcome: dict[str, object] = {
        "verdict": verdict,
        "reason_codes": reasons,
        "weighted_risk_score_basis_points": risk,
        "compliance_score_basis_points": compliance,
    }
    return outcome, agent_scores


def _explanation_templates(raw: bytes) -> dict[tuple[str, str], str]:
    """``templates.<decision>.<reason_code>.text`` of the versioned explanation catalog."""

    templates: dict[tuple[str, str], str] = {}
    decision: str | None = None
    reason: str | None = None
    try:
        lines = raw.decode("utf-8").splitlines()
        start = lines.index("templates:") + 1
    except (UnicodeError, ValueError):
        raise GovernanceClientError("review-artifact-invalid") from None
    for line in lines[start:]:
        if not line.strip():
            continue
        if not line.startswith("  "):
            break
        matched = re.fullmatch(r"  ([A-Z][A-Z_-]+):", line)
        if matched is not None:
            decision, reason = matched.group(1), None
            continue
        matched = re.fullmatch(r"    ([A-Z][A-Z0-9_]+):", line)
        if matched is not None:
            reason = matched.group(1)
            continue
        matched = re.fullmatch(r"      text: (\".*\")", line)
        if matched is not None and decision is not None and reason is not None:
            templates[(decision, reason)] = str(_decode(matched.group(1).encode("utf-8")))
    return templates


def _rationale(components: dict[str, Any], outcome: dict[str, object]) -> str:
    """The decision's summary from the versioned template of its first reason code."""

    reasons = cast(list[str], outcome["reason_codes"])
    template = _explanation_templates(components["explanations"]).get(
        (str(outcome["verdict"]), reasons[0])
    )
    if template is None:
        raise GovernanceClientError("review-artifact-invalid")
    text = template.format(decision=outcome["verdict"], reason_code=reasons[0])
    if len(reasons) > 1:
        text += f" Ek gerekçe kodları: {', '.join(reasons[1:])}."
    return text


def _empty_manifest(canonicalization: str) -> dict[str, object]:
    return {
        "canonicalization": canonicalization,
        "availability": "not-used",
        "reason_code": "NOT_USED",
        "item_count": 0,
        "sha256": _canonical_sha256({"canonicalization": canonicalization, "items": []}),
    }


def _model_rerun(model: dict[str, object]) -> dict[str, object]:
    """Best-effort rerun metadata; only the reported model id and effort are ever known."""

    def unavailable(reason: str) -> dict[str, object]:
        return {
            "availability": "unavailable",
            "reason_code": reason,
            "id": None,
            "version": None,
            "sha256": None,
        }

    effort = model.get("effort")
    parameter: dict[str, object] = (
        {"name": "effort", "availability": "available", "reason_code": None, "value": effort}
        if effort is not None
        else {
            "name": "effort",
            "availability": "unavailable",
            "reason_code": "INFERENCE_PARAMETER_UNAVAILABLE",
            "value": None,
        }
    )
    return {
        "capability": "model_rerun",
        "requirement": "best-effort",
        "status": "unavailable",
        "reason_codes": ["MODEL_METADATA_UNAVAILABLE"],
        "exact_output_guaranteed": False,
        "provider": unavailable("PROVIDER_METADATA_UNAVAILABLE"),
        "deployment": unavailable("DEPLOYMENT_METADATA_UNAVAILABLE"),
        "model": unavailable("MODEL_VERSION_UNAVAILABLE"),
        "inference_parameters": {
            "availability": "partial" if effort is not None else "unavailable",
            "parameters": [parameter],
        },
        "controlled_evidence_reference": {
            "status": "unavailable",
            "reason_code": "CONTROLLED_EVIDENCE_NOT_CONFIGURED",
            "reference": None,
            "content_sha256": None,
            "access_controlled": False,
            "time_bounded": False,
            "expires_at": None,
        },
    }


def _decision_evidence(
    guard: dict[str, Any],
    context: dict[str, Any],
    components: dict[str, Any],
    results: list[dict[str, object]],
    primary_outcome: dict[str, object],
    second_outcome: dict[str, object],
    started_at: str,
    decided_at: str,
    scan_evidence: dict[str, object],
) -> dict[str, object]:
    """The single versioned evidence object; every digest is recomputed from its sources.

    ``scan_evidence`` binds the rule-based scan record, its code findings and every dismissed
    candidate with its specialist's reason.
    """

    harness = components["mandatory_governed_execution"]
    evaluator = components["agentic_evaluator"]
    client = context["client"]
    metadata = prompt_metadata_by_ref(str(context["prompt_source_ref"]))
    envelope: dict[str, object] = {
        "kind": "redacted-digest-only-prompt-envelope",
        "version": "1.0.0",
        "source_event_id": metadata["event_id"],
        "source_prompt_turn_id": metadata["prompt_turn_id"],
        "source_receipt_sha256": metadata["source_receipt_sha256"],
        "prompt_capture_sha256": metadata["prompt_capture_sha256"],
        "raw_content_stored": False,
    }
    envelope["sha256"] = _canonical_sha256(envelope)
    component_binding = {
        "authority": {
            "ref": "authority:project-manifest",
            "version": components["authority"]["version"],
            "sha256": components["authority"]["sha256"],
        },
        "orchestration": {
            key: components["orchestration"][key] for key in ("ref", "version", "sha256")
        },
        "aggregation_policy": {
            key: components["aggregation_policy"][key] for key in ("ref", "version", "sha256")
        },
        "agentic_evaluator": {
            "ref": evaluator["policy_ref"],
            "version": evaluator["version"],
            "sha256": evaluator["sha256"],
        },
        "harness": {
            "ref": harness["protocol_id"],
            "version": harness["version"],
            "sha256": harness["sha256"],
        },
        "rule": {key: harness["rule"][key] for key in ("ref", "version", "sha256")},
        "skill": {key: harness["skill"][key] for key in ("ref", "version", "sha256")},
        "agent_manifest": {
            "canonicalization": "kt-agentic-agent-component-manifest-json-v1",
            "agent_count": len(results),
            "sha256": _canonical_sha256(guard["_agent_manifest"](results)),
        },
        "client": {key: client[key] for key in ("id", "version", "sha256")},
    }
    manifests = {
        "context": _empty_manifest("kt-agentic-context-manifest-json-v1"),
        "retrieval": _empty_manifest("kt-agentic-retrieval-manifest-json-v1"),
        "tool_results": _empty_manifest("kt-agentic-tool-result-manifest-json-v1"),
    }
    primary: dict[str, object] = {
        "canonicalization": "kt-agentic-primary-evaluation-json-v1",
        "sha256": "",
        "invocation_id": context["evaluator"]["invocation_id"],
        "span_id": context["evaluator"]["span_id"],
        "started_at": started_at,
        "completed_at": started_at,
        **primary_outcome,
    }
    primary["sha256"] = _canonical_sha256(primary, excluding="sha256")
    snapshot_sha256 = context["snapshot_sha256"]
    checked = {
        "canonicalization": "kt-agentic-checked-digest-set-json-v1",
        "canonical_input_sha256": snapshot_sha256,
        "snapshot_sha256": snapshot_sha256,
        "authority_sha256": component_binding["authority"]["sha256"],
        "orchestration_sha256": component_binding["orchestration"]["sha256"],
        "aggregation_policy_sha256": component_binding["aggregation_policy"]["sha256"],
        "agentic_evaluator_sha256": component_binding["agentic_evaluator"]["sha256"],
        "harness_sha256": component_binding["harness"]["sha256"],
        "rule_sha256": component_binding["rule"]["sha256"],
        "skill_sha256": component_binding["skill"]["sha256"],
        "agent_manifest_sha256": component_binding["agent_manifest"]["sha256"],
        "client_sha256": component_binding["client"]["sha256"],
        "prompt_template_sha256": component_binding["skill"]["sha256"],
        "prompt_envelope_sha256": envelope["sha256"],
        "context_manifest_sha256": manifests["context"]["sha256"],
        "retrieval_manifest_sha256": manifests["retrieval"]["sha256"],
        "tool_result_manifest_sha256": manifests["tool_results"]["sha256"],
        "primary_evaluation_sha256": primary["sha256"],
    }
    audit_replay: dict[str, object] = {
        "capability": "audit_replay",
        "requirement": "mandatory",
        "canonicalization": "kt-agentic-audit-replay-json-v1",
        "sha256": "",
        "status": "verified",
        "reason_codes": ["AUDIT_REPLAY_VERIFIED"],
        "project_id": context["project_id"],
        "run_id": context["run_id"],
        "trace_id": context["trace_id"],
        "input_binding": {
            "canonical_input": {
                "canonicalization": "kt-agentic-review-input-manifest-json-v1",
                "item_count": 1,
                "sha256": snapshot_sha256,
            },
            "snapshot": {
                "canonicalization": "kt-git-index-snapshot-json-v1",
                "sha256": snapshot_sha256,
            },
            "acceptance_criteria": context["acceptance_criteria"],
        },
        "component_binding": component_binding,
        "prompt_binding": {
            "template": {key: harness["skill"][key] for key in ("ref", "version", "sha256")},
            "envelope": envelope,
        },
        "manifests": manifests,
        "primary_evaluation": primary,
        "second_pass_validator": {
            "validator_id": "validator:governed-review-agentic-second-pass",
            "version": evaluator["version"],
            "sha256": _canonical_sha256(
                {
                    "canonicalization": "kt-agentic-second-pass-validator-binding-json-v1",
                    "agentic_evaluator_sha256": evaluator["sha256"],
                    "harness_sha256": harness["sha256"],
                    "skill_sha256": harness["skill"]["sha256"],
                }
            ),
            "method": "independent-second-pass-policy-recalculation",
            "invocation_id": context["second_pass"]["invocation_id"],
            "span_id": context["second_pass"]["span_id"],
            "checked_digest_set": checked,
            "checked_digest_set_sha256": _canonical_sha256(checked),
            "result": "verified",
            "recalculated": second_outcome,
            "matches_primary_evaluation": True,
            "claim_boundary": {
                "external_independence_proven": False,
                "deterministic_runtime": False,
                "production_authority": False,
            },
            "completed_at": decided_at,
        },
    }
    audit_replay["sha256"] = _canonical_sha256(audit_replay, excluding="sha256")
    evidence: dict[str, object] = {
        "schema_version": "1.1",
        "kind": "AgenticGovernedReviewDecisionEvidence",
        "evidence_profile": "phase1-evidence-bound-accountable-replay",
        "canonicalization": "kt-agentic-decision-evidence-json-v1",
        "evidence_sha256": "",
        "audit_replay": audit_replay,
        "deterministic_scan": scan_evidence,
        "model_rerun": _model_rerun(cast(dict[str, object], context["model"])),
        "data_handling": {**_data_handling(), "credential_stored": False},
    }
    evidence["evidence_sha256"] = _canonical_sha256(evidence, excluding="evidence_sha256")
    return evidence


def _decision(
    context: dict[str, Any],
    components: dict[str, Any],
    evidence: dict[str, Any],
    observations: list[dict[str, object]],
) -> dict[str, object]:
    primary = evidence["audit_replay"]["primary_evaluation"]
    policy = components["aggregation_policy"]
    return {
        "schema_version": "1.0",
        "kind": "AgenticGovernedReviewDecision",
        "evidence_profile": "phase1-agentic-advisory",
        "receipt_id": context["receipt_id"],
        "project_id": context["project_id"],
        "run_id": context["run_id"],
        "trace_id": context["trace_id"],
        "span_id": primary["span_id"],
        "evaluator_invocation_id": primary["invocation_id"],
        "snapshot_sha256": context["snapshot_sha256"],
        "aggregation_policy": {
            key: policy[key]
            for key in ("ref", "version", "sha256", "instructions_ref", "instructions_sha256")
        },
        "agentic_evaluator": components["agentic_evaluator"],
        "agent_statuses": {
            str(observation["agent_id"]): observation["status"] for observation in observations
        },
        "acceptance_criteria": context["acceptance_criteria"],
        "decision": primary["verdict"],
        "reason_codes": primary["reason_codes"],
        "rationale_summary": primary["rationale_summary"],
        "weighted_risk_score_basis_points": primary["weighted_risk_score_basis_points"],
        "compliance_score_basis_points": primary["compliance_score_basis_points"],
        "decision_evidence_sha256": evidence["evidence_sha256"],
        "claim_boundary": {
            "deterministic_decision": False,
            "canonical_conformance": False,
            "runtime_admission": False,
            "production_decision": False,
        },
        "data_handling": _data_handling(),
        "evaluation_started_at": primary["started_at"],
        "decided_at": evidence["audit_replay"]["second_pass_validator"]["completed_at"],
    }


def _receipt(
    guard: dict[str, Any],
    context: dict[str, Any],
    components: dict[str, Any],
    snapshot: dict[str, object],
    results: list[dict[str, object]],
    evidence: dict[str, Any],
    decision: dict[str, object],
    decision_raw: bytes,
    created_at: str,
) -> dict[str, object]:
    run_id = context["run_id"]
    client_id = context["client"]["id"]
    hook_error, timeout = guard["EXPECTED_NATIVE_SURFACE"][client_id]
    receipt: dict[str, object] = {
        "schema_version": "1.0",
        "kind": "AgenticGovernedReviewReceipt",
        "evidence_profile": "phase1-agentic-advisory",
        "receipt_id": context["receipt_id"],
        "project_id": context["project_id"],
        "run_id": run_id,
        "trace_id": context["trace_id"],
        "authority": components["authority"],
        "snapshot": {**snapshot, "snapshot_sha256": context["snapshot_sha256"]},
        "orchestration": components["orchestration"],
        "aggregation_policy": components["aggregation_policy"],
        "agentic_evaluator": components["agentic_evaluator"],
        "mandatory_governed_execution": components["mandatory_governed_execution"],
        "execution": {
            "session_id": context["session_id"],
            "client": context["client"],
            "model": context["model"],
        },
        "agent_results": results,
        "acceptance_criteria": context["acceptance_criteria"],
        "reuse_identity_canonicalization": "kt-agentic-review-reuse-json-v3",
        "reuse_identity_sha256": "",
        "decision_evidence": evidence,
        "decision": decision["decision"],
        "reason_codes": decision["reason_codes"],
        "weighted_risk_score_basis_points": decision["weighted_risk_score_basis_points"],
        "compliance_score_basis_points": decision["compliance_score_basis_points"],
        "report_directory": f"governed-review/{run_id}/reports",
        "decision_path": f"governed-review/{run_id}/decision.json",
        "decision_sha256": hashlib.sha256(decision_raw).hexdigest(),
        "audit_path": f"governed-review/{run_id}/audit.json",
        "audit_event_count": 14,
        "receipt_canonicalization": "kt-agentic-governed-review-receipt-json-v1",
        "receipt_sha256": "",
        "same_snapshot_retry_only": True,
        "native_surface": {
            "client_id": client_id,
            "adapter_mode": "native-command-receipt-guard",
            "hook_error_behavior": hook_error,
            "timeout_behavior": timeout,
            "enforcement_claim": "conditional-native-guard",
            "native_result_recorded": False,
            "commit_retry_recorded": False,
        },
        "claim_boundary": {
            "deterministic_decision": False,
            "canonical_conformance": False,
            "runtime_admission": False,
            "production_decision": False,
            "immutable_audit": False,
        },
        "data_handling": _data_handling(),
        "created_at": created_at,
    }
    receipt["reuse_identity_sha256"] = _canonical_sha256(guard["_reuse_identity"](receipt))
    receipt["receipt_sha256"] = _canonical_sha256(receipt, excluding="receipt_sha256")
    return receipt


def _finding_summaries(
    observations: list[dict[str, object]], catalog: dict[str, dict[str, str]]
) -> list[dict[str, object]]:
    """Report references for the Agent's answer to the user; no raw source or prompt.

    A specialist finding's reason is its redacted evidence summary and its basis is the
    institutional policy binding code wrote into `controls`; it has no ISO/KVKK basis of its own.
    """

    summaries: list[dict[str, object]] = []
    for observation in observations:
        for finding in cast(list[dict[str, object]], observation.get("findings", [])):
            locations = cast(list[dict[str, object]], finding.get("locations", []))
            controls = cast(list[dict[str, object]], finding.get("controls", []))
            if any(item.get("standard_id") != INSTITUTIONAL_STANDARD for item in controls):
                raise _basis_failure()
            summaries.append(
                {
                    "agent_id": observation["agent_id"],
                    "finding_id": finding.get("finding_id"),
                    "severity": finding.get("severity"),
                    "confidence": finding.get("confidence"),
                    "title": finding.get("title"),
                    "locations": [
                        f"{location.get('path')}:{location.get('start_line')}"
                        for location in locations[:3]
                    ],
                    "reason_line": reason_line(str(finding.get("evidence_summary")), catalog),
                    "basis_lines": basis_lines(
                        [
                            {**item, "mapping_status": "institutional-policy-binding"}
                            for item in controls
                        ],
                        catalog,
                    ),
                }
            )
    return summaries


def _run_inputs(
    run_root: Path, guard: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, object], dict[str, dict[str, object]]]:
    """The code-written run context, snapshot identity and twelve bindings inputs."""

    _, context = _read_review_json(run_root / "inputs" / "run.json")
    _, snapshot = _read_review_json(run_root / "inputs" / "snapshot.json")
    if (
        context.get("canonicalization") != RUN_CONTEXT_CANONICALIZATION
        or context.get("run_id") != run_root.name
        or _canonical_sha256(snapshot) != context.get("snapshot_sha256")
    ):
        raise GovernanceClientError("review-artifact-invalid")
    bindings: dict[str, dict[str, object]] = {}
    for agent_id in guard["AGENTS"]:
        slug = agent_id.removeprefix("agent:")
        bindings[agent_id] = _read_review_json(run_root / "inputs" / f"{slug}.bindings.json")[1]
    return cast(dict[str, Any], context), snapshot, bindings


def _verified_scan_record(
    project_root: Path,
    run_root: Path,
    guard: dict[str, Any],
    context: dict[str, Any],
    schemas: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """The run's scan record after the scan is run again on the staged tree and matches it."""

    raw, record = _read_review_json(run_root / f"{SCAN_RECORD_NAME}.json")
    try:
        guard["_validate_against_schema"](record, guard["SCAN_RECORD_SCHEMA"], schemas)
    except guard["GuardError"]:
        raise GovernanceClientError(
            "review-run-invalid", reason_code="DETERMINISTIC_SCAN_INVALID"
        ) from None
    if (
        record.get("project_id") != context["project_id"]
        or record.get("run_id") != context["run_id"]
        or record.get("snapshot_sha256") != context["snapshot_sha256"]
    ):
        raise GovernanceClientError("review-run-invalid", reason_code="DETERMINISTIC_SCAN_INVALID")
    if record.get("status") != "complete":
        raise GovernanceClientError(
            "review-run-invalid", reason_code="DETERMINISTIC_SCAN_INCOMPLETE"
        )
    try:
        body = deterministic_scan(project_root)
    except GovernanceClientError as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.reason_code) from None
    if record != _scan_record(
        str(context["project_id"]), str(context["run_id"]), str(context["snapshot_sha256"]), body
    ):
        raise GovernanceClientError("review-run-invalid", reason_code="DETERMINISTIC_SCAN_MISMATCH")
    return raw, cast(dict[str, Any], record)


def _scan_finding_summaries(
    record: dict[str, Any],
    code_findings: list[dict[str, Any]],
    dismissed: list[dict[str, Any]],
    basis: dict[str, dict[str, Any]],
    catalog: dict[str, dict[str, str]],
) -> dict[str, object]:
    """The rule-based scan's findings and dismissals for the Agent's answer to the user.

    Each code finding carries its detector's reason and basis lines from the packs this run read.
    """

    summaries = {item["candidate_id"]: item["summary"] for item in record["matches"]}
    return {
        "deterministic_findings": [
            {
                "agent_id": item["agent_id"],
                "detector_id": item["detector_id"],
                "severity": item["severity"],
                "location": f"{item['path']}:{item['start_line']}",
                "summary": summaries[item["candidate_id"]],
                **detector_explanation(item["detector_id"], basis, catalog),
            }
            for item in code_findings
        ],
        "dismissed_candidates": [
            {
                "agent_id": item["agent_id"],
                "detector_id": item["detector_id"],
                "location": f"{item['path']}:{item['start_line']}",
                "reason": item["reason"],
            }
            for item in dismissed
        ],
    }


DECISION_EVENT_VERDICTS = frozenset({"HARD-FAIL", "FAIL"})
MAX_DECISION_EVENT_FINDINGS = 64


def _location_fields(location: dict[str, Any]) -> dict[str, object]:
    return {field: location[field] for field in ("path", "start_line", "end_line")}


def _record_decision_event(
    project_id: str,
    decision: dict[str, object],
    decision_raw: bytes,
    code_findings: list[dict[str, Any]],
    observations: list[dict[str, object]],
) -> None:
    """Chain a HARD-FAIL or FAIL decision so the central notifier receives it.

    The record names detectors, agents, finding identifiers and file locations only; no title,
    rationale, source line or prompt.  A record that cannot be written never changes the decision.
    """

    if decision.get("decision") not in DECISION_EVENT_VERDICTS:
        return
    try:
        run_id = str(decision["run_id"])
        veto: list[dict[str, object]] = []
        for observation in observations:
            if observation.get("agent_id") not in SECURITY_CRITICAL_VETO_AGENTS:
                continue
            for finding in cast(list[dict[str, Any]], observation.get("findings", [])):
                if finding.get("severity") != "critical":
                    continue
                veto.append(
                    {
                        "agent_id": observation["agent_id"],
                        "finding_id": finding["finding_id"],
                        "severity": "critical",
                        "locations": [
                            _location_fields(location) for location in finding["locations"][:3]
                        ],
                    }
                )
        body = {
            "schema_version": "1.0",
            "kind": "GovernedReviewDecisionEvent",
            "run_id": run_id,
            "project_id": project_id,
            "snapshot_sha256": decision["snapshot_sha256"],
            "decision": decision["decision"],
            "reason_codes": decision["reason_codes"],
            "decision_sha256": hashlib.sha256(decision_raw).hexdigest(),
            "decided_at": decision["decided_at"],
            "code_findings": [
                {
                    "agent_id": item["agent_id"],
                    "detector_id": item["detector_id"],
                    "severity": item["severity"],
                    "decision_effect": item["decision_effect"],
                    **_location_fields(item),
                }
                for item in code_findings[:MAX_DECISION_EVENT_FINDINGS]
            ],
            "security_veto_findings": veto[:MAX_DECISION_EVENT_FINDINGS],
            "raw_content_recorded": False,
        }
        record_id = hashlib.sha256(f"review-decision\n{run_id}".encode()).hexdigest()[:32]
        _hook_module("governance_records.py")["write_event"](
            "review-decision",
            project_id,
            body,
            record_id=record_id,
            location=_record_location(),
        )
    except Exception:  # noqa: S110 -- the record never changes the review decision
        return


def finalize_review(run_id: str) -> dict[str, object]:
    """Decide a complete run and, for PASS, write its receipt, audit and publication; resumable.

    The decision, its evidence and the receipt come from the twelve reports, the run inputs and
    the versioned policies.  An interrupted run resumes from its stored decision and receipt;
    the Agent never writes or corrects them.
    """

    started = time.monotonic()
    project_root = Path.cwd().resolve(strict=True)
    project_id, run_root = _review_run(project_root, run_id)
    guard = _hook_module("agentic_review_receipt_guard.py")
    context, snapshot, bindings = _run_inputs(run_root, guard)
    try:
        current = guard["_capture_snapshot"](project_root, "git")
        components = _component_bindings(project_root, guard, str(context["client"]["id"]))
    except guard["GuardError"] as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.code) from None
    if current["snapshot_sha256"] != context["snapshot_sha256"]:
        raise GovernanceClientError("review-run-invalid", reason_code="SNAPSHOT_CHANGED")
    schemas = guard["_schema_registry"](project_root)
    record_raw, record = _verified_scan_record(project_root, run_root, guard, context, schemas)
    try:
        basis = finding_basis(project_root)
        catalog = finding_catalog(components["explanations"])
    except GovernanceClientError as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.reason_code) from None
    missing = [
        agent_id
        for agent_id in guard["AGENTS"]
        if not (run_root / "reports" / f"{agent_id.removeprefix('agent:')}.json").exists()
    ]
    if missing:
        return {
            "status": "incomplete",
            "run_id": run_id,
            "missing_agents": missing,
            "next_action": "dispatch-specialists",
        }
    observations: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for agent_id in guard["AGENTS"]:
        slug = agent_id.removeprefix("agent:")
        raw, observation = _read_review_json(run_root / "reports" / f"{slug}.json")
        try:
            guard["_validate_against_schema"](
                observation, "agentic-governance-observation.schema.json", schemas
            )
        except guard["GuardError"]:
            raise GovernanceClientError(
                "review-run-invalid", reason_code="REPORT_SCHEMA_INVALID"
            ) from None
        candidates = guard["deterministic_candidates"](record, agent_id)
        expected = _observation_bindings(context, components, agent_id, candidates)
        if any(observation.get(key) != value for key, value in expected.items()) or any(
            observation.get(key) != value for key, value in bindings[agent_id].items()
        ):
            raise GovernanceClientError("review-run-invalid", reason_code="REPORT_BINDING_MISMATCH")
        if (
            guard["candidate_response_problem"](
                candidates, observation.get("candidate_responses"), observation.get("status")
            )
            is not None
        ):
            raise GovernanceClientError(
                "review-run-invalid", reason_code="CANDIDATE_RESPONSES_INVALID"
            )
        observations.append(observation)
        findings = cast(list[object], observation.get("findings", []))
        results.append(
            {
                "agent_id": agent_id,
                "invocation_id": expected["invocation_id"],
                "span_id": expected["span_id"],
                "status": observation["status"],
                "component_binding": expected["component_binding"],
                "report_path": f"governed-review/{run_id}/reports/{slug}.json",
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "finding_count": len(findings),
                "max_risk_score_basis_points": 0,
            }
        )
    try:
        code_findings, dismissed = guard["deterministic_scan_findings"](record, observations)
    except guard["GuardError"] as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.code) from None
    outcome, agent_scores = _policy_outcome(components, observations, code_findings)
    for index, score in enumerate(agent_scores):
        results[index]["max_risk_score_basis_points"] = score
    outcome = {**outcome, "rationale_summary": _rationale(components, outcome)}
    decision_path = run_root / "decision.json"
    if decision_path.exists() or decision_path.is_symlink():
        decision_raw, decision = _read_review_json(decision_path)
        started_at = str(decision.get("evaluation_started_at"))
        decided_at = str(decision.get("decided_at"))
    else:
        started_at = _iso_utc(datetime.now(UTC))
        decided_at = ""
    receipt_like = {
        "aggregation_policy": components["aggregation_policy"],
        "agent_results": results,
    }
    try:
        recalculated = guard["recalculate_policy_outcome"](
            receipt_like, observations, components["severity_scores"], code_findings
        )
    except guard["GuardError"] as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.code) from None
    second_outcome = {**recalculated, "rationale_summary": _rationale(components, recalculated)}
    if second_outcome != outcome:
        # Producer and commit-hook verifier disagree: record nothing and let the tests show why.
        raise GovernanceClientError(
            "review-run-invalid", reason_code="POLICY_RECALCULATION_MISMATCH"
        )
    if not decided_at:
        decided_at = _iso_utc(datetime.now(UTC))
    scan_evidence = guard["deterministic_scan_evidence"](
        run_id, hashlib.sha256(record_raw).hexdigest(), code_findings, dismissed
    )
    evidence = _decision_evidence(
        guard,
        context,
        components,
        results,
        outcome,
        second_outcome,
        started_at,
        decided_at,
        scan_evidence,
    )
    decision = _decision(context, components, evidence, observations)
    try:
        explained = {
            "findings": _finding_summaries(observations, catalog),
            **_scan_finding_summaries(record, code_findings, dismissed, basis, catalog),
        }
    except GovernanceClientError as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.reason_code) from None
    try:
        guard["_validate_against_schema"](
            evidence, "agentic-governed-review-decision-evidence.schema.json", schemas
        )
        guard["_validate_against_schema"](
            decision, "agentic-governed-review-decision.schema.json", schemas
        )
    except guard["GuardError"] as exc:
        raise GovernanceClientError("review-run-invalid", reason_code=exc.code) from None
    _, decision_raw, _ = _write_artifact(project_id, run_id, "decision", decision)
    _record_decision_event(project_id, decision, decision_raw, code_findings, observations)
    summary: dict[str, object] = {
        "run_id": run_id,
        "acceptance_criteria": decision["acceptance_criteria"],
        "decision": decision["decision"],
        "reason_codes": decision["reason_codes"],
        "rationale_summary": decision["rationale_summary"],
        "weighted_risk_score_basis_points": decision["weighted_risk_score_basis_points"],
        "compliance_score_basis_points": decision["compliance_score_basis_points"],
        **explained,
    }
    if decision["decision"] != "PASS":
        return {
            **summary,
            "status": "decided",
            "next_action": "resolve-findings-and-start-a-new-run",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    receipt_path = run_root / "receipt.json"
    if not (receipt_path.exists() or receipt_path.is_symlink()):
        receipt = _receipt(
            guard,
            context,
            components,
            snapshot,
            results,
            evidence,
            decision,
            decision_raw,
            _iso_utc(datetime.now(UTC)),
        )
        _write_artifact(project_id, run_id, "receipt", receipt)
    receipt_raw, receipt = _read_review_json(receipt_path)
    events = _build_review_audit_events(run_root, receipt_path, receipt, decision_raw, decision)
    _verify_review_run(project_root, receipt_raw, receipt, events)
    writer = _hook_module("governance_records.py")
    location = _record_location()
    try:
        try:
            writer["write_review_run_file"](
                project_id, run_id, "audit", {"events": events}, location=location
            )
            audit = "written"
        except writer["RecordError"] as exc:
            if exc.code != "review-run-file-exists":
                raise
            _, stored = writer["read_review_run_file"](
                project_id, run_id, "audit", location=location
            )
            if stored.get("body") != {"events": events}:
                raise GovernanceClientError("audit-invalid") from None
            audit = "reused"
        _, created = writer["publish_review"](
            project_id,
            context["snapshot_sha256"],
            run_id,
            hashlib.sha256(receipt_raw).hexdigest(),
            location=location,
        )
    except writer["RecordError"]:
        raise GovernanceClientError("current-publication-failed") from None
    return {
        **summary,
        "status": "complete",
        "audit": audit,
        "current_receipt": "published" if created else "reused",
        "next_action": "commit-retry",
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _restore_relative(value: str) -> str:
    """A project-relative POSIX path; Windows separators are accepted, escapes are not."""

    if "\0" in value:
        raise ValueError("UNSAFE_PATH")
    windows = PureWindowsPath(value)
    text = value.replace("\\", "/")
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if text.startswith("/") or windows.drive or windows.root or not parts or ".." in parts:
        raise ValueError("UNSAFE_PATH")
    return "/".join(parts)


def _restore_destination(project_root: Path, relative: str) -> Path:
    """The project path of `relative` when no part of it is a link and it stays in the project."""

    current = project_root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError("LINKED_PATH")
    try:
        current.resolve(strict=False).relative_to(project_root)
    except (OSError, ValueError):
        raise ValueError("LINKED_PATH") from None
    if current.exists() and not current.is_file():
        raise ValueError("LINKED_PATH")
    return current


def _recorded_digests(project_root: Path) -> dict[str, str]:
    """The managed path to SHA-256 record of the scaffold ownership manifest."""

    try:
        manifest = _restore_destination(project_root, MANAGED_MANIFEST_PATH)
        payload = _decode(manifest.read_bytes())
    except (OSError, ValueError, GovernanceClientError):
        raise GovernanceClientError("restore-refused", reason_code="MANIFEST_INVALID") from None
    managed = payload.get("managed") if isinstance(payload, dict) else None
    if not isinstance(managed, dict) or any(
        not isinstance(path, str) or not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest)
        for path, digest in managed.items()
    ):
        raise GovernanceClientError("restore-refused", reason_code="MANIFEST_INVALID")
    return cast(dict[str, str], managed)


class _History:
    """Read the project's object store only: commit trees and blobs, never the index."""

    def __init__(self, project_root: Path, records: dict[str, Any]) -> None:
        executable = shutil.which("git")
        if executable is None:
            raise OSError("git-unavailable")
        self.command = [executable, "-C", str(project_root), "--literal-pathspecs"]
        excluded = records["GIT_LOCATION_VARIABLES"]
        self.environment = {key: value for key, value in os.environ.items() if key not in excluded}
        self.environment["GIT_OPTIONAL_LOCKS"] = "0"
        self.environment["GIT_TERMINAL_PROMPT"] = "0"

    def __call__(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [*self.command, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=self.environment,
        )


def _recorded_bytes(git: _History, relative: str, expected: str) -> tuple[bytes, int] | None:
    """Find the recorded bytes of `relative` in `HEAD`, then in its history, newest first."""

    checked: set[str] = set()

    def search(commits: list[str]) -> tuple[bytes, int] | None:
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
                    or mode not in RESTORE_FILE_MODES
                    or object_id in checked
                    or not size.isdigit()
                    or int(size) > MAX_RESTORE_BLOB_BYTES
                ):
                    continue
                checked.add(object_id)
                blob = git("cat-file", "blob", object_id)
                if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == expected:
                    return blob.stdout, RESTORE_FILE_MODES[mode]
        return None

    found = search(["HEAD"])
    if found is not None:
        return found
    history = git("rev-list", "--full-history", "HEAD", "--", relative)
    if history.returncode != 0:
        return None
    return search(history.stdout.decode("ascii", "replace").split())


def _replace_file(destination: Path, content: bytes, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".kt-restore-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise


def _utf8_output() -> None:
    """A Windows pipe defaults to the ANSI code page, which cannot print Turkish letters."""

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def _restore_refused(refused: list[dict[str, str]]) -> GovernanceClientError:
    reasons = list(dict.fromkeys(item["reason"] for item in refused))
    guidance = " ".join(RESTORE_GUIDANCE[reason] for reason in reasons)
    return GovernanceClientError(
        "restore-refused",
        reason_code=reasons[0],
        violation={"refused": refused},
        guidance=f"{guidance} Hiçbir dosya değiştirilmedi.",
    )


def restore_managed_files(arguments: list[str]) -> dict[str, object]:
    """Write drifted scaffold-managed files back to their recorded bytes from commit history.

    All named paths are checked first; one refusal writes nothing.  Output names only paths.
    """

    project_root = Path(__file__).resolve().parents[2]
    managed = _recorded_digests(project_root)
    refused: list[dict[str, str]] = []
    current: list[str] = []
    planned: list[tuple[str, Path, bytes, int]] = []
    git: _History | None = None
    for value in dict.fromkeys(arguments):
        shown = value[:512]
        try:
            relative = shown = _restore_relative(value)
            if relative in {item[0] for item in planned} or relative in current:
                continue
            expected = managed.get(relative)
            if expected is None:
                raise ValueError("UNMANAGED_PATH")
            destination = _restore_destination(project_root, relative)
            if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == (
                expected
            ):
                current.append(relative)
                continue
            if git is None:
                records = _hook_module("governance_records.py")
                if records["repository_status"](project_root) != "ok":
                    raise ValueError("NOT_IN_HISTORY")
                git = _History(project_root, records)
            found = _recorded_bytes(git, relative, expected)
            if found is None:
                raise ValueError("NOT_IN_HISTORY")
            planned.append((relative, destination, *found))
        except ValueError as reason:
            code = str(reason) if str(reason) in RESTORE_GUIDANCE else "UNSAFE_PATH"
            refused.append({"path": shown, "reason": code})
        except (OSError, subprocess.SubprocessError):
            refused.append({"path": shown, "reason": "NOT_IN_HISTORY"})
    if refused:
        raise _restore_refused(refused)
    restored: list[str] = []
    for relative, destination, content, mode in planned:
        try:
            _restore_destination(project_root, relative)
            _replace_file(destination, content, mode)
        except (OSError, ValueError):
            error = _restore_refused([{"path": relative, "reason": "WRITE_FAILED"}])
            error.guidance = (
                f"{RESTORE_GUIDANCE['WRITE_FAILED']} Geri alınan dosyalar: "
                f"{', '.join(restored) or 'yok'}."
            )
            raise error from None
        restored.append(relative)
    status = "restored" if restored else "current"
    return {"status": status, "restored": restored, "current": current}


def _project_id(project_root: Path) -> str:
    value = _read_regular_json(
        project_root / ".kt-scaffold/project-manifest.json", maximum=MAX_PROMPT_METADATA_BYTES
    ).get("project_id")
    if not isinstance(value, str) or PROJECT_ID_RE.fullmatch(value) is None:
        raise GovernanceClientError("prompt-metadata-invalid")
    return value


def _metadata_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GovernanceClientError("prompt-metadata-invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise GovernanceClientError("prompt-metadata-invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise GovernanceClientError("prompt-metadata-invalid")
    return parsed


def _validate_prompt_metadata(
    value: dict[str, object], *, client_id: str, project_id: str, event_token: str
) -> datetime:
    source_ref = f"record:v1:{project_id}:prompt-ingress:{event_token}"
    expected_event = "beforeSubmitPrompt" if client_id == "cursor" else "UserPromptSubmit"
    if (
        set(value) != PROMPT_METADATA_KEYS
        or value.get("schema_version") != "2.0"
        or value.get("kind") != "PromptIngressMetadata"
        or value.get("project_id") != project_id
        or value.get("client_id") != client_id
        or value.get("event") != expected_event
        or value.get("event_id") != f"event:{event_token}"
        or value.get("source_receipt_path") != source_ref
        or not isinstance(value.get("source_receipt_sha256"), str)
        or DIGEST_RE.fullmatch(str(value["source_receipt_sha256"])) is None
        or not isinstance(value.get("prompt_capture_sha256"), str)
        or DIGEST_RE.fullmatch(str(value["prompt_capture_sha256"])) is None
        or not isinstance(value.get("prompt_session_id"), str)
        or SESSION_ID_RE.fullmatch(str(value["prompt_session_id"])) is None
        or value.get("prompt_session_id_source") != "client-envelope"
        or not isinstance(value.get("prompt_turn_id"), str)
        or TURN_ID_RE.fullmatch(str(value["prompt_turn_id"])) is None
        or value.get("prompt_turn_id_source")
        not in {"client-envelope", "local-generated-client-unavailable"}
        or value.get("decision") not in {"allow", "block"}
        or value.get("outcome") not in {"clean", "matched", "input-invalid", "guard-error"}
        or (value.get("decision") == "allow" and value.get("outcome") != "clean")
        or (value.get("decision") == "block" and value.get("outcome") == "clean")
    ):
        raise GovernanceClientError("prompt-metadata-invalid")
    try:
        _hook_module("llm_call_events.py")["validate_model"](value.get("model"))
    except Exception:
        raise GovernanceClientError("prompt-metadata-invalid") from None
    return _metadata_time(value.get("occurred_at"))


def _hook_module(name: str) -> dict[str, Any]:
    path = Path(__file__).resolve().with_name(name)
    if path.is_symlink() or not path.is_file():
        raise GovernanceClientError("prompt-metadata-invalid")
    return runpy.run_path(str(path))


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _managed_preferences() -> Any:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


DEVICE_GATED_OPERATIONS = frozenset({"review-start", "finalize-review", "restore"})


def _local_override_gate(project_root: Path) -> None:
    """Refuse a governed review on a managed device while a local client file bypasses governance.

    Any other device only hears the warning on stderr; the review goes on.
    """
    records = _hook_module("governance_records.py")
    findings = records["local_client_overrides"](project_root)
    if not findings:
        return
    blocking = bool(records["managed_device"](_managed_preferences()))
    message = str(records["local_override_message"](findings, blocking=blocking))
    if blocking:
        raise GovernanceClientError("local-client-override", guidance=message)
    print(message, file=sys.stderr)


def _device_refusal(operation: str) -> GovernanceClientError | None:
    """Refuse a review or restore command on a stopped device, before any other check."""
    try:
        records = _hook_module("governance_records.py")
        decision, _ = records["device_gate"](
            location=_record_location(), managed_preferences=_managed_preferences()
        )
    except Exception:
        return None
    if decision not in {"stop", "unverified"}:
        return None
    records["record_refusal"](
        "governance-client", decision, client=None, location=_record_location()
    )
    code = "device-stopped" if decision == "stop" else "device-state-unverified"
    return GovernanceClientError(code, guidance=records["gate_message"](decision, marker=True))


def _stored_prompt_metadata(record: dict[str, Any]) -> dict[str, object]:
    try:
        return cast(
            dict[str, object], _hook_module("prompt_ingress_guard.py")["prompt_metadata"](record)
        )
    except GovernanceClientError:
        raise
    except Exception:
        raise GovernanceClientError("prompt-metadata-invalid") from None


def prompt_metadata_by_ref(source_ref: str) -> dict[str, object]:
    """Return the metadata projection of one stored prompt record in the shared root."""

    match = re.fullmatch(
        r"record:v1:(project-[0-9a-f]{32}):prompt-ingress:([0-9a-f]{32})", source_ref
    )
    if match is None:
        raise GovernanceClientError("invalid-request")
    writer = _hook_module("governance_records.py")
    try:
        record = writer["read_event"](
            "prompt-ingress", match.group(1), match.group(2), location=_record_location()
        )
    except writer["RecordError"]:
        raise GovernanceClientError("prompt-metadata-missing") from None
    return _stored_prompt_metadata(record)


def current_prompt_metadata(client_id: str) -> dict[str, object]:
    """Return the latest prompt metadata bound to the current native client session."""
    environment_names = CLIENT_SESSION_ENVIRONMENT.get(client_id)
    if environment_names is None:
        raise GovernanceClientError("invalid-request")
    session_ids = {
        "session:client." + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        for name in environment_names
        if (raw := os.environ.get(name))
    }
    if not session_ids:
        raise GovernanceClientError("current-session-unavailable")

    project_id = _project_id(Path.cwd())
    writer = _hook_module("governance_records.py")
    try:
        records = writer["recent_events"](
            "prompt-ingress",
            project_id,
            limit=MAX_PROMPT_METADATA_FILES,
            location=_record_location(),
        )
    except writer["RecordError"]:
        raise GovernanceClientError("prompt-metadata-invalid") from None
    candidates: list[tuple[datetime, dict[str, object]]] = []
    for record in records:
        body = record.get("body")
        if (
            record.get("client") != client_id
            or not isinstance(body, dict)
            or body.get("prompt_session_id") not in session_ids
        ):
            continue
        metadata = _stored_prompt_metadata(record)
        observed_at = _validate_prompt_metadata(
            metadata,
            client_id=client_id,
            project_id=project_id,
            event_token=str(record["record_id"]),
        )
        if metadata["prompt_session_id"] in session_ids:
            candidates.append((observed_at, metadata))

    if not candidates:
        raise GovernanceClientError(
            "prompt-metadata-missing", guidance=PROMPT_HOOK_TRUST_GUIDANCE.get(client_id)
        )
    if len({str(value["prompt_session_id"]) for _, value in candidates}) != 1:
        raise GovernanceClientError("prompt-metadata-ambiguous")
    latest_time = max(observed_at for observed_at, _ in candidates)
    latest = [value for observed_at, value in candidates if observed_at == latest_time]
    if len(latest) != 1:
        raise GovernanceClientError("prompt-metadata-ambiguous")
    selected = latest[0]
    if selected["decision"] != "allow" or selected["outcome"] != "clean":
        raise GovernanceClientError("prompt-metadata-invalid")
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description="Shared-root prompt metadata and review publication.")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("preflight")
    current_metadata = commands.add_parser("current-prompt-metadata")
    current_metadata.add_argument(
        "--client-id", choices=tuple(CLIENT_SESSION_ENVIRONMENT), required=True
    )
    metadata = commands.add_parser("metadata")
    metadata.add_argument("--source-ref", required=True)
    start = commands.add_parser("review-start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--client-id", choices=tuple(CLIENT_SESSION_ENVIRONMENT), required=True)
    start.add_argument("--client-version", required=True)
    start.add_argument("--criteria-path", required=True)
    finalize = commands.add_parser("finalize-review")
    finalize.add_argument("--run-id", required=True)
    observation = commands.add_parser("observation")
    observation.add_argument("--run-id", required=True)
    observation.add_argument("--agent", required=True)
    commands.add_parser("consultation")
    commands.add_parser("scan-worker")
    restore = commands.add_parser("restore")
    restore.add_argument("paths", nargs="+")
    # A scan worker runs under the interpreter of the scan that started it.
    if argv is None and sys.argv[1:] != ["scan-worker"]:
        script = Path(__file__)
        if _hook_module("governance_records.py")["ensure_profile_interpreter"](
            Path.cwd(), script, sys.argv[1:]
        ):
            print(json.dumps({"error": "python-runtime-mismatch"}, separators=(",", ":")))
            return 1
    try:
        arguments = parser.parse_args(argv)
        exit_code = 0
        if arguments.operation in DEVICE_GATED_OPERATIONS:
            refusal = _device_refusal(arguments.operation)
            if refusal is not None:
                _utf8_output()
                raise refusal
        if arguments.operation == "preflight":
            result = preflight()
            exit_code = 0 if result["ok"] is True else 1
        elif arguments.operation == "current-prompt-metadata":
            result = current_prompt_metadata(arguments.client_id)
        elif arguments.operation == "metadata":
            result = prompt_metadata_by_ref(arguments.source_ref)
        elif arguments.operation == "review-start":
            result = review_start(
                arguments.run_id,
                arguments.client_id,
                arguments.client_version,
                arguments.criteria_path,
            )
        elif arguments.operation == "finalize-review":
            result = finalize_review(arguments.run_id)
            exit_code = 0 if result["status"] == "complete" else 1
        elif arguments.operation == "consultation":
            result = record_consultation(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
        elif arguments.operation == "scan-worker":
            result = scan_worker(sys.stdin.buffer.read())
        elif arguments.operation == "restore":
            _utf8_output()
            result = restore_managed_files(arguments.paths)
        else:
            result = record_observation(arguments.run_id, arguments.agent)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return exit_code
    except GovernanceClientError as exc:
        failure: dict[str, object] = {"error": str(exc)}
        if exc.reason_code is not None:
            failure["reason_code"] = exc.reason_code
        if exc.violation is not None:
            failure["violation"] = exc.violation
        if exc.guidance is not None:
            failure["guidance"] = exc.guidance
        print(json.dumps(failure, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
