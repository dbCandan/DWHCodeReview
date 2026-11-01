"""Insert-only persistence of LLM call summaries and their retention delete."""

from datetime import datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.llm import LlmCallAttempt
from app.domain.models.llm_call import LlmCallSummary
from app.domain.models.review import ReviewRun

# pg_try_advisory_xact_lock key of the retention job: one running copy deletes at a time.
RETENTION_LOCK_KEY = 0x6477_6863_6C6C_6D01  # "dwhcllm" + 1


SummaryRow = tuple[LlmCallSummary, str | None]


class LlmCallSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, attempt: LlmCallAttempt) -> None:
        target = attempt.target
        self.session.add(
            LlmCallSummary(
                public_id=attempt.public_id,
                tenant_id=target.tenant_id,
                review_run_id=target.review_run_id,
                started_at=attempt.started_at,
                object_label=target.object_label,
                rule_code=target.rule_code,
                part_index=target.part_index,
                attempt=attempt.attempt,
                chat_api=attempt.chat_api.value,
                model=attempt.model,
                endpoint_host=attempt.endpoint_host,
                streamed=attempt.streamed,
                outcome=attempt.outcome.value,
                http_status=attempt.http_status,
                duration_ms=attempt.duration_ms,
                completion_tokens=attempt.completion_tokens,
                prompt_tokens=attempt.prompt_tokens,
                response_chars=attempt.response_chars,
            )
        )
        await self.session.flush()

    def _select(self, tenant_id: int) -> Select[LlmCallSummary, str]:
        return (
            select(LlmCallSummary, ReviewRun.public_id)
            .outerjoin(ReviewRun, ReviewRun.review_run_id == LlmCallSummary.review_run_id)
            .where(LlmCallSummary.tenant_id == tenant_id, LlmCallSummary.is_deleted.is_(False))
        )

    async def list_recent(self, tenant_id: int, *, limit: int) -> tuple[list[SummaryRow], int]:
        total = await self.session.scalar(
            select(func.count())
            .select_from(LlmCallSummary)
            .where(LlmCallSummary.tenant_id == tenant_id, LlmCallSummary.is_deleted.is_(False))
        )
        result = await self.session.execute(
            self._select(tenant_id)
            .order_by(LlmCallSummary.started_at.desc(), LlmCallSummary.llm_call_summary_id.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()], int(total or 0)

    async def get(self, tenant_id: int, public_id: str) -> SummaryRow | None:
        row = (
            await self.session.execute(
                self._select(tenant_id).where(LlmCallSummary.public_id == public_id)
            )
        ).first()
        return None if row is None else (row[0], row[1])

    async def try_retention_lock(self) -> bool:
        """Transaction-scoped advisory lock; False when another copy is already deleting."""

        return bool(
            await self.session.scalar(select(func.pg_try_advisory_xact_lock(RETENTION_LOCK_KEY)))
        )

    async def delete_started_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(LlmCallSummary).where(LlmCallSummary.started_at < cutoff)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
