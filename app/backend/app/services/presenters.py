"""ORM -> response model conversion and small shared lookups."""

from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import crypto, models, schemas
from app.db import utcnow
from app.services.catalog import ConnectionConfig
from app.services.llm import LlmConfig

SEVERITY_ORDER = {name: index for index, name in enumerate(schemas.SEVERITIES)}

LLM_NOT_READY = "Seçili kurallar arasında LLM kuralı var ancak LLM ayarları etkin değil."


def empty_severity_counts() -> dict[str, int]:
    return {name: 0 for name in schemas.SEVERITIES}


# ------------------------------------------------------------------ rules & groups
def rule_out(rule: models.Rule) -> schemas.RuleOut:
    return schemas.RuleOut(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        description=rule.description or "",
        recommendation=rule.recommendation or "",
        severity=rule.severity,  # type: ignore[arg-type]
        kind=rule.kind,  # type: ignore[arg-type]
        pattern=rule.pattern,
        match_mode=rule.match_mode,  # type: ignore[arg-type]
        target=rule.target,  # type: ignore[arg-type]
        ignore_case=rule.ignore_case,
        ignore_comments=rule.ignore_comments,
        llm_prompt=rule.llm_prompt,
        object_types=list(rule.object_types or []),
        enabled=rule.enabled,
        group_ids=sorted(group.id for group in rule.groups),
        builtin_check=rule.builtin_check,  # type: ignore[arg-type]
        precondition=rule.precondition,
        metadata_precondition=rule.metadata_precondition,  # type: ignore[arg-type]
        requires_metadata=bool(rule.requires_metadata),
        databases=list(rule.databases or []),
        name_pattern=rule.name_pattern,
        sample_sql=rule.sample_sql,
        sample_object_name=rule.sample_object_name,
        sample_object_type=rule.sample_object_type,  # type: ignore[arg-type]
        sample_database=rule.sample_database,
        exception_count=len(rule.exceptions),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def exception_out(exc: models.RuleException) -> schemas.RuleExceptionOut:
    return schemas.RuleExceptionOut(
        id=exc.id,
        rule_id=exc.rule_id,
        rule_code=exc.rule.code,
        database=exc.database,
        schema_=exc.schema,
        object_name=exc.object_name,
        snippet_pattern=exc.snippet_pattern,
        reason=exc.reason,
        created_at=exc.created_at,
    )


def group_out(group: models.RuleGroup) -> schemas.RuleGroupOut:
    return schemas.RuleGroupOut(
        id=group.id,
        name=group.name,
        description=group.description or "",
        color=group.color,
        rule_ids=sorted(rule.id for rule in group.rules),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


# ------------------------------------------------------------------ connections
def connection_out(conn: models.Connection) -> schemas.ConnectionOut:
    return schemas.ConnectionOut(
        id=conn.id,
        name=conn.name,
        server=conn.server,
        port=conn.port,
        username=conn.username,
        has_password=bool(conn.password_enc),
        encrypt=conn.encrypt,
        trust_server_certificate=conn.trust_server_certificate,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def connection_config(conn: models.Connection) -> ConnectionConfig:
    return ConnectionConfig(
        server=conn.server,
        port=conn.port,
        username=conn.username,
        password=crypto.decrypt(conn.password_enc),
        encrypt=conn.encrypt,
        trust_server_certificate=conn.trust_server_certificate,
    )


# ------------------------------------------------------------------ LLM settings
def llm_settings_row(session: Session) -> models.LlmSettings:
    row = session.get(models.LlmSettings, 1)
    if row is None:
        row = models.LlmSettings(id=1)
        session.add(row)
        session.commit()
    return row


def llm_settings_out(row: models.LlmSettings) -> schemas.LlmSettingsOut:
    return schemas.LlmSettingsOut(
        enabled=row.enabled,
        base_url=row.base_url,
        model=row.model,
        has_api_key=bool(row.api_key_enc),
        temperature=row.temperature,
        timeout_seconds=row.timeout_seconds,
        chunk_lines=row.chunk_lines or 250,
    )


def llm_config(row: models.LlmSettings) -> LlmConfig | None:
    """The usable LLM configuration, or None when disabled or incomplete."""
    if not row.enabled or not row.base_url.strip() or not row.model.strip():
        return None
    return LlmConfig(
        base_url=row.base_url.strip(),
        model=row.model.strip(),
        api_key=crypto.decrypt(row.api_key_enc),
        temperature=row.temperature,
        timeout_seconds=row.timeout_seconds,
        chunk_lines=row.chunk_lines or 250,
    )


# ------------------------------------------------------------------ analyses
def severity_counts(
    session: Session, analysis_ids: Sequence[int]
) -> dict[int, dict[str, int]]:
    result = {analysis_id: empty_severity_counts() for analysis_id in analysis_ids}
    if not analysis_ids:
        return result
    rows = session.execute(
        select(models.Finding.analysis_id, models.Finding.severity, func.count())
        .where(models.Finding.analysis_id.in_(analysis_ids))
        .group_by(models.Finding.analysis_id, models.Finding.severity)
    )
    for analysis_id, severity, count in rows:
        if severity in result[analysis_id]:
            result[analysis_id][severity] = int(count)
    return result


def duration_ms(analysis: models.Analysis) -> int | None:
    if analysis.started_at is None:
        return None
    end = analysis.finished_at or (utcnow() if analysis.status == "running" else None)
    if end is None:
        return None
    return max(0, int((end - analysis.started_at).total_seconds() * 1000))


def analysis_summary(
    analysis: models.Analysis, counts: dict[str, int]
) -> schemas.AnalysisSummary:
    return schemas.AnalysisSummary(
        id=analysis.id,
        name=analysis.name,
        connection_id=analysis.connection_id,
        connection_name=analysis.connection_name,
        status=analysis.status,  # type: ignore[arg-type]
        object_count=analysis.object_count,
        rule_count=analysis.rule_count,
        total_checks=analysis.total_checks,
        completed_checks=analysis.completed_checks,
        finding_count=sum(counts.values()),
        suppressed_count=analysis.suppressed_count or 0,
        severity_counts=counts,
        error=analysis.error,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        finished_at=analysis.finished_at,
        duration_ms=duration_ms(analysis),
        schedule_id=analysis.schedule_id,
        schedule_name=analysis.schedule_name,
        schedule_run_id=analysis.schedule_run_id,
    )


def summaries(
    session: Session, analyses: Iterable[models.Analysis]
) -> list[schemas.AnalysisSummary]:
    items = list(analyses)
    counts = severity_counts(session, [a.id for a in items])
    return [analysis_summary(a, counts[a.id]) for a in items]


def analysis_detail(session: Session, analysis: models.Analysis) -> schemas.AnalysisDetail:
    summary = analysis_summary(analysis, severity_counts(session, [analysis.id])[analysis.id])
    return schemas.AnalysisDetail(
        **summary.model_dump(),
        filters=analysis.filters or {},
        rules=[
            schemas.AnalysisRuleRef(
                id=r.rule_id,
                code=r.code,
                name=r.name,
                severity=r.severity,  # type: ignore[arg-type]
                kind=r.kind,  # type: ignore[arg-type]
            )
            for r in analysis.rules
        ],
        objects=[object_out(o) for o in analysis.objects],
    )


def object_out(obj: models.AnalysisObject) -> schemas.AnalysisObjectOut:
    return schemas.AnalysisObjectOut(
        id=obj.id,
        database=obj.database,
        schema_=obj.schema,
        name=obj.name,
        type=obj.type,  # type: ignore[arg-type]
        create_date=obj.create_date,
        modify_date=obj.modify_date,
        status=obj.status,  # type: ignore[arg-type]
        error=obj.error,
        finding_count=obj.finding_count,
        suppressed_count=obj.suppressed_count or 0,
        line_count=obj.line_count,
    )


def finding_out(finding: models.Finding) -> schemas.FindingOut:
    return schemas.FindingOut(
        id=finding.id,
        object_id=finding.object_id,
        object_label=finding.object_label,
        rule_code=finding.rule_code,
        rule_name=finding.rule_name,
        severity=finding.severity,  # type: ignore[arg-type]
        kind=finding.kind,  # type: ignore[arg-type]
        line=finding.line,
        snippet=finding.snippet,
        message=finding.message,
        recommendation=finding.recommendation,
    )


def finding_sort_key(finding: models.Finding) -> tuple[int, str, int, int]:
    return (
        SEVERITY_ORDER.get(finding.severity, 99),
        finding.object_label.lower(),
        finding.line if finding.line is not None else 0,
        finding.id,
    )
