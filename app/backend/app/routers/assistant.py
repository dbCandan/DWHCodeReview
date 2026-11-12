"""LLM rule assistant (RULE_ASSISTANT_SPEC v1.6)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_session
from app.routers.rules import _apply, _validate
from app.services import presenters
from app.services.assistant import LLM_REQUIRED, AssistantRunner
from app.services.catalog import Catalog, get_catalog
from app.services.rule_groups import sync_kind_groups

router = APIRouter(prefix="/api/rule-assistant", tags=["rule-assistant"])

LOG_LIMIT_IN_LIST = 5


def _runner(request: Request) -> AssistantRunner:
    return request.app.state.assistant  # type: ignore[no-any-return]


def _get(session: Session, session_id: int) -> models.RuleAssistantSession:
    row = session.get(models.RuleAssistantSession, session_id)
    if row is None:
        raise HTTPException(404, "Asistan oturumu bulunamadı.")
    return row


def session_out(row: models.RuleAssistantSession, short_log: bool = False) -> schemas.AssistantSession:
    log = row.log or []
    return schemas.AssistantSession(
        id=row.id, status=row.status, stage=row.stage,  # type: ignore[arg-type]
        log=log[-LOG_LIMIT_IN_LIST:] if short_log else log,
        request=row.request or {}, decision=row.decision,  # type: ignore[arg-type]
        target_rule_id=row.target_rule_id, target_rule_code=row.target_rule_code,
        rationale=row.rationale, change_summary=row.change_summary,
        builtin_needed=bool(row.builtin_needed), builtin_note=row.builtin_note,
        proposal=row.proposal, original=row.original,
        validation=row.validation, noise=row.noise,  # type: ignore[arg-type]
        saved_rule_id=row.saved_rule_id, error=row.error,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _check_request(session: Session, body: schemas.AssistantRequest) -> dict[str, Any]:
    description = body.description.strip()
    if not 10 <= len(description) <= 4000:
        raise HTTPException(422, "Açıklama 10 ile 4000 karakter arasında olmalıdır.")
    if not 1 <= len(body.positive_examples) <= 10:
        raise HTTPException(422, "En az 1, en fazla 10 yakalanması gereken örnek verilmelidir.")
    if len(body.negative_examples) > 10:
        raise HTTPException(422, "En fazla 10 yakalanmaması gereken örnek verilebilir.")
    if any(not e.sql.strip() for e in [*body.positive_examples, *body.negative_examples]):
        raise HTTPException(422, "Örnek SQL boş olamaz.")
    if body.noise is not None:
        if not 10 <= body.noise.sample_size <= 200:
            raise HTTPException(422, "Örneklem büyüklüğü 10 ile 200 arasında olmalıdır.")
        if not body.noise.databases:
            raise HTTPException(422, "Gürültü testi için en az bir veritabanı seçilmelidir.")
        if session.get(models.Connection, body.noise.connection_id) is None:
            raise HTTPException(422, "Gürültü testi bağlantısı bulunamadı.")
    data = body.model_dump(mode="json")
    data["description"] = description
    if data.get("preferred_kind") == "builtin":
        data["preferred_kind"] = None  # the UI offers only Otomatik / Regex / LLM
    return data


@router.post("/sessions", response_model=schemas.AssistantSession, status_code=201)
def create_session(
    body: schemas.AssistantRequest,
    request: Request,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.AssistantSession:
    if presenters.llm_config(presenters.llm_settings_row(session)) is None:
        raise HTTPException(400, LLM_REQUIRED)
    data = _check_request(session, body)
    row = models.RuleAssistantSession(status="running", stage="matching", request=data, log=[])
    session.add(row)
    session.commit()
    _runner(request).submit(row.id, catalog)
    return session_out(row)


@router.get("/sessions", response_model=list[schemas.AssistantSession])
def list_sessions(limit: int = 20, session: Session = Depends(get_session)
                  ) -> list[schemas.AssistantSession]:
    rows = session.scalars(
        select(models.RuleAssistantSession)
        .order_by(models.RuleAssistantSession.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    return [session_out(row, short_log=True) for row in rows]


@router.get("/sessions/{session_id}", response_model=schemas.AssistantSession)
def get_session_detail(session_id: int, session: Session = Depends(get_session)
                       ) -> schemas.AssistantSession:
    return session_out(_get(session, session_id))


@router.post("/sessions/{session_id}/revalidate", response_model=schemas.AssistantSession)
def revalidate(
    session_id: int,
    body: schemas.AssistantRevalidate,
    request: Request,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.AssistantSession:
    row = _get(session, session_id)
    if row.status not in ("ready", "failed"):
        raise HTTPException(409, "Yalnız hazır veya başarısız oturum yeniden doğrulanabilir.")
    row.status = "running"
    row.stage = "validating"
    row.error = None
    session.commit()
    _runner(request).submit(
        row.id, catalog,
        {"proposal": body.proposal.model_dump(mode="json"), "run_noise": body.run_noise},
    )
    return session_out(row)


@router.post("/sessions/{session_id}/save", response_model=schemas.AssistantSaveResult)
def save(session_id: int, body: schemas.AssistantSave, session: Session = Depends(get_session)
         ) -> schemas.AssistantSaveResult:
    row = _get(session, session_id)
    if row.status != "ready":
        raise HTTPException(409, "Yalnız hazır durumdaki öneri kaydedilebilir.")
    proposal = body.proposal
    target = session.get(models.Rule, row.target_rule_id) if row.decision == "extend" and \
        row.target_rule_id else None
    if row.decision == "extend" and target is None:
        raise HTTPException(409, "Genişletilecek kural artık mevcut değil.")
    groups = _validate(session, proposal, target.id if target else None)
    rule = target or models.Rule()
    _apply(rule, proposal, groups)
    if not (rule.sample_sql or "").strip():
        examples = (row.request or {}).get("positive_examples") or []
        if examples:  # live-tester sample from the first positive example
            first = examples[0]
            rule.sample_sql = first.get("sql")
            rule.sample_object_name = first.get("object_name")
            rule.sample_object_type = first.get("object_type")
            rule.sample_database = first.get("database")
    if target is None:
        session.add(rule)
    sync_kind_groups(session, rule)
    session.flush()
    row.status = "saved"
    row.saved_rule_id = rule.id
    row.proposal = proposal.model_dump(mode="json")
    session.commit()
    return schemas.AssistantSaveResult(rule=presenters.rule_out(rule), session=session_out(row))


@router.post("/sessions/{session_id}/cancel", response_model=schemas.AssistantSession)
def cancel(session_id: int, session: Session = Depends(get_session)) -> schemas.AssistantSession:
    row = _get(session, session_id)
    # A running session stops; a ready proposal is discarded without saving (UI "Vazgeç").
    if row.status in ("running", "ready"):
        row.status = "cancelled"
        session.commit()
    elif row.status != "cancelled":
        raise HTTPException(409, "Yalnız çalışan veya kaydedilmemiş bir oturum iptal edilebilir.")
    return session_out(row)
