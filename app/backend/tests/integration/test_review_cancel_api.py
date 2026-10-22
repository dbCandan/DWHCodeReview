""" "Analizi durdur" by request on real PostgreSQL.

sql-review/PRDs/003-object-review Requirement 15 and Decision 9 (Acceptance 6): the owner stops a
running review with a request that does not depend on the stream closing; the run ends cancelled
at once, its stream ends, no result is stored and the LLM call in flight is abandoned. Only the
owner (or the super admin) may stop it; a finished run answers 409.
"""

import asyncio
from typing import Any

import pytest
from sqlalchemy import update

from app.db.session import async_session_factory
from app.domain.models.review import ReviewRun
from tests.integration.conftest import ReviewEnv, RoleSession, sse_events
from tests.integration.review_helpers import result_counts, run_of, runs_of

pytestmark = pytest.mark.integration

SCRIPT = "SELECT *\nFROM dbo.Musteri"


async def _ready(env: ReviewEnv) -> RoleSession:
    manager = await env.sessions.rule_manager()
    await env.publish(manager, [("Yıldız kullanma.", False)], [("NULL eşitliği yazma.", False)])
    return await env.sessions.reviewer()


def _cancel(env: ReviewEnv, run_id: str, session: RoleSession) -> Any:
    return env.auth.client.post(
        f"{env.prefix}/review-runs/{run_id}/cancel", headers=session.headers
    )


async def test_the_owner_stops_a_running_review_and_its_stream_ends(
    review_env: ReviewEnv,
) -> None:
    reviewer = await _ready(review_env)
    review_env.llm.gate = asyncio.Event()
    request = asyncio.create_task(review_env.script_review(reviewer, SCRIPT, "durdurulacak"))
    await review_env.llm.started.wait()
    [run] = await runs_of(reviewer.public_id)

    other = await review_env.sessions.reviewer()
    assert (await _cancel(review_env, run.public_id, other)).status_code == 404
    stopped = await _cancel(review_env, run.public_id, reviewer)
    assert stopped.status_code == 202
    assert stopped.json() == {"id": run.public_id, "status": "cancelling"}

    # The stream ends without waiting for the LLM call it abandoned.
    response = await asyncio.wait_for(request, timeout=5)
    phases = [event["phase"] for event in sse_events(response.text)]
    assert "complete" not in phases
    ended = await run_of(run.public_id)
    assert ended.status == "cancelled"
    assert await result_counts(ended) == (0, 0)
    again = await _cancel(review_env, run.public_id, reviewer)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "review_run_not_running"


async def test_a_running_run_without_a_task_here_ends_cancelled_at_once(
    review_env: ReviewEnv,
) -> None:
    reviewer = await _ready(review_env)
    response = await review_env.script_review(reviewer, SCRIPT, "kalıntı")
    run_id = sse_events(response.text)[0]["run_id"]
    async with async_session_factory() as session:
        await session.execute(
            update(ReviewRun)
            .where(ReviewRun.public_id == run_id)
            .values(status="running", finished_at=None)
        )
        await session.commit()

    # Another user does not see the run; its owner stops it.
    other = await review_env.sessions.reviewer()
    assert (await _cancel(review_env, run_id, other)).status_code == 404
    stopped = await _cancel(review_env, run_id, reviewer)
    assert stopped.json() == {"id": run_id, "status": "cancelled"}
    ended = await run_of(run_id)
    assert ended.status == "cancelled" and ended.finished_at is not None
