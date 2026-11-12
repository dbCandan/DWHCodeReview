"""Scheduled analyses (SCHEDULED_SPEC v1.7).

- `next_run_after`: next run time for a schedule (local wall clock, stored as naive UTC).
- `Scheduler`: background thread; every TICK_SECONDS it starts the due schedules (one run per
  due schedule, missed periods while the app was down give a single "catch_up" run).
- `start_run`: resolves rules and objects (incremental by create/modify date watermark),
  creates a normal Analysis through the analysis runner, or records a skipped/failed run.
- `finalize_analysis`: called when an analysis ends; fills the run's counts and new/resolved
  comparison (`compare_analysis`) and advances the watermark on success.
"""

from __future__ import annotations

import calendar
import logging
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import utcnow
from app.services import presenters
from app.services.analysis_factory import ObjectRow, build_analysis
from app.services.catalog import Catalog, CatalogError, CatalogObject, ObjectQuery

logger = logging.getLogger("dwhcr.scheduler")

TICK_SECONDS = 30
WATERMARK_OVERLAP = timedelta(minutes=5)
CATCH_UP_AFTER = timedelta(minutes=5)
WEEKDAY_SHORT = {1: "Pzt", 2: "Sal", 3: "Çar", 4: "Per", 5: "Cum", 6: "Cmt", 7: "Paz"}

SKIP_RUNNING = "Önceki çalıştırma devam ediyor"
SKIP_UNCHANGED = "Son çalıştırmadan beri değişen veya yeni nesne yok"
FAIL_NO_RULES = "Çalıştırılacak etkin kural yok"
FAIL_NO_CONNECTION = "Bağlantı bulunamadı."


# ------------------------------------------------------------------ time computation
def _parse_time(text: str) -> time:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", (text or "").strip())
    if match is None:
        raise ValueError("Saat HH:MM biçiminde olmalıdır.")
    return time(int(match.group(1)), int(match.group(2)))


def _to_local(value_utc: datetime, tz: tzinfo | None) -> datetime:
    aware = value_utc.replace(tzinfo=UTC)
    return aware.astimezone(tz) if tz is not None else aware.astimezone()


def _to_utc(local_naive: datetime, tz: tzinfo | None) -> datetime:
    aware = local_naive.replace(tzinfo=tz) if tz is not None else local_naive.astimezone()
    return aware.astimezone(UTC).replace(tzinfo=None)


def next_run_after(spec: dict[str, Any], after_utc: datetime, tz: tzinfo | None = None) -> datetime:
    """First run time strictly after `after_utc` (naive UTC in, naive UTC out).

    Times are local wall-clock times (system zone unless `tz` is given). Monthly runs on a
    day the month does not have move to the month's last day.
    """
    at = _parse_time(spec.get("time") or "00:00")
    local_after = _to_local(after_utc, tz).replace(tzinfo=None)
    kind = spec.get("kind", "daily")

    def candidate(day: date) -> datetime:
        return datetime.combine(day, at)

    if kind == "daily":
        run = candidate(local_after.date())
        if run <= local_after:
            run = candidate(local_after.date() + timedelta(days=1))
        return _to_utc(run, tz)
    if kind == "weekly":
        days = {int(d) for d in spec.get("weekdays") or []} or {1}
        for offset in range(0, 8):
            day = local_after.date() + timedelta(days=offset)
            if day.isoweekday() in days and candidate(day) > local_after:
                return _to_utc(candidate(day), tz)
        raise ValueError("Haftalık zamanlama için gün seçilmelidir.")  # pragma: no cover
    if kind == "monthly":
        wanted = max(1, min(int(spec.get("month_day") or 1), 31))
        year, month = local_after.year, local_after.month
        for _ in range(14):
            last = calendar.monthrange(year, month)[1]
            run = candidate(date(year, month, min(wanted, last)))
            if run > local_after:
                return _to_utc(run, tz)
            month += 1
            if month > 12:
                year, month = year + 1, 1
        raise ValueError("Aylık zamanlama hesaplanamadı.")  # pragma: no cover
    if kind == "interval":
        step = timedelta(hours=max(1, min(int(spec.get("interval_hours") or 1), 168)))
        anchor = candidate(local_after.date())  # runs at time + k * interval
        if anchor > local_after:
            while anchor - step > local_after:
                anchor -= step
            return _to_utc(anchor, tz)
        periods = (local_after - anchor) // step + 1
        return _to_utc(anchor + periods * step, tz)
    raise ValueError(f"Bilinmeyen zamanlama türü: {kind}")


def next_runs(spec: dict[str, Any], after_utc: datetime, count: int = 3,
              tz: tzinfo | None = None) -> list[datetime]:
    runs: list[datetime] = []
    current = after_utc
    for _ in range(count):
        current = next_run_after(spec, current, tz)
        runs.append(current)
    return runs


def schedule_text(spec: dict[str, Any]) -> str:
    kind = spec.get("kind", "daily")
    at = spec.get("time") or "00:00"
    if kind == "daily":
        return f"Her gün {at}"
    if kind == "weekly":
        days = sorted({int(d) for d in spec.get("weekdays") or []})
        return f"{', '.join(WEEKDAY_SHORT.get(d, str(d)) for d in days)} {at}"
    if kind == "monthly":
        return f"Her ayın {int(spec.get('month_day') or 1)}'i {at}"
    hours = int(spec.get("interval_hours") or 1)
    return "Her saat" if hours == 1 else f"Her {hours} saatte bir"


# ------------------------------------------------------------------ selection
def resolve_rules(session: Session, selection: dict[str, Any]) -> list[models.Rule]:
    """Enabled rules of the selection, resolved now (group memberships are current)."""
    mode = selection.get("mode", "all_enabled")
    stmt = select(models.Rule).where(models.Rule.enabled.is_(True)).order_by(models.Rule.code)
    if mode == "groups":
        ids = set(selection.get("group_ids") or [])
        if not ids:
            return []
        stmt = stmt.where(models.Rule.groups.any(models.RuleGroup.id.in_(ids)))
    elif mode == "rules":
        ids = set(selection.get("rule_ids") or [])
        if not ids:
            return []
        stmt = stmt.where(models.Rule.id.in_(ids))
    return list(session.scalars(stmt))


def _query(databases: list[str], raw: dict[str, Any]) -> ObjectQuery:
    def day(value: Any) -> date | None:
        if not value:
            return None
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    return ObjectQuery(
        databases=databases,
        schemas=raw.get("schemas") or [],
        types=raw.get("types") or [],
        created_from=day(raw.get("created_from")),
        created_to=day(raw.get("created_to")),
        modified_from=day(raw.get("modified_from")),
        modified_to=day(raw.get("modified_to")),
        search=raw.get("search") or None,
    )


def scope_objects(catalog: Catalog, config: Any, scope: dict[str, Any]) -> list[CatalogObject]:
    """Union of the scope's queries (no query = every object of the databases), de-duplicated."""
    databases = list(scope.get("databases") or [])
    queries = list(scope.get("queries") or []) or [{}]
    found: dict[tuple[str, str, str], CatalogObject] = {}
    for raw in queries:
        for obj in catalog.list_objects(config, _query(databases, raw)):
            found.setdefault((obj.database.lower(), obj.schema.lower(), obj.name.lower()), obj)
    return sorted(found.values(), key=lambda o: (o.database, o.schema, o.name))


def changed_objects(objects: list[CatalogObject], since: datetime | None) -> list[CatalogObject]:
    """Objects created or modified after `since - 5 min` (all objects when since is None)."""
    if since is None:
        return list(objects)
    limit = since - WATERMARK_OVERLAP

    def after(value: datetime | None) -> bool:
        return value is not None and value.replace(tzinfo=None) > limit

    return [o for o in objects if after(o.create_date) or after(o.modify_date)]


# ------------------------------------------------------------------ comparison
def finding_key(finding: models.Finding) -> tuple[str, str]:
    snippet = re.sub(r"\s+", " ", finding.snippet or "").strip().lower()
    return finding.rule_code, snippet


def _object_key(obj: models.AnalysisObject) -> tuple[str, str, str]:
    return obj.database.lower(), obj.schema.lower(), obj.name.lower()


def compare_analysis(
    session: Session, analysis: models.Analysis
) -> tuple[list[models.Finding], list[models.Finding], int, int]:
    """(new, resolved, unchanged count, compared objects) against earlier runs of the schedule.

    For every analysed object the latest earlier completed analysis of the same schedule that
    contains the object is the baseline. Identity = (object, rule_code, normalised snippet),
    counted as a multiset; line numbers are ignored. Only rules present in both analyses can
    be "resolved"; findings of rules the baseline did not run are new.
    """
    current_codes = {r.code for r in analysis.rules}
    findings_by_object: dict[int, list[models.Finding]] = defaultdict(list)
    for finding in session.scalars(
        select(models.Finding).where(models.Finding.analysis_id == analysis.id)
        .order_by(models.Finding.id)
    ):
        findings_by_object[finding.object_id].append(finding)

    new: list[models.Finding] = []
    resolved: list[models.Finding] = []
    unchanged = 0
    compared = 0
    for obj in analysis.objects:
        current = findings_by_object.get(obj.id, [])
        baseline = None
        if analysis.schedule_id is not None:
            baseline = session.scalar(
                select(models.AnalysisObject)
                .join(models.Analysis, models.Analysis.id == models.AnalysisObject.analysis_id)
                .where(
                    models.Analysis.schedule_id == analysis.schedule_id,
                    models.Analysis.status == "completed",
                    models.Analysis.id < analysis.id,
                    func.lower(models.AnalysisObject.database) == obj.database.lower(),
                    func.lower(models.AnalysisObject.schema) == obj.schema.lower(),
                    func.lower(models.AnalysisObject.name) == obj.name.lower(),
                )
                .order_by(models.Analysis.id.desc())
                .limit(1)
            )
        if baseline is None:
            new.extend(current)
            continue
        compared += 1
        previous_analysis = session.get(models.Analysis, baseline.analysis_id)
        previous_codes = {r.code for r in previous_analysis.rules} if previous_analysis else set()
        previous = [
            f for f in session.scalars(
                select(models.Finding).where(models.Finding.object_id == baseline.id)
                .order_by(models.Finding.id)
            )
            if f.rule_code in current_codes  # a rule not run now cannot be "resolved"
        ]
        new_part, resolved_part, same = _multiset_diff(current, previous, previous_codes)
        new.extend(new_part)
        resolved.extend(resolved_part)
        unchanged += same
    return new, resolved, unchanged, compared


def _multiset_diff(
    current: list[models.Finding], previous: list[models.Finding], previous_codes: set[str]
) -> tuple[list[models.Finding], list[models.Finding], int]:
    remaining = Counter(finding_key(f) for f in previous)
    new: list[models.Finding] = []
    unchanged = 0
    for finding in current:
        key = finding_key(finding)
        if finding.rule_code in previous_codes and remaining[key] > 0:
            remaining[key] -= 1
            unchanged += 1
        else:
            new.append(finding)
    resolved: list[models.Finding] = []
    for finding in previous:
        key = finding_key(finding)
        if remaining[key] > 0:
            remaining[key] -= 1
            resolved.append(finding)
    return new, resolved, unchanged


# ------------------------------------------------------------------ runs
def _local_stamp(value: datetime) -> str:
    return _to_local(value, None).strftime("%d.%m.%Y %H:%M")


def previous_running(session: Session, schedule: models.ScheduledAnalysis) -> bool:
    return session.scalar(
        select(func.count()).select_from(models.Analysis).where(
            models.Analysis.schedule_id == schedule.id,
            models.Analysis.status.in_(("queued", "running")),
        )
    ) > 0


class Scheduler:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        submit: Callable[..., Any],
        catalog_provider: Callable[[], Catalog],
        tick_seconds: int = TICK_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._submit = submit  # AnalysisRunner.submit
        self._catalog_provider = catalog_provider
        self._tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- thread
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive
                logger.exception("scheduler tick failed")
            self._stop.wait(self._tick_seconds)

    def tick(self, now: datetime | None = None) -> list[int]:
        """Start every due schedule once; returns the created run ids."""
        now = now or utcnow()
        started: list[int] = []
        with self._lock, self._session_factory() as session:
            due = list(session.scalars(
                select(models.ScheduledAnalysis).where(
                    models.ScheduledAnalysis.enabled.is_(True),
                    models.ScheduledAnalysis.next_run_at.is_not(None),
                    models.ScheduledAnalysis.next_run_at <= now,
                )
            ))
            for schedule in due:
                trigger = "catch_up" if schedule.next_run_at < now - CATCH_UP_AFTER else "schedule"
                schedule.next_run_at = next_run_after(schedule.schedule, now)
                session.commit()
                run = self.start_run(session, schedule, trigger, now=now)
                started.append(run.id)
        return started

    # -------------------------------------------------------------- one run
    def start_run(
        self, session: Session, schedule: models.ScheduledAnalysis, trigger: str,
        now: datetime | None = None, catalog: Catalog | None = None,
    ) -> models.ScheduledRun:
        now = now or utcnow()
        run = models.ScheduledRun(schedule_id=schedule.id, trigger=trigger, status="running",
                                  started_at=now)
        session.add(run)
        session.flush()

        def end(status: str, reason: str | None) -> models.ScheduledRun:
            run.status = status
            run.reason = reason
            run.finished_at = utcnow()
            schedule.last_run_at = now
            schedule.last_run_status = status
            session.commit()
            return run

        if previous_running(session, schedule):
            return end("skipped", SKIP_RUNNING)
        rules = resolve_rules(session, schedule.rule_selection or {})
        if not rules:
            return end("failed", FAIL_NO_RULES)
        llm_config = presenters.llm_config(presenters.llm_settings_row(session))
        if any(rule.kind == "llm" for rule in rules) and llm_config is None:
            return end("failed", presenters.LLM_NOT_READY)
        conn = session.get(models.Connection, schedule.connection_id)
        if conn is None:
            return end("failed", FAIL_NO_CONNECTION)
        config = presenters.connection_config(conn)
        try:
            objects = scope_objects(catalog or self._catalog_provider(), config,
                                    schedule.scope or {})
        except CatalogError as error:
            return end("failed", str(error))
        since = schedule.watermark_at
        if since is None and not schedule.first_run_full:
            since = schedule.created_at
        selected = changed_objects(objects, since) if schedule.incremental else list(objects)
        run.object_count = len(objects)
        run.changed_object_count = len(selected)
        if not selected:
            schedule.watermark_at = now  # nothing changed since: move the watermark on
            return end("skipped", SKIP_UNCHANGED if objects else "Kapsamda nesne yok")

        filters = {
            "schedule": schedule.name,
            "incremental": bool(schedule.incremental),
            "changed_since": schemas.iso_utc(since) if schedule.incremental and since else None,
            "databases": list((schedule.scope or {}).get("databases") or []),
            "queries": list((schedule.scope or {}).get("queries") or []),
        }
        analysis = build_analysis(
            conn,
            [ObjectRow(o.database, o.schema, o.name, o.type, o.create_date, o.modify_date)
             for o in selected],
            rules,
            f"{schedule.name} · {_local_stamp(now)}",
            filters,
        )
        analysis.schedule_id = schedule.id
        analysis.schedule_run_id = run.id
        analysis.schedule_name = schedule.name
        session.add(analysis)
        session.flush()
        run.analysis_id = analysis.id
        schedule.last_run_at = now
        schedule.last_run_status = "running"
        schedule.last_analysis_id = analysis.id
        session.commit()
        self._submit(analysis.id, catalog or self._catalog_provider(), config, llm_config)
        return run

    # -------------------------------------------------------------- completion
    def finalize_analysis(self, analysis_id: int) -> None:
        with self._session_factory() as session:
            finalize(session, analysis_id)


def finalize(session: Session, analysis_id: int) -> models.ScheduledRun | None:
    analysis = session.get(models.Analysis, analysis_id)
    if analysis is None or analysis.schedule_run_id is None:
        return None
    run = session.get(models.ScheduledRun, analysis.schedule_run_id)
    if run is None or run.status != "running":
        return run
    schedule = session.get(models.ScheduledAnalysis, run.schedule_id)
    run.finished_at = analysis.finished_at or utcnow()
    run.finding_count = session.scalar(
        select(func.count()).select_from(models.Finding)
        .where(models.Finding.analysis_id == analysis.id)
    ) or 0
    if analysis.status == "completed":
        new, resolved, unchanged, _ = compare_analysis(session, analysis)
        run.new_count, run.resolved_count, run.unchanged_count = len(new), len(resolved), unchanged
        run.status = "completed"
        if schedule is not None:
            schedule.watermark_at = run.started_at
    else:
        run.status = "failed"
        run.reason = analysis.error or ("Analiz iptal edildi" if analysis.status == "cancelled"
                                        else "Analiz başarısız oldu")
    if schedule is not None and schedule.last_analysis_id == analysis.id:
        schedule.last_run_status = run.status
    session.commit()
    return run


def recover_runs(session: Session) -> None:
    """Runs left running whose analysis already ended (or vanished) are finalised."""
    for run in session.scalars(
        select(models.ScheduledRun).where(models.ScheduledRun.status == "running")
    ):
        analysis = session.get(models.Analysis, run.analysis_id) if run.analysis_id else None
        if analysis is None:
            run.status = "failed"
            run.reason = "Uygulama yeniden başlatıldı"
            run.finished_at = utcnow()
        elif analysis.status in ("completed", "failed", "cancelled"):
            finalize(session, analysis.id)
    session.commit()


def detach_schedule(session: Session, schedule_id: int) -> None:
    """Analyses outlive their schedule: unlink them (name kept)."""
    for analysis in session.scalars(
        select(models.Analysis).where(or_(models.Analysis.schedule_id == schedule_id))
    ):
        analysis.schedule_id = None
