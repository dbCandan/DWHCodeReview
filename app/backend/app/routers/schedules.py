"""Scheduled analyses (SCHEDULED_SPEC v1.7)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_session, utcnow
from app.services import presenters
from app.services.analysis_factory import ObjectRow, count_checks
from app.services.catalog import Catalog, CatalogError, get_catalog
from app.services.scheduler import (
    Scheduler,
    _parse_time,
    changed_objects,
    compare_analysis,
    detach_schedule,
    next_run_after,
    next_runs,
    resolve_rules,
    schedule_text,
    scope_objects,
)

router = APIRouter(tags=["scheduled-analyses"])


def _scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler  # type: ignore[no-any-return]


def _get(session: Session, schedule_id: int) -> models.ScheduledAnalysis:
    row = session.get(models.ScheduledAnalysis, schedule_id)
    if row is None:
        raise HTTPException(404, "Zamanlanmış analiz bulunamadı.")
    return row


def run_out(run: models.ScheduledRun) -> schemas.ScheduledRunOut:
    return schemas.ScheduledRunOut(
        id=run.id, schedule_id=run.schedule_id, trigger=run.trigger,  # type: ignore[arg-type]
        status=run.status, reason=run.reason, analysis_id=run.analysis_id,  # type: ignore[arg-type]
        started_at=run.started_at, finished_at=run.finished_at, object_count=run.object_count,
        changed_object_count=run.changed_object_count, finding_count=run.finding_count,
        new_count=run.new_count, resolved_count=run.resolved_count,
        unchanged_count=run.unchanged_count,
    )


def schedule_out(session: Session, row: models.ScheduledAnalysis) -> schemas.ScheduledAnalysisOut:
    last = session.scalar(
        select(models.ScheduledRun).where(models.ScheduledRun.schedule_id == row.id)
        .order_by(models.ScheduledRun.id.desc()).limit(1)
    )
    return schemas.ScheduledAnalysisOut(
        id=row.id, name=row.name, description=row.description or "", enabled=row.enabled,
        connection_id=row.connection_id,
        connection_name=row.connection.name if row.connection else "",
        scope=row.scope or {}, rule_selection=row.rule_selection or {},  # type: ignore[arg-type]
        schedule=row.schedule or {},  # type: ignore[arg-type]
        incremental=row.incremental, first_run_full=row.first_run_full,
        schedule_text=schedule_text(row.schedule or {}),
        next_run_at=row.next_run_at, last_run_at=row.last_run_at,
        last_run=run_out(last) if last else None, watermark_at=row.watermark_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _validate(session: Session, body: schemas.ScheduledAnalysisInput, schedule_id: int | None) -> None:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Ad zorunludur.")
    if len(name) > 200:
        raise HTTPException(422, "Ad en fazla 200 karakter olabilir.")
    existing = session.scalar(select(models.ScheduledAnalysis).where(models.ScheduledAnalysis.name == name))
    if existing is not None and existing.id != schedule_id:
        raise HTTPException(409, f"'{name}' adlı bir zamanlanmış analiz zaten var.")
    if session.get(models.Connection, body.connection_id) is None:
        raise HTTPException(422, "Bağlantı bulunamadı.")
    if not [d for d in body.scope.databases if d.strip()]:
        raise HTTPException(422, "En az bir veritabanı seçilmelidir.")
    spec = body.schedule
    try:
        _parse_time(spec.time)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if spec.kind == "weekly":
        if not spec.weekdays:
            raise HTTPException(422, "Haftalık zamanlama için en az bir gün seçilmelidir.")
        if any(not 1 <= d <= 7 for d in spec.weekdays):
            raise HTTPException(422, "Haftanın günleri 1 (Pzt) ile 7 (Paz) arasında olmalıdır.")
    if spec.kind == "monthly" and not 1 <= spec.month_day <= 31:
        raise HTTPException(422, "Ayın günü 1 ile 31 arasında olmalıdır.")
    if spec.kind == "interval" and not 1 <= spec.interval_hours <= 168:
        raise HTTPException(422, "Saat aralığı 1 ile 168 arasında olmalıdır.")
    selection = body.rule_selection
    if selection.mode == "groups" and not selection.group_ids:
        raise HTTPException(422, "En az bir kural grubu seçilmelidir.")
    if selection.mode == "rules" and not selection.rule_ids:
        raise HTTPException(422, "En az bir kural seçilmelidir.")


def _apply(row: models.ScheduledAnalysis, body: schemas.ScheduledAnalysisInput) -> bool:
    """Write the input; returns True when the timing changed."""
    schedule = body.schedule.model_dump(mode="json")
    changed = row.schedule != schedule or row.enabled != body.enabled
    row.name = body.name.strip()
    row.description = body.description.strip()
    row.enabled = body.enabled
    row.connection_id = body.connection_id
    scope = body.scope.model_dump(mode="json")
    scope["databases"] = [d.strip() for d in scope["databases"] if d.strip()]
    row.scope = scope
    row.rule_selection = body.rule_selection.model_dump(mode="json")
    row.schedule = schedule
    row.incremental = body.incremental
    row.first_run_full = body.first_run_full
    return changed


@router.get("/api/scheduled-analyses", response_model=list[schemas.ScheduledAnalysisOut])
def list_schedules(session: Session = Depends(get_session)) -> list[schemas.ScheduledAnalysisOut]:
    rows = session.scalars(select(models.ScheduledAnalysis).order_by(models.ScheduledAnalysis.name))
    return [schedule_out(session, row) for row in rows]


@router.post("/api/scheduled-analyses", response_model=schemas.ScheduledAnalysisOut, status_code=201)
def create_schedule(body: schemas.ScheduledAnalysisInput, session: Session = Depends(get_session)
                    ) -> schemas.ScheduledAnalysisOut:
    _validate(session, body, None)
    row = models.ScheduledAnalysis()
    _apply(row, body)
    row.next_run_at = next_run_after(row.schedule, utcnow())
    session.add(row)
    session.commit()
    return schedule_out(session, row)


@router.post("/api/scheduled-analyses/preview", response_model=schemas.SchedulePreview)
async def preview(
    body: schemas.ScheduledAnalysisInput,
    schedule_id: int | None = None,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.SchedulePreview:
    conn = session.get(models.Connection, body.connection_id)
    if conn is None:
        raise HTTPException(422, "Bağlantı bulunamadı.")
    if not body.scope.databases:
        raise HTTPException(422, "En az bir veritabanı seçilmelidir.")
    try:
        _parse_time(body.schedule.time)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    rules = resolve_rules(session, body.rule_selection.model_dump())
    try:
        objects = await run_in_threadpool(
            scope_objects, catalog, presenters.connection_config(conn), body.scope.model_dump(mode="json")
        )
    except CatalogError as error:
        raise HTTPException(502, str(error)) from None
    watermark = None
    if schedule_id is not None:
        existing = session.get(models.ScheduledAnalysis, schedule_id)
        watermark = existing.watermark_at if existing else None
    selected = changed_objects(objects, watermark) if watermark and body.incremental else objects
    rows = [ObjectRow(o.database, o.schema, o.name, o.type) for o in selected]
    llm_rules = [r for r in rules if r.kind == "llm"]
    return schemas.SchedulePreview(
        object_count=len(objects),
        changed_count=len(selected) if watermark and body.incremental else None,
        rule_count=len(rules), llm_rule_count=len(llm_rules),
        estimated_checks=count_checks(rows, rules),
        estimated_llm_checks=count_checks(rows, llm_rules),
        next_runs=next_runs(body.schedule.model_dump(mode="json"), utcnow(), 3),
    )


@router.get("/api/scheduled-analyses/{schedule_id}", response_model=schemas.ScheduledAnalysisOut)
def get_schedule(schedule_id: int, session: Session = Depends(get_session)) -> schemas.ScheduledAnalysisOut:
    return schedule_out(session, _get(session, schedule_id))


@router.put("/api/scheduled-analyses/{schedule_id}", response_model=schemas.ScheduledAnalysisOut)
def update_schedule(schedule_id: int, body: schemas.ScheduledAnalysisInput,
                    session: Session = Depends(get_session)) -> schemas.ScheduledAnalysisOut:
    row = _get(session, schedule_id)
    _validate(session, body, schedule_id)
    if _apply(row, body) or row.next_run_at is None:
        row.next_run_at = next_run_after(row.schedule, utcnow())
    session.commit()
    return schedule_out(session, row)


@router.delete("/api/scheduled-analyses/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, session: Session = Depends(get_session)) -> Response:
    row = _get(session, schedule_id)
    detach_schedule(session, schedule_id)
    session.delete(row)
    session.commit()
    return Response(status_code=204)


@router.post("/api/scheduled-analyses/{schedule_id}/run", response_model=schemas.ScheduledRunOut,
             status_code=202)
def run_now(schedule_id: int, request: Request, session: Session = Depends(get_session),
            catalog: Catalog = Depends(get_catalog)) -> schemas.ScheduledRunOut:
    row = _get(session, schedule_id)
    run = _scheduler(request).start_run(session, row, "manual", catalog=catalog)
    return run_out(run)


@router.get("/api/scheduled-analyses/{schedule_id}/runs", response_model=list[schemas.ScheduledRunOut])
def list_runs(schedule_id: int, limit: int = 50, session: Session = Depends(get_session)
              ) -> list[schemas.ScheduledRunOut]:
    _get(session, schedule_id)
    rows = session.scalars(
        select(models.ScheduledRun).where(models.ScheduledRun.schedule_id == schedule_id)
        .order_by(models.ScheduledRun.id.desc()).limit(max(1, min(limit, 500)))
    )
    return [run_out(r) for r in rows]


def _diff_item(session: Session, finding: models.Finding) -> schemas.RunDiffFinding:
    return schemas.RunDiffFinding(
        object_label=finding.object_label, rule_code=finding.rule_code, rule_name=finding.rule_name,
        severity=finding.severity, line=finding.line, snippet=finding.snippet,  # type: ignore[arg-type]
        message=finding.message, finding_id=finding.id,
    )


@router.get("/api/scheduled-runs/{run_id}/diff", response_model=schemas.RunDiff)
def run_diff(run_id: int, session: Session = Depends(get_session)) -> schemas.RunDiff:
    run = session.get(models.ScheduledRun, run_id)
    if run is None:
        raise HTTPException(404, "Çalıştırma bulunamadı.")
    analysis = session.get(models.Analysis, run.analysis_id) if run.analysis_id else None
    if analysis is None:
        return schemas.RunDiff(new=[], resolved=[], compared_objects=0)
    new, resolved, _, compared = compare_analysis(session, analysis)
    return schemas.RunDiff(
        new=[_diff_item(session, f) for f in new],
        resolved=[_diff_item(session, f) for f in resolved],
        compared_objects=compared,
    )


def upcoming(session: Session, limit: int = 5) -> list[schemas.UpcomingSchedule]:
    rows = session.scalars(
        select(models.ScheduledAnalysis)
        .where(models.ScheduledAnalysis.enabled.is_(True),
               models.ScheduledAnalysis.next_run_at.is_not(None))
        .order_by(models.ScheduledAnalysis.next_run_at).limit(limit)
    )
    return [schemas.UpcomingSchedule(id=r.id, name=r.name, next_run_at=r.next_run_at,
                                     schedule_text=schedule_text(r.schedule or {})) for r in rows]
