#!/usr/bin/env python3
"""Yerel üreteç kurulumu olmadan üretilen ajan-istemci izdüşümlerini doğrula."""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules"
LOCK = RULES / "GENERATED.lock"
AGENT_PLATFORM = ROOT / "agent-platform"
PROJECTION_ROOT = ROOT / ".kt-scaffold" / "agent-projections"
PROJECTION_LOCK = PROJECTION_ROOT / "PROJECTIONS.lock.json"
SCAFFOLD_MANIFEST = ROOT / ".kt-scaffold" / "manifest.json"
PROMPT_INGRESS_ASSETS = {
    ".kt-scaffold/hooks/prompt_ingress_guard.py",
    "agent-platform/prompt-ingress-metadata.schema.json",
    "agent-platform/llm-call-event.schema.json",
    ".kt-scaffold/hooks/governance_client.py",
    ".kt-scaffold/hooks/governance_records.py",
    ".kt-scaffold/hooks/governance_identity.py",
    ".kt-scaffold/hooks/python_environment.py",
    ".kt-scaffold/hooks/llm_call_events.py",
    ".kt-scaffold/hooks/llm_call_audit_hook.py",
    "agent-platform/policies/prompt-ingress/prompt-ingress-policy.json",
    "agent-platform/policies/local-state/local-governance-state-policy.json",
    "agent-platform/local-governance-state-policy.schema.json",
    "agent-platform/prompt-ingress-policy.schema.json",
    "agent-platform/prompt-ingress-receipt.schema.json",
}
LOCAL_GOVERNANCE_GUARD_ASSETS = {
    ".github/workflows/governance-drift.yml",
    ".kt-scaffold/hooks/agentic_review_receipt_guard.py",
    ".kt-scaffold/hooks/authority_sync.py",
    ".kt-scaffold/hooks/codex_hook_trust.py",
    ".kt-scaffold/hooks/governance_forwarder.py",
    ".kt-scaffold/hooks/commit_governance_guard.py",
    ".kt-scaffold/hooks/initial_scaffold_commit.py",
    ".kt-scaffold/hooks/governance_drift_feedback.py",
    ".kt-scaffold/hooks/git/pre-commit",
    ".kt-scaffold/hooks/governance_surface_guard.py",
    ".pre-commit-config.yaml",
    "scripts/git-gate.sh",
    "agent-platform/agentic-governance-observation.schema.json",
    "agent-platform/agentic-governed-review-audit-event.schema.json",
    "agent-platform/agentic-governed-review-decision-evidence.schema.json",
    "agent-platform/agentic-governed-review-decision.schema.json",
    "agent-platform/agentic-governed-review-deterministic-scan.schema.json",
    "agent-platform/agentic-governed-review-evaluator-policy.schema.json",
    "agent-platform/agentic-governed-review-receipt.schema.json",
    "agent-platform/policies/aggregation/governed-review-agentic-evaluation.yml",
}
UNTRUSTED_CONTENT_ASSETS = {
    "agent-platform/evals/indirect-injection-v1.json",
    "agent-platform/indirect-injection-eval.schema.json",
    "agent-platform/untrusted-content-envelope.schema.json",
}
# A file planted under one of these directories by a shell command, bypassing the native
# file tools, is drift even when every recorded managed file still matches its digest.
GOVERNED_DIRECTORIES = (
    ".agents",
    ".claude/agents",
    ".claude/commands",
    ".claude/rules",
    ".claude/skills",
    ".codex",
    ".cursor",
    ".github/agents",
    ".github/hooks",
    ".github/instructions",
    ".github/skills",
    ".kt-scaffold/agent-activation",
    ".kt-scaffold/agent-projections",
    ".kt-scaffold/hooks",
    "agent-evals",
    "agent-platform",
    "rules",
)
ACTIVATION_STATE_ROOT = Path(".kt-scaffold/agent-activation")
EXPECTED_RENDERER_VERSION = "0.4.0"
RESTORE_COMMAND = "python3 .kt-scaffold/hooks/governance_client.py restore"
GOVERNANCE_RECORDS = ROOT / ".kt-scaffold" / "hooks" / "governance_records.py"
# A local client override stops the commit gate with its own exit code and its own guidance.
LOCAL_OVERRIDE_EXIT = 3
# The project's CI passes this flag: there a committed override stops on any device.  Only the
# flag selects it, so no environment variable can relax the managed-device decision.
CI_FLAG = "--ci"
AGENT_IDS = {
    "acik-kaynak-lisansi",
    "bilgi-guvenligi",
    "devops",
    "dokumantasyon",
    "gereksinim-kapsami",
    "gizlilik-kvkk",
    "gozlemlenebilirlik",
    "kod-inceleme",
    "kod-kalitesi",
    "kurumsal-mimari",
    "otomatik-duzeltme",
    "test-otomasyonu",
    "uygulama-guvenligi",
    "yuk-testi",
}
CLIENT_PATHS = {
    "claude-code": ".claude/agents/{agent_id}.md",
    "codex": ".codex/agents/{agent_id}.toml",
    "cursor": ".cursor/agents/{agent_id}.md",
    "github-copilot-vscode": ".github/agents/{agent_id}.agent.md",
}
LOCAL_DISCOVERY_ROOTS = {
    Path(pattern.format(agent_id="placeholder")).parent for pattern in CLIENT_PATHS.values()
}
COMMAND_SKILL_NAMES = {
    "kt-baslat",
    "kt-guncelle",
    "kt-kurallar",
    "kt-kural",
    "kt-yansit",
    "kt-spesifikasyon",
    "kt-alan",
    "kt-sayfa",
    "kt-sema",
    "kt-kalite-kapisi",
    "kt-senaryo",
    "kt-tamamla",
}
# Skills of commands that exist only in the separated-web layout.
WEB_ONLY_SKILL_NAMES = {"kt-alan", "kt-sayfa", "kt-sema", "kt-senaryo"}
REPORT_SKILL_NAME = "kt-test-kosumu-raporu"
GOVERNED_REVIEW_SKILL_NAME = "governed-review"


def digest_corpus() -> str:
    digest = hashlib.sha256()
    # Order by the name's code points; Path ordering ignores case on Windows.
    for path in sorted(RULES.glob("*"), key=lambda item: item.name):
        if path.is_file() and path.name != "GENERATED.lock":
            digest.update(path.name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def drifted(problem: str, relative: str) -> NoReturn:
    """Stop on a managed file whose bytes differ from its record and name the restoring command."""

    raise SystemExit(
        f"{problem}: {relative}\n"
        f"Kaydedilmiş doğru hâline geri almak için: {RESTORE_COMMAND} {relative} "
        "(Windows'ta python3 yerine .venv\\Scripts\\python.exe)"
    )


def safe_relative(value: object, label: str) -> Path:
    if not isinstance(value, str):
        raise SystemExit(f"{label} yol değeri metin değildir")
    path = Path(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise SystemExit(f"güvenli olmayan {label} yol değeri: {value}")
    return path


def safe_project_path(relative: Path, label: str) -> Path:
    current = ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SystemExit(f"{label} yolunda sembolik bağlantı var: {relative}")
    try:
        current.resolve(strict=False).relative_to(ROOT.resolve(strict=True))
    except ValueError as exc:
        raise SystemExit(f"{label} proje kökü dışına çıkıyor: {relative}") from exc
    return current


def scaffold_managed_digests() -> dict[str, str]:
    manifest = safe_project_path(SCAFFOLD_MANIFEST.relative_to(ROOT), "scaffold manifesti")
    if not manifest.is_file():
        raise SystemExit("scaffold ownership manifesti eksik veya güvenli değil")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("generator_version") != EXPECTED_RENDERER_VERSION
    ):
        raise SystemExit(
            "scaffold ownership manifestinin generator_version değeri doğrulayıcıyla eşleşmiyor"
        )
    managed = payload.get("managed") if isinstance(payload, dict) else None
    if not isinstance(managed, dict) or any(
        not isinstance(path, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for path, digest in managed.items()
    ):
        raise SystemExit("scaffold ownership manifesti bozuk")
    return managed


def scaffold_seed_paths() -> set[str]:
    """Application-seed paths the generator records; these are project-owned, not drift."""
    manifest = safe_project_path(SCAFFOLD_MANIFEST.relative_to(ROOT), "scaffold manifesti")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    seed = payload.get("application_seed") if isinstance(payload, dict) else None
    return set(seed) if isinstance(seed, dict) else set()


def drifted_unmanaged_extra(relative: str) -> NoReturn:
    """Stop on a file added under a governed directory that the generator does not own."""

    raise SystemExit(
        f"yönetişim yüzeyine eklenen beklenmeyen dosya: {relative}\n"
        "Bu dosya üreticinin yönettiği bir dosya değil; yönetişim yüzeyine kabuk komutuyla "
        "eklenmiş olabilir. Dosyayı kaldır (silmek için dosya aracını kullanma, kabuktan sil) "
        "ya da projeyi fabrika güncellemesiyle yeniden üret: asistanın proje fabrikası "
        "bağlantısındaki (MCP) proje_iskelesini_esitle aracı veya kt-iskelet guncelle komutu. "
        "Kontrolü silerek bulgu kapatılmaz."
    )


def verify_no_unmanaged_governed_files() -> None:
    """Flag any extra file a shell added under a governed directory as drift.

    The managed-file checks only compare files the generator recorded, so a file planted
    beside them — a fake skill, an override policy, a bypass hook — would otherwise pass
    unseen.  Every regular file under a governed directory must be a generator-managed path
    or a recorded application-seed path; a symlink or special file there is never expected.
    """
    managed = scaffold_managed_digests()
    seed = scaffold_seed_paths()
    for relative_root in GOVERNED_DIRECTORIES:
        root_path = ROOT / relative_root
        if not root_path.exists():
            continue
        if root_path.is_symlink() or not root_path.is_dir():
            drifted("yönetilen dizin beklenen biçimde değil", relative_root)
        for path in sorted(root_path.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            if path.is_symlink():
                drifted("yönetilen dizinde beklenmeyen sembolik bağlantı var", relative)
            if path.is_dir():
                continue
            if not path.is_file():
                drifted("yönetilen dizinde beklenmeyen özel dosya var", relative)
            if relative not in managed and relative not in seed:
                drifted_unmanaged_extra(relative)


def _managed_preferences() -> Path | None:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


def verify_local_client_overrides(*, ci: bool) -> int:
    """Stop on a managed device or in CI, and warn elsewhere, on a local client governance bypass.

    A client-local settings or instruction file is not a generator-managed file, so the digest
    checks above never see it; it can still switch the project's hooks off or add rules.  The
    detection and the managed-device test are the shared governance runtime's, whose bytes the
    prompt-ingress asset check has already matched against the manifest.  CI mode only adds a
    stop: a managed device stops either way.
    """
    records = runpy.run_path(str(GOVERNANCE_RECORDS))
    findings = records["local_client_overrides"](ROOT)
    if not findings:
        return 0
    blocking = bool(records["managed_device"](_managed_preferences())) or ci
    print(
        records["local_override_message"](findings, blocking=blocking, ci=ci), file=sys.stderr
    )
    return LOCAL_OVERRIDE_EXIT if blocking else 0


def ci_mode(arguments: list[str]) -> bool:
    """Read the only accepted argument; anything else is a usage error, never a silent default."""
    if not arguments:
        return False
    if arguments == [CI_FLAG]:
        return True
    raise SystemExit(f"kullanım: check-governance-drift.py [{CI_FLAG}]")


def application_mode() -> str:
    answers = ROOT / ".kt-scaffold" / "answers.yml"
    for line in answers.read_text(encoding="utf-8").splitlines():
        if line.startswith("application_mode:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return "separated-web"


def mode_skill_names() -> set[str]:
    if application_mode() == "separated-web":
        return set(COMMAND_SKILL_NAMES)
    return COMMAND_SKILL_NAMES - WEB_ONLY_SKILL_NAMES


def expected_governance_files(selected_clients: set[str]) -> set[str]:
    expected = {"AGENTS.md", ".specify/memory/constitution.md"}
    if "claude-code" in selected_clients:
        expected.update(
            {
                "CLAUDE.md",
                ".claude/settings.json",
                f".claude/skills/{REPORT_SKILL_NAME}/SKILL.md",
                f".claude/skills/{GOVERNED_REVIEW_SKILL_NAME}/SKILL.md",
            }
        )
        for skill_name in mode_skill_names():
            expected.add(f".claude/skills/{skill_name}/SKILL.md")
    if "codex" in selected_clients:
        expected.update(
            {
                ".codex/config.toml",
                ".codex/hooks.json",
                f".agents/skills/{REPORT_SKILL_NAME}/SKILL.md",
                f".agents/skills/{GOVERNED_REVIEW_SKILL_NAME}/SKILL.md",
            }
        )
        for skill_name in mode_skill_names():
            expected.add(f".agents/skills/{skill_name}/SKILL.md")
    if "cursor" in selected_clients:
        expected.update(
            {
                ".cursor/hooks.json",
                f".cursor/skills/{GOVERNED_REVIEW_SKILL_NAME}/SKILL.md",
            }
        )
    if "github-copilot-vscode" in selected_clients:
        expected.update(
            {
                ".github/hooks/kt-prompt-ingress.json",
                ".github/hooks/kt-call-audit.json",
                ".github/hooks/kt-commit-governance.json",
                f".github/skills/{GOVERNED_REVIEW_SKILL_NAME}/SKILL.md",
            }
        )
    for rule in sorted(RULES.glob("*.md")):
        content = rule.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            continue
        header = content.split("---", 2)[1]
        fields = {}
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
        if fields.get("trigger") == "path-match":
            rule_id = fields.get("id")
            if not rule_id:
                raise SystemExit(f"path-match kural kimliği eksik: {rule.name}")
            if "claude-code" in selected_clients:
                expected.add(f".claude/rules/{rule_id}.md")
            if "cursor" in selected_clients:
                expected.add(f".cursor/rules/{rule_id}.mdc")
            if "github-copilot-vscode" in selected_clients:
                expected.add(f".github/instructions/{rule_id}.instructions.md")
            # Only the web layout gets Rule 58's Codex directory-scoped copies.
            if (
                rule_id == "58-kimlik-dogrulama-ve-yetkilendirme"
                and "codex" in selected_clients
                and application_mode() == "separated-web"
            ):
                expected.update({"app/backend/AGENTS.md", "app/frontend/AGENTS.md", "helm/AGENTS.md"})
    return expected


def verify_prompt_ingress_assets() -> None:
    managed = scaffold_managed_digests()
    for relative in sorted(PROMPT_INGRESS_ASSETS):
        destination = safe_project_path(Path(relative), "prompt giriş koruması varlığı")
        if not destination.is_file():
            drifted("prompt giriş koruması varlığı eksik veya güvenli değil", relative)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if managed.get(relative) != actual:
            drifted("prompt giriş koruması varlığı scaffold özetiyle eşleşmiyor", relative)


def verify_local_governance_guard_assets() -> None:
    managed = scaffold_managed_digests()
    for relative in sorted(LOCAL_GOVERNANCE_GUARD_ASSETS):
        destination = safe_project_path(Path(relative), "yerel yönetişim kapısı varlığı")
        if not destination.is_file():
            drifted("yerel yönetişim kapısı varlığı eksik veya güvenli değil", relative)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if managed.get(relative) != actual:
            drifted("yerel yönetişim kapısı varlığı scaffold özetiyle eşleşmiyor", relative)


def verify_untrusted_content_assets() -> None:
    managed = scaffold_managed_digests()
    for relative in sorted(UNTRUSTED_CONTENT_ASSETS):
        destination = safe_project_path(Path(relative), "harici içerik güven sınırı varlığı")
        if not destination.is_file():
            drifted("harici içerik güven sınırı varlığı eksik veya güvenli değil", relative)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if managed.get(relative) != actual:
            drifted("harici içerik güven sınırı varlığı scaffold özetiyle eşleşmiyor", relative)


def verify_agent_projections() -> tuple[int, set[str]]:
    activation_root = safe_project_path(
        ACTIVATION_STATE_ROOT, "yönetilen etkinleştirme durumu kökü"
    )
    if activation_root.exists() and (
        not activation_root.is_dir() or any(activation_root.iterdir())
    ):
        raise SystemExit(
            "yönetilen etkinleştirme durumu yerel danışman projeksiyonu denetimiyle karıştırılamaz"
        )
    managed = scaffold_managed_digests()
    projection_lock = safe_project_path(PROJECTION_LOCK.relative_to(ROOT), "ajan izdüşüm kilidi")
    if not projection_lock.is_file():
        raise SystemExit("ajan izdüşüm kilidi eksik veya güvenli değil")
    payload = json.loads(projection_lock.read_text(encoding="utf-8"))
    if payload.get("kind") != "AgentProjectionLock":
        raise SystemExit("ajan izdüşüm kilidinin kind değeri geçersiz")
    if payload.get("generation_status") != "generated":
        raise SystemExit("ajan izdüşüm kilidi generation_status=generated durumunu kaydetmiyor")
    if payload.get("activation_status") != "not_activated":
        raise SystemExit("ajan izdüşüm kilidi yönetişimli etkinleştirme iddiası taşıyor")
    if payload.get("runtime_conformance") != "not_run":
        raise SystemExit("eylemsiz ajan izdüşüm kilidi çalışma zamanı uygunluğu iddiası taşıyor")
    if payload.get("runtime_admission") != "research":
        raise SystemExit("ajan izdüşüm kilidi runtime admission iddiası taşıyor")

    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise SystemExit("ajan izdüşüm kilidi kanonik girdi envanteri taşımıyor")
    for item in inputs:
        if not isinstance(item, dict):
            raise SystemExit("ajan izdüşüm girdi kaydı bozuk")
        relative = safe_relative(item.get("path"), "agent-platform girdisi")
        source = safe_project_path(
            AGENT_PLATFORM.relative_to(ROOT) / relative,
            "kanonik agent-platform girdisi",
        )
        source_relative = source.relative_to(ROOT).as_posix()
        if not source.is_file():
            drifted("kanonik agent-platform girdisi eksik veya güvenli değil", source_relative)
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != item.get("sha256"):
            drifted("kanonik agent-platform girdisi sapma gösteriyor", source_relative)

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise SystemExit("ajan izdüşüm kilidi varlık envanteri taşımıyor")
    expected_files = {PROJECTION_LOCK.relative_to(PROJECTION_ROOT).as_posix()}
    seen: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    selected_clients: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise SystemExit("ajan izdüşüm varlık kaydı bozuk")
        client_id = item.get("client_id")
        agent_id = item.get("agent_id")
        if client_id not in CLIENT_PATHS or agent_id not in AGENT_IDS:
            raise SystemExit(f"bilinmeyen ajan izdüşüm kimliği: {client_id}/{agent_id}")
        relative = safe_relative(item.get("relative_path"), "ajan izdüşümü")
        normalized = relative.as_posix()
        expected_relative = CLIENT_PATHS[client_id].format(agent_id=agent_id)
        if normalized != expected_relative:
            raise SystemExit(
                f"ajan izdüşüm yolu kanonik istemci/ajan kimliğiyle eşleşmiyor: {normalized}"
            )
        if normalized in seen:
            raise SystemExit(f"yinelenen ajan izdüşüm yolu: {normalized}")
        seen.add(normalized)
        pair = (client_id, agent_id)
        if pair in seen_pairs:
            raise SystemExit(f"yinelenen ajan izdüşüm kimliği: {client_id}/{agent_id}")
        seen_pairs.add(pair)
        selected_clients.add(client_id)
        expected_files.add(normalized)
        if item.get("runtime_conformance") != "not_run":
            raise SystemExit(
                f"ajan izdüşümü çalışma zamanı uygunluğu iddiası taşıyor: {normalized}"
            )
        if item.get("runtime_admission") != "research":
            raise SystemExit(f"ajan izdüşümü runtime admission iddiası taşıyor: {normalized}")
        destination = safe_project_path(
            PROJECTION_ROOT.relative_to(ROOT) / relative,
            "eylemsiz ajan izdüşümü",
        )
        inert_relative = destination.relative_to(ROOT).as_posix()
        if not destination.is_file():
            drifted("eylemsiz ajan izdüşümü eksik veya güvenli değil", inert_relative)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual != item.get("sha256"):
            drifted("eylemsiz ajan izdüşümü sapma gösteriyor", inert_relative)
        if managed.get(inert_relative) != actual:
            raise SystemExit(
                f"eylemsiz ajan izdüşümü scaffold tarafından sahiplenilmiyor: {normalized}"
            )
        live_destination = safe_project_path(relative, "yerel ajan keşif dosyası")
        if not live_destination.is_file():
            drifted("yerel ajan keşif dosyası eksik veya güvenli değil", normalized)
        live_actual = hashlib.sha256(live_destination.read_bytes()).hexdigest()
        if live_actual != item.get("sha256"):
            drifted("yerel ajan keşif dosyası sapma gösteriyor", normalized)
        if managed.get(normalized) != live_actual:
            raise SystemExit(
                f"yerel ajan keşif dosyası scaffold tarafından sahiplenilmiyor: {normalized}"
            )

    expected_pairs = {
        (client_id, agent_id) for client_id in selected_clients for agent_id in AGENT_IDS
    }
    if seen_pairs != expected_pairs:
        raise SystemExit(
            "ajan izdüşüm kilidi seçili istemciler için eksik kimlik envanteri taşıyor"
        )

    projection_root = safe_project_path(PROJECTION_ROOT.relative_to(ROOT), "eylemsiz izdüşüm kökü")
    actual_files: set[str] = set()
    for path in projection_root.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"eylemsiz izdüşüm ağacında sembolik bağlantı var: {path}")
        if path.is_file():
            actual_files.add(path.relative_to(projection_root).as_posix())
    extra = sorted(actual_files - expected_files)
    if extra:
        raise SystemExit(f"sahipsiz eski eylemsiz ajan izdüşümleri: {', '.join(extra)}")

    actual_live_files: set[str] = set()
    existing_live_roots: set[str] = set()
    for relative_root in sorted(LOCAL_DISCOVERY_ROOTS):
        discovery_root = safe_project_path(relative_root, "yerel ajan keşif kökü")
        if not discovery_root.exists():
            continue
        existing_live_roots.add(relative_root.as_posix())
        if not discovery_root.is_dir():
            raise SystemExit(f"yerel ajan keşif kökü dizin değil: {relative_root}")
        for path in discovery_root.rglob("*"):
            relative = path.relative_to(ROOT)
            safe_project_path(relative, "yerel ajan keşif ağacı")
            if path.is_file():
                actual_live_files.add(relative.as_posix())
            elif not path.is_dir():
                raise SystemExit(f"yerel ajan keşif ağacında özel dosya var: {relative}")
    extra_live = sorted(actual_live_files - seen)
    if extra_live:
        raise SystemExit(f"sahipsiz yerel ajan keşif dosyaları: {', '.join(extra_live)}")
    selected_live_roots = {
        Path(CLIENT_PATHS[client_id].format(agent_id="placeholder")).parent.as_posix()
        for client_id in selected_clients
    }
    extra_live_roots = sorted(existing_live_roots - selected_live_roots)
    if extra_live_roots:
        raise SystemExit(f"seçilmemiş yerel ajan keşif kökleri: {', '.join(extra_live_roots)}")
    projection_lock_relative = projection_lock.relative_to(ROOT).as_posix()
    projection_lock_digest = hashlib.sha256(projection_lock.read_bytes()).hexdigest()
    if managed.get(projection_lock_relative) != projection_lock_digest:
        raise SystemExit("ajan izdüşüm kilidi scaffold tarafından sahiplenilmiyor")
    return len(artifacts), selected_clients


def main() -> int:
    ci = ci_mode(sys.argv[1:])
    lock_path = safe_project_path(LOCK.relative_to(ROOT), "yönetişim kilidi")
    if not lock_path.is_file():
        raise SystemExit("yönetişim kilidi eksik veya güvenli değil")
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("renderer_version") != EXPECTED_RENDERER_VERSION:
        raise SystemExit(
            "yönetişim kilidinin renderer_version değeri üretilmiş doğrulayıcıyla eşleşmiyor: "
            f"{payload.get('renderer_version')} != {EXPECTED_RENDERER_VERSION}"
        )
    if payload.get("corpus_digest") != digest_corpus():
        raise SystemExit("kanonik kural külliyatı üretilmiş izdüşüm kilidiyle eşleşmiyor")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("yönetişim kilidi üretilmiş dosya envanteri taşımıyor")
    agent_count, selected_clients = verify_agent_projections()
    verify_prompt_ingress_assets()
    verify_local_governance_guard_assets()
    verify_untrusted_content_assets()
    verify_no_unmanaged_governed_files()
    expected_files = expected_governance_files(selected_clients)
    if set(files) != expected_files:
        missing = sorted(expected_files - set(files))
        unexpected = sorted(set(files) - expected_files)
        raise SystemExit(
            "yönetişim kilidi tam üretilmiş envanterle eşleşmiyor: "
            f"eksik={missing or 'yok'}, beklenmeyen={unexpected or 'yok'}"
        )
    managed = scaffold_managed_digests()
    for relative, expected in sorted(files.items()):
        path = safe_relative(relative, "yönetişim kilidi")
        destination = safe_project_path(path, "üretilmiş yönetişim dosyası")
        if not destination.is_file():
            drifted("üretilmiş yönetişim dosyası eksik veya güvenli değil", relative)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual != expected:
            drifted("üretilmiş yönetişim dosyası sapma gösteriyor", relative)
        if managed.get(relative) != actual:
            raise SystemExit(
                f"üretilmiş yönetişim dosyası scaffold tarafından sahiplenilmiyor: {relative}"
            )
    local_override = verify_local_client_overrides(ci=ci)
    if local_override:
        return local_override
    print(f"yönetişim izdüşümleri güncel: {len(files)} dosya")
    print(
        f"ajan izdüşümleri güncel: {agent_count} etkisiz kopya ve "
        f"{agent_count} salt-okunur yetki talebiyle yapılandırılmış yerel keşif dosyası; "
        "conformance/admission iddiası yok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
