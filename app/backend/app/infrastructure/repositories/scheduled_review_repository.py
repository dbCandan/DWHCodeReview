"""Persistence of scheduled review definitions, their run records, run recipients and setting.

sql-review/PRDs/008-scheduled-review-email. Every read is scoped to one tenant. The scheduler's
claims take rows with ``FOR UPDATE SKIP LOCKED``, so several backend copies never handle the same
due time, queued run or e-mail attempt twice (Requirement 3). Definitions are deleted physically
with their run records; review runs stay and lose the link.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.models.review import (
    ReviewFinding,
    ReviewRuleResult,
    ReviewRun,
    ReviewRunObject,
)
from app.domain.models.scheduled_review import (
    MAX_CONCURRENT_RUNS_DEFAULT,
    EmailStatus,
    ReviewRunRecipient,
    ScheduledReview,
    ScheduledReviewRun,
    ScheduledReviewSetting,
    ScheduledReviewStatus,
    ScheduledRunState,
)
from app.domain.models.user import User

OPEN_STATES = (ScheduledRunState.QUEUED.value, ScheduledRunState.RUNNING.value)


@dataclass(frozen=True, slots=True)
class DefinitionRow:
    definition: ScheduledReview
    owner_name: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    record: ScheduledReviewRun
    review_run_public_id: str | None
    triggered_by_name: str | None
    finding_count: int | None


class ScheduledReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- definitions ------------------------------------------------------------------------

    def _definitions(self, tenant_id: int) -> Select[tuple[ScheduledReview, str]]:
        return (
            select(ScheduledReview, User.display_name)
            .join(User, User.user_id == ScheduledReview.owner_user_id)
            .where(ScheduledReview.tenant_id == tenant_id, ScheduledReview.is_deleted.is_(False))
        )

    async def list_definitions(
        self,
        tenant_id: int,
        *,
        owner_user_id: int | None,
        offset: int,
        limit: int,
    ) -> tuple[list[DefinitionRow], int]:
        conditions = [ScheduledReview.tenant_id == tenant_id, ScheduledReview.is_deleted.is_(False)]
        query = self._definitions(tenant_id)
        if owner_user_id is not None:
            conditions.append(ScheduledReview.owner_user_id == owner_user_id)
            query = query.where(ScheduledReview.owner_user_id == owner_user_id)
        total = await self.session.scalar(
            select(func.count(ScheduledReview.scheduled_review_id)).where(*conditions)
        )
        rows = await self.session.execute(
            query.order_by(func.lower(ScheduledReview.name), ScheduledReview.scheduled_review_id)
            .offset(offset)
            .limit(limit)
        )
        return [DefinitionRow(definition, name) for definition, name in rows.all()], int(total or 0)

    async def get_definition(
        self, tenant_id: int, public_id: str, *, lock: bool = False
    ) -> DefinitionRow | None:
        query = self._definitions(tenant_id).where(ScheduledReview.public_id == public_id)
        if lock:
            query = query.with_for_update(of=ScheduledReview)
        row = (await self.session.execute(query)).first()
        return None if row is None else DefinitionRow(row[0], row[1])

    async def names_of_owner(self, owner_user_id: int, *, except_id: int | None) -> list[str]:
        query = select(ScheduledReview.name).where(
            ScheduledReview.owner_user_id == owner_user_id, ScheduledReview.is_deleted.is_(False)
        )
        if except_id is not None:
            query = query.where(ScheduledReview.scheduled_review_id != except_id)
        return list(await self.session.scalars(query))

    async def add_definition(self, definition: ScheduledReview) -> None:
        self.session.add(definition)
        await self.session.flush()

    async def delete_definition(self, definition_id: int) -> None:
        await self.session.execute(
            delete(ScheduledReview).where(ScheduledReview.scheduled_review_id == definition_id)
        )

    async def has_open_run(self, definition_id: int) -> bool:
        found = await self.session.scalar(
            select(ScheduledReviewRun.scheduled_review_run_id)
            .where(
                ScheduledReviewRun.scheduled_review_id == definition_id,
                ScheduledReviewRun.state.in_(OPEN_STATES),
            )
            .limit(1)
        )
        return found is not None

    async def open_run(self, definition_id: int) -> ScheduledReviewRun | None:
        """The definition's queued or running record, locked for the stop request."""

        record: ScheduledReviewRun | None = await self.session.scalar(
            select(ScheduledReviewRun)
            .where(
                ScheduledReviewRun.scheduled_review_id == definition_id,
                ScheduledReviewRun.state.in_(OPEN_STATES),
            )
            .order_by(ScheduledReviewRun.scheduled_review_run_id.desc())
            .limit(1)
            .with_for_update()
        )
        return record

    # --- run records ------------------------------------------------------------------------

    async def _finding_counts(self, review_run_ids: Sequence[int]) -> dict[int, int]:
        if not review_run_ids:
            return {}
        rows = await self.session.execute(
            select(ReviewRunObject.review_run_id, func.count(ReviewFinding.review_finding_id))
            .join(
                ReviewRuleResult,
                ReviewRuleResult.review_run_object_id == ReviewRunObject.review_run_object_id,
            )
            .join(
                ReviewFinding,
                ReviewFinding.review_rule_result_id == ReviewRuleResult.review_rule_result_id,
            )
            .where(
                ReviewRunObject.review_run_id.in_(review_run_ids),
                ReviewFinding.is_deleted.is_(False),
            )
            .group_by(ReviewRunObject.review_run_id)
        )
        return {int(run_id): int(count) for run_id, count in rows.all()}

    async def _records(self, query: Select[tuple[ScheduledReviewRun]]) -> list[RunRecord]:
        trigger_user = aliased(User)
        rows = (
            await self.session.execute(
                query.add_columns(ReviewRun.public_id, trigger_user.display_name)
                .outerjoin(ReviewRun, ReviewRun.review_run_id == ScheduledReviewRun.review_run_id)
                .outerjoin(
                    trigger_user, trigger_user.user_id == ScheduledReviewRun.triggered_by_user_id
                )
            )
        ).all()
        stored = [
            row[0].review_run_id for row in rows if row[1] is not None and row[0].review_run_id
        ]
        counts = await self._finding_counts([int(run_id) for run_id in stored])
        return [
            RunRecord(
                record,
                review_public_id,
                trigger_name,
                (
                    counts.get(int(record.review_run_id), 0)
                    if review_public_id is not None and record.review_run_id is not None
                    else None
                ),
            )
            for record, review_public_id, trigger_name in rows
        ]

    async def runs_of(
        self, definition_id: int, *, offset: int, limit: int
    ) -> tuple[list[RunRecord], int]:
        total = await self.session.scalar(
            select(func.count(ScheduledReviewRun.scheduled_review_run_id)).where(
                ScheduledReviewRun.scheduled_review_id == definition_id
            )
        )
        query = (
            select(ScheduledReviewRun)
            .where(ScheduledReviewRun.scheduled_review_id == definition_id)
            .order_by(
                ScheduledReviewRun.due_at.desc(), ScheduledReviewRun.scheduled_review_run_id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return await self._records(query), int(total or 0)

    async def last_runs(self, definition_ids: Sequence[int]) -> dict[int, RunRecord]:
        if not definition_ids:
            return {}
        latest = (
            select(func.max(ScheduledReviewRun.scheduled_review_run_id))
            .where(ScheduledReviewRun.scheduled_review_id.in_(definition_ids))
            .group_by(ScheduledReviewRun.scheduled_review_id)
        )
        records = await self._records(
            select(ScheduledReviewRun).where(
                ScheduledReviewRun.scheduled_review_run_id.in_(latest.scalar_subquery())
            )
        )
        return {int(item.record.scheduled_review_id): item for item in records}

    async def add_run(self, record: ScheduledReviewRun) -> None:
        self.session.add(record)
        await self.session.flush()

    # --- setting ----------------------------------------------------------------------------

    async def max_concurrent_runs(self, tenant_id: int) -> int:
        value = await self.session.scalar(
            select(ScheduledReviewSetting.max_concurrent_runs).where(
                ScheduledReviewSetting.tenant_id == tenant_id,
                ScheduledReviewSetting.is_deleted.is_(False),
            )
        )
        return MAX_CONCURRENT_RUNS_DEFAULT if value is None else int(value)

    async def set_max_concurrent_runs(self, tenant_id: int, value: int, actor_id: int) -> None:
        setting = await self.session.get(ScheduledReviewSetting, tenant_id, with_for_update=True)
        if setting is None:
            self.session.add(
                ScheduledReviewSetting(
                    tenant_id=tenant_id,
                    max_concurrent_runs=value,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            setting.max_concurrent_runs = value
            setting.updated_by = actor_id
        await self.session.flush()

    # --- scheduler claims (Requirement 3, 7, 8) -----------------------------------------------

    async def claim_due_definitions(self, now: datetime, limit: int) -> list[ScheduledReview]:
        """Active definitions whose due time has come, locked; other copies skip them."""

        return list(
            await self.session.scalars(
                select(ScheduledReview)
                .where(
                    ScheduledReview.status == ScheduledReviewStatus.ACTIVE.value,
                    ScheduledReview.is_deleted.is_(False),
                    ScheduledReview.next_run_at.is_not(None),
                    ScheduledReview.next_run_at <= now,
                )
                .order_by(ScheduledReview.next_run_at, ScheduledReview.scheduled_review_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def running_count(self, tenant_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count(ScheduledReviewRun.scheduled_review_run_id)).where(
                    ScheduledReviewRun.tenant_id == tenant_id,
                    ScheduledReviewRun.state == ScheduledRunState.RUNNING.value,
                )
            )
            or 0
        )

    async def tenants_with_queued_runs(self) -> list[int]:
        return [
            int(tenant)
            for tenant in await self.session.scalars(
                select(ScheduledReviewRun.tenant_id)
                .where(ScheduledReviewRun.state == ScheduledRunState.QUEUED.value)
                .distinct()
            )
        ]

    async def lock_tenant_queue(self, tenant_id: int) -> bool:
        """Transaction-scoped advisory lock of a tenant's start step; False when held elsewhere.

        Counting running records and starting the oldest queued ones must be one step per tenant,
        or two copies could each see room under the limit and start one run too many.
        """

        return bool(
            await self.session.scalar(
                select(func.pg_try_advisory_xact_lock(_QUEUE_LOCK_BASE + tenant_id))
            )
        )

    async def oldest_queued(self, tenant_id: int, limit: int) -> list[ScheduledReviewRun]:
        return list(
            await self.session.scalars(
                select(ScheduledReviewRun)
                .where(
                    ScheduledReviewRun.tenant_id == tenant_id,
                    ScheduledReviewRun.state == ScheduledRunState.QUEUED.value,
                )
                .order_by(ScheduledReviewRun.due_at, ScheduledReviewRun.scheduled_review_run_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def claim_due_emails(self, now: datetime, limit: int) -> list[ScheduledReviewRun]:
        return list(
            await self.session.scalars(
                select(ScheduledReviewRun)
                .where(
                    ScheduledReviewRun.email_status == EmailStatus.PENDING.value,
                    ScheduledReviewRun.next_email_at.is_not(None),
                    ScheduledReviewRun.next_email_at <= now,
                )
                .order_by(ScheduledReviewRun.next_email_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def get_run_record(
        self, record_id: int, *, lock: bool = False
    ) -> ScheduledReviewRun | None:
        query = select(ScheduledReviewRun).where(
            ScheduledReviewRun.scheduled_review_run_id == record_id
        )
        if lock:
            query = query.with_for_update()
        record: ScheduledReviewRun | None = await self.session.scalar(query)
        return record

    async def get_definition_by_id(self, definition_id: int) -> ScheduledReview | None:
        definition: ScheduledReview | None = await self.session.get(ScheduledReview, definition_id)
        return definition

    async def interrupt_running_records(self, finished_at: datetime) -> int:
        """Records still running when the process starts become interrupted (Requirement 8)."""

        result = await self.session.execute(
            update(ScheduledReviewRun)
            .where(ScheduledReviewRun.state == ScheduledRunState.RUNNING.value)
            .values(state=ScheduledRunState.INTERRUPTED.value, finished_at=finished_at)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # --- recipients (Requirement 6, review-history-export Decision 8) -------------------------

    async def add_recipients(self, review_run_id: int, recipients: Sequence[str]) -> None:
        self.session.add_all(
            ReviewRunRecipient(review_run_id=review_run_id, email=address) for address in recipients
        )
        await self.session.flush()

    async def recipients_of(self, review_run_id: int) -> list[str]:
        return list(
            await self.session.scalars(
                select(ReviewRunRecipient.email)
                .where(
                    ReviewRunRecipient.review_run_id == review_run_id,
                    ReviewRunRecipient.is_deleted.is_(False),
                )
                .order_by(ReviewRunRecipient.email)
            )
        )

    async def is_recipient(self, review_run_id: int, email: str) -> bool:
        found = await self.session.scalar(
            select(ReviewRunRecipient.review_run_id).where(
                ReviewRunRecipient.review_run_id == review_run_id,
                ReviewRunRecipient.email == email.strip().lower(),
                ReviewRunRecipient.is_deleted.is_(False),
            )
        )
        return found is not None


# Advisory lock keys of the scheduled start step: this base plus the tenant id.
_QUEUE_LOCK_BASE = 0x6477_6863_7363_0000  # "dwhcsc" + tenant id
