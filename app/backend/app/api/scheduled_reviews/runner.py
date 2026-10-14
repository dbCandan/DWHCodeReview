"""Wiring of the in-process scheduler (sql-review 008-scheduled-review-email Decision 2).

The scheduler uses the same process-wide collaborators as a browser review: the LLM adapter and
its process limit, the review registry, the saved SQL Server connection and the LLM endpoint the
super admin configured. It is built only when ``DWHCODEREVIEW_SCHEDULER_ENABLED`` is on.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import (
    get_llm_chat,
    get_llm_connection_store,
    get_review_registry,
    get_sql_catalog_adapter,
    get_sql_connection_storage,
)
from app.api.reviews.router import get_review_runtime
from app.core.config import Settings
from app.core.review_throttle import ReviewRateLimiter
from app.db.session import async_session_factory
from app.domain.review import ObjectSelection
from app.infrastructure.mail.smtp_client import SmtpMailSender
from app.infrastructure.sql_server.catalog_adapter import PyodbcSqlCatalog
from app.services.review_catalog_service import ReviewCatalogService
from app.services.review_run_service import ReviewExecution, ReviewRunService
from app.services.scheduled_review_scheduler import (
    ScheduledReviewScheduler,
    ScheduledStart,
    list_selected_objects,
)


def build_mail_sender(settings: Settings) -> SmtpMailSender | None:
    """The SMTP adapter, or None when the relay is not configured (e-mail ``not_configured``)."""

    if not settings.smtp_configured:
        return None
    return SmtpMailSender(
        host=settings.smtp_host.strip(),
        port=settings.smtp_port,
        security=settings.smtp_security,
        sender=settings.smtp_sender.strip(),
        username=settings.smtp_username,
        password=(
            settings.smtp_password.get_secret_value() if settings.smtp_password is not None else ""
        ),
        ca_bundle=settings.smtp_ca_bundle,
        timeout_seconds=float(settings.smtp_timeout_seconds),
    )


def build_scheduler(settings: Settings) -> ScheduledReviewScheduler:
    runtime = get_review_runtime(settings, get_llm_chat(), get_review_registry())
    llm_connection = get_llm_connection_store()
    # Scheduled runs are not throttled per user; the concurrency limit protects the LLM.
    limiter = ReviewRateLimiter()

    async def catalog() -> PyodbcSqlCatalog:
        # A connection saved through another replica is read again before each use (002 Req. 11).
        storage = get_sql_connection_storage()
        if storage is not None:
            await storage.refresh()
        return get_sql_catalog_adapter()

    async def start_run(session: AsyncSession, start: ScheduledStart) -> ReviewExecution:
        service = ReviewRunService(
            session,
            settings=settings,
            runtime=runtime,
            llm_endpoint=llm_connection.endpoint,
            limiter=limiter,
            catalog=await catalog(),
        )
        return await service.start_scheduled_review(
            tenant_id=start.tenant_id,
            owner_user_id=start.owner_user_id,
            owner_public_id=start.owner_public_id,
            scheduled_review_id=start.scheduled_review_id,
            selections=start.selections,
            rule_group_ids=start.rule_group_ids,
        )

    async def list_objects(selection: dict[str, Any]) -> list[ObjectSelection]:
        service = ReviewCatalogService(await catalog())
        return await list_selected_objects(selection, service.matching_objects)

    return ScheduledReviewScheduler(
        session_factory=async_session_factory,
        start_run=start_run,
        list_objects=list_objects,
        mailer=build_mail_sender(settings),
        public_origin=settings.public_origin,
        tick_seconds=float(settings.scheduler_tick_seconds),
    )
