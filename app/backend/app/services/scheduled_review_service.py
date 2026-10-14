"""Scheduled review definitions, their run history, "Şimdi çalıştır" and the setting.

sql-review/PRDs/008-scheduled-review-email Requirement 1, 2, 6, 8, 9 and Decision 3, 5, 8, 9. A
user manages only their own definitions; the super admin manages every definition of the tenant,
triggers a run by hand and sets the concurrency limit. A definition the caller may not see
answers 404 as if it did not exist. Names, recipient addresses and object names never reach a
log line; events carry public identifiers only.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.core.request_context import RequestContext
from app.domain.models.scheduled_review import (
    MAX_CONCURRENT_RUNS_MAX,
    MAX_CONCURRENT_RUNS_MIN,
    EmailStatus,
    ScheduledReview,
    ScheduledReviewRun,
    ScheduledReviewStatus,
    ScheduledRunState,
    ScheduledRunTrigger,
    SelectionMode,
)
from app.domain.models.tenant import Tenant
from app.domain.models.user import User
from app.domain.rule_set import RuleSetValidationError
from app.domain.scheduled_review import (
    Period,
    ScheduleValidationError,
    fold_name,
    next_run_after,
    normalize_recipients,
    normalize_schedule_name,
    validate_period,
)
from app.infrastructure.repositories.scheduled_review_repository import (
    DefinitionRow,
    RunRecord,
    ScheduledReviewRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.schemas.scheduled_reviews.contracts import (
    LastScheduledRun,
    ObjectFilter,
    ObjectSelection,
    ScheduledReviewDetail,
    ScheduledReviewItem,
    ScheduledReviewPage,
    ScheduledReviewSettings,
    ScheduledReviewWrite,
    ScheduledRuleGroup,
    ScheduledRunItem,
    ScheduledRunPage,
    ScheduledRunQueued,
    SchedulePeriod,
)
from app.services.request_scope import acting_user, active_tenant
from app.services.rule_set_service import RuleSetService

logger = logging.getLogger("app.scheduled_review")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _not_found() -> ApplicationError:
    return ApplicationError(
        status.HTTP_404_NOT_FOUND,
        "scheduled_review_not_found",
        "Zamanlanmış inceleme bulunamadı.",
    )


def _running() -> ApplicationError:
    return ApplicationError(
        status.HTTP_409_CONFLICT,
        "scheduled_review_running",
        "Bu tanımın bir koşumu sırada bekliyor veya sürüyor.",
    )


def _unprocessable(code: str, message: str) -> ApplicationError:
    return ApplicationError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def _duplicate() -> ApplicationError:
    return _unprocessable(
        "schedule_name_duplicate", "Aynı adla ikinci bir zamanlanmış inceleme tanımlanamaz."
    )


def _period_of(definition: ScheduledReview) -> Period:
    return validate_period(
        definition.frequency,
        hour=definition.run_hour,
        minute=definition.run_minute,
        timezone=definition.timezone,
        weekday=definition.weekday,
        day_of_month=definition.day_of_month,
    )


def selection_summary(selection: dict[str, Any]) -> str:
    """One Turkish line describing the object selection; object names only, never SQL."""

    if selection.get("mode") == SelectionMode.LIST.value:
        items = selection.get("items", [])
        databases = sorted({str(item.get("database", "")) for item in items})
        return f"{len(items)} nesne ({', '.join(databases)})"
    parts = [str(selection.get("database", ""))]
    if selection.get("query"):
        parts.append(f"arama: {selection['query']}")
    if selection.get("type_code"):
        parts.append(f"tür: {selection['type_code']}")
    if selection.get("from_date"):
        day = datetime.fromisoformat(str(selection["from_date"]))
        parts.append(f"{day:%d.%m.%Y} sonrası")
    return " · ".join(parts)


def _selection_json(selection: ObjectSelection) -> dict[str, Any]:
    if selection.mode == SelectionMode.FILTER.value:
        if selection.filter is None or selection.items:
            raise ScheduleValidationError(
                "schedule_invalid", "Süzgeç seçiminde veritabanı seçilmelidir."
            )
        chosen = selection.filter
        return {
            "mode": SelectionMode.FILTER.value,
            "database": chosen.database.strip(),
            "query": (chosen.query or "").strip() or None,
            "type_code": chosen.type_code,
            "from_date": chosen.from_date.isoformat() if chosen.from_date else None,
        }
    if not selection.items or selection.filter is not None:
        raise ScheduleValidationError("schedule_invalid", "Listeden en az bir nesne seçilmelidir.")
    return {
        "mode": SelectionMode.LIST.value,
        "items": [
            {
                "database": item.database,
                "schema": item.schema_,
                "name": item.name,
                "type_code": item.type_code,
            }
            for item in selection.items
        ],
    }


def _selection_contract(selection: dict[str, Any]) -> ObjectSelection:
    if selection.get("mode") == SelectionMode.LIST.value:
        return ObjectSelection.model_validate({"mode": "list", "items": selection["items"]})
    return ObjectSelection(
        mode="filter",
        filter=ObjectFilter(
            database=selection["database"],
            query=selection.get("query"),
            type_code=selection.get("type_code"),
            from_date=selection.get("from_date"),
        ),
    )


def _period_contract(definition: ScheduledReview) -> SchedulePeriod:
    return SchedulePeriod(
        frequency=definition.frequency,  # type: ignore[arg-type]
        hour=definition.run_hour,
        minute=definition.run_minute,
        timezone=definition.timezone,
        weekday=definition.weekday,
        day_of_month=definition.day_of_month,
    )


def _last_run(item: RunRecord | None) -> LastScheduledRun | None:
    if item is None:
        return None
    return LastScheduledRun(
        due_at=item.record.due_at,
        trigger=item.record.trigger,  # type: ignore[arg-type]
        state=item.record.state,  # type: ignore[arg-type]
        email_status=item.record.email_status,  # type: ignore[arg-type]
        error_code=item.record.error_code,
        finding_count=item.finding_count,
        review_run_id=item.review_run_public_id,
    )


def _run_item(item: RunRecord) -> ScheduledRunItem:
    record = item.record
    return ScheduledRunItem(
        id=record.public_id,
        review_run_id=item.review_run_public_id,
        due_at=record.due_at,
        trigger=record.trigger,  # type: ignore[arg-type]
        triggered_by_name=item.triggered_by_name,
        state=record.state,  # type: ignore[arg-type]
        skip_reason=record.skip_reason,  # type: ignore[arg-type]
        error_code=record.error_code,
        started_at=record.started_at,
        finished_at=record.finished_at,
        finding_count=item.finding_count,
        email_status=record.email_status,  # type: ignore[arg-type]
        email_attempts=record.email_attempts,
    )


class ScheduledReviewService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        allowed_domains: Sequence[str],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.session = session
        self.schedules = ScheduledReviewRepository(session)
        self.users = UserRepository(session)
        self.rules = RuleSetService(session)
        self._allowed_domains = tuple(allowed_domains)
        self._clock = clock

    # --- scope ------------------------------------------------------------------------------

    async def _scope(self, context: RequestContext) -> tuple[Tenant, User]:
        tenant = await active_tenant(self.users, context)
        actor = await acting_user(self.users, context)
        return tenant, actor

    async def _visible(
        self, context: RequestContext, public_id: str, *, lock: bool = False
    ) -> tuple[Tenant, User, DefinitionRow]:
        tenant, actor = await self._scope(context)
        row = await self.schedules.get_definition(tenant.tenant_id, public_id, lock=lock)
        if row is None or not (
            context.is_super_admin or row.definition.owner_user_id == actor.user_id
        ):
            raise _not_found()
        return tenant, actor, row

    # --- reads ------------------------------------------------------------------------------

    async def _group_names(self, tenant_id: int) -> dict[str, str]:
        latest = await self.rules.latest_published_rule_set(tenant_id)
        if latest is None:
            return {}
        return {group.public_id: group.name for group in latest.rules.rule_groups}

    def _item_values(
        self,
        context: RequestContext,
        actor: User,
        row: DefinitionRow,
        names: dict[str, str],
        last: RunRecord | None,
    ) -> dict[str, Any]:
        definition = row.definition
        active = definition.status == ScheduledReviewStatus.ACTIVE.value
        return {
            "id": definition.public_id,
            "name": definition.name,
            "owner_display_name": row.owner_name,
            "owned": definition.owner_user_id == actor.user_id,
            "selection": _selection_contract(definition.selection),
            "selection_summary": selection_summary(definition.selection),
            "rule_groups": [
                ScheduledRuleGroup(id=group_id, name=names.get(group_id))
                for group_id in definition.rule_group_ids
            ],
            "period": _period_contract(definition),
            "recipient_count": len(definition.recipients),
            "status": definition.status,
            "next_run_at": definition.next_run_at if active else None,
            "last_run": _last_run(last),
            "missed": last is not None and last.record.state == ScheduledRunState.MISSED.value,
            "email_failed": last is not None
            and last.record.email_status == EmailStatus.FAILED.value,
            "can_edit": True,
            "can_run_now": context.is_super_admin,
        }

    async def list_definitions(
        self, context: RequestContext, *, page: int, page_size: int
    ) -> ScheduledReviewPage:
        tenant, actor = await self._scope(context)
        rows, total = await self.schedules.list_definitions(
            tenant.tenant_id,
            owner_user_id=None if context.is_super_admin else actor.user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        names = await self._group_names(tenant.tenant_id)
        last = await self.schedules.last_runs([row.definition.scheduled_review_id for row in rows])
        return ScheduledReviewPage(
            items=[
                ScheduledReviewItem(
                    **self._item_values(
                        context,
                        actor,
                        row,
                        names,
                        last.get(row.definition.scheduled_review_id),
                    )
                )
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def _detail(
        self, context: RequestContext, tenant: Tenant, actor: User, row: DefinitionRow
    ) -> ScheduledReviewDetail:
        names = await self._group_names(tenant.tenant_id)
        last = await self.schedules.last_runs([row.definition.scheduled_review_id])
        return ScheduledReviewDetail(
            **self._item_values(
                context, actor, row, names, last.get(row.definition.scheduled_review_id)
            ),
            recipients=list(row.definition.recipients),
        )

    async def detail(self, context: RequestContext, public_id: str) -> ScheduledReviewDetail:
        tenant, actor, row = await self._visible(context, public_id)
        return await self._detail(context, tenant, actor, row)

    async def runs(
        self, context: RequestContext, public_id: str, *, page: int, page_size: int
    ) -> ScheduledRunPage:
        _, _, row = await self._visible(context, public_id)
        records, total = await self.schedules.runs_of(
            row.definition.scheduled_review_id, offset=(page - 1) * page_size, limit=page_size
        )
        return ScheduledRunPage(
            items=[_run_item(record) for record in records],
            page=page,
            page_size=page_size,
            total=total,
        )

    # --- writes -----------------------------------------------------------------------------

    async def _validated(
        self,
        tenant_id: int,
        owner_user_id: int,
        body: ScheduledReviewWrite,
        *,
        except_id: int | None,
    ) -> dict[str, Any]:
        try:
            name = normalize_schedule_name(body.name)
            period = validate_period(
                body.period.frequency,
                hour=body.period.hour,
                minute=body.period.minute,
                timezone=body.period.timezone,
                weekday=body.period.weekday,
                day_of_month=body.period.day_of_month,
            )
            selection = _selection_json(body.selection)
            recipients = normalize_recipients(body.recipients, self._allowed_domains)
        except ScheduleValidationError as error:
            raise _unprocessable(error.code, error.message) from None
        group_ids = list(dict.fromkeys(body.rule_group_ids))
        if group_ids:
            # The same check a review start makes (rule-group-selection Requirement 4); the run
            # checks again against the version it pins.
            latest = await self.rules.latest_published_rule_set(tenant_id)
            if latest is None:
                raise _unprocessable(
                    "rule_group_unknown", "Seçilen kural grubu yayımlanmış sürümde yok."
                )
            try:
                latest.select(group_ids)
            except RuleSetValidationError as error:
                raise _unprocessable(error.code, error.message) from None
        key = fold_name(name)
        names = await self.schedules.names_of_owner(owner_user_id, except_id=except_id)
        if any(fold_name(existing) == key for existing in names):
            raise _duplicate()
        return {
            "name": name,
            "selection_mode": selection["mode"],
            "selection": selection,
            "rule_group_ids": group_ids,
            "frequency": period.frequency.value,
            "weekday": period.weekday,
            "day_of_month": period.day_of_month,
            "run_hour": period.hour,
            "run_minute": period.minute,
            "timezone": period.timezone,
            "recipients": list(recipients),
            "_period": period,
        }

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError:
            # Another request of the same owner saved the same ASCII-folded name first.
            raise _duplicate() from None

    async def create(
        self, context: RequestContext, body: ScheduledReviewWrite
    ) -> ScheduledReviewDetail:
        tenant, actor = await self._scope(context)
        values = await self._validated(tenant.tenant_id, actor.user_id, body, except_id=None)
        period: Period = values.pop("_period")
        definition = ScheduledReview(
            tenant_id=tenant.tenant_id,
            owner_user_id=actor.user_id,
            status=ScheduledReviewStatus.ACTIVE.value,
            next_run_at=next_run_after(period, self._clock()),
            created_by=actor.user_id,
            updated_by=actor.user_id,
            **values,
        )
        self.session.add(definition)
        await self._flush()
        log_event(
            logger,
            "scheduled_review.created",
            schedule_public_id=definition.public_id,
            user_public_id=actor.public_id,
        )
        return await self._detail(
            context, tenant, actor, DefinitionRow(definition, actor.display_name)
        )

    async def update(
        self, context: RequestContext, public_id: str, body: ScheduledReviewWrite
    ) -> ScheduledReviewDetail:
        tenant, actor, row = await self._visible(context, public_id, lock=True)
        definition = row.definition
        values = await self._validated(
            tenant.tenant_id,
            definition.owner_user_id,
            body,
            except_id=definition.scheduled_review_id,
        )
        period: Period = values.pop("_period")
        for name, value in values.items():
            setattr(definition, name, value)
        definition.updated_by = actor.user_id
        if definition.status == ScheduledReviewStatus.ACTIVE.value:
            definition.next_run_at = next_run_after(period, self._clock())
        await self._flush()
        log_event(
            logger,
            "scheduled_review.updated",
            schedule_public_id=definition.public_id,
            user_public_id=actor.public_id,
        )
        return await self._detail(context, tenant, actor, row)

    async def delete(self, context: RequestContext, public_id: str) -> None:
        _, actor, row = await self._visible(context, public_id, lock=True)
        definition = row.definition
        if await self.schedules.has_open_run(definition.scheduled_review_id):
            raise _running()
        await self.schedules.delete_definition(definition.scheduled_review_id)
        log_event(
            logger,
            "scheduled_review.deleted",
            schedule_public_id=definition.public_id,
            user_public_id=actor.public_id,
        )

    async def set_paused(
        self, context: RequestContext, public_id: str, *, paused: bool
    ) -> ScheduledReviewDetail:
        tenant, actor, row = await self._visible(context, public_id, lock=True)
        definition = row.definition
        wanted = ScheduledReviewStatus.PAUSED if paused else ScheduledReviewStatus.ACTIVE
        if definition.status != wanted.value:
            definition.status = wanted.value
            definition.updated_by = actor.user_id
            if not paused:
                # Resuming never catches up on the time spent paused (Decision 9).
                definition.next_run_at = next_run_after(_period_of(definition), self._clock())
            await self.session.flush()
            log_event(
                logger,
                "scheduled_review.paused" if paused else "scheduled_review.resumed",
                schedule_public_id=definition.public_id,
                user_public_id=actor.public_id,
            )
        return await self._detail(context, tenant, actor, row)

    async def run_now(self, context: RequestContext, public_id: str) -> ScheduledRunQueued:
        """Queue a manual run; it starts through the scheduler like a due one (Requirement 8)."""

        tenant, actor, row = await self._visible(context, public_id, lock=True)
        if not context.is_super_admin:
            raise ApplicationError(
                status.HTTP_403_FORBIDDEN, "forbidden", "Bu işlem için yetkiniz yok."
            )
        definition = row.definition
        if await self.schedules.has_open_run(definition.scheduled_review_id):
            raise _running()
        record = ScheduledReviewRun(
            scheduled_review_id=definition.scheduled_review_id,
            tenant_id=tenant.tenant_id,
            due_at=self._clock(),
            trigger=ScheduledRunTrigger.MANUAL.value,
            triggered_by_user_id=actor.user_id,
            state=ScheduledRunState.QUEUED.value,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        await self.schedules.add_run(record)
        log_event(
            logger,
            "scheduled_review.manual_run",
            schedule_public_id=definition.public_id,
            user_public_id=actor.public_id,
        )
        return ScheduledRunQueued(id=record.public_id)

    # --- setting (Decision 8) ---------------------------------------------------------------

    async def settings(self, context: RequestContext) -> ScheduledReviewSettings:
        tenant, _ = await self._scope(context)
        return ScheduledReviewSettings(
            max_concurrent_runs=await self.schedules.max_concurrent_runs(tenant.tenant_id)
        )

    async def update_settings(
        self, context: RequestContext, body: ScheduledReviewSettings
    ) -> ScheduledReviewSettings:
        tenant, actor = await self._scope(context)
        value = body.max_concurrent_runs
        if not MAX_CONCURRENT_RUNS_MIN <= value <= MAX_CONCURRENT_RUNS_MAX:
            raise _unprocessable(
                "setting_out_of_range",
                f"Aynı anda çalışacak zamanlanmış koşum sayısı "
                f"{MAX_CONCURRENT_RUNS_MIN}-{MAX_CONCURRENT_RUNS_MAX} arasında olmalıdır.",
            )
        await self.schedules.set_max_concurrent_runs(tenant.tenant_id, value, actor.user_id)
        log_event(
            logger,
            "scheduled_review.settings_changed",
            max_concurrent_runs=value,
            user_public_id=actor.public_id,
        )
        return ScheduledReviewSettings(max_concurrent_runs=value)
