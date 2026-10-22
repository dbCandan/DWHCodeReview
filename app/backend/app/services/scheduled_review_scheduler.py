"""The scheduled review loop inside the backend process (sql-review 008, Decision 2).

Every tick, in this order and each step in its own transaction:

1. Due definitions are claimed with ``FOR UPDATE SKIP LOCKED``. A due time older than two ticks
   was missed while the application was down: it is recorded as ``missed`` and never caught up
   (Decision 9). A due definition whose previous run is still queued or running is recorded as
   ``skipped`` (Requirement 3). Otherwise a ``queued`` record opens. The next due time always
   follows from now.
2. Per tenant, under a transaction-scoped advisory lock, the oldest queued records start while
   fewer scheduled runs than the tenant's limit are running (Requirement 7). A run starts through
   the same review service as an object review and stores the recipient list with it
   (Requirement 4, 6). Without a published version the record is ``skipped``.
3. Summary e-mails whose time has come are sent; a failure is retried 1, 5 and 15 minutes later
   and then recorded as failed (Requirement 5, Decision 7). The state is stored, so a restart
   continues pending attempts.

The run itself is driven by a task of this process; its events are consumed here instead of a
browser stream. A record still running when the process starts again becomes ``interrupted``
(Requirement 8). Names, addresses, object names and SQL never reach a log line.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.domain.models.review import (
    ReviewFinding,
    ReviewRuleResult,
    ReviewRun,
    ReviewRunObject,
    ReviewRunStatus,
    Severity,
)
from app.domain.models.scheduled_review import (
    EmailStatus,
    ScheduledReview,
    ScheduledReviewRun,
    ScheduledRunState,
    ScheduledRunTrigger,
    SelectionMode,
    SkipReason,
)
from app.domain.models.user import User
from app.domain.review import ObjectSelection
from app.domain.scheduled_review import (
    Period,
    RunSummary,
    SummaryEmail,
    build_summary_email,
    email_retry_at,
    next_run_after,
    report_link,
    validate_period,
)
from app.infrastructure.mail.smtp_client import MailDeliveryError
from app.infrastructure.repositories.review_repository import ReviewRepository
from app.infrastructure.repositories.scheduled_review_repository import (
    ScheduledReviewRepository,
)
from app.services.review_run_service import ReviewExecution

logger = logging.getLogger("app.scheduled_review")

# Definitions, queued records and e-mails handled per tick and step; the rest wait for the next.
CLAIM_BATCH = 50
# Missing heartbeats of a running run are not a problem: the run reports only at its end.
_EVENT_IDLE_SECONDS = 5.0

_FINISHED_STATES = {
    ReviewRunStatus.COMPLETED.value: ScheduledRunState.COMPLETED,
    ReviewRunStatus.FAILED.value: ScheduledRunState.FAILED,
    ReviewRunStatus.CANCELLED.value: ScheduledRunState.CANCELLED,
    ReviewRunStatus.INTERRUPTED.value: ScheduledRunState.INTERRUPTED,
}


@dataclass(frozen=True, slots=True)
class ScheduledStart:
    """What the review service needs to start one scheduled run."""

    tenant_id: int
    owner_user_id: int
    owner_public_id: str
    scheduled_review_id: int
    selections: tuple[ObjectSelection, ...]
    rule_group_ids: tuple[str, ...]


class MailSender(Protocol):
    async def send(self, recipients: Sequence[str], email: SummaryEmail) -> int: ...


StartRun = Callable[[AsyncSession, ScheduledStart], Awaitable[ReviewExecution]]
ListObjects = Callable[[dict[str, Any]], Awaitable[list[ObjectSelection]]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _period(definition: ScheduledReview) -> Period:
    return validate_period(
        definition.frequency,
        hour=definition.run_hour,
        minute=definition.run_minute,
        timezone=definition.timezone,
        weekday=definition.weekday,
        day_of_month=definition.day_of_month,
    )


async def interrupt_stale_scheduled_runs(
    session_factory: async_sessionmaker[AsyncSession], *, now: datetime | None = None
) -> int:
    """At process start, scheduled records still running were cut off (Requirement 8)."""

    try:
        async with session_factory() as session, session.begin():
            count = await ScheduledReviewRepository(session).interrupt_running_records(
                now or _utcnow()
            )
    except Exception as error:  # noqa: BLE001 - reported with its type only
        log_event(logger, "scheduled_review.interrupt_failed", error_type=type(error).__name__)
        return 0
    log_event(logger, "scheduled_review.interrupted_at_startup", count=count)
    return count


async def list_selected_objects(
    selection: dict[str, Any], list_catalog: Callable[..., Awaitable[list[Any]]]
) -> list[ObjectSelection]:
    """The objects of a definition: the stored list, or the filter evaluated now (Decision 4)."""

    if selection.get("mode") == SelectionMode.LIST.value:
        return [
            ObjectSelection(item["database"], item["schema"], item["name"], item["type_code"])
            for item in selection.get("items", [])
        ]
    database = str(selection["database"])
    from_date = selection.get("from_date")
    rows = await list_catalog(
        database,
        query=selection.get("query") or None,
        from_date=date.fromisoformat(from_date) if from_date else None,
    )
    type_code = selection.get("type_code")
    return [
        ObjectSelection(database, row.schema, row.name, row.type_code)
        for row in rows
        if not type_code or row.type_code == type_code
    ]


class ScheduledReviewScheduler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        start_run: StartRun,
        list_objects: ListObjects,
        mailer: MailSender | None,
        public_origin: str,
        tick_seconds: float = 60.0,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session_factory = session_factory
        self._start_run = start_run
        self._list_objects = list_objects
        self._mailer = mailer
        self._public_origin = public_origin
        self._tick = timedelta(seconds=tick_seconds)
        self._clock = clock
        self._runs: set[asyncio.Task[None]] = set()

    async def run_forever(self) -> None:
        """Background task of the backend process; a failing tick is logged and retried."""

        await interrupt_stale_scheduled_runs(self._session_factory, now=self._clock())
        try:
            while True:
                try:
                    await self.tick()
                except Exception as error:  # noqa: BLE001 - reported with its type only
                    log_event(
                        logger, "scheduled_review.tick_failed", error_type=type(error).__name__
                    )
                await asyncio.sleep(self._tick.total_seconds())
        finally:
            for task in list(self._runs):
                task.cancel()

    async def tick(self) -> None:
        await self.queue_due_definitions()
        await self.start_queued_runs()
        await self.send_due_emails()

    async def drain(self) -> None:
        """Wait for the runs this scheduler drives (tests and an orderly shutdown)."""

        while self._runs:
            await asyncio.gather(*list(self._runs), return_exceptions=True)

    # --- step 1: due definitions ------------------------------------------------------------

    async def queue_due_definitions(self) -> None:
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            schedules = ScheduledReviewRepository(session)
            for definition in await schedules.claim_due_definitions(now, CLAIM_BATCH):
                due = definition.next_run_at
                assert due is not None
                state, reason = ScheduledRunState.QUEUED, None
                trigger = ScheduledRunTrigger.SCHEDULED
                if due < now - 2 * self._tick:
                    state, trigger = ScheduledRunState.MISSED, ScheduledRunTrigger.MISSED
                elif await schedules.has_open_run(definition.scheduled_review_id):
                    state, reason = ScheduledRunState.SKIPPED, SkipReason.PREVIOUS_RUNNING
                record = ScheduledReviewRun(
                    scheduled_review_id=definition.scheduled_review_id,
                    tenant_id=definition.tenant_id,
                    due_at=due,
                    trigger=trigger.value,
                    state=state.value,
                    skip_reason=reason.value if reason else None,
                )
                await schedules.add_run(record)
                definition.last_run_at = due
                definition.next_run_at = next_run_after(_period(definition), now)
                self._log_trigger(definition, record, state, reason)

    def _log_trigger(
        self,
        definition: ScheduledReview,
        record: ScheduledReviewRun,
        state: ScheduledRunState,
        reason: SkipReason | None,
    ) -> None:
        if state is ScheduledRunState.MISSED:
            log_event(
                logger,
                "scheduled_review.missed",
                schedule_public_id=definition.public_id,
                record_public_id=record.public_id,
            )
        elif state is ScheduledRunState.SKIPPED:
            log_event(
                logger,
                "scheduled_review.skipped",
                schedule_public_id=definition.public_id,
                reason=reason.value if reason else None,
            )

    # --- step 2: start queued runs under the tenant limit -------------------------------------

    async def start_queued_runs(self) -> None:
        async with self._session_factory() as session:
            tenants = await ScheduledReviewRepository(session).tenants_with_queued_runs()
        for tenant_id in tenants:
            await self._start_for_tenant(tenant_id)

    async def _start_for_tenant(self, tenant_id: int) -> None:
        async with self._session_factory() as session, session.begin():
            schedules = ScheduledReviewRepository(session)
            if not await schedules.lock_tenant_queue(tenant_id):
                return
            room = await schedules.max_concurrent_runs(tenant_id) - await schedules.running_count(
                tenant_id
            )
            if room <= 0:
                return
            started = 0
            for record in await schedules.oldest_queued(tenant_id, CLAIM_BATCH):
                if started >= room:
                    break
                if await self._start_record(session, schedules, record):
                    started += 1

    async def _start_record(
        self,
        session: AsyncSession,
        schedules: ScheduledReviewRepository,
        record: ScheduledReviewRun,
    ) -> bool:
        """Start one queued record; True when a run is now running for it."""

        definition = await schedules.get_definition_by_id(record.scheduled_review_id)
        owner = None if definition is None else await session.get(User, definition.owner_user_id)
        if definition is None or owner is None:
            self._end_record(record, ScheduledRunState.FAILED, error_code="schedule_unavailable")
            return False
        try:
            selections = await self._list_objects(dict(definition.selection))
        except ApplicationError as error:
            self._end_record(record, ScheduledRunState.FAILED, error_code=error.code)
            return False
        if not selections:
            self._skip(definition, record, SkipReason.NO_OBJECTS)
            return False
        start = ScheduledStart(
            tenant_id=definition.tenant_id,
            owner_user_id=owner.user_id,
            owner_public_id=owner.public_id,
            scheduled_review_id=definition.scheduled_review_id,
            selections=tuple(selections),
            rule_group_ids=tuple(definition.rule_group_ids),
        )
        try:
            # The review service commits the new run in a session of its own.
            async with self._session_factory() as run_session:
                execution = await self._start_run(run_session, start)
        except ApplicationError as error:
            if error.code == SkipReason.NO_PUBLISHED_RULE_SET.value:
                self._skip(definition, record, SkipReason.NO_PUBLISHED_RULE_SET)
            else:
                self._end_record(record, ScheduledRunState.FAILED, error_code=error.code)
            return False
        run = await session.scalar(
            select(ReviewRun).where(ReviewRun.public_id == execution.run_public_id)
        )
        assert run is not None
        record.state = ScheduledRunState.RUNNING.value
        record.review_run_id = run.review_run_id
        record.started_at = run.started_at
        # Requirement 6: the recipients of this run are the definition's list at its start.
        await schedules.add_recipients(run.review_run_id, list(definition.recipients))
        log_event(
            logger,
            "scheduled_review.triggered",
            schedule_public_id=definition.public_id,
            run_public_id=execution.run_public_id,
            trigger=record.trigger,
        )
        task = asyncio.create_task(self._drive(record.scheduled_review_run_id, execution))
        self._runs.add(task)
        task.add_done_callback(self._runs.discard)
        return True

    def _skip(
        self, definition: ScheduledReview, record: ScheduledReviewRun, reason: SkipReason
    ) -> None:
        record.state = ScheduledRunState.SKIPPED.value
        record.skip_reason = reason.value
        record.finished_at = self._clock()
        self._log_trigger(definition, record, ScheduledRunState.SKIPPED, reason)

    def _end_record(
        self, record: ScheduledReviewRun, state: ScheduledRunState, *, error_code: str | None
    ) -> None:
        record.state = state.value
        record.error_code = error_code
        record.finished_at = self._clock()
        log_event(
            logger,
            "scheduled_review.start_failed",
            record_public_id=record.public_id,
            error_code=error_code,
        )

    async def _drive(self, record_id: int, execution: ReviewExecution) -> None:
        """Consume the run's events to its end, then store the outcome and queue the e-mail."""

        async for _ in execution.events(_EVENT_IDLE_SECONDS):
            pass
        async with self._session_factory() as session, session.begin():
            schedules = ScheduledReviewRepository(session)
            record = await schedules.get_run_record(record_id, lock=True)
            if record is None or record.review_run_id is None:
                return
            run = await session.get(ReviewRun, record.review_run_id)
            status = run.status if run is not None else ReviewRunStatus.FAILED.value
            state = _FINISHED_STATES.get(status, ScheduledRunState.FAILED)
            record.state = state.value
            record.error_code = run.error_code if run is not None else None
            record.finished_at = self._clock()
            if state not in (ScheduledRunState.COMPLETED, ScheduledRunState.FAILED):
                return
            if self._mailer is None:
                record.email_status = EmailStatus.NOT_CONFIGURED.value
                log_event(
                    logger,
                    "scheduled_review.skipped",
                    record_public_id=record.public_id,
                    reason="smtp_not_configured",
                )
                return
            record.email_status = EmailStatus.PENDING.value
            record.next_email_at = self._clock()
        await self.send_due_emails()

    # --- step 3: summary e-mails -------------------------------------------------------------

    async def send_due_emails(self) -> None:
        if self._mailer is None:
            return
        async with self._session_factory() as session, session.begin():
            schedules = ScheduledReviewRepository(session)
            for record in await schedules.claim_due_emails(self._clock(), CLAIM_BATCH):
                await self._send(session, schedules, record)

    async def _send(
        self,
        session: AsyncSession,
        schedules: ScheduledReviewRepository,
        record: ScheduledReviewRun,
    ) -> None:
        assert self._mailer is not None
        summary, recipients = await self._summary(session, schedules, record)
        record.email_attempts += 1
        now = self._clock()
        if summary is None or not recipients:
            record.email_status = EmailStatus.FAILED.value
            record.next_email_at = None
            log_event(
                logger,
                "scheduled_review.email_failed",
                record_public_id=record.public_id,
                error_code="report_unavailable",
                recipient_count=len(recipients),
            )
            return
        email = build_summary_email(
            summary, report_link(self._public_origin, summary.run_public_id)
        )
        try:
            refused = await self._mailer.send(recipients, email)
        except MailDeliveryError as error:
            retry = email_retry_at(record.email_attempts, now)
            record.next_email_at = retry
            if retry is None:
                record.email_status = EmailStatus.FAILED.value
            log_event(
                logger,
                "scheduled_review.email_failed",
                record_public_id=record.public_id,
                error_code=error.code,
                attempt=record.email_attempts,
                will_retry=retry is not None,
                recipient_count=len(recipients),
            )
            return
        record.email_status = EmailStatus.SENT.value
        record.next_email_at = None
        log_event(
            logger,
            "scheduled_review.email_sent",
            record_public_id=record.public_id,
            recipient_count=len(recipients) - refused,
            refused_count=refused,
        )

    async def _summary(
        self,
        session: AsyncSession,
        schedules: ScheduledReviewRepository,
        record: ScheduledReviewRun,
    ) -> tuple[RunSummary | None, list[str]]:
        definition = await schedules.get_definition_by_id(record.scheduled_review_id)
        run = (
            None
            if record.review_run_id is None
            else await session.get(ReviewRun, record.review_run_id)
        )
        if definition is None or run is None:
            return None, []
        recipients = await schedules.recipients_of(run.review_run_id)
        groups = await ReviewRepository(session).selected_groups_of_run(run.review_run_id)
        rows = await session.execute(
            select(
                ReviewRuleResult.rule_group_names,
                ReviewFinding.severity,
                func.count(ReviewFinding.review_finding_id),
            )
            .join(
                ReviewRuleResult,
                ReviewRuleResult.review_rule_result_id == ReviewFinding.review_rule_result_id,
            )
            .join(
                ReviewRunObject,
                ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
            )
            .where(
                ReviewRunObject.review_run_id == run.review_run_id,
                ReviewFinding.is_deleted.is_(False),
            )
            .group_by(ReviewRuleResult.rule_group_names, ReviewFinding.severity)
        )
        # A finding counts under every group of its rule; an ungrouped rule counts under None.
        counts: dict[tuple[str | None, Severity], int] = {}
        for names, severity, count in rows:
            for group in names or [None]:
                key = (group, Severity(severity))
                counts[key] = counts.get(key, 0) + int(count)
        return (
            RunSummary(
                schedule_name=definition.name,
                run_public_id=run.public_id,
                started_at=run.started_at,
                timezone=definition.timezone,
                status=run.status,
                rule_groups=tuple(group.name for group in groups),
                object_count=run.object_count,
                finding_counts=counts,
            ),
            recipients,
        )
