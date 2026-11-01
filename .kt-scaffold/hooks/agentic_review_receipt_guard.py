#!/usr/bin/env python3
"""Validate Phase 1 Agentic evidence before a client-visible direct Git commit.

This dependency-free command hook is an evidence-integrity harness, not a semantic decision
engine.  It never creates or repairs evidence, invokes an Agent or interprets findings.  It
recalculates the aggregation policy outcome of the bound specialist reports only to verify the
declared one, and it permits a narrowly classified direct ``git commit`` only when an
already-produced PASS receipt is bound to the exact staged snapshot and its local evidence chain.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

MAX_EVENT_BYTES = 262_144
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_AUDIT_BYTES = 8 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 8
DENIAL_MARKER = "GOVERNED_REVIEW_REQUIRED"
UTC = timezone.utc  # noqa: UP017 -- generated hook must run on the host's Python 3.9.
UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z$"
)

CLIENTS = ("claude-code", "codex", "cursor", "github-copilot-vscode")
AGENTS = (
    "agent:gereksinim-kapsami",
    "agent:kurumsal-mimari",
    "agent:kod-kalitesi",
    "agent:kod-inceleme",
    "agent:bilgi-guvenligi",
    "agent:uygulama-guvenligi",
    "agent:acik-kaynak-lisansi",
    "agent:gizlilik-kvkk",
    "agent:test-otomasyonu",
    "agent:dokumantasyon",
    "agent:devops",
    "agent:gozlemlenebilirlik",
)
STAGE_ORDER = (
    "exact-snapshot",
    "twelve-agent-observations",
    "agentic-policy-evaluation",
    "decision-evidence-assembly",
    "independent-second-pass-validation",
    "decision",
    "snapshot-bound-receipt",
    "review-audit",
    "current-receipt-publication",
    "same-snapshot-action-retry",
)
TEST_AUTOMATION_AGENT = "agent:test-otomasyonu"
# The PRD under `specs/<domain>/PRDs/<nnn>-<slug>/PRD.md` whose acceptance criteria frame the Test
# Automation Agent; its `criteria_id` is `criteria:<domain>.<slug>`.
CRITERIA_PATH_RE = re.compile(
    r"specs/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)/PRDs/[0-9]{3}-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)/PRD\.md"
)
# The PRD's first `Status:` line is its status.  An accepted PRD binds as `accepted-frozen`; a
# draft binds as `draft` and still frames the review, because only the PRD's owner accepts it.
# Any other status stops the review.
PRD_STATUS_RE = re.compile(r"^Status:(.*)$", re.MULTILINE | re.IGNORECASE)
PRD_LIFECYCLES = {"accepted": "accepted-frozen", "draft": "draft"}
PRD_VERSION_RE = re.compile(
    r"^(?:Document version|Version):\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE
)
DRAFT_PRD_INITIAL_VERSION = "0.1.0"
# The agent's own remedy for a draft PRD that predates the spec tool's `Version: 0.1.0` line.
# The hook never adds the line itself and an accepted PRD stays the owner's to change.
DRAFT_VERSION_REMEDY = (
    "Seçilen PRD (ürün gereksinim belgesi) taslak (`Status: Draft`) ama sürüm satırı yok. "
    "Kendin düzelt: `{path}` dosyasında `Status:` satırının altına boş bir satır ve "
    f"`Version: {DRAFT_PRD_INITIAL_VERSION}` satırını ekle; durumu ve başka hiçbir metni "
    "değiştirme. Sonra yalnız bu dosyayı `git add -- {path}` komutuyla kayda hazırla (stage) "
    "ve aynı `review-start` komutunu yeniden çalıştır."
)
ACCEPTED_VERSION_REMEDY = (
    "Seçilen PRD (ürün gereksinim belgesi) kabul edilmiş (`Status: Accepted`) ama sürüm satırı "
    "yok. Bu PRD'yi değiştirme; sürüm satırını PRD'nin sahibi ekler. İnceleme o zamana kadar "
    "durur."
)

SCAFFOLD_MANIFEST_KEYS = {"format", "generator_version", "managed", "application_seed"}
SHELL_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "evidence_profile",
    "receipt_id",
    "project_id",
    "run_id",
    "trace_id",
    "authority",
    "snapshot",
    "orchestration",
    "aggregation_policy",
    "agentic_evaluator",
    "mandatory_governed_execution",
    "execution",
    "agent_results",
    "acceptance_criteria",
    "reuse_identity_canonicalization",
    "reuse_identity_sha256",
    "decision_evidence",
    "decision",
    "reason_codes",
    "weighted_risk_score_basis_points",
    "compliance_score_basis_points",
    "report_directory",
    "decision_path",
    "decision_sha256",
    "audit_path",
    "audit_event_count",
    "receipt_canonicalization",
    "receipt_sha256",
    "same_snapshot_retry_only",
    "native_surface",
    "claim_boundary",
    "data_handling",
    "created_at",
}
DECISION_KEYS = {
    "schema_version",
    "kind",
    "evidence_profile",
    "receipt_id",
    "project_id",
    "run_id",
    "trace_id",
    "span_id",
    "evaluator_invocation_id",
    "snapshot_sha256",
    "aggregation_policy",
    "agentic_evaluator",
    "agent_statuses",
    "acceptance_criteria",
    "decision",
    "reason_codes",
    "rationale_summary",
    "weighted_risk_score_basis_points",
    "compliance_score_basis_points",
    "decision_evidence_sha256",
    "claim_boundary",
    "data_handling",
    "evaluation_started_at",
    "decided_at",
}
EVIDENCE_KEYS = {
    "schema_version",
    "kind",
    "evidence_profile",
    "canonicalization",
    "evidence_sha256",
    "audit_replay",
    "deterministic_scan",
    "model_rerun",
    "data_handling",
}
OBSERVATION_KEYS = {
    "schema_version",
    "kind",
    "evidence_profile",
    "receipt_id",
    "project_id",
    "agent_id",
    "run_id",
    "trace_id",
    "span_id",
    "invocation_id",
    "snapshot_sha256",
    "agentic_evaluator",
    "status",
    "component_binding",
    "acceptance_criteria",
    "findings",
    "scanned_files",
    "deterministic_candidates",
    "candidate_responses",
    "error_code",
    "error_summary",
    "claim_boundary",
    "data_handling",
}
AUDIT_KEYS = {
    "schema_version",
    "kind",
    "evidence_profile",
    "receipt_id",
    "project_id",
    "event",
    "chain_position",
    "event_canonicalization",
    "run_id",
    "trace_id",
    "span_id",
    "snapshot_sha256",
    "agentic_evaluator",
    "agent_id",
    "invocation_id",
    "status",
    "decision",
    "reason_code",
    "report_sha256",
    "decision_sha256",
    "decision_evidence_sha256",
    "receipt_sha256",
    "previous_event_sha256",
    "event_sha256",
    "native_result",
    "claim_boundary",
    "data_handling",
    "observed_at",
    "prompt_session_id",
    "prompt_turn_id",
    "client_id",
}

EXPECTED_NATIVE_SURFACE = {
    "claude-code": ("fail-open", "fail-open"),
    "codex": ("unknown", "unknown"),
    "cursor": ("fail-closed", "fail-closed"),
    "github-copilot-vscode": ("fail-open", "unknown"),
}
CLIENT_SKILLS = {
    "claude-code": ".claude/skills/governed-review/SKILL.md",
    "codex": ".agents/skills/governed-review/SKILL.md",
    "cursor": ".cursor/skills/governed-review/SKILL.md",
    "github-copilot-vscode": ".github/skills/governed-review/SKILL.md",
}
CLIENT_PROJECTION_PATHS = {
    "claude-code": ".claude/agents/{agent}.md",
    "codex": ".codex/agents/{agent}.toml",
    "cursor": ".cursor/agents/{agent}.md",
    "github-copilot-vscode": ".github/agents/{agent}.agent.md",
}
# Mirrors policies/aggregation/governed-review.yml#security_critical_veto; a factory parity
# test binds both.  A covered Agent's accepted critical finding removes PASS whatever the
# weighted score is.
SECURITY_CRITICAL_VETO_AGENTS = frozenset(
    {"agent:bilgi-guvenligi", "agent:uygulama-guvenligi", "agent:gizlilik-kvkk"}
)
CRITICAL_SCORE_BASIS_POINTS = 7500
AGGREGATION_POLICY_PATH = "agent-platform/policies/aggregation/governed-review.yml"
SEVERITIES = ("info", "low", "medium", "high", "critical")
CLIENT_HOOK_PATHS = {
    "claude-code": ".claude/settings.json",
    "codex": ".codex/hooks.json",
    "cursor": ".cursor/hooks.json",
    "github-copilot-vscode": ".github/hooks/kt-commit-governance.json",
}
AUTHORITY_MANAGED_ASSET_RELATIVE_PATHS = (
    *(
        f"agents/{agent}/{filename}"
        for agent in sorted(
            {item.removeprefix("agent:") for item in AGENTS} | {"otomatik-duzeltme", "yuk-testi"}
        )
        for filename in ("agent.yml", "detectors.yml", "instructions.md", "policy.yml")
    ),
    "detector-pack.schema.json",
    "standard-reference.schema.json",
    "seed-normalization.schema.json",
    "seed-normalization.yml",
    "agentic-agent-consultation.schema.json",
    "agentic-governance-observation.schema.json",
    "agentic-governed-review-audit-event.schema.json",
    "agentic-governed-review-decision-evidence.schema.json",
    "agentic-governed-review-decision.schema.json",
    "agentic-governed-review-deterministic-scan.schema.json",
    "agentic-governed-review-evaluator-policy.schema.json",
    "agentic-governed-review-receipt.schema.json",
    "llm-call-event.schema.json",
    "local-governance-state-policy.schema.json",
    "prompt-ingress-metadata.schema.json",
    "prompt-ingress-receipt.schema.json",
    "policies/local-state/local-governance-state-policy.json",
    "client-capabilities.yml",
    "governance-source-manifest.yml",
    "orchestrations/governed-review.yml",
    "policies/aggregation/decision-explanation-templates.yml",
    "policies/aggregation/governed-review-agentic-evaluation.yml",
    "policies/aggregation/governed-review-instructions.md",
    "policies/aggregation/governed-review.yml",
)
AUTHORITY_MANAGED_GENERATED_ARTIFACTS = (
    "generated/.kt-scaffold/hooks/agentic_review_receipt_guard.py",
    "generated/governed-review/SKILL.md",
    "generated/.kt-scaffold/hooks/prompt_ingress_guard.py",
    "generated/.kt-scaffold/hooks/governance_client.py",
    "generated/.kt-scaffold/hooks/governance_records.py",
    "generated/.kt-scaffold/hooks/llm_call_events.py",
    "generated/.kt-scaffold/hooks/llm_call_audit_hook.py",
    "generated/.kt-scaffold/hooks/initial_scaffold_commit.py",
    "generated/.kt-scaffold/hooks/authority_sync.py",
    "generated/.kt-scaffold/hooks/governance_forwarder.py",
    "generated/.kt-scaffold/hooks/governance_identity.py",
)
SCHEMA_IDS = {
    "agentic-agent-consultation.schema.json": (
        "urn:kt:agent-platform:agentic-agent-consultation:1.0"
    ),
    "agentic-governance-observation.schema.json": (
        "urn:kt:agent-platform:agentic-governance-observation:1.1"
    ),
    "agentic-governed-review-audit-event.schema.json": (
        "urn:kt:agent-platform:agentic-governed-review-audit-event:1.1"
    ),
    "agentic-governed-review-decision-evidence.schema.json": (
        "urn:kt:agent-platform:agentic-governed-review-decision-evidence:1.1"
    ),
    "agentic-governed-review-decision.schema.json": (
        "urn:kt:agent-platform:agentic-governed-review-decision:1.0"
    ),
    "agentic-governed-review-deterministic-scan.schema.json": (
        "urn:kt:agent-platform:agentic-governed-review-deterministic-scan:1.0"
    ),
    "agentic-governed-review-receipt.schema.json": (
        "urn:kt:agent-platform:agentic-governed-review-receipt:1.0"
    ),
    "prompt-ingress-receipt.schema.json": "prompt-ingress-receipt.schema.json",
    "prompt-ingress-metadata.schema.json": "prompt-ingress-metadata.schema.json",
    "standard-reference.schema.json": "urn:kt:agent-platform:standard-reference:1.0",
}
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SUPPORTED_SCHEMA_KEYWORDS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "allOf",
    "const",
    "contains",
    "description",
    "else",
    "enum",
    "format",
    "if",
    "items",
    "maxContains",
    "maxItems",
    "maxLength",
    "maximum",
    "minContains",
    "minItems",
    "minLength",
    "minimum",
    "not",
    "oneOf",
    "pattern",
    "properties",
    "required",
    "then",
    "title",
    "type",
    "uniqueItems",
}


class GuardError(RuntimeError):
    """A redacted, fail-deny evidence validation result."""

    def __init__(self, code: str, diagnostic: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.diagnostic = diagnostic


def _non_pass_diagnostic(receipt: dict[str, Any], *, root: Path | None = None) -> str:
    """Locate declared blockers without trusting prose or changing validation/authority."""
    guidance = {
        "AGG_AUTHORITATIVE_CONFLICT": (
            "Rapordaki findings[].source ile findings[].locations başvurularını "
            "agent-platform/seed-normalization.yml source_conflicts kayıtlarıyla karşılaştır. "
            "Çelişen kanonik kaynak önceliğini çöz, üretilmiş projeye aktar; "
            "çelişki giderilmeden tam incelemeyi tekrarlama."
        ),
        "AGG_LOW_CONFIDENCE": (
            "Rapordaki düşük confidence bulgusunun eksik kanıtını tamamla; "
            "güven değerini veya eşiği elle yükseltme."
        ),
        "AGG_THRESHOLD_FAIL": "Rapordaki bulguları düzelt; karar puanını elle değiştirme.",
    }
    decision = receipt.get("decision")
    if decision not in {"BLOCKED_INCOMPLETE", "FAIL", "HARD-FAIL"}:
        decision = "unavailable"
    lines = [
        f"Makbuz beyanı (tam zincir doğrulanmadı): {decision}.",
        "Başvuru: ortak yönetişim kökünde governed-review/published/<snapshot>/",
    ]
    run_id = receipt.get("run_id")
    if isinstance(run_id, str) and re.fullmatch(r"run-[A-Za-z0-9._-]{4,120}", run_id):
        base = f"{REVIEW_AREA}/{run_id}"
        lines.extend((f"Karar: {base}/decision.json", f"Bulgular: {base}/reports/"))
        if root is not None:
            lines.extend(_diagnostic_findings(root, receipt, base))
    codes = receipt.get("reason_codes")
    known = [code for code in guidance if isinstance(codes, list) and code in codes]
    lines.extend(f"Gerekçe: {code}. Düzeltme: {guidance[code]}" for code in known)
    if not known:
        lines.append(
            "Gerekçe için kararın reason_codes ve uzman raporlarının findings alanını oku."
        )
    lines.append(
        "Engel giderilince sabit adayın incelemesini yenile; bu açıklama commit izni değildir."
    )
    return "\n".join(lines)


def _diagnostic_reference(value: object, *, source: bool = False) -> str:
    unavailable = "[başvuru gösterilemiyor]"
    if not isinstance(value, str) or len(value) > 200:
        return unavailable
    parts = value.split("; ") if source else [value]
    prefixes = (
        "policy:",
        "rule:",
        "detector:",
        "control:",
        "source-conflict:",
        "governance-source:",
        "agent-platform/",
        "rules/",
        "technology-profile.yml",
    )
    for part in parts:
        pattern = r"[A-Za-z0-9][A-Za-z0-9._:/#-]*" if source else r"[A-Za-z0-9_.-][A-Za-z0-9_./-]*"
        if (
            not re.fullmatch(pattern, part)
            or any(segment in {"", ".", ".."} for segment in part.split("/"))
            or (source and not part.startswith(prefixes))
        ):
            return unavailable
    return value


def _finding_reference(finding: dict[str, Any]) -> str:
    identifier = finding.get("finding_id")
    _require(
        isinstance(identifier, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,119}", identifier) is not None,
        "DIAGNOSTIC_FINDING_INVALID",
    )
    locations = finding.get("locations")
    if not isinstance(locations, list):
        _deny("DIAGNOSTIC_FINDING_INVALID")
    references = []
    for location in locations[:3]:
        _require(isinstance(location, dict), "DIAGNOSTIC_FINDING_INVALID")
        path = _diagnostic_reference(location.get("path"))
        line = location.get("start_line")
        references.append(
            f"{path}:{line}"
            if type(line) is int and 0 < line <= 10_000_000
            else "[başvuru gösterilemiyor]"
        )
    if len(locations) > 3:
        references.append(f"+{len(locations) - 3} konum raporda")
    source = _diagnostic_reference(finding.get("source"), source=True)
    return f"Bulgu: {identifier} | Kaynak: {source} | Konum: {', '.join(references)}"


def _diagnostic_report(
    root: Path, receipt: dict[str, Any], result: dict[str, Any], relative: str
) -> dict[str, Any]:
    _require(result.get("report_path") == relative, "REPORT_PATH_INVALID")
    _, raw = _regular_file(root, relative, limit=131_072)
    _require(_raw_sha256(raw) == result.get("report_sha256"), "REPORT_DIGEST_MISMATCH")
    report = _exact_keys(
        _strict_json_loads(raw, "ARTIFACT_JSON_INVALID"),
        OBSERVATION_KEYS,
        "ARTIFACT_SCHEMA_INVALID",
    )
    for field in ("receipt_id", "project_id", "run_id", "trace_id"):
        _require(report.get(field) == receipt.get(field), "REPORT_CORRELATION_MISMATCH")
    for field in ("agent_id", "span_id", "invocation_id", "component_binding", "status"):
        _require(report.get(field) == result.get(field), "REPORT_CORRELATION_MISMATCH")
    _require(
        report.get("snapshot_sha256") == receipt["snapshot"]["snapshot_sha256"],
        "REPORT_CORRELATION_MISMATCH",
    )
    _require(
        isinstance(report.get("findings"), list)
        and len(report["findings"]) == result.get("finding_count"),
        "REPORT_FINDINGS_MISMATCH",
    )
    return report


def _diagnostic_findings(root: Path, receipt: dict[str, Any], base: str) -> list[str]:
    """Bounded report references, never raw finding prose or a new assessment."""
    results = receipt.get("agent_results")
    if not isinstance(results, list):
        return ["Bulgu listesi gösterilemedi: AGENT_RESULTS_INVALID"]
    entries: list[tuple[tuple[int, int], str]] = []
    problems = []
    severities = ("critical", "high", "medium", "low", "info")
    for result in results[:12]:
        if not isinstance(result, dict) or result.get("agent_id") not in AGENTS:
            problems.append("Rapor gösterilemedi: AGENT_RESULTS_INVALID")
            continue
        slug = result["agent_id"].removeprefix("agent:")
        try:
            report = _diagnostic_report(root, receipt, result, f"{base}/reports/{slug}.json")
            report_entries = []
            for finding in report["findings"][:100]:
                _require(isinstance(finding, dict), "DIAGNOSTIC_FINDING_INVALID")
                severity = finding.get("severity")
                _require(severity in severities, "DIAGNOSTIC_FINDING_INVALID")
                source = finding.get("source")
                conflict = isinstance(source, str) and source.startswith("source-conflict:")
                order = (0 if conflict else 1, severities.index(severity))
                report_entries.append((order, _finding_reference(finding)))
            entries.extend(report_entries)
            if len(report["findings"]) > 100:
                problems.append(f"{slug}: ilk 100 bulgu işlendi; kalanlar raporda.")
        except GuardError as error:
            problems.append(
                f"{slug}: rapor gösterilemedi ({error.code}); {base}/reports/{slug}.json"
            )
    entries.sort(key=lambda entry: entry[0])  # Explicit conflict refs first; no new risk score.
    lines = ["Makbuzdaki rapor özetleriyle eşleşen başvurular (tam zincir doğrulaması değildir):"]
    lines.extend(entry[1] for entry in entries[:12])
    if len(entries) > 12:
        lines.append(f"+{len(entries) - 12} bulgu raporlarda; bu liste tüm bulguları göstermez.")
    return lines + problems


class _SchemaMismatch(ValueError):
    """Internal branch mismatch used by the dependency-free schema subset validator.

    It names the violated keyword with the schema's own constraint and, while it propagates, the
    instance path to it; it never carries the offending instance value. A length violation also
    carries the observed length, an integer and never the text.
    """

    def __init__(
        self,
        keyword: str = "",
        constraint: object = None,
        observed_length: int | None = None,
    ) -> None:
        super().__init__(keyword)
        self.keyword = keyword
        self.constraint = constraint
        self.observed_length = observed_length
        self.path: list[str | int] = []


def _deny(code: str) -> NoReturn:
    raise GuardError(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        _deny(code)


def _canonical_bytes(payload: object, *, excluding: str | None = None) -> bytes:
    candidate = copy.deepcopy(payload)
    if excluding is not None:
        _require(isinstance(candidate, dict), "CANONICALIZATION_FAILURE")
        candidate.pop(excluding, None)
    try:
        rendered = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _deny("CANONICALIZATION_FAILURE")
    return rendered.encode("utf-8") + b"\n"


def _canonical_sha256(payload: object, *, excluding: str | None = None) -> str:
    return hashlib.sha256(_canonical_bytes(payload, excluding=excluding)).hexdigest()


def _raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json_loads(payload: bytes, code: str) -> Any:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    def reject_constant(_: str) -> NoReturn:
        raise ValueError("non-finite JSON number")

    try:
        return json.loads(
            payload,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _deny(code)


def _yaml_metadata_version(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        _deny("COMPONENT_VERSION_INVALID")
    matched = re.search(r'(?m)^  version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$', text)
    _require(matched is not None, "COMPONENT_VERSION_INVALID")
    return matched.group(1)


def _yaml_scalar(value: str) -> object:
    if value.startswith(('"', "'")):
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            _deny("COMPONENT_POLICY_INVALID")
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _yaml_direct_mapping(payload: bytes, section: str) -> dict[str, object]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _deny("COMPONENT_POLICY_INVALID")
    try:
        start = lines.index(f"{section}:") + 1
    except ValueError:
        _deny("COMPONENT_POLICY_INVALID")
    result: dict[str, object] = {}
    skipping_nested = False
    for line in lines[start:]:
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        if line.startswith("    "):
            _require(skipping_nested, "COMPONENT_POLICY_INVALID")
            continue
        _require(line.startswith("  "), "COMPONENT_POLICY_INVALID")
        if line.endswith(":"):
            skipping_nested = True
            continue
        skipping_nested = False
        if ": " not in line:
            _deny("COMPONENT_POLICY_INVALID")
        key, raw_value = line[2:].rsplit(": ", 1)
        _require(bool(key) and key not in result, "COMPONENT_POLICY_INVALID")
        result[key] = _yaml_scalar(raw_value)
    _require(bool(result), "COMPONENT_POLICY_INVALID")
    return result


def _yaml_top_level_scalar(payload: bytes, key: str) -> object:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        _deny("COMPONENT_POLICY_INVALID")
    matches = re.findall(rf"(?m)^{re.escape(key)}:\s+([^\r\n]+)$", text)
    _require(len(matches) == 1, "COMPONENT_POLICY_INVALID")
    return _yaml_scalar(matches[0])


def _exact_keys(payload: object, expected: set[str], code: str) -> dict[str, Any]:
    _require(isinstance(payload, dict), code)
    _require(set(payload) == expected, code)
    return payload


def _schema_condition(
    condition: bool,
    keyword: str = "",
    constraint: object = None,
    observed_length: int | None = None,
) -> None:
    if not condition:
        raise _SchemaMismatch(keyword, constraint, observed_length)


def _schema_matches(
    instance: object,
    schema: object,
    root_schema: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    *,
    depth: int = 0,
) -> None:
    """Validate the JSON-Schema keywords used by the five Phase 1 evidence schemas."""

    _schema_condition(depth <= 128)
    if isinstance(schema, bool):
        _schema_condition(schema)
        return
    _schema_condition(isinstance(schema, dict))
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = [expected_type] if isinstance(expected_type, str) else expected_type

        def is_type(name: str) -> bool:
            return {
                "array": isinstance(instance, list),
                "boolean": isinstance(instance, bool),
                "integer": isinstance(instance, int) and not isinstance(instance, bool),
                "null": instance is None,
                "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
                "object": isinstance(instance, dict),
                "string": isinstance(instance, str),
            }.get(name, False)

        _schema_condition(
            isinstance(allowed, list) and any(is_type(name) for name in allowed),
            "type",
            expected_type,
        )
    if "const" in schema:
        _schema_condition(instance == schema["const"], "const", schema["const"])
    if "enum" in schema:
        _schema_condition(instance in schema["enum"], "enum", schema["enum"])

    if isinstance(instance, dict):
        missing = [field for field in schema.get("required", []) if field not in instance]
        _schema_condition(not missing, "required", missing)
        properties = schema.get("properties", {})
        for field, subschema in properties.items():
            if field in instance:
                try:
                    _schema_matches(
                        instance[field],
                        subschema,
                        root_schema,
                        registry,
                        depth=depth + 1,
                    )
                except _SchemaMismatch as mismatch:
                    mismatch.path.insert(0, field)
                    raise
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(instance) - set(properties))
            _schema_condition(not unexpected, "additionalProperties", unexpected)
    if isinstance(instance, list):
        if "minItems" in schema:
            _schema_condition(len(instance) >= schema["minItems"], "minItems", schema["minItems"])
        if "maxItems" in schema:
            _schema_condition(len(instance) <= schema["maxItems"], "maxItems", schema["maxItems"])
        if schema.get("uniqueItems"):
            identities = [_canonical_bytes(item) for item in instance]
            _schema_condition(len(identities) == len(set(identities)), "uniqueItems", True)
        if "items" in schema:
            for index, item in enumerate(instance):
                try:
                    _schema_matches(
                        item,
                        schema["items"],
                        root_schema,
                        registry,
                        depth=depth + 1,
                    )
                except _SchemaMismatch as mismatch:
                    mismatch.path.insert(0, index)
                    raise
        if "contains" in schema:
            contains_count = 0
            for item in instance:
                try:
                    _schema_matches(
                        item,
                        schema["contains"],
                        root_schema,
                        registry,
                        depth=depth + 1,
                    )
                except _SchemaMismatch:
                    continue
                contains_count += 1
            minimum_contains = schema.get("minContains", 1)
            _schema_condition(contains_count >= minimum_contains, "contains", minimum_contains)
            if "maxContains" in schema:
                _schema_condition(
                    contains_count <= schema["maxContains"], "maxContains", schema["maxContains"]
                )
    if isinstance(instance, str):
        if "minLength" in schema:
            _schema_condition(
                len(instance) >= schema["minLength"],
                "minLength",
                schema["minLength"],
                len(instance),
            )
        if "maxLength" in schema:
            _schema_condition(
                len(instance) <= schema["maxLength"],
                "maxLength",
                schema["maxLength"],
                len(instance),
            )
        if "pattern" in schema:
            try:
                matched = re.search(schema["pattern"], instance) is not None
            except re.error as error:
                raise _SchemaMismatch("pattern", schema["pattern"]) from error
            _schema_condition(matched, "pattern", schema["pattern"])
        if schema.get("format") == "date-time":
            _schema_condition(
                UTC_TIMESTAMP_RE.fullmatch(instance) is not None, "format", "date-time"
            )
            try:
                parsed = datetime.fromisoformat(instance.replace("Z", "+00:00"))
            except ValueError as error:
                raise _SchemaMismatch("format", "date-time") from error
            _schema_condition(parsed.tzinfo is not None, "format", "date-time")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema:
            _schema_condition(instance >= schema["minimum"], "minimum", schema["minimum"])
        if "maximum" in schema:
            _schema_condition(instance <= schema["maximum"], "maximum", schema["maximum"])

    # Applicators follow the node's own keywords: validity is the same in any order, and the
    # first violation reported is then the most local one.
    reference = schema.get("$ref")
    if isinstance(reference, str):
        base, separator, fragment = reference.partition("#")
        if separator and fragment.startswith("/"):
            # "#/..." stays in this document; "<$id>#/..." points into a registered one.
            if base:
                _schema_condition(base in registry)
            pointer_root = registry[base] if base else root_schema
            target: object = pointer_root
            for raw_part in fragment[1:].split("/"):
                part = raw_part.replace("~1", "/").replace("~0", "~")
                _schema_condition(isinstance(target, dict) and part in target)
                target = target[part]
            _schema_matches(
                instance,
                target,
                pointer_root,
                registry,
                depth=depth + 1,
            )
        else:
            _schema_condition(reference in registry)
            referenced_root = registry[reference]
            _schema_matches(
                instance,
                referenced_root,
                referenced_root,
                registry,
                depth=depth + 1,
            )

    for subschema in schema.get("allOf", []):
        _schema_matches(instance, subschema, root_schema, registry, depth=depth + 1)
    if "oneOf" in schema:
        matches = 0
        for subschema in schema["oneOf"]:
            try:
                _schema_matches(instance, subschema, root_schema, registry, depth=depth + 1)
            except _SchemaMismatch:
                continue
            matches += 1
        _schema_condition(matches == 1, "oneOf")
    if "not" in schema:
        try:
            _schema_matches(instance, schema["not"], root_schema, registry, depth=depth + 1)
        except _SchemaMismatch:
            pass
        else:
            raise _SchemaMismatch("not")
    if "if" in schema:
        try:
            _schema_matches(instance, schema["if"], root_schema, registry, depth=depth + 1)
        except _SchemaMismatch:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if branch is not None:
            _schema_matches(instance, branch, root_schema, registry, depth=depth + 1)


def _validate_schema_source(schema: object, *, root: bool = False) -> None:
    _require(isinstance(schema, (bool, dict)), "SCHEMA_SOURCE_INVALID")
    if isinstance(schema, bool):
        return
    _require(set(schema) <= SUPPORTED_SCHEMA_KEYWORDS, "SCHEMA_KEYWORD_UNSUPPORTED")
    if not root:
        _require("$schema" not in schema and "$id" not in schema, "SCHEMA_SOURCE_INVALID")
    for mapping_name in ("$defs", "properties"):
        mapping = schema.get(mapping_name, {})
        _require(isinstance(mapping, dict), "SCHEMA_SOURCE_INVALID")
        for subschema in mapping.values():
            _validate_schema_source(subschema)
    for sequence_name in ("allOf", "oneOf"):
        sequence = schema.get(sequence_name, [])
        _require(isinstance(sequence, list), "SCHEMA_SOURCE_INVALID")
        for subschema in sequence:
            _validate_schema_source(subschema)
    for single_name in ("not", "if", "then", "else", "items", "contains"):
        if single_name in schema:
            _validate_schema_source(schema[single_name])
    additional = schema.get("additionalProperties")
    _require(
        additional is None or isinstance(additional, bool),
        "SCHEMA_KEYWORD_UNSUPPORTED",
    )


def _schema_registry(root: Path) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for name, expected_id in SCHEMA_IDS.items():
        _, raw = _regular_file(root, f"agent-platform/{name}", limit=MAX_JSON_BYTES)
        schema = _strict_json_loads(raw, "SCHEMA_SOURCE_INVALID")
        _require(
            isinstance(schema, dict)
            and schema.get("$schema") == SCHEMA_DRAFT
            and schema.get("$id") == expected_id,
            "SCHEMA_SOURCE_INVALID",
        )
        _validate_schema_source(schema, root=True)
        _require(expected_id not in registry, "SCHEMA_SOURCE_INVALID")
        registry[schema["$id"]] = schema
        registry[name] = schema
    return registry


def _validate_against_schema(
    instance: object,
    name: str,
    registry: dict[str, dict[str, Any]],
) -> None:
    try:
        schema = registry[name]
        _schema_matches(instance, schema, schema, registry)
    except (KeyError, _SchemaMismatch, TypeError, ValueError):
        _deny("SCHEMA_VALIDATION_FAILURE")


def schema_violation(
    instance: object,
    name: str,
    registry: dict[str, dict[str, Any]],
) -> dict[str, object] | None:
    """Name the first violated keyword so the instance's author can correct its own answer.

    ``_validate_against_schema`` stays the only verdict. This returns the JSON pointer, the keyword
    and the schema's constraint, never the offending value, or ``None`` for a valid instance. A
    length violation adds the observed length, so the author learns how far over the limit it is.
    """
    try:
        schema = registry[name]
        _schema_matches(instance, schema, schema, registry)
    except _SchemaMismatch as mismatch:
        pointer = "".join(
            "/" + str(part).replace("~", "~0").replace("/", "~1") for part in mismatch.path
        )
        violation: dict[str, object] = {
            "pointer": pointer,
            "keyword": mismatch.keyword,
            "constraint": mismatch.constraint,
        }
        if mismatch.observed_length is not None:
            violation["observed_length"] = mismatch.observed_length
        return violation
    except (KeyError, TypeError, ValueError):
        return {"pointer": "", "keyword": "", "constraint": None}
    return None


def _all_false(payload: object, expected: set[str], code: str) -> None:
    candidate = _exact_keys(payload, expected, code)
    _require(all(value is False for value in candidate.values()), code)


def _parse_time(value: object, code: str) -> datetime:
    _require(isinstance(value, str) and UTC_TIMESTAMP_RE.fullmatch(value) is not None, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _deny(code)
    _require(parsed.tzinfo is not None, code)
    return parsed.astimezone(UTC)


def _observed_time(value: object, now: datetime) -> datetime:
    parsed = _parse_time(value, "TIMESTAMP_INVALID")
    _require(parsed <= now.astimezone(UTC), "FUTURE_TIMESTAMP")
    return parsed


def _validate_snapshot_binding(receipt_snapshot: object, observed_snapshot: object) -> None:
    _require(receipt_snapshot == observed_snapshot, "SNAPSHOT_MISMATCH")


def _event() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    _require(len(raw) <= MAX_EVENT_BYTES, "HOOK_EVENT_OVERSIZE")
    parsed = _strict_json_loads(raw or b"{}", "HOOK_EVENT_INVALID")
    _require(isinstance(parsed, dict), "HOOK_EVENT_INVALID")
    return parsed


def _command(event: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    direct = event.get("command")
    if isinstance(direct, str):
        candidates.append(direct)
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = event.get("toolInput")
    if isinstance(tool_input, dict):
        direct = tool_input.get("command")
        if isinstance(direct, str):
            candidates.append(direct)
        nested = tool_input.get("input")
        if isinstance(nested, dict) and isinstance(nested.get("command"), str):
            candidates.append(nested["command"])
    if not candidates:
        return None
    _require(len(set(candidates)) == 1, "HOOK_COMMAND_CONFLICT")
    return candidates[0]


def _has_dynamic_shell_syntax(command: str) -> bool:
    """Detect expansion/composition that can change the post-hook argv or staged tree."""

    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if character == "'" and quote != '"':
            quote = None if quote == "'" else "'"
            continue
        if character == '"' and quote != "'":
            quote = None if quote == '"' else '"'
            continue
        if character in "\r\n":
            return True
        if quote == "'":
            continue
        if character in "`$":
            return True
        if quote is None and character in ";|&<>()*?[]{}":
            return True
    return escaped or quote is not None


_SHELL_INTERPRETERS = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "rbash", "busybox"}
)
_SHELL_EXECUTION_BUILTINS = frozenset({"eval", "source", "."})
_PIPE_FORWARDERS = frozenset(
    {"xargs", "nohup", "timeout", "stdbuf", "nice", "ionice", "env", "command", "sudo"}
)


def _shell_basename(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()


def _shell_pipeline_segments(command: str) -> list:
    """Split a command at top-level shell operators without executing or expanding it.

    Returns ``(preceding_operator, segment_text)`` pairs; operators inside quotes or inside
    a ``(...)``/``$(...)``/``<(...)`` group are not split points.
    """
    segments = []
    current: list = []
    operator = None
    quote = None
    escaped = False
    depth = 0
    index = 0
    length = len(command)
    while index < length:
        character = command[index]
        if escaped:
            current.append(character)
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            index += 1
            continue
        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
            current.append(character)
            index += 1
            continue
        if character == "(":
            depth += 1
            current.append(character)
            index += 1
            continue
        if character == ")":
            if depth > 0:
                depth -= 1
            current.append(character)
            index += 1
            continue
        if depth == 0:
            if command[index : index + 2] in ("&&", "||"):
                segments.append((operator, "".join(current)))
                operator = command[index : index + 2]
                current = []
                index += 2
                continue
            if character in (";", "\n", "\r"):
                segments.append((operator, "".join(current)))
                operator = ";"
                current = []
                index += 1
                continue
            if character in ("|", "&"):
                segments.append((operator, "".join(current)))
                operator = character
                current = []
                index += 1
                continue
        current.append(character)
        index += 1
    segments.append((operator, "".join(current)))
    return segments


def _shell_segment_leading(segment: str):
    try:
        tokens = list(shlex.split(segment, posix=True))
    except ValueError:
        return None, ()
    while tokens and SHELL_ASSIGNMENT_RE.match(tokens[0]) is not None:
        tokens = tokens[1:]
    if not tokens:
        return None, ()
    return _shell_basename(tokens[0]), tuple(_shell_basename(token) for token in tokens[1:])


def _shell_active_substitution(text: str) -> bool:
    quote = None
    escaped = False
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if character == '"':
                quote = None
                index += 1
                continue
            if character == "`" or text[index : index + 2] == "$(":
                return True
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
            index += 1
            continue
        if character == "`" or text[index : index + 2] in ("$(", "<("):
            return True
        index += 1
    return False


def _decodes_into_shell(command: str) -> bool:
    """Flag a pipeline that feeds decoded or obfuscated content into a shell interpreter.

    ``echo <base64> | base64 -d | sh`` and ``sh -c "$(… | base64 -d)"`` hide the real
    command from this classifier.  This hook never executes or expands the string, so a
    shell interpreter fed by a pipe, command substitution or process substitution is an
    unsafe commit shape.  A command that only decodes without executing the result is not
    flagged.
    """
    try:
        segments = _shell_pipeline_segments(command)
    except Exception:
        return True
    for operator, segment in segments:
        binary, arguments = _shell_segment_leading(segment)
        if binary is None:
            continue
        if operator == "|" and binary in _SHELL_INTERPRETERS:
            return True
        if (
            operator == "|"
            and binary in _PIPE_FORWARDERS
            and any(name in _SHELL_INTERPRETERS for name in arguments)
        ):
            return True
        if (
            binary in _SHELL_INTERPRETERS or binary in _SHELL_EXECUTION_BUILTINS
        ) and _shell_active_substitution(segment):
            return True
    return False


def _contains_direct_git_commit_segment(command: str) -> bool:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return True
    segment: list[str] = []
    segments: list[list[str]] = []
    for token in tokens:
        if token and all(character in ";&|<>()" for character in token):
            if segment:
                segments.append(segment)
                segment = []
            continue
        segment.append(token)
    if segment:
        segments.append(segment)
    safe_global_flags = {
        "--glob-pathspecs",
        "--icase-pathspecs",
        "--literal-pathspecs",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        "--noglob-pathspecs",
        "--paginate",
    }
    for words in segments:
        # `NAME=value git commit` runs Git with a changed environment; it is still a commit.
        while words and SHELL_ASSIGNMENT_RE.match(words[0]) is not None:
            words = words[1:]
        if not words or words[0] not in {"git", "/usr/bin/git"}:
            continue
        index = 1
        while index < len(words) and words[index] in safe_global_flags:
            index += 1
        if index < len(words) and words[index] == "commit":
            return True
    return False


def _wrapper_can_execute_git_commit(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if tokens[0] in {"sh", "bash", "zsh", "/bin/sh", "/bin/bash", "/bin/zsh"}:
        command_index = next(
            (
                index + 1
                for index, token in enumerate(tokens[:-1])
                if token == "--command"  # noqa: S105 -- command-line option, not a credential
                or (token.startswith("-") and "c" in token[1:])
            ),
            None,
        )
        if command_index is None:
            return False
        nested = tokens[command_index]
        return _classify_command(nested) != "outside"
    if tokens[0] not in {"command", "env", "sudo", "/usr/bin/env", "/usr/bin/sudo"}:
        return False
    try:
        git_index = next(
            index
            for index, token in enumerate(tokens[1:], start=1)
            if token in {"git", "/usr/bin/git"}
        )
    except StopIteration:
        return any(_contains_direct_git_commit_segment(token) for token in tokens[1:])
    return "commit" in tokens[git_index + 1 :]


def _without_simple_heredoc_bodies(command: str) -> str | None:
    """Strip literal bodies for the simple heredoc shape emitted by supported clients."""

    lines = command.splitlines()
    if not lines or "<<" not in lines[0]:
        return None
    declarations = re.findall(
        r"<<(-?)\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))",
        lines[0],
    )
    if not declarations:
        return None
    cursor = 1
    for strip_tabs, single_quoted, double_quoted, bare in declarations:
        delimiter = single_quoted or double_quoted or bare
        while cursor < len(lines):
            candidate = lines[cursor].lstrip("\t") if strip_tabs else lines[cursor]
            cursor += 1
            if candidate == delimiter:
                break
        else:
            return ""
    return lines[0] + "\n;\n" + "\n".join(lines[cursor:])


def _commit_arguments_are_snapshot_preserving(arguments: list[str]) -> bool:
    flag_options = {
        "--ahead-behind",
        "--allow-empty",
        "--allow-empty-message",
        "--branch",
        "--dry-run",
        "--edit",
        "--gpg-sign",
        "--long",
        "--no-ahead-behind",
        "--no-edit",
        "--no-gpg-sign",
        "--no-post-rewrite",
        "--no-show-stash",
        "--no-signoff",
        "--no-status",
        "--no-verify",
        "--null",
        "--porcelain",
        "--quiet",
        "--short",
        "--show-stash",
        "--signoff",
        "--status",
        "--verbose",
        "-e",
        "-n",
        "-q",
        "-s",
        "-S",
        "-v",
        "-z",
    }
    value_options = {
        "--author",
        "--cleanup",
        "--date",
        "--file",
        "--gpg-sign",
        "--message",
        "--reedit-message",
        "--reuse-message",
        "--template",
        "--trailer",
        "--untracked-files",
        "-C",
        "-F",
        "-S",
        "-c",
        "-m",
    }
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token in flag_options:
            index += 1
            continue
        if len(token) > 2 and token[:2] in {"-C", "-F", "-S", "-c", "-m"}:
            index += 1
            continue
        option = token.split("=", 1)[0]
        if option in value_options:
            if "=" in token or (option in {"-C", "-F", "-S", "-c", "-m"} and token != option):
                index += 1
                continue
            index += 2
            if index <= len(arguments):
                continue
        return False
    return True


def _classify_command(command: str | None) -> str:
    """Classify as outside, snapshot-preserving direct commit, or unsafe direct commit."""

    if command is None:
        return "outside"
    if _decodes_into_shell(command):
        return "unsafe"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "unsafe"
    if not tokens:
        return "outside"
    if tokens[0] not in {"git", "/usr/bin/git"}:
        if _wrapper_can_execute_git_commit(tokens):
            return "unsafe"
        without_heredoc = _without_simple_heredoc_bodies(command)
        if without_heredoc == "":
            return "unsafe"
        inspected = command if without_heredoc is None else without_heredoc
        if _contains_direct_git_commit_segment(inspected):
            return "unsafe"
        return "outside"
    index = 1
    safe_global_flags = {
        "--glob-pathspecs",
        "--icase-pathspecs",
        "--literal-pathspecs",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        "--noglob-pathspecs",
        "--paginate",
    }
    while index < len(tokens) and tokens[index] in safe_global_flags:
        index += 1
    if index >= len(tokens):
        return "outside"
    if tokens[index] != "commit":
        dynamic_subcommand = any(character in tokens[index] for character in "`$*?[]{}")
        if (
            _contains_direct_git_commit_segment(command)
            or dynamic_subcommand
            or (tokens[index].startswith("commit") and _has_dynamic_shell_syntax(command))
            or (tokens[index].startswith("-") and "commit" in tokens[index + 1 :])
        ):
            return "unsafe"
        return "outside"
    if _has_dynamic_shell_syntax(command):
        return "unsafe"
    return "direct" if _commit_arguments_are_snapshot_preserving(tokens[index + 1 :]) else "unsafe"


def _is_direct_git_commit(command: str | None) -> bool:
    return _classify_command(command) == "direct"


def _direct_git_executable(command: str) -> str:
    try:
        executable = shlex.split(command, posix=True)[0]
    except (IndexError, ValueError):
        _deny("HOOK_COMMAND_INVALID")
    _require(executable in {"git", "/usr/bin/git"}, "HOOK_COMMAND_INVALID")
    return executable


def _project_root() -> Path:
    script = Path(__file__)
    _require(not script.is_symlink(), "HOOK_SCRIPT_UNSAFE")
    root = script.resolve().parents[2]
    _require((root / ".kt-scaffold").is_dir(), "PROJECT_ROOT_INVALID")
    return root


def _initial_scaffold_commit(command: str, event: dict[str, Any], client: str) -> str | None:
    """The shared `INITIAL_SCAFFOLD_COMMIT` exception's notice, or None for the ordinary check."""
    path = Path(__file__).resolve().with_name("initial_scaffold_commit.py")
    try:
        _require(path.is_file() and not path.is_symlink(), "HOOK_SCRIPT_UNSAFE")
        exception = runpy.run_path(str(path))
        if exception["allowed"](_project_root(), command, event, client) is True:
            return cast(str, exception["NOTICE"])
    except Exception:
        return None
    return None


def _relative_parts(relative: str) -> tuple[str, ...]:
    _require("\\" not in relative, "ARTIFACT_PATH_INVALID")
    path = PurePosixPath(relative)
    _require(not path.is_absolute(), "ARTIFACT_PATH_INVALID")
    _require(
        path.parts and all(part not in {"", ".", ".."} for part in path.parts),
        "ARTIFACT_PATH_INVALID",
    )
    return path.parts


REVIEW_AREA = "governed-review"


def _records_module() -> dict[str, Any]:
    path = Path(__file__).resolve().with_name("governance_records.py")
    _require(path.is_file() and not path.is_symlink(), "SHARED_ROOT_UNAVAILABLE")
    return runpy.run_path(str(path))


def _review_project_directory(root: Path) -> Path:
    """``<shared root>/<project_id>``: the base of every ``governed-review/`` artifact path."""
    _, raw = _regular_file(root, ".kt-scaffold/project-manifest.json", limit=MAX_JSON_BYTES)
    manifest = _strict_json_loads(raw, "PROJECT_MANIFEST_INVALID")
    project_id = manifest.get("project_id") if isinstance(manifest, dict) else None
    _require(isinstance(project_id, str), "PROJECT_MANIFEST_INVALID")
    writer = _records_module()
    try:
        area = writer["review_area"](project_id, location=_record_location())
    except Exception:
        _deny("SHARED_ROOT_UNAVAILABLE")
    return cast(Path, area).parent


def _regular_file(root: Path, relative: str, *, limit: int) -> tuple[Path, bytes]:
    parts = _relative_parts(relative)
    current = _review_project_directory(root) if parts[0] == REVIEW_AREA else root
    for part in parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError:
            _deny("ARTIFACT_UNREADABLE")
        _require(not stat.S_ISLNK(metadata.st_mode), "ARTIFACT_SYMLINK")
    _require(stat.S_ISREG(metadata.st_mode), "ARTIFACT_NOT_REGULAR")
    _require(metadata.st_size <= limit, "ARTIFACT_OVERSIZE")
    try:
        content = current.read_bytes()
    except OSError:
        _deny("ARTIFACT_UNREADABLE")
    _require(len(content) <= limit, "ARTIFACT_OVERSIZE")
    return current, content


def _json_file(
    root: Path, relative: str, *, expected_keys: set[str]
) -> tuple[Path, bytes, dict[str, Any]]:
    path, raw = _regular_file(root, relative, limit=MAX_JSON_BYTES)
    payload = _strict_json_loads(raw, "ARTIFACT_JSON_INVALID")
    return path, raw, _exact_keys(payload, expected_keys, "ARTIFACT_SCHEMA_INVALID")


def _run_git(
    root: Path, arguments: tuple[str, ...], executable: str | None
) -> subprocess.CompletedProcess[bytes]:
    resolved_executable = shutil.which("git") if executable in {None, "git"} else executable
    _require(resolved_executable is not None, "GIT_UNAVAILABLE")
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            [cast(str, resolved_executable), "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        _deny("GIT_TOOL_FAILURE")


def _git_bytes(root: Path, *arguments: str, executable: str | None = None) -> bytes:
    completed = _run_git(root, arguments, executable)
    _require(completed.returncode == 0, "GIT_TOOL_FAILURE")
    return completed.stdout


def _git(
    root: Path,
    *arguments: str,
    allow_absent: bool = False,
    executable: str | None = None,
) -> str | None:
    completed = _run_git(root, arguments, executable)
    if allow_absent and completed.returncode == 1:
        return None
    _require(completed.returncode == 0, "GIT_TOOL_FAILURE")
    try:
        value = completed.stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        _deny("GIT_OUTPUT_INVALID")
    _require(bool(value), "GIT_OUTPUT_INVALID")
    return value


def _capture_snapshot(root: Path, executable: str | None = None) -> dict[str, Any]:
    top_level = _git(root, "rev-parse", "--show-toplevel", executable=executable)
    _require(
        isinstance(top_level, str) and Path(top_level).resolve() == root.resolve(),
        "GIT_TOP_LEVEL_MISMATCH",
    )
    object_format = _git(root, "rev-parse", "--show-object-format", executable=executable)
    _require(object_format in {"sha1", "sha256"}, "GIT_OBJECT_FORMAT_INVALID")
    object_length = 40 if object_format == "sha1" else 64
    oid = re.compile(rf"^[0-9a-f]{{{object_length}}}$")
    index_tree = _git(root, "write-tree", executable=executable)
    _require(
        isinstance(index_tree, str) and oid.fullmatch(index_tree) is not None, "INDEX_TREE_INVALID"
    )
    head = _git(
        root,
        "rev-parse",
        "--verify",
        "--quiet",
        "HEAD",
        allow_absent=True,
        executable=executable,
    )
    _require(head is None or oid.fullmatch(head) is not None, "HEAD_INVALID")
    merge_path_text = _git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "MERGE_HEAD",
        executable=executable,
    )
    _require(isinstance(merge_path_text, str), "MERGE_HEAD_INVALID")
    merge_path = Path(merge_path_text)
    merge_heads: list[str] = []
    if merge_path.exists():
        _require(not merge_path.is_symlink() and merge_path.is_file(), "MERGE_HEAD_INVALID")
        try:
            merge_raw = merge_path.read_bytes()
        except OSError:
            _deny("MERGE_HEAD_INVALID")
        _require(len(merge_raw) <= 4096, "MERGE_HEAD_INVALID")
        try:
            merge_heads = merge_raw.decode("ascii").split()
        except UnicodeDecodeError:
            _deny("MERGE_HEAD_INVALID")
        _require(0 < len(merge_heads) <= 16, "MERGE_HEAD_INVALID")
        _require(all(oid.fullmatch(item) is not None for item in merge_heads), "MERGE_HEAD_INVALID")
        _require(len(merge_heads) == len(set(merge_heads)), "MERGE_HEAD_INVALID")
    identity = {
        "canonicalization": "kt-git-index-snapshot-json-v1",
        "git_object_format": object_format,
        "head": head,
        "index_tree": index_tree,
        "merge_heads": merge_heads,
    }
    return {**identity, "snapshot_sha256": _canonical_sha256(identity)}


def acceptance_criteria(root: Path, path: str, executable: str | None = None) -> dict[str, Any]:
    """Bind the Test Automation Agent to one PRD exactly as the staged index holds it.

    `review-start` records this binding and the commit hook derives it again from the index, so
    the recorded lifecycle always states the PRD's own status.  A draft PRD frames the review as
    `draft`; no command or Agent changes a PRD's status.
    """

    matched = CRITERIA_PATH_RE.fullmatch(path)
    if matched is None:
        _deny("CRITERIA_PATH_INVALID")
    staged = _git_bytes(root, "ls-files", "--cached", "-z", "--", path, executable=executable)
    _require(staged.split(b"\0")[0] == path.encode("utf-8"), "CRITERIA_NOT_STAGED")
    raw = _git_bytes(root, "cat-file", "blob", f":{path}", executable=executable)
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        _deny("CRITERIA_PATH_INVALID")
    status = PRD_STATUS_RE.search(text)
    lifecycle = PRD_LIFECYCLES.get(status.group(1).strip().casefold() if status else "")
    if lifecycle is None:
        _deny("CRITERIA_STATUS_UNSUPPORTED")
    version = PRD_VERSION_RE.search(text)
    if version is None:
        remedy = (
            DRAFT_VERSION_REMEDY.format(path=path)
            if lifecycle == "draft"
            else ACCEPTED_VERSION_REMEDY
        )
        raise GuardError("CRITERIA_VERSION_UNAVAILABLE", remedy)
    return {
        "criteria_id": f"criteria:{matched.group(1)}.{matched.group(2)}",
        "criteria_version": version.group(1),
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "lifecycle": lifecycle,
        "derived_from_application_code": False,
    }


def _reuse_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "project_id": receipt["project_id"],
            "authority": copy.deepcopy(receipt["authority"]),
            "snapshot": copy.deepcopy(receipt["snapshot"]),
            "orchestration": copy.deepcopy(receipt["orchestration"]),
            "aggregation_policy": copy.deepcopy(receipt["aggregation_policy"]),
            "agentic_evaluator": copy.deepcopy(receipt["agentic_evaluator"]),
            "mandatory_governed_execution": copy.deepcopy(receipt["mandatory_governed_execution"]),
            "execution": {
                "session_id": receipt["execution"]["session_id"],
                "client": copy.deepcopy(receipt["execution"]["client"]),
            },
            "agent_results": copy.deepcopy(receipt["agent_results"]),
            "decision_evidence": {
                "audit_replay": {"sha256": receipt["decision_evidence"]["audit_replay"]["sha256"]}
            },
            "decision": receipt["decision"],
            "decision_sha256": receipt["decision_sha256"],
        }
    except (KeyError, TypeError):
        _deny("REUSE_IDENTITY_INVALID")


def _agent_manifest(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "canonicalization": "kt-agentic-agent-component-manifest-json-v1",
        "agents": [
            {"agent_id": item["agent_id"], "component_binding": item["component_binding"]}
            for item in results
        ],
    }


def _event_identity(
    event: dict[str, Any], client: str, root: Path, executable: str
) -> tuple[str | None, str | None]:
    cwd = event.get("cwd")
    if cwd is None and client == "github-copilot-vscode":
        observed_cwd = Path.cwd().resolve()
    else:
        _require(isinstance(cwd, str) and bool(cwd), "EVENT_CWD_MISMATCH")
        try:
            observed_cwd = Path(cwd).resolve()
        except OSError:
            _deny("EVENT_CWD_MISMATCH")
    observed_top_level = _git(
        observed_cwd,
        "rev-parse",
        "--show-toplevel",
        executable=executable,
    )
    _require(
        isinstance(observed_top_level, str)
        and Path(observed_top_level).resolve() == root.resolve(),
        "EVENT_CWD_MISMATCH",
    )

    raw_session = event.get("session_id")
    if client == "cursor":
        raw_session = event.get("conversation_id")
    if raw_session is None and client == "github-copilot-vscode":
        session = None
    else:
        _require(
            isinstance(raw_session, str)
            and bool(raw_session)
            and "\x00" not in raw_session
            and len(raw_session.encode("utf-8")) <= 4096,
            "EVENT_SESSION_INVALID",
        )
        session = f"session:client.{hashlib.sha256(raw_session.encode('utf-8')).hexdigest()}"
    version = event.get("cursor_version") if client == "cursor" else None
    if client == "cursor":
        _require(isinstance(version, str) and bool(version), "EVENT_CLIENT_INVALID")
    return session, version


def _validate_native_surface(receipt: dict[str, Any], client: str) -> None:
    hook_error, timeout = EXPECTED_NATIVE_SURFACE[client]
    expected = {
        "client_id": client,
        "adapter_mode": "native-command-receipt-guard",
        "hook_error_behavior": hook_error,
        "timeout_behavior": timeout,
        "enforcement_claim": "conditional-native-guard",
        "native_result_recorded": False,
        "commit_retry_recorded": False,
    }
    _require(receipt.get("native_surface") == expected, "NATIVE_SURFACE_MISMATCH")


def _managed_inventory(root: Path) -> dict[str, str]:
    _, _, payload = _json_file(
        root,
        ".kt-scaffold/manifest.json",
        expected_keys=SCAFFOLD_MANIFEST_KEYS,
    )
    _require(payload.get("format") == 1, "MANAGED_MANIFEST_INVALID")
    managed = payload.get("managed")
    _require(isinstance(managed, dict) and bool(managed), "MANAGED_MANIFEST_INVALID")
    verified: dict[str, str] = {}
    for relative, digest in managed.items():
        _require(
            isinstance(relative, str)
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "MANAGED_MANIFEST_INVALID",
        )
        _relative_parts(relative)
        verified[relative] = digest
    return verified


def _require_managed_bytes(
    root: Path, managed: dict[str, str], relative: str, *, limit: int = MAX_JSON_BYTES
) -> bytes:
    _require(relative in managed, "MANAGED_AUTHORITY_ARTIFACT_MISSING")
    _, raw = _regular_file(root, relative, limit=limit)
    _require(_raw_sha256(raw) == managed[relative], "MANAGED_AUTHORITY_ARTIFACT_DRIFT")
    return raw


def _recomputed_governance_digest(
    root: Path,
    manifest: dict[str, Any],
    managed: dict[str, str],
    client: str,
) -> str:
    artifacts = manifest.get("artifacts")
    _require(isinstance(artifacts, list), "AUTHORITY_MANIFEST_INVALID")
    normalized: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for raw_artifact in artifacts:
        artifact = _exact_keys(
            raw_artifact,
            {"artifact_id", "kind", "authority", "version", "sha256"},
            "AUTHORITY_MANIFEST_INVALID",
        )
        artifact_id = artifact.get("artifact_id")
        kind = artifact.get("kind")
        authority = artifact.get("authority")
        sha256 = artifact.get("sha256")
        _require(
            isinstance(artifact_id, str)
            and artifact_id not in seen
            and isinstance(kind, str)
            and isinstance(authority, str)
            and isinstance(sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", sha256) is not None,
            "AUTHORITY_MANIFEST_INVALID",
        )
        seen.add(artifact_id)
        normalized.append((artifact_id, kind, authority, sha256))

    digest = hashlib.sha256()
    for artifact_id, kind, authority, sha256 in sorted(normalized):
        for value in (artifact_id, kind, authority, sha256):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    for relative in AUTHORITY_MANAGED_ASSET_RELATIVE_PATHS:
        raw = _require_managed_bytes(root, managed, f"agent-platform/{relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_raw_sha256(raw).encode("ascii"))
        digest.update(b"\0")
    generated_sources = (
        ".kt-scaffold/hooks/agentic_review_receipt_guard.py",
        CLIENT_SKILLS[client],
        ".kt-scaffold/hooks/prompt_ingress_guard.py",
        ".kt-scaffold/hooks/governance_client.py",
        ".kt-scaffold/hooks/governance_records.py",
        ".kt-scaffold/hooks/llm_call_events.py",
        ".kt-scaffold/hooks/llm_call_audit_hook.py",
        ".kt-scaffold/hooks/initial_scaffold_commit.py",
        ".kt-scaffold/hooks/authority_sync.py",
        ".kt-scaffold/hooks/governance_forwarder.py",
        ".kt-scaffold/hooks/governance_identity.py",
    )
    for index, virtual_relative in enumerate(AUTHORITY_MANAGED_GENERATED_ARTIFACTS):
        project_relative = generated_sources[index]
        raw = _require_managed_bytes(root, managed, project_relative)
        digest.update(virtual_relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_raw_sha256(raw).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_project_bindings(root: Path, receipt: dict[str, Any], client: str) -> None:
    _, manifest_raw, manifest = _json_file(
        root,
        ".kt-scaffold/project-manifest.json",
        expected_keys={
            "format",
            "blueprint_id",
            "project_id",
            "blueprint_version",
            "project_intent",
            "primary_domain",
            "application_mode",
            "backend_profile",
            "persistence_profile",
            "locales",
            "authority_generation",
            "governance_version",
            "governance_digest",
            "artifacts",
        },
    )
    authority = receipt.get("authority")
    managed = _managed_inventory(root)
    _require(
        _raw_sha256(manifest_raw) == managed.get(".kt-scaffold/project-manifest.json"),
        "MANAGED_PROJECT_MANIFEST_DRIFT",
    )
    _require_managed_bytes(root, managed, CLIENT_HOOK_PATHS[client])
    _require(isinstance(authority, dict), "AUTHORITY_MISMATCH")
    _require(receipt.get("project_id") == manifest.get("project_id"), "PROJECT_ID_MISMATCH")
    _require(
        authority.get("authority_generation") == manifest.get("authority_generation"),
        "AUTHORITY_MISMATCH",
    )
    _require(authority.get("version") == manifest.get("governance_version"), "AUTHORITY_MISMATCH")
    _require(authority.get("sha256") == manifest.get("governance_digest"), "AUTHORITY_MISMATCH")
    _require(authority.get("manifest_sha256") == _raw_sha256(manifest_raw), "AUTHORITY_MISMATCH")
    _require(
        manifest.get("governance_digest")
        == _recomputed_governance_digest(root, manifest, managed, client),
        "AUTHORITY_DIGEST_MISMATCH",
    )

    versioned_bindings = (
        (receipt["orchestration"], "agent-platform/orchestrations/governed-review.yml"),
        (receipt["aggregation_policy"], "agent-platform/policies/aggregation/governed-review.yml"),
        (
            receipt["agentic_evaluator"],
            "agent-platform/policies/aggregation/governed-review-agentic-evaluation.yml",
        ),
    )
    component_sources: dict[str, bytes] = {}
    for binding, relative in versioned_bindings:
        _, raw = _regular_file(root, relative, limit=MAX_JSON_BYTES)
        component_sources[relative] = raw
        _require(binding.get("sha256") == _raw_sha256(raw), "COMPONENT_DIGEST_MISMATCH")
        _require(binding.get("version") == _yaml_metadata_version(raw), "COMPONENT_VERSION_INVALID")

    aggregation_raw = component_sources["agent-platform/policies/aggregation/governed-review.yml"]
    aggregation = receipt["aggregation_policy"]
    _require(
        aggregation.get("weights") == _yaml_direct_mapping(aggregation_raw, "weights")
        and aggregation.get("thresholds") == _yaml_direct_mapping(aggregation_raw, "thresholds")
        and aggregation.get("calibration_status")
        == _yaml_direct_mapping(aggregation_raw, "lineage").get("calibration_status")
        and aggregation.get("runtime_admission")
        == _yaml_direct_mapping(aggregation_raw, "lineage").get("runtime_admission")
        and aggregation.get("instructions_ref")
        == _yaml_top_level_scalar(aggregation_raw, "instructions_ref"),
        "AGGREGATION_POLICY_BINDING_MISMATCH",
    )
    evaluator_source = _yaml_direct_mapping(
        component_sources[
            "agent-platform/policies/aggregation/governed-review-agentic-evaluation.yml"
        ],
        "aggregation_source",
    )
    _require(
        evaluator_source
        == {
            "policy_ref": aggregation["ref"],
            "policy_version": aggregation["version"],
            "policy_sha256": aggregation["sha256"],
            "path": "policies/aggregation/governed-review.yml",
            "copy_values": False,
        },
        "EVALUATOR_POLICY_BINDING_MISMATCH",
    )

    digest_bindings = (
        (
            {"sha256": receipt["aggregation_policy"]["instructions_sha256"]},
            "agent-platform/policies/aggregation/governed-review-instructions.md",
        ),
        (receipt["mandatory_governed_execution"]["rule"], "rules/13-tamamlanma-tanimi.md"),
        (receipt["mandatory_governed_execution"]["skill"], CLIENT_SKILLS[client]),
    )
    for binding, relative in digest_bindings:
        raw = _require_managed_bytes(root, managed, relative)
        _require(binding.get("sha256") == _raw_sha256(raw), "COMPONENT_DIGEST_MISMATCH")
    rule_artifacts = [
        item
        for item in manifest["artifacts"]
        if isinstance(item, dict) and item.get("artifact_id") == "rule:13-tamamlanma-tanimi"
    ]
    _require(len(rule_artifacts) == 1, "AUTHORITY_MANIFEST_INVALID")
    _require(
        rule_artifacts[0].get("sha256")
        == receipt["mandatory_governed_execution"]["rule"].get("sha256"),
        "AUTHORITY_RULE_BINDING_MISMATCH",
    )
    generator_version = manifest.get("blueprint_version")
    _require(
        receipt["mandatory_governed_execution"]["rule"].get("version") == generator_version,
        "COMPONENT_VERSION_INVALID",
    )
    _require(
        receipt["mandatory_governed_execution"]["skill"].get("version") == generator_version,
        "COMPONENT_VERSION_INVALID",
    )

    for result in receipt["agent_results"]:
        slug = result["agent_id"].removeprefix("agent:")
        component = result["component_binding"]
        for name, filename in (
            ("agent", "agent.yml"),
            ("policy", "policy.yml"),
            ("detectors", "detectors.yml"),
            ("instructions", "instructions.md"),
        ):
            _, raw = _regular_file(
                root, f"agent-platform/agents/{slug}/{filename}", limit=MAX_JSON_BYTES
            )
            _require(component[name]["sha256"] == _raw_sha256(raw), "AGENT_COMPONENT_MISMATCH")
            if name == "instructions":
                _require(component[name]["version"] == "unavailable", "COMPONENT_VERSION_INVALID")
            else:
                _require(
                    component[name]["version"] == _yaml_metadata_version(raw),
                    "COMPONENT_VERSION_INVALID",
                )
        projection = component["projection"]
        _require(projection.get("client_id") == client, "AGENT_PROJECTION_MISMATCH")
        _require(
            projection.get("path") == CLIENT_PROJECTION_PATHS[client].format(agent=slug),
            "AGENT_PROJECTION_MISMATCH",
        )
        _, raw = _regular_file(root, projection["path"], limit=MAX_JSON_BYTES)
        _require(
            managed.get(projection["path"]) == _raw_sha256(raw),
            "MANAGED_AGENT_PROJECTION_DRIFT",
        )
        _require(projection.get("sha256") == _raw_sha256(raw), "AGENT_PROJECTION_MISMATCH")
        _require(projection.get("version") == "unavailable", "COMPONENT_VERSION_INVALID")


def _validate_prompt_envelope(
    root: Path,
    receipt: dict[str, Any],
    envelope: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> None:
    event_id = envelope.get("source_event_id")
    _require(
        isinstance(event_id, str) and re.fullmatch(r"event:[0-9a-f]{32}", event_id) is not None,
        "PROMPT_BINDING_MISMATCH",
    )
    client_id = receipt["execution"]["client"]["id"]
    source_ref = f"record:v1:{receipt['project_id']}:prompt-ingress:{event_id[6:]}"
    metadata = _stored_prompt_metadata(receipt["project_id"], event_id[6:])
    _validate_against_schema(metadata, "prompt-ingress-metadata.schema.json", schemas)
    for key, expected in {
        "source_receipt_path": source_ref,
        "project_id": receipt["project_id"],
        "client_id": client_id,
        "prompt_session_id": receipt["execution"]["session_id"],
        "prompt_turn_id": envelope.get("source_prompt_turn_id"),
        "event_id": event_id,
        "decision": "allow",
        "outcome": "clean",
    }.items():
        _require(metadata.get(key) == expected, "PROMPT_BINDING_MISMATCH")
    # The prompt hook, not the Agent, observed the model; the receipt must carry the same record.
    _require(metadata.get("model") == receipt["execution"]["model"], "MODEL_BINDING_MISMATCH")
    expected = {
        "kind": "redacted-digest-only-prompt-envelope",
        "version": "1.0.0",
        "source_event_id": event_id,
        "source_prompt_turn_id": metadata["prompt_turn_id"],
        "source_receipt_sha256": metadata["source_receipt_sha256"],
        "prompt_capture_sha256": metadata["prompt_capture_sha256"],
        "raw_content_stored": False,
    }
    _require(
        envelope == {**expected, "sha256": _canonical_sha256(expected)}, "PROMPT_BINDING_MISMATCH"
    )


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _stored_prompt_metadata(project_id: str, event_token: str) -> dict[str, Any]:
    hooks = Path(__file__).resolve().parent
    for name in ("governance_records.py", "prompt_ingress_guard.py"):
        path = hooks / name
        _require(path.is_file() and not path.is_symlink(), "PROMPT_BINDING_MISMATCH")
    try:
        writer = runpy.run_path(str(hooks / "governance_records.py"))
        record = writer["read_event"](
            "prompt-ingress", project_id, event_token, location=_record_location()
        )
        metadata = runpy.run_path(str(hooks / "prompt_ingress_guard.py"))["prompt_metadata"](record)
    except Exception:
        _deny("PROMPT_BINDING_MISMATCH")
    _require(isinstance(metadata, dict), "PROMPT_BINDING_MISMATCH")
    return cast(dict[str, Any], metadata)


def _validate_evidence(
    root: Path,
    receipt: dict[str, Any],
    decision: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> tuple[datetime, datetime, datetime]:
    evidence = _exact_keys(
        receipt.get("decision_evidence"), EVIDENCE_KEYS, "DECISION_EVIDENCE_INVALID"
    )
    _require(evidence.get("schema_version") == "1.1", "DECISION_EVIDENCE_INVALID")
    _require(
        evidence.get("kind") == "AgenticGovernedReviewDecisionEvidence", "DECISION_EVIDENCE_INVALID"
    )
    _require(
        evidence.get("evidence_profile") == "phase1-evidence-bound-accountable-replay",
        "DECISION_EVIDENCE_INVALID",
    )
    _require(
        evidence.get("canonicalization") == "kt-agentic-decision-evidence-json-v1",
        "DECISION_EVIDENCE_INVALID",
    )
    _require(
        evidence.get("evidence_sha256") == _canonical_sha256(evidence, excluding="evidence_sha256"),
        "DECISION_EVIDENCE_DIGEST_MISMATCH",
    )
    _all_false(
        evidence.get("data_handling"),
        {
            "raw_prompt_stored",
            "source_content_stored",
            "pii_stored",
            "secret_stored",
            "credential_stored",
        },
        "DATA_HANDLING_INVALID",
    )
    model_rerun = evidence.get("model_rerun")
    _require(
        isinstance(model_rerun, dict) and model_rerun.get("exact_output_guaranteed") is False,
        "MODEL_RERUN_CLAIM_INVALID",
    )

    audit_replay = evidence.get("audit_replay")
    _require(isinstance(audit_replay, dict), "AUDIT_REPLAY_INVALID")
    _require(audit_replay.get("capability") == "audit_replay", "AUDIT_REPLAY_INVALID")
    _require(audit_replay.get("requirement") == "mandatory", "AUDIT_REPLAY_INVALID")
    _require(
        audit_replay.get("canonicalization") == "kt-agentic-audit-replay-json-v1",
        "AUDIT_REPLAY_INVALID",
    )
    _require(audit_replay.get("status") == "verified", "AUDIT_REPLAY_NOT_VERIFIED")
    _require(
        audit_replay.get("sha256") == _canonical_sha256(audit_replay, excluding="sha256"),
        "AUDIT_REPLAY_DIGEST_MISMATCH",
    )
    for field in ("project_id", "run_id", "trace_id"):
        _require(audit_replay.get(field) == receipt.get(field), "AUDIT_REPLAY_CORRELATION_MISMATCH")
    _require(
        audit_replay["input_binding"]["snapshot"]["sha256"]
        == receipt["snapshot"]["snapshot_sha256"],
        "AUDIT_REPLAY_SNAPSHOT_MISMATCH",
    )
    _require(
        audit_replay["input_binding"]["canonical_input"]
        == {
            "canonicalization": "kt-agentic-review-input-manifest-json-v1",
            "item_count": 1,
            "sha256": receipt["snapshot"]["snapshot_sha256"],
        },
        "CANONICAL_INPUT_MISMATCH",
    )
    _require(
        audit_replay["input_binding"].get("acceptance_criteria")
        == receipt.get("acceptance_criteria"),
        "ACCEPTANCE_CRITERIA_MISMATCH",
    )

    components = audit_replay.get("component_binding")
    _require(isinstance(components, dict), "AUDIT_REPLAY_COMPONENT_MISMATCH")
    correlations = (
        ("orchestration", receipt["orchestration"], "ref"),
        ("aggregation_policy", receipt["aggregation_policy"], "ref"),
        ("agentic_evaluator", receipt["agentic_evaluator"], "policy_ref"),
    )
    for name, source, ref_field in correlations:
        for field in ("ref", "version", "sha256"):
            source_field = ref_field if field == "ref" else field
            _require(
                components[name].get(field) == source.get(source_field),
                "AUDIT_REPLAY_COMPONENT_MISMATCH",
            )
    _require(
        components["authority"].get("version") == receipt["authority"].get("version"),
        "AUDIT_REPLAY_COMPONENT_MISMATCH",
    )
    _require(
        components["authority"].get("sha256") == receipt["authority"].get("sha256"),
        "AUDIT_REPLAY_COMPONENT_MISMATCH",
    )
    harness = receipt["mandatory_governed_execution"]
    for name in ("rule", "skill"):
        for field in ("ref", "version", "sha256"):
            _require(
                components[name].get(field) == harness[name].get(field),
                "AUDIT_REPLAY_COMPONENT_MISMATCH",
            )
    _require(
        components["harness"].get("version") == harness.get("version"),
        "AUDIT_REPLAY_COMPONENT_MISMATCH",
    )
    _require(
        components["harness"].get("sha256") == harness.get("sha256"),
        "AUDIT_REPLAY_COMPONENT_MISMATCH",
    )
    agent_manifest_sha = _canonical_sha256(_agent_manifest(receipt["agent_results"]))
    _require(components["agent_manifest"].get("agent_count") == 12, "AGENT_MANIFEST_MISMATCH")
    _require(
        components["agent_manifest"].get("sha256") == agent_manifest_sha, "AGENT_MANIFEST_MISMATCH"
    )
    client_binding = receipt["execution"]["client"]
    for field in ("id", "version", "sha256"):
        _require(
            components["client"].get(field) == client_binding.get(field), "CLIENT_BINDING_MISMATCH"
        )
    _require(
        audit_replay["prompt_binding"]["template"].get("ref") == harness["skill"].get("ref"),
        "PROMPT_BINDING_MISMATCH",
    )
    _require(
        audit_replay["prompt_binding"]["template"].get("sha256") == harness["skill"].get("sha256"),
        "PROMPT_BINDING_MISMATCH",
    )
    _validate_prompt_envelope(root, receipt, audit_replay["prompt_binding"]["envelope"], schemas)
    manifest_canonicalizations = {
        "context": "kt-agentic-context-manifest-json-v1",
        "retrieval": "kt-agentic-retrieval-manifest-json-v1",
        "tool_results": "kt-agentic-tool-result-manifest-json-v1",
    }
    for name, canonicalization in manifest_canonicalizations.items():
        empty_payload = {"canonicalization": canonicalization, "items": []}
        _require(
            audit_replay["manifests"].get(name)
            == {
                "canonicalization": canonicalization,
                "availability": "not-used",
                "reason_code": "NOT_USED",
                "item_count": 0,
                "sha256": _canonical_sha256(empty_payload),
            },
            "AUDIT_MANIFEST_UNVERIFIABLE",
        )

    primary = audit_replay.get("primary_evaluation")
    second = audit_replay.get("second_pass_validator")
    _require(isinstance(primary, dict) and isinstance(second, dict), "SECOND_PASS_INVALID")
    _require(
        primary.get("sha256") == _canonical_sha256(primary, excluding="sha256"),
        "PRIMARY_EVALUATION_DIGEST_MISMATCH",
    )
    _require(
        second.get("validator_id") == "validator:governed-review-agentic-second-pass",
        "SECOND_PASS_INVALID",
    )
    validator_binding = {
        "canonicalization": "kt-agentic-second-pass-validator-binding-json-v1",
        "agentic_evaluator_sha256": components["agentic_evaluator"]["sha256"],
        "harness_sha256": components["harness"]["sha256"],
        "skill_sha256": components["skill"]["sha256"],
    }
    _require(
        second.get("version") == receipt["agentic_evaluator"]["version"]
        and second.get("sha256") == _canonical_sha256(validator_binding),
        "SECOND_PASS_COMPONENT_BINDING_MISMATCH",
    )
    _require(
        second.get("method") == "independent-second-pass-policy-recalculation",
        "SECOND_PASS_INVALID",
    )
    _require(
        second.get("result") == "verified" and second.get("matches_primary_evaluation") is True,
        "SECOND_PASS_INVALID",
    )
    _require(
        second.get("invocation_id") != primary.get("invocation_id"), "SECOND_PASS_NOT_DISTINCT"
    )
    _require(second.get("span_id") != primary.get("span_id"), "SECOND_PASS_NOT_DISTINCT")
    checked = second.get("checked_digest_set")
    _require(isinstance(checked, dict), "CHECKED_DIGEST_SET_INVALID")
    _require(
        second.get("checked_digest_set_sha256") == _canonical_sha256(checked),
        "CHECKED_DIGEST_SET_INVALID",
    )
    expected_checked = {
        "canonicalization": "kt-agentic-checked-digest-set-json-v1",
        "canonical_input_sha256": audit_replay["input_binding"]["canonical_input"]["sha256"],
        "snapshot_sha256": audit_replay["input_binding"]["snapshot"]["sha256"],
        "authority_sha256": components["authority"]["sha256"],
        "orchestration_sha256": components["orchestration"]["sha256"],
        "aggregation_policy_sha256": components["aggregation_policy"]["sha256"],
        "agentic_evaluator_sha256": components["agentic_evaluator"]["sha256"],
        "harness_sha256": components["harness"]["sha256"],
        "rule_sha256": components["rule"]["sha256"],
        "skill_sha256": components["skill"]["sha256"],
        "agent_manifest_sha256": components["agent_manifest"]["sha256"],
        "client_sha256": components["client"]["sha256"],
        "prompt_template_sha256": audit_replay["prompt_binding"]["template"]["sha256"],
        "prompt_envelope_sha256": audit_replay["prompt_binding"]["envelope"]["sha256"],
        "context_manifest_sha256": audit_replay["manifests"]["context"]["sha256"],
        "retrieval_manifest_sha256": audit_replay["manifests"]["retrieval"]["sha256"],
        "tool_result_manifest_sha256": audit_replay["manifests"]["tool_results"]["sha256"],
        "primary_evaluation_sha256": primary["sha256"],
    }
    _require(checked == expected_checked, "CHECKED_DIGEST_SET_INVALID")

    outcome_fields = (
        "verdict",
        "reason_codes",
        "rationale_summary",
        "weighted_risk_score_basis_points",
        "compliance_score_basis_points",
    )
    for field in outcome_fields:
        _require(second["recalculated"].get(field) == primary.get(field), "SECOND_PASS_MISMATCH")
    _require(primary.get("verdict") == "PASS", "PRIMARY_EVALUATION_NOT_PASS")
    _require(primary.get("verdict") == decision.get("decision"), "DECISION_MISMATCH")
    _require(primary.get("reason_codes") == decision.get("reason_codes"), "DECISION_MISMATCH")
    _require(
        primary.get("rationale_summary") == decision.get("rationale_summary"), "DECISION_MISMATCH"
    )
    _require(
        primary.get("weighted_risk_score_basis_points")
        == decision.get("weighted_risk_score_basis_points"),
        "DECISION_MISMATCH",
    )
    _require(
        primary.get("compliance_score_basis_points")
        == decision.get("compliance_score_basis_points"),
        "DECISION_MISMATCH",
    )
    _require(
        primary.get("invocation_id") == decision.get("evaluator_invocation_id"), "DECISION_MISMATCH"
    )
    _require(primary.get("span_id") == decision.get("span_id"), "DECISION_MISMATCH")
    _require(
        evidence["evidence_sha256"] == decision.get("decision_evidence_sha256"), "DECISION_MISMATCH"
    )

    started = _parse_time(primary.get("started_at"), "TIMESTAMP_INVALID")
    completed = _parse_time(primary.get("completed_at"), "TIMESTAMP_INVALID")
    second_completed = _parse_time(second.get("completed_at"), "TIMESTAMP_INVALID")
    _require(started <= completed <= second_completed, "TIMESTAMP_ORDER_INVALID")
    _require(
        _parse_time(decision.get("evaluation_started_at"), "TIMESTAMP_INVALID") == started,
        "TIMESTAMP_ORDER_INVALID",
    )
    _require(
        _parse_time(decision.get("decided_at"), "TIMESTAMP_INVALID") == second_completed,
        "TIMESTAMP_ORDER_INVALID",
    )
    return started, completed, second_completed


SCAN_RECORD_NAME = "deterministic-scan"
SCAN_RECORD_SCHEMA = "agentic-governed-review-deterministic-scan.schema.json"
SCAN_RECORD_HEADER_KEYS = (
    "schema_version",
    "kind",
    "canonicalization",
    "project_id",
    "run_id",
    "snapshot_sha256",
    "claim_boundary",
    "data_handling",
)
CANDIDATE_FIELDS = (
    "candidate_id",
    "detector_id",
    "severity",
    "path",
    "start_line",
    "end_line",
    "summary",
)
MIN_DISMISSAL_REASON_CHARACTERS = 20


def deterministic_candidates(record: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    """The adjudication matches of one Agent, as its bindings input lists them."""

    try:
        return [
            {field: match[field] for field in CANDIDATE_FIELDS}
            for match in record["matches"]
            if match["agent_id"] == agent_id and match["scan_group"] == "adjudication"
        ]
    except (KeyError, TypeError):
        _deny("DETERMINISTIC_SCAN_INVALID")


def candidate_response_problem(
    candidates: object, responses: object, status: object
) -> tuple[str, dict[str, object]] | None:
    """The first way a specialist's responses fail to answer its candidates, or ``None``.

    Every candidate of an ``ok`` report needs exactly one response; a dismissal carries a
    reason. A malformed list is left to the observation schema, which names it.
    """

    if not isinstance(candidates, list) or not isinstance(responses, list):
        return None
    known = [item.get("candidate_id") for item in candidates if isinstance(item, dict)]
    seen: set[object] = set()
    for index, response in enumerate(responses):
        if not isinstance(response, dict):
            continue
        identifier = response.get("candidate_id")
        pointer = f"/candidate_responses/{index}"
        if identifier not in known:
            return "CANDIDATE_UNKNOWN", {
                "pointer": f"{pointer}/candidate_id",
                "keyword": "enum",
                "constraint": known,
            }
        if identifier in seen:
            return "CANDIDATE_RESPONSE_DUPLICATE", {
                "pointer": f"{pointer}/candidate_id",
                "keyword": "uniqueItems",
                "constraint": identifier,
            }
        seen.add(identifier)
        reason = response.get("reason")
        if response.get("decision") == "dismissed" and (
            not isinstance(reason, str) or len(reason.strip()) < MIN_DISMISSAL_REASON_CHARACTERS
        ):
            return "CANDIDATE_REASON_MISSING", {
                "pointer": f"{pointer}/reason",
                "keyword": "minLength",
                "constraint": MIN_DISMISSAL_REASON_CHARACTERS,
            }
    missing = [identifier for identifier in known if identifier not in seen]
    if status == "ok" and missing:
        return "CANDIDATE_RESPONSE_MISSING", {
            "pointer": "/candidate_responses",
            "keyword": "required",
            "constraint": missing,
        }
    return None


def deterministic_scan_findings(
    record: dict[str, Any], observations: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Code findings and dismissed candidates of a scan record and the specialists' responses.

    A blocking-group match is a finding; an adjudication candidate becomes one only when its
    specialist confirms it. A dismissed candidate keeps its reason and never enters the decision.
    A candidate of a report that is not ``ok`` stays unanswered: that report already blocks.
    """

    try:
        effects = {item["detector_id"]: item["decision_effect"] for item in record["detectors"]}
        responses: dict[str, dict[str, dict[str, Any]]] = {}
        statuses: dict[str, object] = {}
        for observation in observations:
            agent_id = observation["agent_id"]
            statuses[agent_id] = observation.get("status")
            responses[agent_id] = {
                item["candidate_id"]: item
                for item in observation.get("candidate_responses", [])
                if isinstance(item, dict)
            }
        findings: list[dict[str, Any]] = []
        dismissed: list[dict[str, Any]] = []
        for match in record["matches"]:
            location = {
                field: match[field]
                for field in (
                    "candidate_id",
                    "agent_id",
                    "detector_id",
                    "scan_group",
                    "severity",
                    "path",
                    "start_line",
                    "end_line",
                )
            }
            if match["scan_group"] == "blocking":
                findings.append({**location, "decision_effect": effects[match["detector_id"]]})
                continue
            response = responses.get(match["agent_id"], {}).get(match["candidate_id"])
            if response is None:
                _require(statuses.get(match["agent_id"]) != "ok", "CANDIDATE_RESPONSES_INVALID")
            elif response.get("decision") == "confirmed":
                findings.append({**location, "decision_effect": effects[match["detector_id"]]})
            else:
                dismissed.append({**location, "reason": response.get("reason")})
    except (KeyError, TypeError, AttributeError):
        _deny("DETERMINISTIC_SCAN_INVALID")
    return findings, dismissed


def deterministic_scan_evidence(
    run_id: str,
    record_sha256: str,
    findings: list[dict[str, Any]],
    dismissed: list[dict[str, Any]],
) -> dict[str, Any]:
    """The decision evidence's binding to the scan record, its code findings and dismissals."""

    return {
        "record_path": f"{REVIEW_AREA}/{run_id}/reports/{SCAN_RECORD_NAME}.json",
        "record_sha256": record_sha256,
        "executor_ref": "executor:governance-client/deterministic-scan",
        "code_findings": findings,
        "dismissed_candidates": dismissed,
    }


def _rescanned(root: Path, executable: str) -> dict[str, Any]:
    """Run the governance client's scan again on the staged tree; the record is never trusted."""

    path = Path(__file__).resolve().with_name("governance_client.py")
    _require(path.is_file() and not path.is_symlink(), "DETERMINISTIC_SCAN_FAILED")
    client = runpy.run_path(str(path))
    try:
        body = client["deterministic_scan"](root, executable)
    except client["GovernanceClientError"] as error:
        _deny(error.reason_code or "DETERMINISTIC_SCAN_FAILED")
    except Exception:
        _deny("DETERMINISTIC_SCAN_FAILED")
    _require(isinstance(body, dict), "DETERMINISTIC_SCAN_FAILED")
    return cast(dict[str, Any], body)


def _validate_scan_record(
    root: Path,
    receipt: dict[str, Any],
    snapshot: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    executable: str,
) -> tuple[dict[str, Any], str]:
    relative = f"{REVIEW_AREA}/{receipt['run_id']}/reports/{SCAN_RECORD_NAME}.json"
    _, raw = _regular_file(root, relative, limit=MAX_JSON_BYTES)
    record = _strict_json_loads(raw, "DETERMINISTIC_SCAN_INVALID")
    _require(
        isinstance(record, dict) and raw == _canonical_bytes(record), "DETERMINISTIC_SCAN_INVALID"
    )
    _validate_against_schema(record, SCAN_RECORD_SCHEMA, schemas)
    _require(
        record.get("project_id") == receipt.get("project_id")
        and record.get("run_id") == receipt.get("run_id")
        and record.get("snapshot_sha256") == snapshot["snapshot_sha256"],
        "DETERMINISTIC_SCAN_INVALID",
    )
    _require(record.get("status") == "complete", "DETERMINISTIC_SCAN_INCOMPLETE")
    body = _rescanned(root, executable)
    _require(
        {key: value for key, value in record.items() if key not in SCAN_RECORD_HEADER_KEYS}
        == body,
        "DETERMINISTIC_SCAN_MISMATCH",
    )
    return record, _raw_sha256(raw)


def _security_veto_clear(
    receipt: dict[str, Any], result: dict[str, Any], findings: list[Any]
) -> bool:
    floor = receipt["aggregation_policy"]["thresholds"]["confidence_floor"]
    score = result.get("max_risk_score_basis_points")
    if type(score) is not int or score >= CRITICAL_SCORE_BASIS_POINTS:
        return False
    return not any(
        isinstance(finding, dict)
        and finding.get("severity") == "critical"
        and isinstance(finding.get("confidence"), (int, float))
        and finding["confidence"] >= floor
        for finding in findings
    )


def severity_scores(aggregation_raw: bytes) -> dict[str, int]:
    """``finding_classification.severity_bands[].detector_score_basis_points`` by severity."""

    try:
        lines = aggregation_raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _deny("COMPONENT_POLICY_INVALID")
    try:
        start = lines.index("  severity_bands:") + 1
    except ValueError:
        _deny("COMPONENT_POLICY_INVALID")
    scores: dict[str, int] = {}
    severity: str | None = None
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith("    "):
            break
        matched = re.fullmatch(r"    - severity: ([a-z]+)", line)
        if matched is not None:
            severity = matched.group(1)
            continue
        matched = re.fullmatch(r"      detector_score_basis_points: ([0-9]+)", line)
        if matched is not None:
            _require(severity is not None and severity not in scores, "COMPONENT_POLICY_INVALID")
            scores[cast(str, severity)] = int(matched.group(1))
    _require(tuple(scores) == SEVERITIES, "COMPONENT_POLICY_INVALID")
    _require(all(0 <= value <= 10_000 for value in scores.values()), "COMPONENT_POLICY_INVALID")
    return scores


def detector_hard_fail_lists(detectors_raw: bytes) -> tuple[frozenset[str], frozenset[str]]:
    """The pack's authoritative and unresolved hard-fail detectors from ``decision_metadata``."""

    try:
        lines = detectors_raw.decode("utf-8").splitlines()
        start = lines.index("decision_metadata:") + 1
    except (UnicodeDecodeError, ValueError):
        _deny("COMPONENT_POLICY_INVALID")
    lists: dict[str, list[str]] = {}
    key: str | None = None
    for line in lines[start:]:
        if not line.strip():
            continue
        if not line.startswith("  "):
            break
        matched = re.fullmatch(r"  ([a-z_]+):( \[\])?", line)
        if matched is not None:
            key = matched.group(1)
            lists[key] = []
            continue
        matched = re.fullmatch(r"    - (detector:[a-z0-9/-]+)", line)
        if matched is not None and key is not None:
            lists[key].append(matched.group(1))
    _require(
        "authoritative_hard_fail_detectors" in lists and "unresolved_hard_fail_detectors" in lists,
        "COMPONENT_POLICY_INVALID",
    )
    return (
        frozenset(lists["authoritative_hard_fail_detectors"]),
        frozenset(lists["unresolved_hard_fail_detectors"]),
    )


def _basis_points(value: object, scale: int) -> int:
    _require(type(value) in {int, float}, "AGGREGATION_POLICY_BINDING_MISMATCH")
    text = repr(value)
    whole, _, fraction = text.partition(".")
    _require(
        re.fullmatch(r"[0-9]+", whole) is not None
        and re.fullmatch(r"[0-9]*", fraction) is not None,
        "AGGREGATION_POLICY_BINDING_MISMATCH",
    )
    digits = len(str(scale)) - 1
    _require(len(fraction.rstrip("0")) <= digits, "AGGREGATION_POLICY_BINDING_MISMATCH")
    return int(whole) * scale + int((fraction + "0" * digits)[:digits] or "0")


def recalculate_policy_outcome(
    receipt: dict[str, Any],
    observations: list[dict[str, Any]],
    scores: dict[str, int],
    code_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute the aggregation outcome of the twelve bound reports and the scan's code findings.

    The receipt's weights and thresholds are already bound to the aggregation policy file.  This
    verifier derives each Agent's maximum score from its findings' and code findings' severities
    and applies the policy's precedence; it never changes, scores or interprets a finding.  Only a
    code finding of a hard-fail detector yields ``HARD-FAIL``; one of an unresolved or conflicting
    detector blocks.
    """

    policy = receipt["aggregation_policy"]
    weights = policy["weights"]
    thresholds = policy["thresholds"]
    floor = thresholds["confidence_floor"]
    _require(type(floor) in {int, float}, "AGGREGATION_POLICY_BINDING_MISMATCH")
    blocked: set[str] = set()
    hard_fail = False
    vetoed = False
    weighted_sum = 0
    total_weight = 0
    results = receipt["agent_results"]
    _require(len(observations) == len(results) == len(AGENTS), "POLICY_RECALCULATION_MISMATCH")
    code_by_agent: dict[str, list[dict[str, Any]]] = {}
    for code_finding in code_findings:
        _require(
            isinstance(code_finding, dict)
            and code_finding.get("severity") in scores
            and code_finding.get("decision_effect") in {"hard-fail", "blocked-incomplete"},
            "POLICY_RECALCULATION_MISMATCH",
        )
        code_by_agent.setdefault(str(code_finding.get("agent_id")), []).append(code_finding)
    _require(set(code_by_agent) <= set(AGENTS), "POLICY_RECALCULATION_MISMATCH")
    for index, result in enumerate(results):
        observation = observations[index]
        agent_id = result["agent_id"]
        _require(observation.get("agent_id") == agent_id, "POLICY_RECALCULATION_MISMATCH")
        status = observation.get("status")
        if status == "failed":
            blocked.add("AGG_AGENT_FAILED")
        elif status == "timeout":
            blocked.add("AGG_TIMEOUT")
        elif status != "ok":
            blocked.add("AGG_INVALID_SCHEMA")
        findings = observation.get("findings")
        _require(isinstance(findings, list), "POLICY_RECALCULATION_MISMATCH")
        maximum = 0
        for finding in findings:
            _require(
                isinstance(finding, dict) and finding.get("severity") in scores,
                "POLICY_RECALCULATION_MISMATCH",
            )
            maximum = max(maximum, scores[finding["severity"]])
            confidence = finding.get("confidence")
            _require(type(confidence) in {int, float}, "POLICY_RECALCULATION_MISMATCH")
            if confidence < floor:
                blocked.add("AGG_LOW_CONFIDENCE")
            source = finding.get("source")
            if isinstance(source, str) and source.startswith("source-conflict:"):
                blocked.add("AGG_AUTHORITATIVE_CONFLICT")
            if (
                agent_id in SECURITY_CRITICAL_VETO_AGENTS
                and finding["severity"] == "critical"
                and confidence >= floor
            ):
                vetoed = True
        for code_finding in code_by_agent.get(agent_id, []):
            maximum = max(maximum, scores[code_finding["severity"]])
            if code_finding["decision_effect"] == "hard-fail":
                hard_fail = True
            else:
                blocked.add("AGG_AUTHORITATIVE_CONFLICT")
            if agent_id in SECURITY_CRITICAL_VETO_AGENTS and code_finding["severity"] == "critical":
                vetoed = True
        _require(
            result.get("max_risk_score_basis_points") == maximum, "POLICY_RECALCULATION_MISMATCH"
        )
        weight = _basis_points(weights.get(agent_id), 1_000_000)
        _require(weight > 0, "AGGREGATION_POLICY_BINDING_MISMATCH")
        weighted_sum += maximum * weight
        total_weight += weight
    risk = (weighted_sum + total_weight // 2) // total_weight
    compliance = max(0, _basis_points(thresholds["compliance_baseline"], 100) - risk)
    if blocked:
        verdict, reasons = "BLOCKED_INCOMPLETE", sorted(blocked)
    elif hard_fail:
        verdict, reasons = "HARD-FAIL", ["AGG_HARD_FAIL"]
    elif vetoed:
        verdict, reasons = "FAIL", ["AGG_SECURITY_CRITICAL_VETO"]
    elif risk >= _basis_points(thresholds["fail_score"], 100):
        verdict, reasons = "FAIL", ["AGG_THRESHOLD_FAIL"]
    elif risk >= _basis_points(thresholds["warning_score"], 100):
        verdict, reasons = "PASS", ["AGG_THRESHOLD_WARNING"]
    else:
        verdict, reasons = "PASS", ["AGG_THRESHOLD_PASS"]
    return {
        "verdict": verdict,
        "reason_codes": reasons,
        "weighted_risk_score_basis_points": risk,
        "compliance_score_basis_points": compliance,
    }


def _validate_reports(
    root: Path,
    receipt: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> list[tuple[Path, dict[str, Any]]]:
    reports: list[tuple[Path, dict[str, Any]]] = []
    results = receipt.get("agent_results")
    _require(isinstance(results, list) and len(results) == 12, "AGENT_RESULTS_INVALID")
    _require(
        tuple(item.get("agent_id") for item in results if isinstance(item, dict)) == AGENTS,
        "AGENT_RESULTS_INVALID",
    )
    _require(len({item.get("invocation_id") for item in results}) == 12, "AGENT_RESULTS_INVALID")
    _require(len({item.get("span_id") for item in results}) == 12, "AGENT_RESULTS_INVALID")
    report_root = f"{REVIEW_AREA}/{receipt['run_id']}/reports"
    _require(receipt.get("report_directory") == report_root, "REPORT_DIRECTORY_INVALID")
    for result in results:
        slug = result["agent_id"].removeprefix("agent:")
        relative = f"{report_root}/{slug}.json"
        _require(result.get("report_path") == relative, "REPORT_PATH_INVALID")
        _require(result.get("status") == "ok", "AGENT_RESULT_NOT_OK")
        path, raw, observation = _json_file(root, relative, expected_keys=OBSERVATION_KEYS)
        _require(raw == _canonical_bytes(observation), "REPORT_FORMAT_INVALID")
        _validate_against_schema(
            observation,
            "agentic-governance-observation.schema.json",
            schemas,
        )
        _require(result.get("report_sha256") == _raw_sha256(raw), "REPORT_DIGEST_MISMATCH")
        for field in ("receipt_id", "project_id", "run_id", "trace_id"):
            _require(observation.get(field) == receipt.get(field), "REPORT_CORRELATION_MISMATCH")
        for field in ("agent_id", "span_id", "invocation_id", "status", "component_binding"):
            _require(observation.get(field) == result.get(field), "REPORT_CORRELATION_MISMATCH")
        _require(
            observation.get("snapshot_sha256") == receipt["snapshot"]["snapshot_sha256"],
            "REPORT_CORRELATION_MISMATCH",
        )
        _require(
            observation.get("agentic_evaluator") == receipt.get("agentic_evaluator"),
            "REPORT_CORRELATION_MISMATCH",
        )
        if result["agent_id"] == TEST_AUTOMATION_AGENT:
            _require(
                observation.get("acceptance_criteria") == receipt.get("acceptance_criteria"),
                "ACCEPTANCE_CRITERIA_MISMATCH",
            )
        findings = observation.get("findings")
        _require(
            isinstance(findings, list) and len(findings) == result.get("finding_count"),
            "REPORT_FINDINGS_MISMATCH",
        )
        if result["agent_id"] in SECURITY_CRITICAL_VETO_AGENTS:
            _require(_security_veto_clear(receipt, result, findings), "SECURITY_CRITICAL_VETO")
        _all_false(
            observation.get("data_handling"),
            {"raw_prompt_stored", "source_content_stored", "pii_stored", "secret_stored"},
            "DATA_HANDLING_INVALID",
        )
        reports.append((path, observation))
    return reports


def _validate_audit(
    root: Path,
    receipt: dict[str, Any],
    decision: dict[str, Any],
    now: datetime,
    schemas: dict[str, dict[str, Any]],
) -> tuple[int, list[datetime]]:
    run_id = receipt["run_id"]
    _require(
        receipt.get("audit_path") == f"{REVIEW_AREA}/{run_id}/audit.json"
        and receipt.get("audit_event_count") == 14,
        "AUDIT_PATH_INVALID",
    )
    project_directory = _review_project_directory(root)
    writer = _records_module()
    try:
        path, record = writer["read_review_run_file"](
            project_directory.name, run_id, "audit", location=_record_location()
        )
    except Exception:
        _deny("AUDIT_CHAIN_MISMATCH")
    body = record.get("body")
    events = body.get("events") if isinstance(body, dict) else None
    _require(isinstance(events, list), "AUDIT_FORMAT_INVALID")
    raw = "".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for event in events
    ).encode("utf-8")
    times = validate_audit_bytes(raw, receipt, decision, now, schemas)
    return cast(Path, path).stat().st_mtime_ns, times


def validate_audit_bytes(
    raw: bytes,
    receipt: dict[str, Any],
    decision: dict[str, Any],
    now: datetime,
    schemas: dict[str, dict[str, Any]],
) -> list[datetime]:
    """Verify the complete 14-event audit chain of one finalized review run."""
    _require(raw.endswith(b"\n"), "AUDIT_FORMAT_INVALID")
    parts = raw.split(b"\n")
    _require(parts[-1] == b"", "AUDIT_FORMAT_INVALID")
    lines = parts[:-1]
    _require(len(lines) == 14 and all(lines), "AUDIT_FORMAT_INVALID")
    events: list[dict[str, Any]] = []
    for line in lines:
        event = _strict_json_loads(line, "AUDIT_FORMAT_INVALID")
        exact_event = _exact_keys(event, AUDIT_KEYS, "AUDIT_SCHEMA_INVALID")
        _require(line + b"\n" == _canonical_bytes(exact_event), "AUDIT_FORMAT_INVALID")
        _validate_against_schema(
            exact_event,
            "agentic-governed-review-audit-event.schema.json",
            schemas,
        )
        events.append(exact_event)
    previous = receipt["receipt_sha256"]
    observed_times: list[datetime] = []
    # Reports retain canonical catalog order; audit records observed completion order.
    results_by_agent = {result["agent_id"]: result for result in receipt["agent_results"]}
    observed_agents: set[str] = set()
    for position, event in enumerate(events):
        expected_event = (
            "review_started"
            if position == 0
            else "review_completed"
            if position == 13
            else "agent_completed"
        )
        _require(
            event.get("event") == expected_event and event.get("chain_position") == position,
            "AUDIT_ORDER_INVALID",
        )
        envelope = receipt["decision_evidence"]["audit_replay"]["prompt_binding"]["envelope"]
        _require(
            event.get("client_id") == receipt["execution"]["client"]["id"]
            and event.get("prompt_session_id") == receipt["execution"]["session_id"]
            and event.get("prompt_turn_id") == envelope["source_prompt_turn_id"],
            "AUDIT_CORRELATION_MISMATCH",
        )
        for field in ("receipt_id", "project_id", "run_id", "trace_id"):
            _require(event.get(field) == receipt.get(field), "AUDIT_CORRELATION_MISMATCH")
        _require(
            event.get("snapshot_sha256") == receipt["snapshot"]["snapshot_sha256"],
            "AUDIT_CORRELATION_MISMATCH",
        )
        _require(
            event.get("agentic_evaluator") == receipt.get("agentic_evaluator"),
            "AUDIT_CORRELATION_MISMATCH",
        )
        _require(
            event.get("decision_evidence_sha256")
            == receipt["decision_evidence"]["evidence_sha256"],
            "AUDIT_CORRELATION_MISMATCH",
        )
        _require(
            event.get("receipt_sha256") == receipt["receipt_sha256"], "AUDIT_CORRELATION_MISMATCH"
        )
        _require(event.get("previous_event_sha256") == previous, "AUDIT_CHAIN_MISMATCH")
        _require(
            event.get("event_sha256") == _canonical_sha256(event, excluding="event_sha256"),
            "AUDIT_CHAIN_MISMATCH",
        )
        previous = event["event_sha256"]
        _all_false(
            event.get("data_handling"),
            {"raw_prompt_stored", "source_content_stored", "pii_stored", "secret_stored"},
            "DATA_HANDLING_INVALID",
        )
        event_time = _observed_time(event.get("observed_at"), now)
        observed_times.append(event_time)
        if 0 < position < 13:
            agent_id = event.get("agent_id")
            if not isinstance(agent_id, str):
                _deny("AUDIT_AGENT_MISMATCH")
            _require(
                agent_id in results_by_agent and agent_id not in observed_agents,
                "AUDIT_AGENT_MISMATCH",
            )
            result = results_by_agent[agent_id]
            observed_agents.add(agent_id)
            for field in ("agent_id", "invocation_id", "span_id", "status"):
                _require(event.get(field) == result.get(field), "AUDIT_AGENT_MISMATCH")
            _require(
                event.get("report_sha256") == result.get("report_sha256"), "AUDIT_AGENT_MISMATCH"
            )
        elif position == 13:
            _require(event.get("decision") == "PASS", "AUDIT_DECISION_MISMATCH")
            _require(
                event.get("decision_sha256") == receipt["decision_sha256"],
                "AUDIT_DECISION_MISMATCH",
            )
            _require(event.get("span_id") == decision.get("span_id"), "AUDIT_DECISION_MISMATCH")
    _require(observed_agents == set(AGENTS), "AUDIT_AGENT_MISMATCH")
    _require(observed_times == sorted(observed_times), "TIMESTAMP_ORDER_INVALID")
    return observed_times


def _published_receipt(root: Path, executable: str) -> tuple[Path, bytes, dict[str, Any]]:
    """The newest finalized review published for exactly the staged snapshot."""
    snapshot = _capture_snapshot(root, executable)
    project_directory = _review_project_directory(root)
    writer = _records_module()
    try:
        marks = writer["published_reviews"](
            project_directory.name, snapshot["snapshot_sha256"], location=_record_location()
        )
    except Exception:
        _deny("SHARED_ROOT_UNAVAILABLE")
    _require(bool(marks), "ARTIFACT_UNREADABLE")
    mark_path, mark = marks[0]
    run_id = mark["body"]["run_id"]
    _require(
        isinstance(run_id, str) and re.fullmatch(r"run-[A-Za-z0-9._-]{4,120}", run_id) is not None,
        "CURRENT_RECEIPT_PUBLICATION_MISMATCH",
    )
    _, raw = _regular_file(root, f"{REVIEW_AREA}/{run_id}/receipt.json", limit=MAX_JSON_BYTES)
    _require(
        _raw_sha256(raw) == mark["body"].get("receipt_sha256"),
        "CURRENT_RECEIPT_PUBLICATION_MISMATCH",
    )
    payload = _strict_json_loads(raw, "ARTIFACT_JSON_INVALID")
    return mark_path, raw, _exact_keys(payload, RECEIPT_KEYS, "ARTIFACT_SCHEMA_INVALID")


def _event_model(event: dict[str, Any], client: str) -> dict[str, Any]:
    """The model the client reports for this commit attempt, read like the prompt hook reads it."""
    path = Path(__file__).resolve().with_name("llm_call_events.py")
    _require(path.is_file() and not path.is_symlink(), "EVENT_MODEL_INVALID")
    try:
        model = runpy.run_path(str(path))["observed_model"](event, client)
    except Exception:
        _deny("EVENT_MODEL_INVALID")
    _require(isinstance(model, dict), "EVENT_MODEL_INVALID")
    return cast(dict[str, Any], model)


def _validate(
    root: Path,
    client: str,
    event: dict[str, Any],
    now: datetime,
    executable: str,
) -> None:
    session, event_version = _event_identity(event, client, root, executable)
    event_model = _event_model(event, client)
    current_path, current_raw, receipt = _published_receipt(root, executable)
    validate_review_run(
        root,
        client,
        current_raw,
        receipt,
        now,
        executable,
        session=session,
        event_version=event_version,
        event_model=event_model,
        current_path=current_path,
    )


def validate_review_run(
    root: Path,
    client: str,
    receipt_raw: bytes,
    receipt: dict[str, Any],
    now: datetime,
    executable: str,
    *,
    session: str | None = None,
    event_version: str | None = None,
    event_model: dict[str, Any] | None = None,
    current_path: Path | None = None,
    audit_raw: bytes | None = None,
) -> None:
    """Check one review run as the commit hook does.

    The hook passes the published receipt and its publication mark and reads the stored audit.
    The finalizer passes the run receipt and the audit it is about to write, so a run that the
    hook would reject is never published.
    """
    _require(receipt_raw == _canonical_bytes(receipt), "RECEIPT_FORMAT_INVALID")
    schemas = _schema_registry(root)
    _validate_against_schema(
        receipt,
        "agentic-governed-review-receipt.schema.json",
        schemas,
    )
    _require(receipt.get("schema_version") == "1.0", "RECEIPT_INVALID")
    _require(receipt.get("kind") == "AgenticGovernedReviewReceipt", "RECEIPT_INVALID")
    _require(receipt.get("evidence_profile") == "phase1-agentic-advisory", "RECEIPT_INVALID")
    if receipt.get("decision") != "PASS":
        raise GuardError("RECEIPT_NOT_PASS", _non_pass_diagnostic(receipt, root=root))
    _require(receipt.get("same_snapshot_retry_only") is True, "RECEIPT_INVALID")
    _require(
        receipt.get("reuse_identity_canonicalization") == "kt-agentic-review-reuse-json-v3",
        "RECEIPT_INVALID",
    )
    _require(
        receipt.get("receipt_canonicalization") == "kt-agentic-governed-review-receipt-json-v1",
        "RECEIPT_INVALID",
    )
    _all_false(
        receipt.get("claim_boundary"),
        {
            "deterministic_decision",
            "canonical_conformance",
            "runtime_admission",
            "production_decision",
            "immutable_audit",
        },
        "CLAIM_BOUNDARY_INVALID",
    )
    _all_false(
        receipt.get("data_handling"),
        {"raw_prompt_stored", "source_content_stored", "pii_stored", "secret_stored"},
        "DATA_HANDLING_INVALID",
    )
    _validate_native_surface(receipt, client)

    run_root = f"{REVIEW_AREA}/{receipt.get('run_id')}"
    run_receipt_path, run_receipt_raw = _regular_file(
        root, f"{run_root}/receipt.json", limit=MAX_JSON_BYTES
    )
    _require(run_receipt_raw == receipt_raw, "CURRENT_RECEIPT_PUBLICATION_MISMATCH")
    _require(
        receipt.get("receipt_sha256") == _canonical_sha256(receipt, excluding="receipt_sha256"),
        "RECEIPT_DIGEST_MISMATCH",
    )
    _require(
        receipt.get("reuse_identity_sha256") == _canonical_sha256(_reuse_identity(receipt)),
        "REUSE_IDENTITY_MISMATCH",
    )

    execution = receipt.get("execution")
    _require(isinstance(execution, dict), "CLIENT_BINDING_MISMATCH")
    client_binding = execution.get("client")
    _require(isinstance(client_binding, dict), "CLIENT_BINDING_MISMATCH")
    expected_client_source = (
        "native-event-observed" if client == "cursor" else "agent-self-observed"
    )
    _require(
        client_binding.get("source") == expected_client_source
        and client_binding.get("id") == client,
        "CLIENT_BINDING_MISMATCH",
    )
    _require(
        isinstance(client_binding.get("version"), str) and client_binding.get("version"),
        "CLIENT_BINDING_MISMATCH",
    )
    _require(
        client_binding.get("sha256")
        == _canonical_sha256({"id": client, "version": client_binding["version"]}),
        "CLIENT_BINDING_MISMATCH",
    )
    if session is not None:
        _require(execution.get("session_id") == session, "SESSION_BINDING_MISMATCH")
    if event_version is not None:
        _require(client_binding.get("version") == event_version, "CLIENT_VERSION_MISMATCH")
    reviewed_model = execution.get("model")
    if (
        event_model is not None
        and event_model.get("id") is not None
        and isinstance(reviewed_model, dict)
        and reviewed_model.get("id") is not None
    ):
        # A review holds only for the model that ran it; a switched model needs a new review.
        _require(reviewed_model.get("id") == event_model["id"], "MODEL_CHANGED_SINCE_REVIEW")

    snapshot = _capture_snapshot(root, executable)
    _validate_snapshot_binding(receipt.get("snapshot"), snapshot)
    _validate_project_bindings(root, receipt, client)

    harness = receipt.get("mandatory_governed_execution")
    _require(isinstance(harness, dict), "HARNESS_BINDING_INVALID")
    _require(
        harness.get("protocol_id") == "protocol:mandatory-governed-execution-phase1",
        "HARNESS_BINDING_INVALID",
    )
    _require(harness.get("version") == "1.3.0", "HARNESS_BINDING_INVALID")
    _require(
        harness.get("canonicalization") == "kt-mandatory-governed-execution-json-v1",
        "HARNESS_BINDING_INVALID",
    )
    _require(
        harness.get("mandatory") is True
        and harness.get("missing_or_stale_result") == "BLOCKED_INCOMPLETE",
        "HARNESS_BINDING_INVALID",
    )
    _require(tuple(harness.get("stage_order", ())) == STAGE_ORDER, "HARNESS_BINDING_INVALID")
    _require(
        harness["rule"].get("ref") == "rules/13-tamamlanma-tanimi.md", "HARNESS_BINDING_INVALID"
    )
    _require(harness["skill"].get("ref") == CLIENT_SKILLS[client], "HARNESS_BINDING_INVALID")
    _require(
        harness["rule"].get("version_source") == "project-manifest.blueprint_version"
        and harness["skill"].get("version_source") == "project-manifest.blueprint_version",
        "HARNESS_BINDING_INVALID",
    )
    harness_payload = copy.deepcopy(harness)
    harness_payload.pop("sha256", None)
    _require(harness.get("sha256") == _canonical_sha256(harness_payload), "HARNESS_DIGEST_MISMATCH")

    reports = _validate_reports(root, receipt, schemas)
    # The criteria binding and its lifecycle must still be the staged PRD's own.
    criteria = receipt.get("acceptance_criteria")
    _require(isinstance(criteria, dict), "ACCEPTANCE_CRITERIA_MISMATCH")
    _require(
        acceptance_criteria(root, str(criteria.get("path")), executable) == criteria,
        "ACCEPTANCE_CRITERIA_MISMATCH",
    )
    decision_relative = f"{run_root}/decision.json"
    _require(receipt.get("decision_path") == decision_relative, "DECISION_PATH_INVALID")
    decision_path, decision_raw, decision = _json_file(
        root, decision_relative, expected_keys=DECISION_KEYS
    )
    _require(decision_raw == _canonical_bytes(decision), "DECISION_FORMAT_INVALID")
    _validate_against_schema(
        decision,
        "agentic-governed-review-decision.schema.json",
        schemas,
    )
    _require(
        receipt.get("decision_sha256") == _raw_sha256(decision_raw), "DECISION_DIGEST_MISMATCH"
    )
    for field in (
        "receipt_id",
        "project_id",
        "run_id",
        "trace_id",
        "acceptance_criteria",
        "decision",
        "reason_codes",
        "weighted_risk_score_basis_points",
        "compliance_score_basis_points",
    ):
        _require(decision.get(field) == receipt.get(field), "DECISION_CORRELATION_MISMATCH")
    _require(
        decision.get("snapshot_sha256") == snapshot["snapshot_sha256"],
        "DECISION_CORRELATION_MISMATCH",
    )
    _require(
        decision.get("aggregation_policy")
        == {
            key: receipt["aggregation_policy"][key]
            for key in ("ref", "version", "sha256", "instructions_ref", "instructions_sha256")
        },
        "DECISION_CORRELATION_MISMATCH",
    )
    _require(
        decision.get("agentic_evaluator") == receipt.get("agentic_evaluator"),
        "DECISION_CORRELATION_MISMATCH",
    )
    _require(
        decision.get("agent_statuses") == dict.fromkeys(AGENTS, "ok"),
        "DECISION_CORRELATION_MISMATCH",
    )
    started, primary_completed, second_completed = _validate_evidence(
        root, receipt, decision, schemas
    )
    # The scan runs again on the staged tree; the record, every report's candidate list and
    # responses, and the decision evidence's code findings must all match it.
    observations = [observation for _, observation in reports]
    record, record_sha256 = _validate_scan_record(root, receipt, snapshot, schemas, executable)
    for observation in observations:
        candidates = observation.get("deterministic_candidates")
        _require(
            candidates == deterministic_candidates(record, observation["agent_id"]),
            "CANDIDATE_BINDING_MISMATCH",
        )
        _require(
            candidate_response_problem(
                candidates, observation.get("candidate_responses"), observation.get("status")
            )
            is None,
            "CANDIDATE_RESPONSES_INVALID",
        )
    code_findings, dismissed = deterministic_scan_findings(record, observations)
    _require(
        receipt["decision_evidence"].get("deterministic_scan")
        == deterministic_scan_evidence(receipt["run_id"], record_sha256, code_findings, dismissed),
        "DECISION_EVIDENCE_SCAN_MISMATCH",
    )
    _, aggregation_raw = _regular_file(root, AGGREGATION_POLICY_PATH, limit=MAX_JSON_BYTES)
    recalculated = recalculate_policy_outcome(
        receipt, observations, severity_scores(aggregation_raw), code_findings
    )
    primary = receipt["decision_evidence"]["audit_replay"]["primary_evaluation"]
    for field, value in recalculated.items():
        _require(primary.get(field) == value, "POLICY_RECALCULATION_MISMATCH")
    receipt_created = _parse_time(receipt.get("created_at"), "TIMESTAMP_INVALID")
    now_utc = now.astimezone(UTC)
    _require(
        started <= primary_completed <= second_completed <= receipt_created <= now_utc,
        "TIMESTAMP_ORDER_INVALID",
    )

    audit_stored_at_ns: int | None = None
    if audit_raw is None:
        audit_stored_at_ns, audit_times = _validate_audit(
            root,
            receipt,
            decision,
            now_utc,
            schemas,
        )
    else:
        _require(
            receipt.get("audit_path") == f"{REVIEW_AREA}/{receipt['run_id']}/audit.json"
            and receipt.get("audit_event_count") == 14,
            "AUDIT_PATH_INVALID",
        )
        audit_times = validate_audit_bytes(audit_raw, receipt, decision, now_utc, schemas)
    _require(
        len(audit_times) == 14
        and audit_times[0] <= audit_times[12] <= started
        and receipt_created <= audit_times[13] <= now_utc,
        "TIMESTAMP_ORDER_INVALID",
    )
    latest_report = max(path.stat().st_mtime_ns for path, _ in reports)
    _require(
        latest_report <= decision_path.stat().st_mtime_ns, "ARTIFACT_PUBLICATION_ORDER_INVALID"
    )
    _require(
        decision_path.stat().st_mtime_ns <= run_receipt_path.stat().st_mtime_ns,
        "ARTIFACT_PUBLICATION_ORDER_INVALID",
    )
    if audit_stored_at_ns is not None:
        _require(
            run_receipt_path.stat().st_mtime_ns <= audit_stored_at_ns,
            "ARTIFACT_PUBLICATION_ORDER_INVALID",
        )
        _require(
            current_path is not None and audit_stored_at_ns <= current_path.stat().st_mtime_ns,
            "ARTIFACT_PUBLICATION_ORDER_INVALID",
        )
    # Whole-second UTC observations cannot attest a receipt rewritten in a later second.
    # Same-second filesystem precision differences remain valid.
    receipt_publication_second = datetime.fromtimestamp(
        run_receipt_path.stat().st_mtime_ns // 1_000_000_000, UTC
    )
    _require(
        receipt_publication_second <= audit_times[13],
        "AUDIT_COMPLETION_PRECEDES_RECEIPT_PUBLICATION",
    )


def _managed_preferences() -> Any:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


def _device_refusal(hook: str, client: str) -> str | None:
    """The fixed refusal when this device is stopped; read locally before any other check."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "governance_records.py")
    try:
        records = runpy.run_path(path)
        decision, _ = records["device_gate"](
            location=_record_location(), managed_preferences=_managed_preferences()
        )
    except Exception:
        return None
    if decision not in {"stop", "unverified"}:
        return None
    records["record_refusal"](hook, decision, client=client, location=_record_location())
    return str(records["gate_message"](decision, marker=True))


def _allow_payload(client: str) -> dict[str, str]:
    return {"permission": "allow"} if client == "cursor" else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, choices=CLIENTS)
    parser.add_argument("--self-check", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.self_check:
        print(
            json.dumps(
                {
                    "agent_invocation": False,
                    "blocking": True,
                    "enforcement_claim": "conditional-native-guard",
                    "native_exit_2_deny": True,
                    "ok": True,
                    "receipt_validation": True,
                    "semantic_decision": False,
                },
                sort_keys=True,
            )
        )
        return 0
    refusal = _device_refusal("command", arguments.client)
    if refusal is not None:
        with contextlib.suppress(OSError):
            sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        print(refusal, file=sys.stderr)
        return 2
    try:
        event = _event()
        if arguments.client == "github-copilot-vscode":
            tool_name = event.get("tool_name")
            _require(isinstance(tool_name, str), "HOOK_TOOL_NAME_INVALID")
            if tool_name != "run_in_terminal":
                print(json.dumps(_allow_payload(arguments.client), sort_keys=True))
                return 0
        command = _command(event)
        _require(command is not None, "HOOK_COMMAND_INVALID")
        classification = _classify_command(command)
        if classification == "outside":
            print(json.dumps(_allow_payload(arguments.client), sort_keys=True))
            return 0
        notice = _initial_scaffold_commit(cast(str, command), event, arguments.client)
        if notice is not None:
            # No receipt is created or implied; the exception is named on its own line.
            print(notice, file=sys.stderr)
            print(json.dumps(_allow_payload(arguments.client), sort_keys=True))
            return 0
        _require(classification == "direct", "UNSAFE_DIRECT_COMMIT_SHAPE")
        _validate(
            _project_root(),
            arguments.client,
            event,
            datetime.now(UTC),
            _direct_git_executable(command),
        )
    except GuardError as error:
        guidance = (
            error.diagnostic or "run governed-review for the exact staged snapshot and retry."
        )
        print(
            f"{DENIAL_MARKER}: BLOCKED_INCOMPLETE ({error.code}); {guidance}",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            f"{DENIAL_MARKER}: BLOCKED_INCOMPLETE (VALIDATION_FAILURE); "
            "run governed-review for the exact staged snapshot and retry.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(_allow_payload(arguments.client), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
