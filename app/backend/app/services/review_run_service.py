"""Object and script review runs (sql-review/PRDs/003-object-review, 004-script-review).

A run starts only after the caller, the per-user limit, the request and the published rule set
have been checked; the run row and its selection rows are committed before the first event. The
review itself runs in its own task and reports through ``ReviewExecution.events``. When the
stream closes early (stop button or lost connection) the task is cancelled: no new LLM call
starts, running calls close, the run is stored as cancelled and no partial result is written.
SQL text, snippets, metadata, labels and model replies never reach a log line.

A run has no object limit (003 Decision 3), so its memory must not follow the selection size:
only ``ReviewRuntime.objects_in_flight`` objects are read from SQL Server and reviewed at a time,
the event queue is bounded so a slow reader holds the run back, and the results are written in
chunks. What grows with the selection is the outcome of each finished object, kept until the
single transaction that stores the run.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, cast

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.core.request_context import RequestContext
from app.core.review_throttle import ReviewRateLimiter
from app.core.telemetry import (
    RunOutcome,
    record_review_run_started,
    record_rule_call,
    record_rule_results,
    review_run,
)
from app.domain.llm import LlmChatPort, LlmEndpoint, LlmNotConfigured, LlmRunSession
from app.domain.models.review import ReviewRunKind, ReviewRunStatus, RuleResultStatus
from app.domain.review import (
    LABEL_MAX_LENGTH,
    REVIEWED_SQL_MAX_LENGTH,
    SCRIPT_DEFAULT_LABEL,
    SCRIPT_SCHEMA,
    SCRIPT_TYPE,
    MetadataContext,
    MetadataSource,
    ObjectOutcome,
    ObjectSelection,
    ReviewRule,
    ordered_rules,
)
from app.domain.rule_set import RuleGroup, RuleSetValidationError
from app.domain.sql_server import (
    CATALOG_OBJECT_TYPES,
    DATABASE_NOT_ALLOWED_CODE,
    DATABASE_NOT_ALLOWED_MESSAGE,
    NOT_CONFIGURED_CODE,
    NOT_CONFIGURED_MESSAGE,
    SQL_SERVER_ERROR_MESSAGES,
    DatabaseNotAllowed,
    SqlCatalogPort,
    SqlServerError,
    SqlServerErrorClass,
    SqlServerNotConfigured,
)
from app.infrastructure.repositories.review_repository import (
    NewRunObject,
    ReviewRepository,
    StoredResult,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.schemas.reviews.contracts import (
    FindingItem,
    LiveObjectResultItem,
    RuleResultItem,
)
from app.schemas.reviews.events import (
    CompleteEvent,
    DefinitionFetchEvent,
    ErrorEvent,
    LlmStreamEvent,
    MetadataFetchEvent,
    MetadataReadyEvent,
    ObjectDoneEvent,
    ObjectErrorEvent,
    ObjectStartEvent,
    ReviewEvent,
    RuleDoneEvent,
    RulesBatchStartEvent,
    RuleStartEvent,
    RunStartedEvent,
    SelectedRuleGroup,
    SqlReadyEvent,
)
from app.services.request_scope import acting_user, active_tenant
from app.services.review_engine import (
    ReviewScope,
    RuleEvent,
    RuleFinished,
    RulesBatchStarted,
    RuleStarted,
    RuleStreamed,
    TextReviewer,
)
from app.services.rule_set_service import RuleSetService

logger = logging.getLogger("app.review")

OBJECT_NOT_FOUND_CODE = "object_not_found"
OBJECT_NOT_FOUND_MESSAGE = "Tanım alınamadı (nesne yok veya yetki yok)."
LLM_NOT_CONFIGURED_CODE = "llm_not_configured"
LLM_NOT_CONFIGURED_MESSAGE = "LLM bağlantısı yapılandırılmamış."
REVIEW_FAILED_CODE = "review_failed"
REVIEW_FAILED_MESSAGE = "İnceleme tamamlanamadı."
INTERRUPTED_CODE = "review_interrupted"
INTERRUPTED_MESSAGE = "İnceleme yarıda kesildi."

# Events waiting for the stream reader; a full queue makes the run wait for the reader.
EVENT_QUEUE_MAX_EVENTS = 256
# The complete event carries the results of a run of at most this many objects, which is one page
# of the stored run detail; a larger run is read from that detail page by page (005 Requirement 3).
LIVE_RESULTS_MAX_OBJECTS = 50

EventSink = Callable[[ReviewEvent], Awaitable[None]]
_ENDED: Final = object()


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def review_text_limit(settings: Settings) -> int:
    """The reviewed-text limit: the setting, never above what a run object can store."""

    return min(settings.review_max_sql_chars, REVIEWED_SQL_MAX_LENGTH)


def _unprocessable(code: str, message: str) -> ApplicationError:
    return ApplicationError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


class ReviewRunRegistry:
    """The review tasks of this process; a shutdown ends them as interrupted, not cancelled."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._by_run: dict[str, asyncio.Task[None]] = {}
        self.shutting_down = False

    def track(self, task: asyncio.Task[None], run_public_id: str | None = None) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if run_public_id is not None:
            self._by_run[run_public_id] = task
            task.add_done_callback(lambda _: self._by_run.pop(run_public_id, None))

    def cancel(self, run_public_id: str) -> bool:
        """Requirement 15 by request: stop the run's task in this process; False if none runs."""

        task = self._by_run.get(run_public_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self, timeout: float = 5.0) -> None:
        self.shutting_down = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)


async def interrupt_stale_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """At process start, runs still marked running were cut off (Requirement 16).

    A database that is not reachable yet does not stop the start; the next start retries.
    """

    try:
        async with session_factory() as session, session.begin():
            count = await ReviewRepository(session).interrupt_running_runs(
                finished_at=datetime.now(UTC),
                error_code=INTERRUPTED_CODE,
                error_message=INTERRUPTED_MESSAGE,
            )
    except Exception as error:  # noqa: BLE001 - reported with its type only
        log_event(logger, "review_run.interrupt_failed", error_type=type(error).__name__)
        return 0
    log_event(logger, "review_run.interrupted_at_startup", count=count)
    return count


@dataclass(frozen=True, slots=True)
class _PlannedObject:
    position: int
    selection: ObjectSelection
    object_type: str
    object_label: str

    def event_fields(self, kind: ReviewRunKind, total: int) -> dict[str, Any]:
        return {
            "kind": kind.value,
            "database": self.selection.database,
            "object_index": self.position,
            "objects_total": total,
            "object_label": self.object_label,
            "schema": self.selection.schema,
            "name": self.selection.name,
            "type_code": self.selection.type_code,
        }


def metric_kind(kind: ReviewRunKind) -> str:
    """The kind label of the run metrics; a scheduled run counts as an object run.

    sql-review 008-scheduled-review-email Decision 10: no new metric, and the existing run
    metrics keep their label values.
    """

    return ReviewRunKind.OBJECT.value if kind is ReviewRunKind.SCHEDULED else kind.value


@dataclass(frozen=True, slots=True)
class _RunPlan:
    run_id: int
    run_public_id: str
    tenant_id: int
    owner_user_id: int
    owner_public_id: str
    kind: ReviewRunKind
    rule_version: int
    rules: tuple[ReviewRule, ...]
    objects: tuple[_PlannedObject, ...]
    script_sql: str | None = field(default=None, repr=False)
    # rule-group-selection Requirement 5: the groups and single rules the run reviews with;
    # both empty = every rule.
    selected_groups: tuple[RuleGroup, ...] = ()
    selected_rule_codes: tuple[str, ...] = ()

    @property
    def rule_group_names(self) -> dict[str, tuple[str, ...]]:
        return {rule.code: rule.group_names for rule in self.rules}


@dataclass(frozen=True, slots=True)
class ReviewRuntime:
    """Process-wide collaborators of a running review."""

    llm: LlmChatPort
    session_factory: async_sessionmaker[AsyncSession]
    registry: ReviewRunRegistry
    reviewer: TextReviewer
    text_limit: int
    # Objects read and reviewed at the same time: the per-run LLM call limit, so every LLM slot
    # stays busy while no more SQL text is held than the calls in progress can use.
    objects_in_flight: int = 1


def _live_results(
    plan: _RunPlan, outcomes: Sequence[ObjectOutcome], stored: Sequence[StoredResult]
) -> list[LiveObjectResultItem]:
    results: list[LiveObjectResultItem] = []
    names = plan.rule_group_names
    for planned, outcome, ids in zip(plan.objects, outcomes, stored, strict=True):
        finding_ids = iter(ids.finding_ids)
        rule_results = [
            RuleResultItem(
                id=result_id,
                rule_id=check.rule_code,
                tier=check.tier.value,
                status=check.status.value,
                severity=None if check.severity is None else check.severity.value,
                decision_basis=check.decision_basis or None,
                description=check.description,
                line_reference=check.line_reference,
                code_snippet=check.code_snippet,
                false_positive=False,
                rule_group_names=list(names.get(check.rule_code, ())),
            )
            for result_id, check in zip(ids.rule_result_ids, outcome.checks, strict=True)
        ]
        findings = [
            FindingItem(
                id=next(finding_ids),
                rule_id=finding.rule_code,
                severity=finding.severity.value,
                description=finding.description,
                line_reference=finding.line_reference,
                code_snippet=finding.code_snippet,
                false_positive=False,
            )
            for check in outcome.checks
            for finding in outcome.findings
            if finding.rule_code == check.rule_code
        ]
        results.append(
            LiveObjectResultItem(
                database=planned.selection.database,
                schema=planned.selection.schema,
                name=planned.selection.name,
                object_type=planned.object_type,
                type_code=planned.selection.type_code,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
                parse_warning=outcome.warning,
                rule_results=rule_results,
                findings=findings,
                source_sql=outcome.source_sql,
            )
        )
    return results


def _root_error(error: BaseException) -> BaseException:
    """The first leaf of nested task-group failures."""

    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


class ReviewExecution:
    """One started run: iterate ``events`` to drive it; closing the iterator stops it."""

    def __init__(
        self, plan: _RunPlan, runtime: ReviewRuntime, catalog: SqlCatalogPort | None
    ) -> None:
        self._plan = plan
        self._runtime = runtime
        self._catalog = catalog
        # The queue also carries _ENDED once the task is over, so a reader of a run stopped by
        # request (which ends without a final event) returns at once.
        self._queue: asyncio.Queue[ReviewEvent | object] = asyncio.Queue(EVENT_QUEUE_MAX_EVENTS)
        self.task: asyncio.Task[None] | None = None

    @property
    def run_public_id(self) -> str:
        return self._plan.run_public_id

    def start(self) -> None:
        """Start the review task; its events wait in order until ``events`` reads them.

        The queue is bounded: once it is full the review waits for the reader.
        """

        if self.task is None:
            self.task = asyncio.create_task(self._run(self._queue.put))
            self.task.add_done_callback(self._mark_ended)
            self._runtime.registry.track(self.task, self._plan.run_public_id)

    def cancel(self) -> None:
        """Requirement 15: stop starting calls, close running ones, store the run cancelled."""

        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def events(self, idle_seconds: float) -> AsyncIterator[ReviewEvent | None]:
        """Events in order until ``complete`` or ``error``; ``None`` after each idle period.

        Closing the iterator early stops the run.
        """

        self.start()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(self._queue.get(), idle_seconds)
                except TimeoutError:
                    if self.task is not None and self.task.done() and self._queue.empty():
                        return
                    yield None
                    continue
                if item is _ENDED:
                    return
                event = cast(ReviewEvent, item)
                yield event
                if isinstance(event, (CompleteEvent, ErrorEvent)):
                    return
        finally:
            # Nothing here awaits: this may run inside an already cancelled scope.
            self.cancel()

    def _mark_ended(self, _: asyncio.Task[None]) -> None:
        try:
            self._queue.put_nowait(_ENDED)
        except asyncio.QueueFull:
            # The reader drains the queue first and then sees the task done on its next wait.
            pass

    async def _run(self, emit: EventSink) -> None:
        plan = self._plan
        with review_run(
            metric_kind(plan.kind), object_count=len(plan.objects), rule_count=len(plan.rules)
        ) as run:
            await self._run_to_end(emit, run)

    async def _run_to_end(self, emit: EventSink, run: RunOutcome) -> None:
        """Drive the run and note its stored final status on ``run``; a cancellation re-raises."""

        plan = self._plan
        started = time.monotonic()
        try:
            await emit(
                RunStartedEvent(
                    run_id=plan.run_public_id,
                    kind=plan.kind.value,
                    rule_version=plan.rule_version,
                    objects_total=len(plan.objects),
                    selected_rule_groups=[
                        SelectedRuleGroup(id=group.public_id, name=group.name)
                        for group in plan.selected_groups
                    ],
                    selected_rule_codes=list(plan.selected_rule_codes),
                    all_rules=not plan.selected_groups and not plan.selected_rule_codes,
                )
            )
            async with self._runtime.llm.open_run() as session:
                outcomes = await self._review(session, emit)
            stored = await self._complete(outcomes)
        except asyncio.CancelledError:
            interrupted = self._runtime.registry.shutting_down
            ended = ReviewRunStatus.INTERRUPTED if interrupted else ReviewRunStatus.CANCELLED
            await asyncio.shield(
                self._finish(
                    ended,
                    INTERRUPTED_CODE if interrupted else None,
                    INTERRUPTED_MESSAGE if interrupted else None,
                )
            )
            self._log("review_run.cancelled", started, status=ended.value)
            run.status = ended.value
            raise
        except Exception as error:  # noqa: BLE001 - reported as a fixed class, never as text
            root = _root_error(error)
            if isinstance(root, LlmNotConfigured):
                code, message = LLM_NOT_CONFIGURED_CODE, LLM_NOT_CONFIGURED_MESSAGE
            else:
                code, message = REVIEW_FAILED_CODE, REVIEW_FAILED_MESSAGE
            await self._finish(ReviewRunStatus.FAILED, code, message)
            self._log(
                "review_run.failed",
                started,
                error_code=code,
                error_type=type(root).__name__,
            )
            run.status = ReviewRunStatus.FAILED.value
            await emit(ErrorEvent(code=code, message=message))
            return
        if stored is None:
            self._log("review_run.failed", started, error_code=REVIEW_FAILED_CODE)
            run.status = ReviewRunStatus.FAILED.value
            await emit(ErrorEvent(code=REVIEW_FAILED_CODE, message=REVIEW_FAILED_MESSAGE))
            return
        record_rule_results(
            metric_kind(plan.kind),
            (check.status.value for outcome in outcomes for check in outcome.checks),
        )
        self._log(
            "review_run.completed",
            started,
            unknown_count=sum(
                1
                for outcome in outcomes
                for check in outcome.checks
                if check.status is RuleResultStatus.UNKNOWN
            ),
            object_error_count=sum(1 for outcome in outcomes if outcome.error_code),
        )
        run.status = ReviewRunStatus.COMPLETED.value
        if len(plan.objects) <= LIVE_RESULTS_MAX_OBJECTS:
            complete = CompleteEvent(
                run_id=plan.run_public_id, results=_live_results(plan, outcomes, stored)
            )
        else:
            complete = CompleteEvent(run_id=plan.run_public_id, results=[], results_omitted=True)
        await emit(complete)

    def _log(self, event: str, started: float, **fields: str | int | bool | None) -> None:
        plan = self._plan
        extra: dict[str, str | int | bool | None] = {}
        if plan.kind is ReviewRunKind.SCRIPT and plan.script_sql is not None:
            extra = {
                "sql_length": len(plan.script_sql),
                "two_part": len(plan.script_sql) > self._runtime.reviewer.threshold,
            }
        log_event(
            logger,
            event,
            run_id=plan.run_public_id,
            user_public_id=plan.owner_public_id,
            kind=plan.kind.value,
            rule_version=plan.rule_version,
            object_count=len(plan.objects),
            rule_count=len(plan.rules),
            duration_ms=int((time.monotonic() - started) * 1000),
            **extra,
            **fields,
        )

    async def _review(self, session: LlmRunSession, emit: EventSink) -> list[ObjectOutcome]:
        plan = self._plan
        if plan.kind is ReviewRunKind.SCRIPT:
            return [await self._review_script(session, emit)]
        # Workers take the next object only when they finished the previous one, so at most
        # ``objects_in_flight`` definitions are fetched and held, whatever the selection size.
        outcomes: dict[int, ObjectOutcome] = {}
        waiting = iter(plan.objects)

        async def worker() -> None:
            for planned in waiting:
                outcomes[planned.position] = await self._review_object(session, planned, emit)

        workers = max(1, min(self._runtime.objects_in_flight, len(plan.objects)))
        async with asyncio.TaskGroup() as group:
            for _ in range(workers):
                group.create_task(worker())
        return [outcomes[planned.position] for planned in plan.objects]

    def _scope(self, planned: _PlannedObject) -> ReviewScope:
        return ReviewScope(
            tenant_id=self._plan.tenant_id,
            object_label=planned.object_label,
            review_run_id=self._plan.run_id,
            review_run_public_id=self._plan.run_public_id,
        )

    def _rule_sink(
        self, fields: dict[str, Any], emit: EventSink
    ) -> Callable[[RuleEvent], Awaitable[None]]:
        async def sink(event: RuleEvent) -> None:
            if isinstance(event, RulesBatchStarted):
                await emit(RulesBatchStartEvent(**fields, rules_total=event.rules_total))
            elif isinstance(event, RuleStarted):
                await emit(
                    RuleStartEvent(
                        **fields,
                        rule_id=event.rule_code,
                        tier=event.tier.value,
                        rule_index=event.rule_index,
                        rules_total=event.rules_total,
                        sql_two_part=event.two_part,
                    )
                )
            elif isinstance(event, RuleStreamed):
                await emit(
                    LlmStreamEvent(
                        **fields,
                        rule_id=event.rule_code,
                        completion_tokens=event.completion_tokens,
                        total_chars=event.total_chars,
                    )
                )
            elif isinstance(event, RuleFinished):
                record_rule_call(metric_kind(self._plan.kind), ok=event.ok)
                await emit(
                    RuleDoneEvent(
                        **fields,
                        rule_id=event.rule_code,
                        tier=event.tier.value,
                        rule_index=event.rule_index,
                        rules_total=event.rules_total,
                        ok=event.ok,
                        sql_two_part=event.two_part,
                        completion_tokens=event.completion_tokens,
                        total_chars=event.total_chars,
                    )
                )

        return sink

    async def _review_script(self, session: LlmRunSession, emit: EventSink) -> ObjectOutcome:
        plan = self._plan
        planned = plan.objects[0]
        sql = plan.script_sql or ""
        fields = planned.event_fields(plan.kind, 1)
        await emit(ObjectStartEvent(**fields))
        await emit(SqlReadyEvent(**fields, sql_length=len(sql)))
        review = await self._runtime.reviewer.review(
            session,
            sql=sql,
            rules=plan.rules,
            metadata=MetadataContext(MetadataSource.NOT_AVAILABLE_FOR_SCRIPT),
            scope=self._scope(planned),
            emit=self._rule_sink(fields, emit),
        )
        await emit(ObjectDoneEvent(**fields))
        return ObjectOutcome(planned.position, source_sql=sql, review=review)

    async def _object_error(
        self,
        planned: _PlannedObject,
        fields: dict[str, Any],
        emit: EventSink,
        code: str,
        message: str,
    ) -> ObjectOutcome:
        log_event(
            logger,
            "review_run.object_error",
            run_id=self._plan.run_public_id,
            database=planned.selection.database,
            schema=planned.selection.schema,
            name=planned.selection.name,
            error_code=code,
        )
        await emit(ObjectErrorEvent(**fields, code=code, message=message))
        return ObjectOutcome(planned.position, error_code=code, error_message=message)

    async def _review_object(
        self, session: LlmRunSession, planned: _PlannedObject, emit: EventSink
    ) -> ObjectOutcome:
        plan = self._plan
        catalog = self._catalog
        assert catalog is not None
        selection = planned.selection
        fields = planned.event_fields(plan.kind, len(plan.objects))
        await emit(ObjectStartEvent(**fields))
        await emit(DefinitionFetchEvent(**fields))
        try:
            definition = await catalog.fetch_definition(
                selection.database,
                selection.schema,
                selection.name,
                selection.type_code,
            )
        except SqlServerError as error:
            return await self._object_error(
                planned, fields, emit, error.error_class.value, error.message
            )
        except SqlServerNotConfigured:
            return await self._object_error(
                planned, fields, emit, NOT_CONFIGURED_CODE, NOT_CONFIGURED_MESSAGE
            )
        except DatabaseNotAllowed:
            return await self._object_error(
                planned,
                fields,
                emit,
                DATABASE_NOT_ALLOWED_CODE,
                DATABASE_NOT_ALLOWED_MESSAGE,
            )
        except Exception:  # noqa: BLE001 - Requirement 5: the other objects continue
            failed = SqlServerErrorClass.QUERY_FAILED
            return await self._object_error(
                planned, fields, emit, failed.value, SQL_SERVER_ERROR_MESSAGES[failed]
            )
        if not definition or not definition.strip():
            return await self._object_error(
                planned, fields, emit, OBJECT_NOT_FOUND_CODE, OBJECT_NOT_FOUND_MESSAGE
            )
        await emit(SqlReadyEvent(**fields, sql_length=len(definition)))
        metadata = MetadataContext(MetadataSource.FETCHED)
        if any(rule.requires_metadata for rule in plan.rules):
            await emit(MetadataFetchEvent(**fields))
            try:
                summary = await catalog.fetch_object_metadata(
                    selection.database, selection.schema, selection.name
                )
                metadata = MetadataContext(MetadataSource.FETCHED, summary)
            except Exception as error:  # noqa: BLE001 - Requirement 6: the review continues
                metadata = MetadataContext(MetadataSource.FAILED)
                log_event(
                    logger,
                    "review_run.metadata_unavailable",
                    run_id=plan.run_public_id,
                    database=selection.database,
                    schema=selection.schema,
                    name=selection.name,
                    error_code=(
                        error.error_class.value
                        if isinstance(error, SqlServerError)
                        else type(error).__name__
                    ),
                )
            await emit(MetadataReadyEvent(**fields))
        limit = self._runtime.text_limit
        reviewed = definition[:limit]
        note = (
            f"Metnin yalnız ilk {_thousands(limit)} karakteri incelendi."
            if len(definition) > limit
            else None
        )
        review = await self._runtime.reviewer.review(
            session,
            sql=reviewed,
            rules=plan.rules,
            metadata=metadata,
            scope=self._scope(planned),
            emit=self._rule_sink(fields, emit),
            leading_note=note,
        )
        await emit(ObjectDoneEvent(**fields))
        return ObjectOutcome(planned.position, source_sql=reviewed, review=review)

    async def _complete(self, outcomes: Sequence[ObjectOutcome]) -> list[StoredResult] | None:
        """Store the run; the identifiers come back only when the complete event shows them."""

        async with self._runtime.session_factory() as session, session.begin():
            return await ReviewRepository(session).complete_run(
                self._plan.run_id,
                owner_user_id=self._plan.owner_user_id,
                finished_at=datetime.now(UTC),
                outcomes=outcomes,
                collect_identifiers=len(outcomes) <= LIVE_RESULTS_MAX_OBJECTS,
                rule_group_names=self._plan.rule_group_names,
            )

    async def _finish(
        self, ended: ReviewRunStatus, error_code: str | None, error_message: str | None
    ) -> None:
        try:
            async with self._runtime.session_factory() as session, session.begin():
                await ReviewRepository(session).finish_run(
                    self._plan.run_id,
                    status=ended,
                    finished_at=datetime.now(UTC),
                    error_code=error_code,
                    error_message=error_message,
                )
        except Exception as error:  # noqa: BLE001 - the startup check interrupts it later
            log_event(
                logger,
                "review_run.finish_failed",
                run_id=self._plan.run_public_id,
                error_type=type(error).__name__,
            )


class ReviewRunService:
    """Request-scoped start of a run; the returned execution outlives the request session."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        runtime: ReviewRuntime,
        llm_endpoint: Callable[[], LlmEndpoint | None],
        limiter: ReviewRateLimiter,
        catalog: SqlCatalogPort | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.runtime = runtime
        self.llm_endpoint = llm_endpoint
        self.limiter = limiter
        self.catalog = catalog
        self.users = UserRepository(session)
        self.reviews = ReviewRepository(session)

    async def start_object_review(
        self,
        context: RequestContext,
        selections: Sequence[ObjectSelection],
        rule_group_ids: Sequence[str] = (),
        rule_codes: Sequence[str] = (),
    ) -> ReviewExecution:
        tenant_id, actor_id, actor_public_id = await self._admit(context)
        catalog, planned = self._plan_objects(selections)
        return await self._create(
            tenant_id,
            actor_id,
            actor_public_id,
            ReviewRunKind.OBJECT,
            planned,
            catalog=catalog,
            rule_group_ids=rule_group_ids,
            rule_codes=rule_codes,
        )

    async def start_scheduled_review(
        self,
        *,
        tenant_id: int,
        owner_user_id: int,
        owner_public_id: str,
        scheduled_review_id: int,
        selections: Sequence[ObjectSelection],
        rule_group_ids: Sequence[str] = (),
    ) -> ReviewExecution:
        """Start a run of a scheduled review definition (sql-review 008 Requirement 4).

        The same checks and execution as an object review, without a request: the run belongs to
        the definition's owner, carries the scheduled kind and its definition, and its events are
        consumed on the server instead of a browser stream.
        """

        catalog, planned = self._plan_objects(selections)
        return await self._create(
            tenant_id,
            owner_user_id,
            owner_public_id,
            ReviewRunKind.SCHEDULED,
            planned,
            catalog=catalog,
            rule_group_ids=rule_group_ids,
            scheduled_review_id=scheduled_review_id,
        )

    def _plan_objects(
        self, selections: Sequence[ObjectSelection]
    ) -> tuple[SqlCatalogPort, list[_PlannedObject]]:
        if not selections:
            raise _unprocessable("selection_empty", "İncelemek için en az bir nesne seçin.")
        if any(item.type_code not in CATALOG_OBJECT_TYPES for item in selections):
            raise _unprocessable("object_type_invalid", "Nesne türü desteklenmiyor.")
        catalog = self.catalog
        assert catalog is not None
        if any(not catalog.is_allowed(item.database) for item in selections):
            raise ApplicationError(
                status.HTTP_403_FORBIDDEN,
                DATABASE_NOT_ALLOWED_CODE,
                DATABASE_NOT_ALLOWED_MESSAGE,
            )
        planned = [
            _PlannedObject(
                position,
                item,
                CATALOG_OBJECT_TYPES[item.type_code],
                f"[{item.database}] {item.schema}.{item.name} "
                f"({CATALOG_OBJECT_TYPES[item.type_code]})",
            )
            for position, item in enumerate(selections)
        ]
        return catalog, planned

    async def start_script_review(
        self,
        context: RequestContext,
        sql: str,
        label: str | None,
        rule_group_ids: Sequence[str] = (),
        rule_codes: Sequence[str] = (),
    ) -> ReviewExecution:
        tenant_id, actor_id, actor_public_id = await self._admit(context)
        text = sql.strip()
        if not text:
            raise _unprocessable("sql_text_empty", "SQL metni boş olamaz.")
        limit = self.runtime.text_limit
        if len(text) > limit:
            raise _unprocessable(
                "sql_text_too_long",
                f"SQL metni en çok {_thousands(limit)} karakter olabilir.",
            )
        display = (label or "").strip() or SCRIPT_DEFAULT_LABEL
        if len(display) > LABEL_MAX_LENGTH:
            raise _unprocessable(
                "label_too_long", f"Etiket en çok {LABEL_MAX_LENGTH} karakter olabilir."
            )
        planned = [
            _PlannedObject(
                0,
                ObjectSelection("", SCRIPT_SCHEMA, display, SCRIPT_TYPE),
                SCRIPT_TYPE,
                f"{display} ({SCRIPT_TYPE})",
            )
        ]
        return await self._create(
            tenant_id,
            actor_id,
            actor_public_id,
            ReviewRunKind.SCRIPT,
            planned,
            label=display,
            script_sql=text,
            rule_group_ids=rule_group_ids,
            rule_codes=rule_codes,
        )

    async def _admit(self, context: RequestContext) -> tuple[int, int, str]:
        tenant = await active_tenant(self.users, context)
        actor = await acting_user(self.users, context)
        wait = self.limiter.acquire(
            (tenant.tenant_id, actor.user_id),
            max_requests=self.settings.review_rate_limit_max_requests,
            window_seconds=self.settings.review_rate_limit_window_seconds,
        )
        if wait is not None:
            raise ApplicationError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                "Çok fazla inceleme başlattınız; biraz sonra yeniden deneyin.",
                headers={"Retry-After": str(wait)},
            )
        return tenant.tenant_id, actor.user_id, actor.public_id

    async def _create(
        self,
        tenant_id: int,
        actor_id: int,
        actor_public_id: str,
        kind: ReviewRunKind,
        planned: list[_PlannedObject],
        *,
        catalog: SqlCatalogPort | None = None,
        label: str | None = None,
        script_sql: str | None = None,
        rule_group_ids: Sequence[str] = (),
        rule_codes: Sequence[str] = (),
        scheduled_review_id: int | None = None,
    ) -> ReviewExecution:
        if self.llm_endpoint() is None:
            raise ApplicationError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                LLM_NOT_CONFIGURED_CODE,
                LLM_NOT_CONFIGURED_MESSAGE,
            )
        # Requirement 4: the latest published version is read once and pinned to the run.
        rule_set = await RuleSetService(self.session).latest_published_rule_set(tenant_id)
        if rule_set is None:
            raise ApplicationError(
                status.HTTP_409_CONFLICT,
                "no_published_rule_set",
                "Yayımlanmış kural olmadığı için inceleme başlatılamaz.",
            )
        # rule-group-selection Requirement 4: restrict the pinned version to the selection.
        try:
            selected = rule_set.select(rule_group_ids, rule_codes)
        except RuleSetValidationError as error:
            raise _unprocessable(error.code, error.message) from None
        group_ids = set(rule_group_ids)
        selected_groups = [
            (position, group)
            for position, group in enumerate(rule_set.rules.rule_groups)
            if group.public_id in group_ids
        ]
        codes = set(rule_codes)
        selected_codes = [
            rule.code
            for _, members in rule_set.rules.grouped()
            for rule in members
            if rule.code in codes
        ]
        run = await self.reviews.create_run(
            tenant_id=tenant_id,
            owner_user_id=actor_id,
            kind=kind.value,
            label=label,
            rule_set_version_id=rule_set.version_id,
            started_at=datetime.now(UTC),
            objects=[
                NewRunObject(
                    database=item.selection.database or None,
                    schema=item.selection.schema,
                    name=item.selection.name,
                    type_code=item.selection.type_code,
                    object_type=item.object_type,
                )
                for item in planned
            ],
            selected_groups=selected_groups,
            selected_rule_codes=selected_codes,
            scheduled_review_id=scheduled_review_id,
        )
        await self.session.commit()
        # The request session lives as long as the stream; it must not keep a row per object.
        self.session.expunge_all()
        plan = _RunPlan(
            run_id=run.review_run_id,
            run_public_id=run.public_id,
            tenant_id=tenant_id,
            owner_user_id=actor_id,
            owner_public_id=actor_public_id,
            kind=kind,
            rule_version=rule_set.number,
            rules=ordered_rules(selected),
            objects=tuple(planned),
            script_sql=script_sql,
            selected_groups=tuple(group for _, group in selected_groups),
            selected_rule_codes=tuple(selected_codes),
        )
        log_event(
            logger,
            "review_run.started",
            run_id=plan.run_public_id,
            user_public_id=actor_public_id,
            kind=kind.value,
            rule_version=plan.rule_version,
            object_count=len(planned),
            rule_count=len(plan.rules),
            rule_group_count=len(plan.selected_groups),
            selected_rule_count=len(plan.selected_rule_codes),
        )
        record_review_run_started(metric_kind(kind))
        return ReviewExecution(plan, self.runtime, catalog)
