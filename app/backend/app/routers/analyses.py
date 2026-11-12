"""Analyses: create/run, progress, findings, source and reports."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.db import get_session, utcnow
from app.services import presenters, report
from app.services.analysis_runner import AnalysisRunner
from app.services.catalog import Catalog, get_catalog
from app.services.analysis_factory import ObjectRow, build_analysis

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

FINAL_STATUSES = ("completed", "failed", "cancelled")


def _get_analysis(session: Session, analysis_id: int) -> models.Analysis:
    analysis = session.get(models.Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analiz bulunamadı.")
    return analysis


def _runner(request: Request) -> AnalysisRunner:
    return request.app.state.runner  # type: ignore[no-any-return]


def _selected_rules(session: Session, body: schemas.AnalysisCreate) -> list[models.Rule]:
    """Enabled rules from the union of `rule_ids` and the members of `group_ids`."""
    conditions = []
    if body.rule_ids:
        conditions.append(models.Rule.id.in_(set(body.rule_ids)))
    if body.group_ids:
        conditions.append(
            models.Rule.groups.any(models.RuleGroup.id.in_(set(body.group_ids)))
        )
    if not conditions:
        return []
    stmt = (
        select(models.Rule)
        .where(or_(*conditions), models.Rule.enabled.is_(True))
        .order_by(models.Rule.code)
    )
    return list(session.scalars(stmt))


@router.post("", response_model=schemas.AnalysisSummary, status_code=201)
def create_analysis(
    body: schemas.AnalysisCreate,
    request: Request,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.AnalysisSummary:
    conn = session.get(models.Connection, body.connection_id)
    if conn is None:
        raise HTTPException(400, "Bağlantı bulunamadı.")
    objects = list(
        {(o.database, o.schema_, o.name): o for o in body.objects}.values()
    )
    if not objects:
        raise HTTPException(400, "En az bir nesne seçilmelidir.")
    rules = _selected_rules(session, body)
    if not rules:
        raise HTTPException(400, "En az bir etkin kural seçilmelidir.")
    llm_config = presenters.llm_config(presenters.llm_settings_row(session))
    if any(rule.kind == "llm" for rule in rules) and llm_config is None:
        raise HTTPException(400, presenters.LLM_NOT_READY)

    analysis = build_analysis(
        conn,
        [ObjectRow(o.database, o.schema_, o.name, o.type, o.create_date, o.modify_date)
         for o in objects],
        rules,
        body.name or "",
        body.filters or {},
    )
    session.add(analysis)
    session.flush()
    if not analysis.name:
        analysis.name = f"Analiz #{analysis.id}"
    session.commit()

    _runner(request).submit(
        analysis.id, catalog, presenters.connection_config(conn), llm_config
    )
    return presenters.analysis_summary(analysis, presenters.empty_severity_counts())


@router.get("", response_model=list[schemas.AnalysisSummary])
def list_analyses(
    status: str | None = None, session: Session = Depends(get_session)
) -> list[schemas.AnalysisSummary]:
    stmt = select(models.Analysis).order_by(models.Analysis.id.desc())
    if status:
        stmt = stmt.where(models.Analysis.status == status)
    return presenters.summaries(session, session.scalars(stmt))


@router.get("/{analysis_id}", response_model=schemas.AnalysisDetail)
def get_analysis(analysis_id: int, session: Session = Depends(get_session)) -> schemas.AnalysisDetail:
    stmt = (
        select(models.Analysis)
        .where(models.Analysis.id == analysis_id)
        .options(selectinload(models.Analysis.rules), selectinload(models.Analysis.objects))
    )
    analysis = session.scalar(stmt)
    if analysis is None:
        raise HTTPException(404, "Analiz bulunamadı.")
    return presenters.analysis_detail(session, analysis)


def _findings(
    session: Session,
    analysis_id: int,
    severity: str | None = None,
    rule_code: str | None = None,
    object_id: int | None = None,
    q: str | None = None,
) -> list[models.Finding]:
    stmt = select(models.Finding).where(models.Finding.analysis_id == analysis_id)
    if severity:
        stmt = stmt.where(models.Finding.severity == severity)
    if rule_code:
        stmt = stmt.where(models.Finding.rule_code == rule_code)
    if object_id is not None:
        stmt = stmt.where(models.Finding.object_id == object_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.Finding.snippet.ilike(like),
                models.Finding.message.ilike(like),
                models.Finding.rule_code.ilike(like),
                models.Finding.rule_name.ilike(like),
                models.Finding.object_label.ilike(like),
            )
        )
    return sorted(session.scalars(stmt), key=presenters.finding_sort_key)


@router.get("/{analysis_id}/findings", response_model=list[schemas.FindingOut])
def list_findings(
    analysis_id: int,
    severity: str | None = None,
    rule_code: str | None = None,
    object_id: int | None = None,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> list[schemas.FindingOut]:
    _get_analysis(session, analysis_id)
    rows = _findings(session, analysis_id, severity, rule_code, object_id, q)
    return [presenters.finding_out(f) for f in rows]


@router.get("/{analysis_id}/objects/{object_id}/source", response_model=schemas.ObjectSource)
def object_source(
    analysis_id: int, object_id: int, session: Session = Depends(get_session)
) -> schemas.ObjectSource:
    obj = session.get(models.AnalysisObject, object_id)
    if obj is None or obj.analysis_id != analysis_id:
        raise HTTPException(404, "Analiz nesnesi bulunamadı.")
    rows = _findings(session, analysis_id, object_id=object_id)
    rows.sort(key=lambda f: (f.line if f.line is not None else 0, presenters.SEVERITY_ORDER.get(f.severity, 9)))
    return schemas.ObjectSource(
        definition=obj.definition, findings=[presenters.finding_out(f) for f in rows]
    )


@router.post("/{analysis_id}/cancel", response_model=schemas.AnalysisSummary)
def cancel_analysis(analysis_id: int, session: Session = Depends(get_session)) -> schemas.AnalysisSummary:
    analysis = _get_analysis(session, analysis_id)
    if analysis.status in FINAL_STATUSES:
        raise HTTPException(409, "Yalnızca kuyruktaki veya çalışan bir analiz iptal edilebilir.")
    analysis.cancel_requested = True
    if analysis.status == "queued":
        analysis.status = "cancelled"
        analysis.finished_at = utcnow()
    session.commit()
    return presenters.summaries(session, [analysis])[0]


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: int, session: Session = Depends(get_session)) -> Response:
    analysis = _get_analysis(session, analysis_id)
    if analysis.status == "running":
        raise HTTPException(409, "Çalışan bir analiz silinemez; önce iptal edin.")
    session.delete(analysis)
    session.commit()
    return Response(status_code=204)


@router.get("/{analysis_id}/report.html")
def report_html(analysis_id: int, session: Session = Depends(get_session)) -> Response:
    analysis = _get_analysis(session, analysis_id)
    html = report.render_html(analysis, _findings(session, analysis_id))
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="analiz-{analysis_id}.html"'},
    )


@router.get("/{analysis_id}/report.csv")
def report_csv(analysis_id: int, session: Session = Depends(get_session)) -> Response:
    analysis = _get_analysis(session, analysis_id)
    objects = {o.id: o for o in analysis.objects}
    data = report.render_csv(_findings(session, analysis_id), objects)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="analiz-{analysis_id}.csv"'},
    )
