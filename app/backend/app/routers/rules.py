"""Rules: CRUD, duplicate and test."""

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.db import get_session
from app.services import presenters, rule_tester
from app.services.rule_groups import sync_kind_groups
from app.services.rule_engine import (
    PRECONDITION_FLAGS,
    RuleError,
    RuleSpec,
    compile_optional,
    compile_pattern,
)

router = APIRouter(prefix="/api/rules", tags=["rules"])

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
METADATA_NOTE = rule_tester.METADATA_NOTE


def _get_rule(session: Session, rule_id: int) -> models.Rule:
    rule = session.get(models.Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "Kural bulunamadı.")
    return rule


def _validate(session: Session, body: schemas.RuleInput, rule_id: int | None) -> list[models.RuleGroup]:
    code = body.code.strip()
    if not CODE_RE.fullmatch(code):
        raise HTTPException(
            422,
            "Kural kodu büyük harfle başlamalı; yalnızca A-Z, 0-9, _ ve - içermeli "
            "(2-32 karakter).",
        )
    if not body.name.strip():
        raise HTTPException(422, "Kural adı zorunludur.")
    if len(body.name.strip()) > 200:
        raise HTTPException(422, "Kural adı en fazla 200 karakter olabilir.")
    if body.kind == "regex":
        try:
            compile_pattern(RuleSpec(code=code, name=body.name, pattern=body.pattern,
                                     ignore_case=body.ignore_case))
        except RuleError as error:
            raise HTTPException(422, str(error)) from None
    elif body.kind == "llm":
        if not (body.llm_prompt or "").strip():
            raise HTTPException(422, "LLM kuralı için kural tanımı (llm_prompt) zorunludur.")
    elif body.kind == "builtin":
        if not body.builtin_check:
            raise HTTPException(422, "Yerleşik kural için kontrol (builtin_check) seçilmelidir.")
        if body.builtin_check not in schemas.BUILTIN_CHECKS:
            raise HTTPException(422, f"Bilinmeyen yerleşik kontrol: {body.builtin_check}")
    metadata_precondition = _clean(body.metadata_precondition)
    if metadata_precondition and metadata_precondition not in schemas.METADATA_PRECONDITIONS:
        raise HTTPException(
            422,
            f"Bilinmeyen katalog ön koşulu (metadata_precondition): {metadata_precondition}",
        )
    for label, value, flags in (
        ("precondition", body.precondition, PRECONDITION_FLAGS),
        ("name_pattern", body.name_pattern, re.IGNORECASE),
    ):
        try:
            compile_optional(_clean(value), flags, label)
        except RuleError as error:
            raise HTTPException(422, str(error)) from None
    if any(len(db.strip()) > 128 for db in body.databases):
        raise HTTPException(422, "Veritabanı adı en fazla 128 karakter olabilir.")

    existing = session.scalar(select(models.Rule).where(models.Rule.code == code))
    if existing is not None and existing.id != rule_id:
        raise HTTPException(409, f"'{code}' kodlu bir kural zaten var.")

    group_ids = sorted(set(body.group_ids))
    groups = list(session.scalars(select(models.RuleGroup).where(models.RuleGroup.id.in_(group_ids))))
    if len(groups) != len(group_ids):
        missing = set(group_ids) - {g.id for g in groups}
        raise HTTPException(422, f"Kural grubu bulunamadı: {', '.join(map(str, sorted(missing)))}")
    return groups


def _apply(rule: models.Rule, body: schemas.RuleInput, groups: list[models.RuleGroup]) -> None:
    rule.code = body.code.strip()
    rule.name = body.name.strip()
    rule.description = body.description.strip()
    rule.recommendation = body.recommendation.strip()
    rule.severity = body.severity
    rule.kind = body.kind
    rule.pattern = body.pattern if body.pattern else None
    rule.match_mode = body.match_mode
    rule.target = body.target
    rule.ignore_case = body.ignore_case
    rule.ignore_comments = body.ignore_comments
    rule.llm_prompt = body.llm_prompt.strip() if body.llm_prompt else None
    rule.object_types = list(dict.fromkeys(body.object_types))
    rule.enabled = body.enabled
    rule.groups = groups
    rule.builtin_check = body.builtin_check if body.kind == "builtin" else None
    rule.precondition = _clean(body.precondition)
    rule.metadata_precondition = _clean(body.metadata_precondition)
    rule.requires_metadata = body.requires_metadata
    rule.databases = clean_databases(body.databases)
    rule.name_pattern = _clean(body.name_pattern)
    # Sample fields left out of the body keep their stored value (older clients do not send them).
    sent = body.model_fields_set
    if "sample_sql" in sent:
        rule.sample_sql = body.sample_sql if body.sample_sql and body.sample_sql.strip() else None
    if "sample_object_name" in sent:
        rule.sample_object_name = _clean(body.sample_object_name)
    if "sample_object_type" in sent:
        rule.sample_object_type = body.sample_object_type
    if "sample_database" in sent:
        rule.sample_database = _clean(body.sample_database)


def _clean(value: str | None) -> str | None:
    """Optional text field: blank means "not set"."""
    return value.strip() if value and value.strip() else None


def clean_databases(values: list[str]) -> list[str]:
    """Trimmed, non-empty, case-insensitively unique database names (first spelling kept)."""
    seen: dict[str, str] = {}
    for value in values:
        name = value.strip()
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return list(seen.values())


@router.get("", response_model=list[schemas.RuleOut])
def list_rules(
    q: str | None = None,
    severity: str | None = None,
    kind: str | None = None,
    group_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[schemas.RuleOut]:
    stmt = (
        select(models.Rule)
        .options(selectinload(models.Rule.groups), selectinload(models.Rule.exceptions))
        .order_by(models.Rule.code)
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.Rule.code.ilike(like),
                models.Rule.name.ilike(like),
                models.Rule.description.ilike(like),
            )
        )
    if severity:
        stmt = stmt.where(models.Rule.severity == severity)
    if kind:
        stmt = stmt.where(models.Rule.kind == kind)
    if group_id is not None:
        stmt = stmt.where(models.Rule.groups.any(models.RuleGroup.id == group_id))
    return [presenters.rule_out(rule) for rule in session.scalars(stmt)]


@router.post("", response_model=schemas.RuleOut, status_code=201)
def create_rule(body: schemas.RuleInput, session: Session = Depends(get_session)) -> schemas.RuleOut:
    groups = _validate(session, body, None)
    rule = models.Rule()
    _apply(rule, body, groups)
    session.add(rule)
    session.commit()
    return presenters.rule_out(rule)


@router.post("/test", response_model=schemas.RuleTestResponse)
def test_rule(
    body: schemas.RuleTestRequest, session: Session = Depends(get_session)
) -> schemas.RuleTestResponse:
    rule = RuleSpec.from_obj(body.rule)
    config = None
    if rule.kind == "llm":
        config = presenters.llm_config(presenters.llm_settings_row(session))
    # No catalog here: builtin and metadata rules run on empty metadata (see API_CONTRACT v1.1).
    outcome = rule_tester.test_sql(
        rule, body.sql, body.object_name, body.object_type, body.database, config
    )
    return schemas.RuleTestResponse(
        findings=[
            schemas.RuleTestFinding(line=f.line, snippet=f.snippet, message=f.message)
            for f in outcome.findings
        ],
        error=outcome.error,
    )


@router.get("/{rule_id}", response_model=schemas.RuleOut)
def get_rule(rule_id: int, session: Session = Depends(get_session)) -> schemas.RuleOut:
    return presenters.rule_out(_get_rule(session, rule_id))


@router.put("/{rule_id}", response_model=schemas.RuleOut)
def update_rule(
    rule_id: int, body: schemas.RuleInput, session: Session = Depends(get_session)
) -> schemas.RuleOut:
    rule = _get_rule(session, rule_id)
    groups = _validate(session, body, rule_id)
    old_kind = rule.kind
    _apply(rule, body, groups)
    if ("llm" in (old_kind, rule.kind)) and old_kind != rule.kind:
        sync_kind_groups(session, rule)  # regex/builtin <-> llm moves between the kind groups
    session.commit()
    return presenters.rule_out(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)) -> Response:
    rule = _get_rule(session, rule_id)
    # Analysis snapshots keep the rule data but lose the link.
    for snapshot in session.scalars(
        select(models.AnalysisRule).where(models.AnalysisRule.rule_id == rule_id)
    ):
        snapshot.rule_id = None
    session.delete(rule)
    session.commit()
    return Response(status_code=204)


@router.post("/{rule_id}/duplicate", response_model=schemas.RuleOut)
def duplicate_rule(rule_id: int, session: Session = Depends(get_session)) -> schemas.RuleOut:
    source = _get_rule(session, rule_id)
    taken = set(session.scalars(select(models.Rule.code)))
    code = _copy_code(source.code, taken)
    copy = models.Rule(
        code=code,
        name=f"{source.name} (kopya)"[:200],
        description=source.description,
        recommendation=source.recommendation,
        severity=source.severity,
        kind=source.kind,
        pattern=source.pattern,
        match_mode=source.match_mode,
        target=source.target,
        ignore_case=source.ignore_case,
        ignore_comments=source.ignore_comments,
        llm_prompt=source.llm_prompt,
        object_types=list(source.object_types or []),
        enabled=source.enabled,
        groups=list(source.groups),
        builtin_check=source.builtin_check,
        precondition=source.precondition,
        metadata_precondition=source.metadata_precondition,
        requires_metadata=source.requires_metadata,
        databases=list(source.databases or []),
        name_pattern=source.name_pattern,
        sample_sql=source.sample_sql,
        sample_object_name=source.sample_object_name,
        sample_object_type=source.sample_object_type,
        sample_database=source.sample_database,
    )
    session.add(copy)
    session.commit()
    return presenters.rule_out(copy)


def _copy_code(code: str, taken: set[str]) -> str:
    for index in range(1, 1000):
        suffix = "_COPY" if index == 1 else f"_COPY{index}"
        candidate = code[: 32 - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
    raise HTTPException(409, "Kopya için benzersiz kod üretilemedi.")
