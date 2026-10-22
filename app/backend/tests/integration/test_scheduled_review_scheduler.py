"""The in-process scheduler against PostgreSQL with the scripted LLM, catalog and mailer.

sql-review/PRDs/008-scheduled-review-email Requirement 3-8 and Decision 1, 2, 7, 9, 12
(Acceptance 2): a due definition starts a background run of the scheduled kind with its group
selection and recipient list; an overlapping trigger is skipped; a due time from while the
application was down is recorded as missed and not caught up; the tenant limit holds and follows
the setting; two scheduler copies run a due time once; a record left running is interrupted at
start; "Şimdi çalıştır" queues a run; the summary e-mail carries no SQL, is retried 1, 5 and 15
minutes later, survives a restart and is recorded as not configured without a relay.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update

from app.core.errors import ApplicationError
from app.core.review_throttle import ReviewRateLimiter
from app.db.session import async_session_factory, engine
from app.domain.llm import LlmChatRequest
from app.domain.models.review import ReviewRun, ReviewRunRuleGroup
from app.domain.models.scheduled_review import (
    ReviewRunRecipient,
    ScheduledReview,
    ScheduledReviewRun,
    ScheduledReviewSetting,
)
from app.domain.scheduled_review import SummaryEmail
from app.domain.sql_server import CatalogObject, SqlServerNotConfigured
from app.infrastructure.mail.smtp_client import MailDeliveryError
from app.services.review_catalog_service import ReviewCatalogService
from app.services.review_engine import TextReviewer
from app.services.review_run_service import (
    ReviewExecution,
    ReviewRunService,
    ReviewRuntime,
    review_text_limit,
)
from app.services.scheduled_review_scheduler import (
    ScheduledReviewScheduler,
    ScheduledStart,
    interrupt_stale_scheduled_runs,
    list_selected_objects,
)
from tests.fakes.review_ports import ok, rule_code_of
from tests.integration.conftest import ReviewEnv, RoleSession, SuperAdmin

pytestmark = pytest.mark.integration

DOMAIN = "kurum.example"
ORIGIN = "https://reviewx.kurum.example"
MARKER = f"GIZLI-{uuid4().hex}"
DEFINITION = f"CREATE PROCEDURE dbo.usp_Load AS SELECT * FROM dbo.Musteri -- {MARKER}"
SECURITY = {"id": str(uuid4()), "name": "Güvenlik", "description": ""}
PERFORMANCE = {"id": str(uuid4()), "name": "Performans", "description": ""}


def _reply(request: LlmChatRequest) -> Any:
    """Every rule reports one violation quoting the reviewed text (which must not be mailed)."""

    violation = {"rule_code": rule_code_of(request), "snippet": MARKER, "reason": f"neden {MARKER}"}
    return ok(json.dumps({"violations": [violation]}))


@dataclass
class Clock:
    now: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeMailer:
    failures: int = 0
    sent: list[tuple[list[str], SummaryEmail]] = field(default_factory=list)
    attempts: int = 0

    async def send(self, recipients: Sequence[str], email: SummaryEmail) -> int:
        self.attempts += 1
        if self.failures:
            self.failures -= 1
            raise MailDeliveryError("smtp_unreachable")
        self.sent.append((list(recipients), email))
        return 0


@dataclass
class Scheduled:
    env: ReviewEnv
    owner: RoleSession
    clock: Clock
    mailer: FakeMailer
    rule_codes: list[str]

    def scheduler(
        self,
        *,
        mailer: FakeMailer | None | bool = True,
        start_run: Any = None,
    ) -> ScheduledReviewScheduler:
        env = self.env
        settings = env.auth.settings
        runtime = ReviewRuntime(
            llm=env.llm,
            session_factory=async_session_factory,
            registry=env.registry,
            reviewer=TextReviewer(
                two_part_threshold_chars=settings.review_two_part_threshold_chars
            ),
            text_limit=review_text_limit(settings),
            objects_in_flight=2,
        )

        async def start(session: Any, request: ScheduledStart) -> ReviewExecution:
            service = ReviewRunService(
                session,
                settings=settings,
                runtime=runtime,
                llm_endpoint=env.llm_store.endpoint,
                limiter=ReviewRateLimiter(),
                catalog=env.catalog,
            )
            return await service.start_scheduled_review(
                tenant_id=request.tenant_id,
                owner_user_id=request.owner_user_id,
                owner_public_id=request.owner_public_id,
                scheduled_review_id=request.scheduled_review_id,
                selections=request.selections,
                rule_group_ids=request.rule_group_ids,
            )

        async def list_objects(selection: dict[str, Any]) -> Any:
            return await list_selected_objects(
                selection, ReviewCatalogService(env.catalog).matching_objects
            )

        return ScheduledReviewScheduler(
            session_factory=async_session_factory,
            start_run=start_run or start,
            list_objects=list_objects,
            mailer=self.mailer if mailer is True else (mailer or None),
            public_origin=ORIGIN,
            tick_seconds=60,
            clock=self.clock,
        )

    async def define(self, **overrides: Any) -> str:
        body: dict[str, Any] = {
            "name": f"Gece taraması {uuid4().hex[:6]}",
            "selection": {"mode": "filter", "filter": {"database": "DWH", "type_code": "P"}},
            "rule_group_ids": [SECURITY["id"]],
            "period": {"frequency": "daily", "hour": 7, "minute": 30},
            "recipients": [f"Ayse@{DOMAIN}", f"ali@{DOMAIN}"],
        }
        body.update(overrides)
        auth = self.env.auth
        response = await auth.client.post(
            f"{auth.prefix}/scheduled-reviews", json=body, headers=self.owner.headers
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    async def make_due(self, public_id: str, *, ago: timedelta = timedelta(seconds=30)) -> None:
        async with engine.begin() as connection:
            await connection.execute(
                update(ScheduledReview)
                .where(ScheduledReview.public_id == public_id)
                .values(next_run_at=self.clock.now - ago)
            )

    async def records(self, public_id: str) -> list[ScheduledReviewRun]:
        async with async_session_factory() as session:
            return list(
                await session.scalars(
                    select(ScheduledReviewRun)
                    .join(
                        ScheduledReview,
                        ScheduledReview.scheduled_review_id
                        == ScheduledReviewRun.scheduled_review_id,
                    )
                    .where(ScheduledReview.public_id == public_id)
                    .order_by(ScheduledReviewRun.scheduled_review_run_id)
                )
            )

    async def definition(self, public_id: str) -> ScheduledReview:
        async with async_session_factory() as session:
            found = await session.scalar(
                select(ScheduledReview).where(ScheduledReview.public_id == public_id)
            )
            assert found is not None
            return found


async def _clean() -> None:
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM review_run WHERE kind = 'scheduled'",
            "DELETE FROM scheduled_review_run",
            "DELETE FROM scheduled_review",
            "DELETE FROM scheduled_review_setting",
        ):
            await connection.execute(text(statement))


@pytest.fixture
async def scheduled(review_env: ReviewEnv) -> AsyncIterator[Scheduled]:
    env = review_env
    env.auth.use_settings(mail_allowed_domains=DOMAIN)
    env.llm.responder = _reply
    manager = await env.sessions.rule_manager()
    _, codes = await env.publish(
        manager,
        [("Yıldız kullanma.", False), ("NOLOCK kullanma.", False)],
        [("Şema adı yaz.", False)],
        groups=[SECURITY, PERFORMANCE],
        membership={0: SECURITY["id"], 1: PERFORMANCE["id"]},
    )
    env.catalog.objects["DWH"] = [
        CatalogObject("dbo", "usp_Load", "PROCEDURE", "P", None, None),
        CatalogObject("dbo", "vw_Rapor", "VIEW", "V", None, None),
    ]
    env.catalog.definitions[("DWH", "dbo", "usp_Load")] = DEFINITION
    owner = await env.sessions.reviewer()
    await _clean()
    try:
        yield Scheduled(env, owner, Clock(), FakeMailer(), codes)
    finally:
        if env.llm.gate is not None:
            env.llm.gate.set()
        await asyncio.sleep(0)
        await _clean()
        client = env.auth.client
        workspace = (await client.get(f"{env.prefix}/rule-set", headers=manager.headers)).json()
        ungrouped = {
            priority: [{**rule, "rule_group_ids": []} for rule in workspace[priority]]
            for priority in ("critical", "normal")
        }
        saved = await client.put(
            f"{env.prefix}/rule-set/draft",
            json={"base_revision": workspace["revision"], "groups": [], **ungrouped},
            headers=manager.headers,
        )
        assert saved.status_code == 200, saved.text


async def _run_of(record: ScheduledReviewRun) -> ReviewRun:
    async with async_session_factory() as session:
        run = await session.get(ReviewRun, record.review_run_id)
        assert run is not None
        return run


async def test_a_due_definition_runs_in_the_background_and_mails_a_summary(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    scheduler = scheduled.scheduler()

    await scheduler.tick()
    await scheduler.drain()

    [record] = await scheduled.records(schedule_id)
    assert (record.trigger, record.state, record.email_status) == ("scheduled", "completed", "sent")
    assert record.email_attempts == 1
    run = await _run_of(record)
    definition = await scheduled.definition(schedule_id)
    assert (run.kind, run.status, run.object_count) == ("scheduled", "completed", 1)
    assert run.scheduled_review_id == definition.scheduled_review_id
    assert definition.next_run_at is not None and definition.next_run_at > scheduled.clock.now
    # Only the selected group's rule reached the LLM (Requirement 4, rule-group-selection).
    assert {rule_code_of(call.request) for call in scheduled.env.llm.calls} == {
        scheduled.rule_codes[0]
    }
    async with async_session_factory() as session:
        recipients = list(
            await session.scalars(
                select(ReviewRunRecipient.email).where(
                    ReviewRunRecipient.review_run_id == run.review_run_id
                )
            )
        )
        groups = list(
            await session.scalars(
                select(ReviewRunRuleGroup.name).where(
                    ReviewRunRuleGroup.review_run_id == run.review_run_id
                )
            )
        )
    assert sorted(recipients) == [f"ali@{DOMAIN}", f"ayse@{DOMAIN}"]
    assert groups == ["Güvenlik"]

    [(to, email)] = scheduled.mailer.sent
    assert sorted(to) == [f"ali@{DOMAIN}", f"ayse@{DOMAIN}"]
    assert email.subject == f"Zamanlanmış inceleme: {definition.name} — Tamamlandı"
    assert "Kural grupları: Güvenlik" in email.text
    assert "Güvenlik: Yüksek 1 · Orta 0 · Düşük 0" in email.text
    assert f"Raporu aç: {ORIGIN}/gecmis?run={run.public_id}" in email.text
    # Decision 1: no SQL text, snippet or finding reason in the e-mail.
    for part in (email.subject, email.text, email.html):
        assert MARKER not in part
        assert "SELECT" not in part


async def test_an_overlapping_trigger_is_skipped_while_the_previous_run_continues(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    scheduled.env.llm.gate = asyncio.Event()
    scheduler = scheduled.scheduler()
    await scheduler.tick()
    await asyncio.wait_for(scheduled.env.llm.started.wait(), 5)

    await scheduled.make_due(schedule_id)
    await scheduler.tick()
    first, second = await scheduled.records(schedule_id)
    assert first.state == "running"
    assert (second.state, second.skip_reason, second.review_run_id) == (
        "skipped",
        "previous_running",
        None,
    )

    scheduled.env.llm.gate.set()
    await scheduler.drain()
    assert (await scheduled.records(schedule_id))[0].state == "completed"


async def test_the_owner_stops_a_running_run_and_no_e_mail_goes_out(
    scheduled: Scheduled,
) -> None:
    # Requirement 11, Decision 15: "Durdur" cuts the running review like "Analizi durdur".
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    scheduled.env.llm.gate = asyncio.Event()
    scheduler = scheduled.scheduler()
    await scheduler.tick()
    await asyncio.wait_for(scheduled.env.llm.started.wait(), 5)

    auth = scheduled.env.auth
    stopped = await auth.client.post(
        f"{auth.prefix}/scheduled-reviews/{schedule_id}/stop", headers=scheduled.owner.headers
    )
    assert stopped.status_code == 202, stopped.text
    assert stopped.json()["state"] == "cancelling"
    await asyncio.wait_for(scheduler.drain(), 10)

    [record] = await scheduled.records(schedule_id)
    assert (record.state, record.email_status) == ("cancelled", None)
    assert (await _run_of(record)).status == "cancelled"
    assert scheduled.mailer.sent == []
    assert (await scheduled.definition(schedule_id)).status == "active"


async def test_a_due_time_missed_while_down_is_recorded_and_not_caught_up(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id, ago=timedelta(hours=5))
    scheduler = scheduled.scheduler()

    await scheduler.tick()
    await scheduler.drain()

    [record] = await scheduled.records(schedule_id)
    assert (record.trigger, record.state, record.review_run_id) == ("missed", "missed", None)
    assert scheduled.env.llm.calls == []
    definition = await scheduled.definition(schedule_id)
    assert definition.next_run_at is not None and definition.next_run_at > scheduled.clock.now

    auth = scheduled.env.auth
    listed = (
        await auth.client.get(f"{auth.prefix}/scheduled-reviews", headers=scheduled.owner.headers)
    ).json()
    assert listed["items"][0]["missed"] is True


async def test_without_a_published_version_or_objects_the_trigger_is_skipped(
    scheduled: Scheduled,
) -> None:
    async def no_rules(_session: Any, _start: ScheduledStart) -> ReviewExecution:
        raise ApplicationError(409, "no_published_rule_set", "Yayımlanmış kural yok.")

    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    await scheduled.scheduler(start_run=no_rules).tick()

    empty_id = await scheduled.define(
        selection={"mode": "filter", "filter": {"database": "DWH", "query": "olmayan"}}
    )
    await scheduled.make_due(empty_id)
    await scheduled.scheduler().tick()

    [record] = await scheduled.records(schedule_id)
    [empty] = await scheduled.records(empty_id)
    assert (record.state, record.skip_reason) == ("skipped", "no_published_rule_set")
    assert (empty.state, empty.skip_reason) == ("skipped", "no_objects")
    assert scheduled.mailer.sent == []


async def test_the_tenant_limit_holds_and_follows_the_setting(scheduled: Scheduled) -> None:
    first_id = await scheduled.define()
    second_id = await scheduled.define()
    async with engine.begin() as connection:
        tenant_id = (
            await connection.execute(
                select(ScheduledReview.tenant_id).where(ScheduledReview.public_id == first_id)
            )
        ).scalar_one()
        await connection.execute(
            ScheduledReviewSetting.__table__.insert().values(
                tenant_id=tenant_id, max_concurrent_runs=1
            )
        )
    await scheduled.make_due(first_id)
    await scheduled.make_due(second_id)
    scheduled.env.llm.gate = asyncio.Event()
    scheduler = scheduled.scheduler()

    await scheduler.tick()
    states = sorted(
        [
            (await scheduled.records(first_id))[0].state,
            (await scheduled.records(second_id))[0].state,
        ]
    )
    assert states == ["queued", "running"]

    async with engine.begin() as connection:
        await connection.execute(
            update(ScheduledReviewSetting)
            .where(ScheduledReviewSetting.tenant_id == tenant_id)
            .values(max_concurrent_runs=2)
        )
    await scheduler.tick()
    states = sorted(
        [
            (await scheduled.records(first_id))[0].state,
            (await scheduled.records(second_id))[0].state,
        ]
    )
    assert states == ["running", "running"]

    scheduled.env.llm.gate.set()
    await scheduler.drain()


async def test_two_scheduler_copies_run_a_due_time_once(scheduled: Scheduled) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    first, second = scheduled.scheduler(), scheduled.scheduler()

    await asyncio.gather(first.tick(), second.tick())
    await asyncio.gather(first.drain(), second.drain())

    records = await scheduled.records(schedule_id)
    assert [(record.trigger, record.state) for record in records] == [("scheduled", "completed")]
    assert len(scheduled.mailer.sent) == 1


async def test_a_record_left_running_is_interrupted_when_the_process_starts(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    definition = await scheduled.definition(schedule_id)
    async with engine.begin() as connection:
        await connection.execute(
            ScheduledReviewRun.__table__.insert().values(
                public_id=str(uuid4()),
                scheduled_review_id=definition.scheduled_review_id,
                tenant_id=definition.tenant_id,
                due_at=scheduled.clock.now,
                trigger="scheduled",
                state="running",
            )
        )

    assert await interrupt_stale_scheduled_runs(async_session_factory) == 1
    [record] = await scheduled.records(schedule_id)
    assert record.state == "interrupted"


async def test_run_now_starts_through_the_queue_and_refuses_a_second_one(
    scheduled: Scheduled, super_admin: SuperAdmin
) -> None:
    schedule_id = await scheduled.define()
    auth = scheduled.env.auth
    login = await auth.login(super_admin.username, super_admin.password)
    admin = auth.auth_headers(login.json())
    url = f"{auth.prefix}/scheduled-reviews/{schedule_id}/run"
    assert (await auth.client.post(url, headers=admin)).status_code == 202
    scheduled.env.llm.gate = asyncio.Event()
    scheduler = scheduled.scheduler()

    await scheduler.tick()
    [record] = await scheduled.records(schedule_id)
    assert (record.trigger, record.state) == ("manual", "running")
    again = await auth.client.post(url, headers=admin)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "scheduled_review_running"

    scheduled.env.llm.gate.set()
    await scheduler.drain()
    history = (
        await auth.client.get(
            f"{auth.prefix}/scheduled-reviews/{schedule_id}/runs", headers=scheduled.owner.headers
        )
    ).json()
    [item] = history["items"]
    assert (item["trigger"], item["state"], item["email_status"]) == ("manual", "completed", "sent")
    assert item["triggered_by_name"] and item["review_run_id"]
    assert item["finding_count"] == 1


async def test_a_failed_e_mail_is_retried_after_1_5_and_15_minutes_across_restarts(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    scheduled.mailer.failures = 10
    scheduler = scheduled.scheduler()
    await scheduler.tick()
    await scheduler.drain()

    [record] = await scheduled.records(schedule_id)
    assert (record.email_status, record.email_attempts) == ("pending", 1)
    assert record.next_email_at == scheduled.clock.now + timedelta(minutes=1)

    for attempt, delay in ((2, timedelta(minutes=5)), (3, timedelta(minutes=15))):
        scheduled.clock.now = record.next_email_at
        # Each attempt by a fresh scheduler: the pending state lives in the database.
        await scheduled.scheduler().send_due_emails()
        [record] = await scheduled.records(schedule_id)
        assert (record.email_status, record.email_attempts) == ("pending", attempt)
        assert record.next_email_at == scheduled.clock.now + delay

    # Not due yet: nothing is sent early.
    scheduled.clock.now = record.next_email_at - timedelta(seconds=1)
    await scheduled.scheduler().send_due_emails()
    assert (await scheduled.records(schedule_id))[0].email_attempts == 3

    scheduled.clock.now = record.next_email_at
    await scheduled.scheduler().send_due_emails()
    [record] = await scheduled.records(schedule_id)
    assert (record.email_status, record.email_attempts, record.next_email_at) == ("failed", 4, None)
    assert record.state == "completed"
    assert scheduled.mailer.attempts == 4

    auth = scheduled.env.auth
    listed = (
        await auth.client.get(f"{auth.prefix}/scheduled-reviews", headers=scheduled.owner.headers)
    ).json()
    assert listed["items"][0]["email_failed"] is True


async def test_without_a_relay_the_report_is_stored_and_the_e_mail_not_configured(
    scheduled: Scheduled,
) -> None:
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    scheduler = scheduled.scheduler(mailer=None)

    await scheduler.tick()
    await scheduler.drain()

    [record] = await scheduled.records(schedule_id)
    assert (record.state, record.email_status, record.email_attempts) == (
        "completed",
        "not_configured",
        0,
    )
    assert (await _run_of(record)).status == "completed"


async def _email_of(session: RoleSession) -> str:
    async with engine.connect() as connection:
        email = (
            await connection.execute(
                text("SELECT email FROM app_user WHERE public_id = :id"), {"id": session.public_id}
            )
        ).scalar_one()
        return str(email)


async def test_a_recipient_reads_the_report_but_cannot_change_it(scheduled: Scheduled) -> None:
    """review-history-export Decision 8 and Acceptance 6; scheduled-review-email Decision 12."""

    env = scheduled.env
    recipient = await env.sessions.reviewer()
    stranger = await env.sessions.reviewer()
    # Directory accounts of the test harness live in another domain; let theirs in too.
    domain = (await _email_of(recipient)).rsplit("@", 1)[1]
    env.auth.use_settings(mail_allowed_domains=f"{DOMAIN},{domain}")
    schedule_id = await scheduled.define(
        recipients=[(await _email_of(recipient)).upper(), f"ayse@{DOMAIN}"]
    )
    await scheduled.make_due(schedule_id)
    scheduler = scheduled.scheduler()
    await scheduler.tick()
    await scheduler.drain()
    [record] = await scheduled.records(schedule_id)
    run = await _run_of(record)
    client, prefix = env.auth.client, env.prefix
    base = f"{prefix}/review-runs/{run.public_id}"

    detail = await client.get(base, headers=recipient.headers)
    assert detail.status_code == 200, detail.text
    assert (detail.json()["kind"], detail.json()["owned"]) == ("scheduled", False)
    assert (await client.get(f"{base}/exports/csv", headers=recipient.headers)).status_code == 200
    assert (await client.get(f"{base}/exports/sql", headers=recipient.headers)).status_code == 200
    finding_id = detail.json()["results"][0]["findings"][0]["id"]
    mark = await client.put(
        f"{base}/findings/{finding_id}/false-positive",
        json={"false_positive": True},
        headers=recipient.headers,
    )
    assert mark.status_code == 404
    assert (await client.delete(base, headers=recipient.headers)).status_code == 404
    listed = (await client.get(f"{prefix}/review-runs", headers=recipient.headers)).json()
    assert run.public_id not in [item["id"] for item in listed["items"]]

    for path in ("", "/exports/csv", "/exports/sql"):
        assert (await client.get(f"{base}{path}", headers=stranger.headers)).status_code == 404
    owner_view = await client.get(base, headers=scheduled.owner.headers)
    assert owner_view.json()["owned"] is True


async def test_a_run_that_cannot_start_shows_its_code_in_the_history(
    scheduled: Scheduled,
) -> None:
    scheduled.env.catalog.failure = SqlServerNotConfigured()
    schedule_id = await scheduled.define()
    await scheduled.make_due(schedule_id)
    await scheduled.scheduler().tick()

    [record] = await scheduled.records(schedule_id)
    assert (record.state, record.error_code, record.review_run_id) == (
        "failed",
        "sql_connection_not_configured",
        None,
    )
    auth = scheduled.env.auth
    headers = scheduled.owner.headers
    [item] = (
        await auth.client.get(
            f"{auth.prefix}/scheduled-reviews/{schedule_id}/runs", headers=headers
        )
    ).json()["items"]
    assert (item["state"], item["error_code"]) == ("failed", "sql_connection_not_configured")
    listed = (await auth.client.get(f"{auth.prefix}/scheduled-reviews", headers=headers)).json()
    assert listed["items"][0]["last_run"]["error_code"] == "sql_connection_not_configured"
