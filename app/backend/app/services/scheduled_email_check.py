"""The summary e-mail's readiness and a test send (sql-review 008 Requirement 10, Decision 13-14).

The super admin sees whether the scheduler runs, whether the SMTP relay is configured and which
domains a recipient may use, and sends one short test message to a single corporate address. The
test uses the same adapter as the summary e-mail, so a failure surfaces with the same stable code
(smtp_unreachable, smtp_tls_failed, ...). Addresses never reach a log line.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.core.request_context import RequestContext
from app.domain.scheduled_review import (
    ScheduleValidationError,
    SummaryEmail,
    build_test_email,
    normalize_recipients,
)
from app.infrastructure.mail.smtp_client import MailDeliveryError
from app.infrastructure.repositories.user_repository import UserRepository
from app.schemas.scheduled_reviews.contracts import (
    ScheduledEmailStatus,
    ScheduledEmailTestResult,
)
from app.services.request_scope import acting_user

logger = logging.getLogger("app.scheduled_review")

# One test per super admin in this window; the relay is a shared corporate service.
TEST_COOLDOWN_SECONDS = 15.0
_last_test: dict[int, float] = {}


class MailSender(Protocol):
    async def send(self, recipients: Sequence[str], email: SummaryEmail) -> int: ...


class ScheduledEmailCheck:
    def __init__(
        self,
        session: AsyncSession,
        *,
        allowed_domains: Sequence[str],
        scheduler_enabled: bool,
        smtp_security: Literal["starttls", "tls"],
        public_origin: str,
        mailer: MailSender | None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.users = UserRepository(session)
        self._allowed_domains = tuple(allowed_domains)
        self._scheduler_enabled = scheduler_enabled
        self._smtp_security = smtp_security
        self._public_origin = public_origin
        self._mailer = mailer
        self._monotonic = monotonic

    async def status(self, context: RequestContext) -> ScheduledEmailStatus:
        actor = await acting_user(self.users, context)
        return ScheduledEmailStatus(
            scheduler_enabled=self._scheduler_enabled,
            smtp_configured=self._mailer is not None,
            smtp_security=self._smtp_security,
            allowed_domains=list(self._allowed_domains),
            suggested_recipient=self._allowed(actor.email),
        )

    async def send_test(self, context: RequestContext, recipient: str) -> ScheduledEmailTestResult:
        actor = await acting_user(self.users, context)
        try:
            recipients = normalize_recipients([recipient], self._allowed_domains)
        except ScheduleValidationError as error:
            raise ApplicationError(
                status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, error.message
            ) from None
        if self._mailer is None:
            self._log(actor.public_id, "not_configured", None)
            return ScheduledEmailTestResult(status="not_configured")
        now = self._monotonic()
        last = _last_test.get(actor.user_id)
        if last is not None and now - last < TEST_COOLDOWN_SECONDS:
            raise ApplicationError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "email_test_too_soon",
                "Deneme e-postası için birkaç saniye bekleyin.",
            )
        _last_test[actor.user_id] = now
        try:
            refused = await self._mailer.send(recipients, build_test_email(self._public_origin))
        except MailDeliveryError as error:
            self._log(actor.public_id, "failed", error.code)
            return ScheduledEmailTestResult(status="failed", error_code=error.code)
        if refused:
            self._log(actor.public_id, "failed", "smtp_rejected")
            return ScheduledEmailTestResult(status="failed", error_code="smtp_rejected")
        self._log(actor.public_id, "sent", None)
        return ScheduledEmailTestResult(status="sent")

    def _allowed(self, address: str | None) -> str | None:
        if not address:
            return None
        try:
            return normalize_recipients([address], self._allowed_domains)[0]
        except ScheduleValidationError:
            return None

    @staticmethod
    def _log(user_public_id: str, outcome: str, error_code: str | None) -> None:
        log_event(
            logger,
            "scheduled_review.email_test",
            user_public_id=user_public_id,
            outcome=outcome,
            error_code=error_code,
        )
