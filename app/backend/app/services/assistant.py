"""LLM rule assistant (RULE_ASSISTANT_SPEC v1.6).

A session runs in a single background worker (at most one assistant job at a time):
matching -> drafting -> validating <-> refining (at most MAX_ROUNDS validation rounds) ->
noise (optional) -> done. Every stage writes its result and a Turkish log line to the
`rule_assistant_sessions` row, so the frontend can poll. Nothing is saved as a rule here;
saving is an explicit user action (router).
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import utcnow
from app.services import llm, presenters
from app.services.builtin_checks import ObjectRef, related_objects
from app.services.catalog import Catalog, CatalogError, ConnectionConfig, ObjectQuery
from app.services.metadata import empty_metadata, metadata_precondition_met
from app.services.rule_engine import (
    CheckContext,
    RuleError,
    RuleSpec,
    applies_to_object,
    mask_sql,
    precondition_met,
    run_rule,
)
from app.services.rule_groups import kind_group_ids
from app.services.rule_tester import test_sql

logger = logging.getLogger("dwhcr.assistant")

MAX_ROUNDS = 3
NOISE_LLM_OBJECTS = 15
NOISE_EXAMPLES = 10
RESTART_MESSAGE = "Uygulama yeniden başlatıldı"
LLM_REQUIRED = "Kural asistanı için LLM ayarlarının etkin olması gerekir."

BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "nolock_physical_tables": "Fiziksel tablolar FROM/JOIN'de WITH (NOLOCK) olmadan okunuyor (katalog).",
    "derived_view_consistency": "EDWDM türev view'ları (Masked/Personnel*) asıl view ile kolon/tip uyumlu değil (katalog).",
    "left_then_inner_join": "Aynı FROM bloğunda LEFT JOIN'den sonra INNER JOIN.",
    "select_list_subquery": "SELECT kolon listesinde FROM'lu alt sorgu.",
    "tablock_physical_insert": "Fiziksel tabloya INSERT WITH (TABLOCK) olmadan (katalog).",
    "join_column_type_mismatch": "JOIN eşitliğinde farklı tip ailesinden kolonlar (katalog).",
    "non_sargable_predicates": "ON/WHERE'de kolon fonksiyon/dönüşüm içinde (CAST, ISNULL, YEAR ...).",
    "or_in_predicates": "JOIN koşulunda OR; WHERE'de farklı kolonları bağlayan OR.",
    "scalar_udf_in_query": "Sorgu içinde scalar UDF çağrısı (katalog).",
    "window_order_by_type": "ROW_NUMBER/RANK ORDER BY'da sabit veya metin tipli kolon (katalog).",
    "date_variable_type_mismatch": "Tarih değişkeni ile farklı tip ailesindeki kolon karşılaştırması (katalog).",
    "personnel_flag_view_source": "EDWDM asıl view'larında PersonnelFlag kaynağı (katalog).",
    "id_literal_filter": "Vekil anahtar (Id) üzerinden sabit değer filtresi (katalog).",
    "calendar_date_predicate": "WHERE/ON'da dönüştürülmüş tarih kolonu; Calendar aralık join'i önerisi.",
}

SYSTEM = """Sen bir SQL Server veri ambarı kod inceleme aracının kural tasarımcısısın.
Yanıtın her zaman TEK bir JSON nesnesidir; markdown, açıklama metni veya <think> bloğu yazma."""

FIELD_GUIDE = """KURAL ALANLARI (RuleInput JSON):
- code: ^[A-Z][A-Z0-9_-]{1,31}$ (önerilen önek "DWH-", örn. DWH-XXX-01), benzersiz
- name / description / recommendation: Türkçe; description = neden önemli, recommendation = nasıl düzeltilir
- severity: "critical" | "high" | "medium" | "low" | "info"
- kind: "regex" | "builtin" | "llm"
  * regex: örnekler sözcüksel bir kalıpla ayrılabiliyorsa (EN HIZLI, TERCİH EDİLİR). pattern Python `re` sözdizimi;
    match_mode "match" (her eşleşme ayrı bulgu) | "absent" (desen hiç yoksa nesne başına tek bulgu);
    target "definition" (SQL tanımı) | "name" ("şema.ad" nesne adı); ignore_case (varsayılan true);
    ignore_comments (varsayılan true): yorumlar hiç görülmez, string literal'ler eşleşmeyi başlatamaz.
  * builtin: aşağıdaki yerleşik kontrollerden biri ihtiyacı TAM karşılıyorsa; builtin_check zorunlu. Yeni yerleşik yazılamaz.
  * llm: anlamsal yorum gerekiyorsa; llm_prompt zorunlu (Türkçe, "İHLAL SAY:" / "İHLAL DEĞİL:" bölümleriyle);
    LLM çağrılarını azaltmak için precondition (regex) ver.
- precondition: regex (IGNORECASE|DOTALL); tanımda eşleşmezse kural o nesnede çalışmaz (özellikle llm için)
- metadata_precondition: null | "references_scd_table" | "references_partitioned_table"
- requires_metadata: llm isteminde KATALOG METADATASI bloğu gerekir mi
- object_types: [] (tümü) veya "PROCEDURE","VIEW","FUNCTION_SCALAR","FUNCTION_INLINE","FUNCTION_TABLE"
- databases: [] (tümü) veya veritabanı adları; name_pattern: "şema.ad" üzerinde regex veya null
- enabled: true; group_ids: aşağıdaki gruplardan uygun olanların id'leri"""


def _now() -> str:
    return presenters_iso(utcnow())


def presenters_iso(value: Any) -> str:
    return schemas.iso_utc(value) or ""


# ------------------------------------------------------------------ prompt material
def rule_catalog(session: Session) -> str:
    lines = []
    for rule in session.scalars(select(models.Rule).order_by(models.Rule.code)):
        scope = []
        if rule.object_types:
            scope.append("tipler=" + ",".join(rule.object_types))
        if rule.databases:
            scope.append("db=" + ",".join(rule.databases))
        if rule.name_pattern:
            scope.append(f"ad~{rule.name_pattern}")
        detail = (rule.pattern or "")[:300] if rule.kind == "regex" else (
            (rule.llm_prompt or "")[:400] if rule.kind == "llm" else
            f"{rule.builtin_check} ({BUILTIN_DESCRIPTIONS.get(rule.builtin_check or '', '')})"
        )
        lines.append(
            f"- {rule.code} | {rule.name} | {rule.kind} | {rule.severity} | "
            f"kapsam: {'; '.join(scope) or 'tümü'}\n  açıklama: {rule.description[:300]}\n"
            f"  tanım: {detail}"
        )
    return "\n".join(lines)


def builtin_list() -> str:
    return "\n".join(f"- {name}: {text}" for name, text in BUILTIN_DESCRIPTIONS.items())


def group_list(session: Session) -> str:
    return "\n".join(
        f"- id={g.id}: {g.name} — {g.description}"
        for g in session.scalars(select(models.RuleGroup).order_by(models.RuleGroup.id))
    )


def examples_text(request: dict[str, Any]) -> str:
    parts = []
    for kind, key in (("YAKALANMASI GEREKEN", "positive_examples"),
                      ("YAKALANMAMASI GEREKEN", "negative_examples")):
        for index, example in enumerate(request.get(key) or [], 1):
            meta = ", ".join(
                f"{label}={example[field]}"
                for label, field in (("tip", "object_type"), ("nesne", "object_name"),
                                     ("db", "database"))
                if example.get(field)
            )
            note = f"\nNot: {example['note']}" if example.get("note") else ""
            parts.append(f"### {kind} ÖRNEK {index}{f' ({meta})' if meta else ''}{note}\n"
                         f"```sql\n{example['sql']}\n```")
    return "\n\n".join(parts)


def rule_definition(rule: models.Rule) -> dict[str, Any]:
    """Full current definition of a rule as RuleInput fields."""
    data = presenters.rule_out(rule).model_dump()
    allowed = set(schemas.RuleInput.model_fields)
    return {k: v for k, v in data.items() if k in allowed}


# ------------------------------------------------------------------ runner
class AssistantRunner:
    """One background worker: assistant jobs run one after another."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="assistant")

    def submit(self, session_id: int, catalog: Catalog, revalidate: dict[str, Any] | None = None
               ) -> Future[None]:
        return self._executor.submit(self._safe, session_id, catalog, revalidate)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _safe(self, session_id: int, catalog: Catalog, revalidate: dict[str, Any] | None) -> None:
        with self._session_factory() as session:
            job = _Job(session, session_id, catalog)
            try:
                if revalidate is None:
                    job.run()
                else:
                    job.revalidate(revalidate["proposal"], bool(revalidate.get("run_noise")))
            except _Cancelled:
                pass
            except Exception as error:  # noqa: BLE001 - the session must end in a final state
                logger.exception("assistant session %s failed", session_id)
                session.rollback()
                job.fail(str(error) or type(error).__name__)


class _Cancelled(Exception):
    pass


class _Job:
    def __init__(self, session: Session, session_id: int, catalog: Catalog) -> None:
        self.session = session
        self.catalog = catalog
        row = session.get(models.RuleAssistantSession, session_id)
        if row is None:
            raise RuntimeError("Asistan oturumu bulunamadı.")
        self.row = row
        self.config = presenters.llm_config(presenters.llm_settings_row(session))

    # -------------------------------------------------------------- bookkeeping
    def log(self, stage: str, message: str, **fields: Any) -> None:
        self.session.refresh(self.row)
        if self.row.status == "cancelled":
            raise _Cancelled
        self.row.stage = stage
        self.row.log = [*(self.row.log or []), {"at": _now(), "stage": stage, "message": message}]
        for name, value in fields.items():
            setattr(self.row, name, value)
        self.session.commit()

    def fail(self, message: str) -> None:
        row = self.session.get(models.RuleAssistantSession, self.row.id)
        if row is None or row.status == "cancelled":
            return
        row.status = "failed"
        row.error = message[:2000]
        row.log = [*(row.log or []), {"at": _now(), "stage": row.stage, "message": f"Hata: {message}"}]
        self.session.commit()

    def ask(self, user: str) -> dict[str, Any]:
        if self.config is None:
            raise RuntimeError(LLM_REQUIRED)
        text = llm._chat_with_retry(
            self.config, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        )
        data = llm.extract_json(text)
        if not isinstance(data, dict):
            raise llm.LlmError("LLM yanıtı bir JSON nesnesi değil.")
        return data

    # -------------------------------------------------------------- flow
    def run(self) -> None:
        request = self.row.request
        self.log("matching", "Mevcut kurallar inceleniyor (eşleştirme).")
        match = self.ask(MATCHING.format(
            description=request["description"], examples=examples_text(request),
            catalog=rule_catalog(self.session), builtins=builtin_list(),
        ))
        decision = "extend" if str(match.get("decision", "")).lower() == "extend" else "new"
        target = None
        if decision == "extend":
            code = str(match.get("target_rule_code") or "").strip()
            target = self.session.scalar(select(models.Rule).where(models.Rule.code == code))
            if target is None:
                decision = "new"
        builtin_needed = bool(match.get("builtin_needed"))
        self.log(
            "drafting",
            f"Karar: {'mevcut kurala dahil et — ' + target.code if target else 'yeni kural'}. "
            "Kural taslağı hazırlanıyor.",
            decision=decision,
            target_rule_id=target.id if target else None,
            target_rule_code=target.code if target else None,
            rationale=str(match.get("rationale") or "") or None,
            builtin_needed=builtin_needed,
            builtin_note=(str(match.get("builtin_note")) if match.get("builtin_note") else None),
            original=presenters.rule_out(target).model_dump(mode="json") if target else None,
        )
        draft_prompt = DRAFTING.format(
            description=request["description"], examples=examples_text(request),
            guide=FIELD_GUIDE, builtins=builtin_list(), groups=group_list(self.session),
            preferred=request.get("preferred_kind") or "otomatik",
            severity=request.get("severity_hint") or "belirtilmedi",
            target=(json.dumps(rule_definition(target), ensure_ascii=False, indent=1)
                    if target else "YOK (yeni kural)"),
            builtin_needed="EVET: " + (self.row.builtin_note or "") if builtin_needed else "hayır",
        )
        proposal = self.parse_proposal(self.ask(draft_prompt), draft_prompt)
        self.row.change_summary = proposal.pop("_change_summary", None) or self.row.change_summary
        self.validate_loop(proposal, refine=True)
        self.noise_stage(run=bool(request.get("noise")))
        self.log("done", "Öneri hazır; inceleyip onaylayın.", status="ready")

    def revalidate(self, proposal: dict[str, Any], run_noise: bool) -> None:
        clean = self.normalize(proposal)
        self.log("validating", "Düzenlenen öneri yeniden doğrulanıyor.", proposal=clean)
        self.validate_loop(clean, refine=False)
        self.noise_stage(run=run_noise and bool(self.row.request.get("noise")))
        self.log("done", "Yeniden doğrulama tamamlandı.", status="ready")

    # -------------------------------------------------------------- proposal handling
    def parse_proposal(self, data: dict[str, Any], prompt: str) -> dict[str, Any]:
        summary = data.pop("change_summary", None)
        try:
            proposal = self.normalize(data)
        except ValidationError as error:
            fix = self.ask(
                f"{prompt}\n\nÖNCEKİ YANITIN ŞEMAYA UYMADI:\n{error}\n"
                "Aynı öneriyi şemaya uygun TAM JSON olarak yeniden yaz."
            )
            summary = fix.pop("change_summary", summary)
            proposal = self.normalize(fix)
        if summary:
            proposal["_change_summary"] = str(summary)
        return proposal

    def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Schema-valid RuleInput dict with assistant defaults (raises ValidationError)."""
        data = {k: v for k, v in data.items() if k in schemas.RuleInput.model_fields}
        proposal = schemas.RuleInput(**data)
        target = (self.session.get(models.Rule, self.row.target_rule_id)
                  if self.row.target_rule_id else None)
        if target is not None:
            proposal.code = target.code
        else:
            proposal.code = self.unique_code(proposal.code)
        if proposal.kind == "builtin" and proposal.builtin_check not in schemas.BUILTIN_CHECKS:
            self.row.builtin_needed = True
            proposal.kind = "llm"
            proposal.builtin_check = None
            proposal.llm_prompt = proposal.llm_prompt or proposal.description
        existing_groups = {g.id for g in self.session.scalars(select(models.RuleGroup))}
        group_ids = [g for g in proposal.group_ids if g in existing_groups]
        join_id, leave_id = kind_group_ids(self.session, proposal.kind)
        group_ids = [g for g in group_ids if g != leave_id]
        if join_id is not None and join_id not in group_ids:
            group_ids.append(join_id)
        proposal.group_ids = sorted(set(group_ids))
        return proposal.model_dump(mode="json")

    def unique_code(self, code: str) -> str:
        import re

        code = re.sub(r"[^A-Z0-9_-]", "", (code or "").upper()) or "DWH-NEW-01"
        if not code[0].isalpha():
            code = f"DWH-{code}"
        code = code[:32]
        taken = set(self.session.scalars(select(models.Rule.code)))
        candidate, index = code, 2
        while candidate in taken:
            suffix = f"-{index}"
            candidate = code[: 32 - len(suffix)] + suffix
            index += 1
        return candidate

    # -------------------------------------------------------------- validation
    def run_cases(self, proposal: dict[str, Any]) -> dict[str, Any]:
        spec = RuleSpec.from_obj(schemas.RuleInput(**proposal))
        old_spec = None
        if self.row.target_rule_id:
            target = self.session.get(models.Rule, self.row.target_rule_id)
            old_spec = RuleSpec.from_obj(target) if target is not None else None
        config = self.config
        cases = []
        for kind, key in (("positive", "positive_examples"), ("negative", "negative_examples")):
            for index, example in enumerate(self.row.request.get(key) or [], 1):
                args = (example["sql"], example.get("object_name"), example.get("object_type"),
                        example.get("database"))
                outcome = test_sql(spec, *args, config if spec.kind == "llm" else None)
                passed = bool(outcome.findings) if kind == "positive" else not outcome.findings
                case: dict[str, Any] = {
                    "kind": kind, "index": index, "passed": passed,
                    "findings": [{"line": f.line, "snippet": f.snippet, "message": f.message}
                                 for f in outcome.findings],
                    "error": outcome.error, "old_passed": None,
                }
                if old_spec is not None:
                    old = test_sql(old_spec, *args, config if old_spec.kind == "llm" else None)
                    case["old_passed"] = bool(old.findings) if kind == "positive" else not old.findings
                cases.append(case)
        return {"passed": all(c["passed"] for c in cases), "cases": cases}

    def problems(self, proposal: dict[str, Any]) -> list[str]:
        from fastapi import HTTPException

        from app.routers.rules import _validate

        try:
            _validate(self.session, schemas.RuleInput(**proposal), self.row.target_rule_id)
        except HTTPException as error:
            return [str(error.detail)]
        return []

    def validate_loop(self, proposal: dict[str, Any], refine: bool) -> None:
        summary = proposal.pop("_change_summary", None)
        if summary:
            self.row.change_summary = summary
        rounds = MAX_ROUNDS if refine else 1
        for iteration in range(1, rounds + 1):
            problems = self.problems(proposal)
            result = (self.run_cases(proposal) if not problems
                      else {"passed": False, "cases": []})
            passed = result["passed"] and not problems
            validation = {"iterations": iteration, "passed": passed, "cases": result["cases"]}
            failed = sum(1 for c in result["cases"] if not c["passed"])
            message = (f"Doğrulama turu {iteration}: "
                       + ("tüm örnekler geçti." if passed else
                          (f"tanım hatası: {problems[0]}" if problems
                           else f"{failed} örnek başarısız.")))
            self.log("validating", message, proposal=proposal, validation=validation)
            if passed or iteration == rounds:
                return
            self.log("refining", "Başarısız örnekler LLM'e geri gönderiliyor (düzeltme).")
            refine_prompt = REFINING.format(
                guide=FIELD_GUIDE, builtins=builtin_list(),
                proposal=json.dumps(proposal, ensure_ascii=False, indent=1),
                problems="\n".join(f"- {p}" for p in problems) or "- (yok)",
                failures=failures_text(self.row.request, result["cases"]),
                description=self.row.request["description"],
            )
            proposal = self.parse_proposal(self.ask(refine_prompt), refine_prompt)
            summary = proposal.pop("_change_summary", None)
            if summary:
                self.row.change_summary = summary

    # -------------------------------------------------------------- noise test
    def noise_stage(self, run: bool) -> None:
        request = self.row.request.get("noise")
        if not run or not request:
            self.log("noise", "Gürültü testi istenmedi.", noise={"status": "skipped"})
            return
        self.log("noise", "Gerçek veride gürültü testi çalışıyor.",
                 noise={"status": "running"})
        started = time.perf_counter()
        try:
            noise = self.noise(request)
        except (CatalogError, llm.LlmError) as error:
            noise = {"status": "failed", "note": str(error)}
        noise["duration_ms"] = int((time.perf_counter() - started) * 1000)
        text = (f"Gürültü testi: {noise.get('sampled', 0)} nesne, "
                f"{noise.get('objects_with_findings', 0)} nesnede {noise.get('findings', 0)} bulgu."
                if noise["status"] == "done" else f"Gürültü testi başarısız: {noise.get('note')}")
        self.log("noise", text, noise=noise)

    def noise(self, request: dict[str, Any]) -> dict[str, Any]:
        conn = self.session.get(models.Connection, request["connection_id"])
        if conn is None:
            return {"status": "failed", "note": "Bağlantı bulunamadı."}
        config: ConnectionConfig = presenters.connection_config(conn)
        proposal = schemas.RuleInput(**self.row.proposal)
        spec = RuleSpec.from_obj(proposal)
        old_spec = None
        if self.row.target_rule_id:
            target = self.session.get(models.Rule, self.row.target_rule_id)
            old_spec = RuleSpec.from_obj(target) if target is not None else None
        types = request.get("object_types") or list(proposal.object_types)
        objects = self.catalog.list_objects(
            config, ObjectQuery(databases=request.get("databases") or [], types=types)
        )
        eligible = [o for o in objects
                    if applies_to_object(spec, o.database, o.schema, o.name, o.type)]
        size = max(1, min(int(request.get("sample_size") or 50), 200))
        sample = random.sample(eligible, min(size, len(eligible)))
        result: dict[str, Any] = {
            "status": "done", "sampled": 0, "objects_with_findings": 0, "findings": 0,
            "old_findings": 0 if old_spec else None, "examples": [], "llm_calls": 0,
            "note": None,
        }
        llm_budget = [NOISE_LLM_OBJECTS]
        with self.catalog.open_reader(config) as reader:
            for obj in sample:
                self.session.refresh(self.row)
                if self.row.status == "cancelled":
                    raise _Cancelled
                sql = reader.fetch(obj.database, obj.schema, obj.name)
                if sql is None:
                    continue
                result["sampled"] += 1
                found = self.evaluate(spec, reader, obj, sql, llm_budget, result)
                if found:
                    result["objects_with_findings"] += 1
                    result["findings"] += len(found)
                    for f in found:
                        if len(result["examples"]) < NOISE_EXAMPLES:
                            result["examples"].append({
                                "object_label": f"{obj.database}.{obj.schema}.{obj.name}",
                                "line": f.line, "snippet": f.snippet, "message": f.message,
                            })
                if old_spec is not None:
                    result["old_findings"] += len(
                        self.evaluate(old_spec, reader, obj, sql, llm_budget, result)
                    )
        if spec.kind == "llm" and llm_budget[0] <= 0:
            result["note"] = f"LLM yalnız ilk {NOISE_LLM_OBJECTS} nesnede çalıştırıldı."
        return result

    def evaluate(self, spec: RuleSpec, reader: Any, obj: Any, sql: str,
                 llm_budget: list[int], result: dict[str, Any]) -> list[Any]:
        masked = mask_sql(sql)
        if not precondition_met(spec, sql, masked):
            return []
        ref = ObjectRef(obj.database, obj.schema, obj.name, obj.type)
        metadata = empty_metadata()
        if spec.needs_metadata and hasattr(reader, "describe"):
            extra = related_objects(spec.builtin_check, ref) if spec.kind == "builtin" else []
            try:
                metadata = reader.describe(obj.database, obj.schema, obj.name, obj.type, sql,
                                           masked, extra)
            except Exception:  # noqa: BLE001 - metadata is optional
                metadata = empty_metadata()
            if not metadata_precondition_met(spec.metadata_precondition, metadata):
                return []
        if spec.kind == "llm":
            if llm_budget[0] <= 0:
                return []
            llm_budget[0] -= 1
            result["llm_calls"] += 1
        try:
            return run_rule(spec, sql, f"{obj.schema}.{obj.name}", self.config,
                            CheckContext(ref, metadata, masked))
        except RuleError as error:
            return list(error.findings)


def failures_text(request: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    lines = []
    for case in cases:
        if case["passed"]:
            continue
        key = "positive_examples" if case["kind"] == "positive" else "negative_examples"
        example = request[key][case["index"] - 1]
        expected = "en az 1 bulgu" if case["kind"] == "positive" else "hiç bulgu yok"
        got = (f"{len(case['findings'])} bulgu (satırlar: "
               f"{', '.join(str(f['line']) for f in case['findings'])})")
        lines.append(
            f"### {'POZİTİF' if case['kind'] == 'positive' else 'NEGATİF'} örnek {case['index']}: "
            f"beklenen {expected}, gerçekleşen {got}"
            + (f"; hata/not: {case['error']}" if case.get("error") else "")
            + f"\n```sql\n{example['sql']}\n```"
        )
    return "\n\n".join(lines) or "(başarısız örnek yok)"


def recover_interrupted(session: Session) -> int:
    result = session.execute(
        update(models.RuleAssistantSession)
        .where(models.RuleAssistantSession.status == "running")
        .values(status="failed", error=RESTART_MESSAGE, updated_at=utcnow())
    )
    session.commit()
    return int(result.rowcount or 0)


# ------------------------------------------------------------------ prompts
MATCHING = """GÖREV: EŞLEŞTİRME
Kullanıcı yeni bir kod inceleme kuralı istiyor. Aşağıdaki mevcut kural kataloğunu incele ve isteğin mevcut bir kurala
dahil edilip edilemeyeceğine karar ver.
Kural: Aynı denetim amacını taşıyan ve örnekleri kapsayacak şekilde makul biçimde genişletilebilecek bir kural varsa
"extend"; aksi halde "new". Sırf aynı alanla (ör. performans) ilgili diye extend etme.
Mevcut yerleşik kontrollerden hiçbiri yetmiyor ve deterministik yeni bir kontrol gerekiyorsa builtin_needed=true yap.

İSTEK:
{description}

ÖRNEKLER:
{examples}

MEVCUT KURALLAR:
{catalog}

YERLEŞİK KONTROLLER:
{builtins}

Çıktı: {{"decision":"extend|new","target_rule_code":"…|null","rationale":"Türkçe gerekçe","builtin_needed":false,"builtin_note":null}}"""

DRAFTING = """GÖREV: TASLAK
Kullanıcının isteği için TAM kural tanımı (RuleInput) hazırla.

İSTEK:
{description}

ÖRNEKLER (pozitifler bulgu üretmeli, negatifler üretmemeli):
{examples}

Tür tercihi: {preferred}; önem ipucu: {severity}; yeni yerleşik kontrol gerekli mi: {builtin_needed}
(Yeni yerleşik gerekiyorsa öneriyi şimdilik "llm" türünde hazırla.)

GENİŞLETİLECEK MEVCUT KURAL (varsa tam hali; yalnız gerekeni değiştir, code aynı kalmalı):
{target}

{guide}

YERLEŞİK KONTROLLER (builtin_check için yalnız bunlar):
{builtins}

KURAL GRUPLARI (group_ids için):
{groups}

Çıktı: RuleInput alanlarının tamamı + "change_summary" (Türkçe; yeni kuralda kısa özet, genişletmede neyin değiştiği)
tek bir JSON nesnesi olarak."""

REFINING = """GÖREV: DÜZELTME
Önceki kural önerisi bazı örneklerde beklenen sonucu vermedi. Öneriyi düzelt ve TAM tanımı yeniden yaz.

İSTEK:
{description}

ÖNCEKİ ÖNERİ:
{proposal}

TANIM HATALARI:
{problems}

BAŞARISIZ ÖRNEKLER:
{failures}

{guide}

YERLEŞİK KONTROLLER:
{builtins}

Çıktı: düzeltilmiş tam RuleInput JSON'u + "change_summary"."""
