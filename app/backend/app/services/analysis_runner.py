"""Background execution of analyses.

Each analysis runs in a worker thread with its own DB session: for every object the
definition is fetched once, then every applicable rule runs in turn. Catalog metadata is
collected lazily, once per object, and only when a rule whose text precondition holds needs
it. A rule whose precondition (text or metadata) fails completes without findings and
without an LLM call. Findings and progress are committed after each check so polling
clients see live progress.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models
from app.db import utcnow
from app.services.builtin_checks import ObjectRef, related_objects
from app.services.catalog import Catalog, CatalogError, ConnectionConfig, DefinitionReader
from app.services.exceptions import ExceptionMatcher, load_matchers
from app.services.llm import LlmConfig
from app.services.metadata import ObjectMetadata, empty_metadata, metadata_precondition_met
from app.services.rule_engine import (
    CheckContext,
    RuleError,
    RuleSpec,
    applies_to_object,
    mask_sql,
    precondition_met,
    run_rule,
)

logger = logging.getLogger("dwhcr.runner")

RESTART_MESSAGE = "Uygulama yeniden başlatıldı"
NO_METADATA = empty_metadata()  # for rules that do not read the catalog
DEFINITION_MISSING = "Nesne tanımı okunamadı (şifreli olabilir veya görüntüleme yetkisi yok)."


class AnalysisRunner:
    def __init__(self, session_factory: Callable[[], Session], workers: int = 2) -> None:
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analysis")
        # Called with the analysis id once an analysis reached its final state (scheduler).
        self.on_finished: Callable[[int], None] | None = None

    def submit(
        self,
        analysis_id: int,
        catalog: Catalog,
        config: ConnectionConfig,
        llm_config: LlmConfig | None,
    ) -> Future[None]:
        return self._executor.submit(self._run_safe, analysis_id, catalog, config, llm_config)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ internals
    def _run_safe(
        self,
        analysis_id: int,
        catalog: Catalog,
        config: ConnectionConfig,
        llm_config: LlmConfig | None,
    ) -> None:
        with self._session_factory() as session:
            try:
                self._run(session, analysis_id, catalog, config, llm_config)
            except Exception as error:  # noqa: BLE001 - the analysis must end in a final state
                logger.exception("analysis %s failed", analysis_id)
                session.rollback()
                analysis = session.get(models.Analysis, analysis_id)
                if analysis is not None:
                    analysis.status = "failed"
                    analysis.error = str(error) or type(error).__name__
                    analysis.finished_at = utcnow()
                    session.commit()
        if self.on_finished is not None:
            try:
                self.on_finished(analysis_id)
            except Exception:  # noqa: BLE001 - bookkeeping must not break the worker
                logger.exception("on_finished hook failed for analysis %s", analysis_id)

    @staticmethod
    def _cancel_requested(session: Session, analysis_id: int) -> bool:
        value = session.scalar(
            select(models.Analysis.cancel_requested).where(models.Analysis.id == analysis_id)
        )
        return value is None or bool(value)

    def _run(
        self,
        session: Session,
        analysis_id: int,
        catalog: Catalog,
        config: ConnectionConfig,
        llm_config: LlmConfig | None,
    ) -> None:
        analysis = session.get(models.Analysis, analysis_id)
        if analysis is None or analysis.status != "queued":
            return
        if analysis.cancel_requested:
            self._finish(session, analysis, "cancelled")
            return
        analysis.status = "running"
        analysis.started_at = utcnow()
        session.commit()

        snapshots = list(analysis.rules)
        specs = [(snap, RuleSpec.from_obj(snap)) for snap in snapshots]
        # Exceptions are read once per run (later edits do not affect a running analysis).
        matchers = load_matchers(session, (snap.rule_id for snap in snapshots))

        with ExitStack() as stack:
            try:
                reader = stack.enter_context(catalog.open_reader(config))
            except CatalogError as error:
                analysis.error = str(error)
                self._finish(session, analysis, "failed")
                return
            skipped_llm = 0
            for obj in list(analysis.objects):
                if self._cancel_requested(session, analysis_id):
                    self._finish(session, analysis, "cancelled")
                    return
                applicable = [
                    (s, r)
                    for s, r in specs
                    if applies_to_object(r, obj.database, obj.schema, obj.name, obj.type)
                ]
                skipped_llm += self._run_object(
                    session, analysis, obj, applicable, reader, llm_config, matchers
                )
                if analysis.status == "cancelled":
                    return

        if skipped_llm:
            logger.info(
                "analysis %s: %s LLM çağrısı ön koşul sağlanmadığı için atlandı",
                analysis_id,
                skipped_llm,
            )
        self._finish(session, analysis, "completed")

    def _run_object(
        self,
        session: Session,
        analysis: models.Analysis,
        obj: models.AnalysisObject,
        applicable: list[tuple[models.AnalysisRule, RuleSpec]],
        reader: DefinitionReader,
        llm_config: LlmConfig | None,
        matchers: dict[int, list[ExceptionMatcher]] | None = None,
    ) -> int:
        """Run the applicable checks of one object; returns the number of skipped LLM calls.

        Findings matching an exception of their rule are not stored, only counted in
        `suppressed_count` of the object and the analysis.
        """
        obj.status = "running"
        session.commit()

        try:
            definition = reader.fetch(obj.database, obj.schema, obj.name)
        except CatalogError as error:
            definition, fetch_error = None, str(error)
        else:
            fetch_error = None if definition is not None else DEFINITION_MISSING

        if definition is None:
            obj.status = "error"
            obj.error = fetch_error
            analysis.completed_checks += len(applicable)
            session.commit()
            return 0

        obj.definition = definition
        obj.line_count = len(definition.splitlines())
        session.commit()

        errors: list[str] = []
        notes: list[str] = []
        skipped_llm = 0
        object_name = f"{obj.schema}.{obj.name}"
        masked = mask_sql(definition)
        ref = ObjectRef(obj.database, obj.schema, obj.name, obj.type)
        extra = sorted(
            {
                item
                for _, spec in applicable
                if spec.kind == "builtin"
                for item in related_objects(spec.builtin_check, ref)
            }
        )
        cached: list[ObjectMetadata] = []

        def metadata() -> ObjectMetadata:
            if not cached:
                cached.append(self._describe(reader, ref, definition, masked, extra))
                if not cached[0].available:
                    notes.extend(cached[0].notes)
            return cached[0]

        for snapshot, spec in applicable:
            if self._cancel_requested(session, analysis.id):
                obj.status = "error" if errors else "done"
                obj.error = "; ".join(errors + notes) or None
                self._finish(session, analysis, "cancelled")
                return skipped_llm
            try:
                run = precondition_met(spec, definition, masked)
                object_metadata = NO_METADATA
                if run and spec.needs_metadata:
                    object_metadata = metadata()
                    run = metadata_precondition_met(spec.metadata_precondition, object_metadata)
                context = CheckContext(ref, object_metadata, masked)
                if run:
                    found = run_rule(spec, definition, object_name, llm_config, context)
                else:
                    found = []
                    skipped_llm += spec.kind == "llm"
            except RuleError as error:
                errors.append(f"{snapshot.code}: {error}")
                found = list(error.findings)  # e.g. the LLM chunks that did succeed
            except Exception as error:  # noqa: BLE001 - one check must not stop the run
                logger.exception("check %s on %s failed", snapshot.code, obj.label)
                errors.append(f"{snapshot.code}: {type(error).__name__}: {error}")
                found = []
            rule_matchers = (matchers or {}).get(snapshot.rule_id or -1, [])
            if rule_matchers:
                kept = [
                    item for item in found
                    if not any(
                        m.matches(obj.database, obj.schema, obj.name, item.snippet, item.message)
                        for m in rule_matchers
                    )
                ]
                hidden = len(found) - len(kept)
                if hidden:
                    obj.suppressed_count = (obj.suppressed_count or 0) + hidden
                    analysis.suppressed_count = (analysis.suppressed_count or 0) + hidden
                found = kept
            for item in found:
                session.add(
                    models.Finding(
                        analysis_id=analysis.id,
                        object_id=obj.id,
                        object_label=obj.label,
                        rule_code=snapshot.code,
                        rule_name=snapshot.name,
                        severity=snapshot.severity,
                        kind=snapshot.kind,
                        line=item.line,
                        snippet=item.snippet,
                        message=item.message,
                        recommendation=snapshot.recommendation,
                    )
                )
            obj.finding_count += len(found)
            if errors or notes:
                obj.error = "; ".join(errors + notes)[:2000]
            analysis.completed_checks += 1
            session.commit()

        obj.status = "error" if errors else "done"
        session.commit()
        return skipped_llm

    @staticmethod
    def _describe(
        reader: DefinitionReader,
        ref: ObjectRef,
        definition: str,
        masked: str,
        extra: list[tuple[str, str, str]],
    ) -> ObjectMetadata:
        """Catalog metadata of one object; failures give empty metadata with a short note."""
        describe = getattr(reader, "describe", None)
        if describe is None:
            return empty_metadata("Katalog metadatası bu bağlantıda okunamıyor.")
        try:
            result = describe(
                ref.database, ref.schema, ref.name, ref.type or "", definition, masked, extra
            )
        except Exception as error:  # noqa: BLE001 - metadata must never fail a check
            logger.info(
                "metadata for %s.%s.%s failed: %s", ref.database, ref.schema, ref.name, error
            )
            return empty_metadata(f"Katalog metadatası alınamadı: {type(error).__name__}")
        return result if isinstance(result, ObjectMetadata) else empty_metadata()

    @staticmethod
    def _finish(session: Session, analysis: models.Analysis, status: str) -> None:
        analysis.status = status
        analysis.finished_at = utcnow()
        session.commit()


def recover_interrupted(session: Session) -> int:
    """Mark analyses left queued/running by a previous process as failed."""
    result = session.execute(
        update(models.Analysis)
        .where(models.Analysis.status.in_(("queued", "running")))
        .values(status="failed", error=RESTART_MESSAGE, finished_at=utcnow())
    )
    session.execute(
        update(models.AnalysisObject)
        .where(models.AnalysisObject.status == "running")
        .values(status="error", error=RESTART_MESSAGE)
    )
    session.commit()
    return int(result.rowcount or 0)

