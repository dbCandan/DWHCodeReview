"""Health check and dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import APP_VERSION
from app.db import get_session
from app.services import presenters
from app.routers.schedules import upcoming

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health", response_model=schemas.Health)
def health() -> schemas.Health:
    return schemas.Health(status="ok", version=APP_VERSION)


def _count(session: Session, stmt) -> int:  # type: ignore[no-untyped-def]
    return int(session.scalar(stmt) or 0)


@router.get("/dashboard", response_model=schemas.Dashboard)
def dashboard(session: Session = Depends(get_session)) -> schemas.Dashboard:
    last_completed = list(
        session.scalars(
            select(models.Analysis.id)
            .where(models.Analysis.status == "completed")
            .order_by(models.Analysis.id.desc())
            .limit(10)
        )
    )
    totals = presenters.empty_severity_counts()
    for counts in presenters.severity_counts(session, last_completed).values():
        for severity, count in counts.items():
            totals[severity] += count

    recent = session.scalars(select(models.Analysis).order_by(models.Analysis.id.desc()).limit(6))

    top_rows = session.execute(
        select(models.Finding.rule_code, func.count(), func.max(models.Finding.id))
        .group_by(models.Finding.rule_code)
        .order_by(func.count().desc(), models.Finding.rule_code)
        .limit(5)
    ).all()
    top_rules: list[schemas.TopRule] = []
    for code, count, latest_id in top_rows:
        latest = session.get(models.Finding, latest_id)
        top_rules.append(
            schemas.TopRule(
                code=code,
                name=latest.rule_name if latest else code,
                severity=latest.severity if latest else "info",  # type: ignore[arg-type]
                count=int(count),
            )
        )

    return schemas.Dashboard(
        rule_count=_count(session, select(func.count()).select_from(models.Rule)),
        enabled_rule_count=_count(
            session, select(func.count()).select_from(models.Rule).where(models.Rule.enabled.is_(True))
        ),
        group_count=_count(session, select(func.count()).select_from(models.RuleGroup)),
        connection_count=_count(session, select(func.count()).select_from(models.Connection)),
        analysis_count=_count(session, select(func.count()).select_from(models.Analysis)),
        total_findings=sum(totals.values()),
        severity_counts=totals,
        recent_analyses=presenters.summaries(session, recent),
        upcoming_schedules=upcoming(session),
        top_rules=top_rules,
    )
