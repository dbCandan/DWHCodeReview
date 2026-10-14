"""Review history, false-positive marks, deletion, retention and exports on real PostgreSQL.

sql-review/PRDs/005-review-history-export Requirement 1-10 (Acceptance 1 and 2): ownership and
role checks (401/403/404), pages, repeated marks, deletion scope, the running-run conflict, the
retention job with its advisory lock, and the CSV and SQL files built on the server.
"""

import asyncio
import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text, update

from app.db.session import async_session_factory, engine
from app.domain.llm import LlmChatRequest
from app.domain.models.llm_call import LlmCallSummary
from app.domain.models.review import (
    ReviewFinding,
    ReviewRuleResult,
    ReviewRun,
    ReviewRunObject,
)
from app.domain.models.tenant import Tenant
from app.infrastructure.repositories.review_repository import RETENTION_LOCK_KEY
from app.services.review_history_service import purge_expired_review_runs
from tests.fakes.review_ports import ok, rule_code_of
from tests.integration.conftest import ReviewEnv, RoleSession, SuperAdmin, sse_events
from tests.integration.review_helpers import run_of, stream_until

pytestmark = pytest.mark.integration

MARKER = f"GIZLI-{uuid4().hex}"
SCRIPT = f"SELECT *\nFROM dbo.Musteri -- {MARKER}\nWHERE Kimlik = NULL"
DEFINITION = f"CREATE VIEW sales.vw_Satis AS\nSELECT *\nFROM b -- {MARKER}"


def _reply(request: LlmChatRequest) -> Any:
    code = rule_code_of(request)
    content = request.user_content
    if "Yıldız kullanma." in content and "SELECT *" in content:
        found = [{"rule_code": code, "snippet": "SELECT *", "reason": "Yıldız var"}]
        if "FROM dbo.Musteri" in content:
            found.append(
                {"rule_code": code, "snippet": "FROM dbo.Musteri", "reason": "=HYPERLINK()"}
            )
        return ok(json.dumps({"violations": found}))
    if "NULL eşitliği yazma." in content and "= NULL" in content:
        return ok(
            json.dumps(
                {
                    "violations": [
                        {"rule_code": code, "snippet": "WHERE Kimlik = NULL", "reason": "NULL"}
                    ]
                }
            )
        )
    return ok('{"violations": []}')


@pytest.fixture
def history_logs() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Handler(level=logging.DEBUG)
    logger = logging.getLogger("app.review_history")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


async def _setup(env: ReviewEnv) -> tuple[RoleSession, list[str]]:
    manager = await env.sessions.rule_manager()
    _, codes = await env.publish(
        manager, [("Yıldız kullanma.", False)], [("NULL eşitliği yazma.", False)]
    )
    env.llm.responder = _reply
    env.catalog.definitions[("DWH2", "sales", "vw_Satis")] = DEFINITION
    return manager, codes


async def _script_run(
    env: ReviewEnv, session: RoleSession, label: str = "Etiket"
) -> dict[str, Any]:
    response = await env.script_review(session, SCRIPT, label)
    events = sse_events(response.text)
    assert events[-1]["phase"] == "complete", events[-1]
    return events[-1]


async def _object_run(env: ReviewEnv, session: RoleSession) -> dict[str, Any]:
    env.catalog.definitions[("DWH", "dbo", "usp_Load")] = SCRIPT
    response = await env.object_review(
        session,
        [
            {"database": "DWH", "schema": "dbo", "name": "usp_Load", "type_code": "P"},
            {"database": "DWH2", "schema": "sales", "name": "vw_Satis", "type_code": "V"},
        ],
    )
    events = sse_events(response.text)
    assert events[-1]["phase"] == "complete", events[-1]
    return events[-1]


def _get(env: ReviewEnv, path: str, session: RoleSession) -> Any:
    return env.auth.client.get(f"{env.prefix}/review-runs{path}", headers=session.headers)


async def test_the_list_shows_own_runs_newest_first_with_titles_and_counts(
    review_env: ReviewEnv,
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    object_run = await _object_run(review_env, reviewer)
    script_run = await _script_run(review_env, reviewer, "Gece yükü")

    listed = (await _get(review_env, "", reviewer)).json()

    assert listed["total"] == 2 and listed["page"] == 1 and listed["page_size"] == 50
    newest, older = listed["items"]
    assert newest["id"] == script_run["run_id"]
    assert (newest["kind"], newest["status"], newest["title"], newest["subtitle"]) == (
        "script",
        "completed",
        "Gece yükü",
        None,
    )
    assert newest["finding_count"] == 3 and newest["object_count"] == 1
    assert older["id"] == object_run["run_id"]
    assert older["title"] == "2 veritabanı (DWH, DWH2) · 2 nesne"
    assert older["subtitle"] == "[DWH] dbo.usp_Load (P), [DWH2] sales.vw_Satis (V)"
    assert older["finding_count"] == 4
    assert newest["owned"] and newest["owner_display_name"] == reviewer.display_name
    assert isinstance(newest["rule_version"], int) and newest["finished_at"]

    page = (await _get(review_env, "?page=2&page_size=1", reviewer)).json()
    assert page["total"] == 2 and [item["id"] for item in page["items"]] == [object_run["run_id"]]
    for query in ("?page=0", "?page_size=201", "?scope=herkes"):
        invalid = await _get(review_env, query, reviewer)
        assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "invalid_request"


async def test_only_the_rule_manager_sees_every_run_and_only_read_only(
    review_env: ReviewEnv,
) -> None:
    manager, _ = await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)

    forbidden = await _get(review_env, "?scope=all", reviewer)
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "review_scope_forbidden"
    everyone = (await _get(review_env, "?scope=all&page_size=200", manager)).json()
    mine = (await _get(review_env, "?scope=mine", manager)).json()
    theirs = next(item for item in everyone["items"] if item["id"] == run["run_id"])
    assert theirs["owned"] is False and theirs["owner_display_name"] == reviewer.display_name
    assert run["run_id"] not in [item["id"] for item in mine["items"]]
    assert run["run_id"] not in [
        item["id"] for item in (await _get(review_env, "", colleague)).json()["items"]
    ]

    detail = await _get(review_env, f"/{run['run_id']}", manager)
    assert detail.status_code == 200
    finding_id = detail.json()["results"][0]["findings"][0]["id"]
    for method, path, body in (
        ("PUT", f"/{run['run_id']}/findings/{finding_id}/false-positive", {"false_positive": True}),
        ("DELETE", f"/{run['run_id']}", None),
    ):
        refused = await review_env.auth.client.request(
            method, f"{review_env.prefix}/review-runs{path}", json=body, headers=manager.headers
        )
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "review_run_not_owner"


async def test_the_detail_is_visible_to_the_owner_and_rule_manager_only(
    review_env: ReviewEnv,
) -> None:
    manager, codes = await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)

    own = await _get(review_env, f"/{run['run_id']}", reviewer)
    assert own.status_code == 200
    body = own.json()
    assert body["label"] == "Etiket" and body["status"] == "completed"
    (result,) = body["results"]
    assert [r["rule_id"] for r in result["rule_results"]] == codes
    assert [f["line_reference"] for f in result["findings"]] == ["Satır 1", "Satır 2", "Satır 3"]
    assert "source_sql" not in own.text and MARKER not in own.text
    assert (await _get(review_env, f"/{run['run_id']}", manager)).status_code == 200
    for session, run_id in ((colleague, run["run_id"]), (reviewer, str(uuid4()))):
        hidden = await _get(review_env, f"/{run_id}", session)
        assert hidden.status_code == 404
        assert hidden.json()["detail"]["code"] == "review_run_not_found"
    header = review_env.auth.settings.tenant_header
    anonymous = await review_env.auth.client.get(
        f"{review_env.prefix}/review-runs/{run['run_id']}",
        headers={header: reviewer.headers[header]},
    )
    assert anonymous.status_code == 401


async def _mark(
    env: ReviewEnv, session: RoleSession, run_id: str, kind: str, item_id: str, value: Any
) -> Any:
    return await env.auth.client.put(
        f"{env.prefix}/review-runs/{run_id}/{kind}/{item_id}/false-positive",
        json={"false_positive": value},
        headers=session.headers,
    )


async def test_false_positive_marks_are_stored_and_repeating_changes_nothing(
    review_env: ReviewEnv,
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)
    finding = run["results"][0]["findings"][0]

    first = await _mark(review_env, reviewer, run["run_id"], "findings", finding["id"], True)
    again = await _mark(review_env, reviewer, run["run_id"], "findings", finding["id"], True)

    assert first.status_code == 200
    assert first.json()["false_positive"] is True and first.json()["id"] == finding["id"]
    assert again.json() == first.json()
    detail = (await _get(review_env, f"/{run['run_id']}", reviewer)).json()
    assert detail["results"][0]["findings"][0]["false_positive"] is True
    cleared = await _mark(review_env, reviewer, run["run_id"], "findings", finding["id"], False)
    assert cleared.json()["false_positive"] is False

    assert (
        await _mark(review_env, colleague, run["run_id"], "findings", finding["id"], True)
    ).status_code == 404
    missing = await _mark(review_env, reviewer, run["run_id"], "findings", str(uuid4()), True)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "review_finding_not_found"
    invalid = await _mark(review_env, reviewer, run["run_id"], "findings", finding["id"], "evet")
    assert invalid.status_code == 422


async def test_only_a_failed_rule_result_without_findings_can_be_marked(
    review_env: ReviewEnv,
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)
    failed, other = run["results"][0]["rule_results"]
    assert failed["status"] == "FAIL"

    with_findings = await _mark(
        review_env, reviewer, run["run_id"], "rule-results", failed["id"], True
    )
    assert with_findings.status_code == 409
    assert with_findings.json()["detail"]["code"] == "false_positive_not_applicable"
    async with async_session_factory() as session:
        result_id = await session.scalar(
            select(ReviewRuleResult.review_rule_result_id).where(
                ReviewRuleResult.public_id == failed["id"]
            )
        )
        await session.execute(
            text("DELETE FROM review_finding WHERE review_rule_result_id = :r"), {"r": result_id}
        )
        await session.execute(
            update(ReviewRuleResult)
            .where(ReviewRuleResult.public_id == other["id"])
            .values(status="PASS", severity=None)
        )
        await session.commit()
    marked = await _mark(review_env, reviewer, run["run_id"], "rule-results", failed["id"], True)
    assert marked.status_code == 200 and marked.json()["false_positive"] is True
    passed = await _mark(review_env, reviewer, run["run_id"], "rule-results", other["id"], True)
    assert passed.status_code == 409


async def test_deleting_a_run_removes_everything_and_keeps_call_summaries(
    review_env: ReviewEnv, history_logs: list[logging.LogRecord]
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)
    stored = await run_of(run["run_id"])
    summary_id = str(uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_call_summary (public_id, tenant_id, review_run_id, started_at, "
                "object_label, rule_code, attempt, chat_api, model, endpoint_host, streamed, "
                "outcome, duration_ms) VALUES (:p, :t, :r, now(), 'Etiket (SCRIPT)', 'Kural01', "
                "1, 'openai', 'model', 'llm.example.test', true, 'ok', 5)"
            ),
            {"p": summary_id, "t": stored.tenant_id, "r": stored.review_run_id},
        )
        await session.commit()

    delete_path = f"{review_env.prefix}/review-runs/{run['run_id']}"
    hidden = await review_env.auth.client.delete(delete_path, headers=colleague.headers)
    assert hidden.status_code == 404
    deleted = await review_env.auth.client.delete(delete_path, headers=reviewer.headers)
    assert deleted.status_code == 204 and deleted.content == b""

    assert (await _get(review_env, f"/{run['run_id']}", reviewer)).status_code == 404
    async with async_session_factory() as session:
        remaining = await session.scalar(
            select(func.count())
            .select_from(ReviewFinding)
            .where(ReviewFinding.public_id.in_([f["id"] for f in run["results"][0]["findings"]]))
        )
        objects = await session.scalar(
            select(func.count())
            .select_from(ReviewRunObject)
            .where(ReviewRunObject.review_run_id == stored.review_run_id)
        )
        summary = await session.scalar(
            select(LlmCallSummary).where(LlmCallSummary.public_id == summary_id)
        )
    assert remaining == 0 and objects == 0
    assert summary is not None and summary.review_run_id is None
    (event,) = [r for r in history_logs if r.getMessage() == "review_history.deleted"]
    fields: dict[str, Any] = event.structured_fields  # type: ignore[attr-defined]
    assert fields["run_id"] == run["run_id"] and fields["count"] == 1


async def _set_running(run_id: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            update(ReviewRun)
            .where(ReviewRun.public_id == run_id)
            .values(status="running", finished_at=None)
        )
        await session.commit()


async def test_a_running_run_cannot_be_deleted_and_delete_all_spares_it(
    review_env: ReviewEnv,
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    kept = await _script_run(review_env, reviewer, "sürüyor")
    finished = [await _script_run(review_env, reviewer) for _ in range(2)]
    others = await _script_run(review_env, colleague)
    await _set_running(kept["run_id"])

    conflict = await review_env.auth.client.delete(
        f"{review_env.prefix}/review-runs/{kept['run_id']}", headers=reviewer.headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "review_run_in_progress"
    missing_scope = await review_env.auth.client.delete(
        f"{review_env.prefix}/review-runs", headers=reviewer.headers
    )
    assert missing_scope.status_code == 422
    everything = await review_env.auth.client.delete(
        f"{review_env.prefix}/review-runs?scope=mine", headers=reviewer.headers
    )
    assert everything.json() == {"deleted_count": 2}
    remaining = [item["id"] for item in (await _get(review_env, "", reviewer)).json()["items"]]
    assert remaining == [kept["run_id"]]
    assert (await _get(review_env, f"/{others['run_id']}", colleague)).status_code == 200
    for run in finished:
        assert (await _get(review_env, f"/{run['run_id']}", reviewer)).status_code == 404


async def test_retention_deletes_only_runs_finished_before_the_window(
    review_env: ReviewEnv, history_logs: list[logging.LogRecord]
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    old = await _script_run(review_env, reviewer, "eski")
    recent = await _script_run(review_env, reviewer, "yeni")
    running = await _script_run(review_env, reviewer, "sürüyor")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        await session.execute(
            update(ReviewRun)
            .where(ReviewRun.public_id == old["run_id"])
            .values(finished_at=now - timedelta(days=2, minutes=1))
        )
        await session.execute(
            update(ReviewRun)
            .where(ReviewRun.public_id == recent["run_id"])
            .values(finished_at=now - timedelta(days=1, hours=23))
        )
        await session.commit()
    await _set_running(running["run_id"])

    result = await purge_expired_review_runs(async_session_factory, retention_days=2, now=now)

    assert result.outcome == "ok" and result.deleted >= 1
    ids = [item["id"] for item in (await _get(review_env, "", reviewer)).json()["items"]]
    assert old["run_id"] not in ids
    assert recent["run_id"] in ids and running["run_id"] in ids
    events = [r for r in history_logs if r.getMessage() == "review_history.retention_run"]
    assert events[-1].structured_fields["deleted"] == result.deleted  # type: ignore[attr-defined]


async def test_only_one_copy_runs_the_retention_at_a_time(review_env: ReviewEnv) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    expired = await _script_run(review_env, reviewer, "süresi doldu")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        await session.execute(
            update(ReviewRun)
            .where(ReviewRun.public_id == expired["run_id"])
            .values(finished_at=now - timedelta(days=200))
        )
        await session.commit()

    async with engine.connect() as holder:
        transaction = await holder.begin()
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RETENTION_LOCK_KEY})
        blocked = await purge_expired_review_runs(async_session_factory, retention_days=90, now=now)
        await transaction.rollback()
    assert (blocked.outcome, blocked.deleted) == ("skipped", 0)
    assert (await _get(review_env, f"/{expired['run_id']}", reviewer)).status_code == 200

    runs = await asyncio.gather(
        purge_expired_review_runs(async_session_factory, retention_days=90, now=now),
        purge_expired_review_runs(async_session_factory, retention_days=90, now=now),
    )
    assert {run.outcome for run in runs} <= {"ok", "skipped"}
    assert sum(run.deleted for run in runs) >= 1
    assert (await _get(review_env, f"/{expired['run_id']}", reviewer)).status_code == 404


async def test_the_csv_export_marks_false_positives_and_blocks_formulas(
    review_env: ReviewEnv, history_logs: list[logging.LogRecord]
) -> None:
    manager, codes = await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    colleague = await review_env.sessions.reviewer()
    run = await _script_run(review_env, reviewer)
    marked = run["results"][0]["findings"][0]
    await _mark(review_env, reviewer, run["run_id"], "findings", marked["id"], True)

    response = await _get(review_env, f"/{run['run_id']}/exports/csv", reviewer)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="sql-review-\d{13}\.csv"', response.headers["content-disposition"]
    )
    assert response.content.startswith(b"\xef\xbb\xbf")
    lines = response.content.decode("utf-8").split("\r\n")
    assert lines[0] == (
        "﻿generated_at,database,schema,name,object_type,rule_id,tier,status,severity,"
        "description,line_reference,code_snippet,false_positive,rule_group"
    )
    assert len(lines) == 4
    # 005 Decision 9: rule_group is the last column; these rules are ungrouped.
    assert lines[1].endswith(",Yıldız var,Satır 1,SELECT *,true,")
    assert ",sql,Etiket,SCRIPT," in lines[1]
    assert ",'=HYPERLINK()," in lines[2] and lines[2].endswith(",false,")
    assert f",{codes[1]},,FAIL,LOW,NULL,Satır 3,WHERE Kimlik = NULL,false" in lines[3]
    assert (await _get(review_env, f"/{run['run_id']}/exports/csv", manager)).status_code == 200
    assert (await _get(review_env, f"/{run['run_id']}/exports/csv", colleague)).status_code == 404
    exported = [r for r in history_logs if r.getMessage() == "review_history.exported"]
    assert exported and all(MARKER not in str(r.__dict__) for r in history_logs)


async def test_the_sql_export_points_every_line_at_the_file_and_skips_false_positives(
    review_env: ReviewEnv,
) -> None:
    manager, _ = await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    run = await _object_run(review_env, reviewer)
    first_object_findings = run["results"][0]["findings"]
    await _mark(
        review_env, reviewer, run["run_id"], "findings", first_object_findings[1]["id"], True
    )

    response = await _get(review_env, f"/{run['run_id']}/exports/sql", manager)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/sql; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="sql-review-source-\d{13}\.sql"',
        response.headers["content-disposition"],
    )
    content = response.content.decode("utf-8")
    lines = content.split("\n")
    comments = [line for line in lines if line.startswith("- ")]
    assert len(comments) == 3
    assert "=HYPERLINK()" not in content.split("*/")[0]
    for comment, expected in zip(
        comments, ("SELECT *", "WHERE Kimlik = NULL", "SELECT *"), strict=True
    ):
        number = int(re.search(r"Satır (\d+)", comment).group(1))  # type: ignore[union-attr]
        assert lines[number - 1] == expected
    assert "\n\nGO\n\n-- [DWH2] sales.vw_Satis (VIEW)\n" in content
    assert content.count(MARKER) == 2


async def test_runs_without_stored_text_have_no_sql_file(review_env: ReviewEnv) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    review_env.llm.gate = asyncio.Event()
    events, _ = await stream_until(
        review_env,
        reviewer,
        "/script-reviews",
        {"sql": SCRIPT},
        lambda event: event["phase"] == "rule_start",
    )
    await review_env.settle()
    review_env.llm.gate = None
    review_env.llm.configured = False
    failed = sse_events((await review_env.script_review(reviewer, SCRIPT)).text)
    review_env.llm.configured = True

    listed = {item["id"]: item for item in (await _get(review_env, "", reviewer)).json()["items"]}
    assert listed[events[0]["run_id"]]["status"] == "cancelled"
    assert listed[failed[0]["run_id"]]["status"] == "failed"
    assert listed[failed[0]["run_id"]]["error_message"] == "LLM bağlantısı yapılandırılmamış."
    for run_id in (events[0]["run_id"], failed[0]["run_id"]):
        refused = await _get(review_env, f"/{run_id}/exports/sql", reviewer)
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "sql_text_unavailable"
        assert (await _get(review_env, f"/{run_id}", reviewer)).json()["results"] == []
    csv = (await _get(review_env, f"/{failed[0]['run_id']}/exports/csv", reviewer)).text
    assert csv.split("\r\n")[1].endswith(",,,,,,,,,LLM bağlantısı yapılandırılmamış.,,,false,")


async def test_other_tenants_never_see_a_run(
    review_env: ReviewEnv, super_admin: SuperAdmin
) -> None:
    manager, _ = await _setup(review_env)
    async with async_session_factory() as session:
        tenant = Tenant(code=f"t-{uuid4().hex[:10]}", name="Başka kurum")
        session.add(tenant)
        await session.commit()
        other = str(tenant.public_id)
    login = await review_env.auth.login(super_admin.username, super_admin.password)
    headers = review_env.auth.auth_headers(login.json())
    headers[review_env.auth.settings.tenant_header] = other
    admin = RoleSession(headers, str(login.json()["user"]["public_id"]), "Yönetici")
    await review_env.publish(admin, [("Yıldız kullanma.", False)])
    run = await _script_run(review_env, admin)

    everyone = (await _get(review_env, "?scope=all&page_size=200", manager)).json()
    assert run["run_id"] not in [item["id"] for item in everyone["items"]]
    assert (await _get(review_env, f"/{run['run_id']}", manager)).status_code == 404
    assert (await _get(review_env, f"/{run['run_id']}/exports/csv", manager)).status_code == 404


# --- runs without an object limit (003 Decision 3, 005 Requirement 2, 3, 7 and 8) --------------


def _many(count: int) -> list[dict[str, str]]:
    return [
        {
            "database": "DWH" if n % 2 == 0 else "DWH2",
            "schema": "dbo",
            "name": f"usp_{n:04d}",
            "type_code": "P",
        }
        for n in range(count)
    ]


async def _large_run(env: ReviewEnv, session: RoleSession, count: int) -> str:
    for item in _many(count):
        env.catalog.definitions[(item["database"], "dbo", item["name"])] = SCRIPT
    events = sse_events((await env.object_review(session, _many(count))).text)
    assert events[-1]["phase"] == "complete", events[-1]
    return str(events[-1]["run_id"])


async def test_the_detail_of_a_large_run_is_read_page_by_page(review_env: ReviewEnv) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    run_id = await _large_run(review_env, reviewer, 120)

    first = (await _get(review_env, f"/{run_id}", reviewer)).json()
    third = (await _get(review_env, f"/{run_id}?page=3&page_size=50", reviewer)).json()
    whole = (await _get(review_env, f"/{run_id}?page_size=200", reviewer)).json()
    beyond = (await _get(review_env, f"/{run_id}?page=9", reviewer)).json()
    invalid = [
        await _get(review_env, f"/{run_id}?page_size=201", reviewer),
        await _get(review_env, f"/{run_id}?page=0", reviewer),
    ]

    assert (first["object_count"], first["results_page"], first["results_page_size"]) == (
        120,
        1,
        50,
    )
    assert [item["name"] for item in first["results"]] == [f"usp_{n:04d}" for n in range(50)]
    assert all(len(item["rule_results"]) == 2 and item["findings"] for item in first["results"])
    assert (third["results_page"], third["results_page_size"]) == (3, 50)
    assert [item["name"] for item in third["results"]] == [f"usp_{n:04d}" for n in range(100, 120)]
    assert len(whole["results"]) == 120 and beyond["results"] == []
    assert first["title"] == "2 veritabanı (DWH, DWH2) · 120 nesne"
    assert first["subtitle"] == (
        "[DWH] dbo.usp_0000 (P), [DWH2] dbo.usp_0001 (P), [DWH] dbo.usp_0002 (P) +117"
    )
    assert first["finding_count"] == 120 * 3
    assert [response.status_code for response in invalid] == [422, 422]
    assert MARKER not in json.dumps(whole)


async def test_the_history_list_never_reads_the_objects_or_the_sql_text_of_a_run(
    review_env: ReviewEnv,
) -> None:
    await _setup(review_env)
    reviewer = await review_env.sessions.reviewer()
    await _large_run(review_env, reviewer, 60)
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        listed = (await _get(review_env, "?scope=mine", reviewer)).json()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    (run,) = listed["items"]
    assert run["title"] == "2 veritabanı (DWH, DWH2) · 60 nesne"
    assert run["subtitle"].endswith("+57") and run["object_count"] == 60
    object_reads = [
        statement for statement in statements if re.search(r"FROM review_run_object\b", statement)
    ]
    assert object_reads and all("source_sql" not in statement for statement in object_reads)
    # The title needs the databases and the first objects only, never a row per object.
    assert all("GROUP BY" in statement or "position <" in statement for statement in object_reads)


async def test_a_run_larger_than_the_driver_parameter_limit_is_read_and_exported(
    review_env: ReviewEnv, history_logs: list[logging.LogRecord]
) -> None:
    # 1,100 objects x 30 rules = 33,000 rule results: more identifiers than one PostgreSQL
    # statement accepts as parameters (32,767), so nothing may be loaded through an IN list.
    manager = await review_env.sessions.rule_manager()
    await review_env.publish(
        manager,
        [("Yıldız kullanma.", False)],
        [(f"Ek kural {number}.", False) for number in range(29)],
    )
    review_env.llm.responder = _reply
    reviewer = await review_env.sessions.reviewer()
    count = 1_100
    run_id = await _large_run(review_env, reviewer, count)

    page = await _get(review_env, f"/{run_id}?page=22&page_size=50", reviewer)
    csv = await _get(review_env, f"/{run_id}/exports/csv", reviewer)
    sql = await _get(review_env, f"/{run_id}/exports/sql", reviewer)

    assert page.status_code == 200, page.text
    assert [item["name"] for item in page.json()["results"]] == [
        f"usp_{n:04d}" for n in range(1050, 1100)
    ]
    assert csv.status_code == 200, csv.text
    rows = csv.text.split("\r\n")
    # One row per finding of the failed rule (two per object) and one per other rule result.
    assert len(rows) == 1 + count * (2 + 29)
    assert rows[1].split(",")[2:4] == ["dbo", "usp_0000"]
    assert rows[-1].split(",")[2:4] == ["dbo", "usp_1099"]
    assert sql.status_code == 200, sql.text
    assert sql.text.count("\n\nGO\n\n") == count - 1
    assert sql.text.count("-- [DWH] dbo.usp_") == count // 2
    exported = [
        record.structured_fields  # type: ignore[attr-defined]
        for record in history_logs
        if record.getMessage() == "review_history.exported"
    ]
    assert [(item["format"], item.get("rows"), item.get("objects")) for item in exported] == [
        ("csv", count * 31, None),
        ("sql", None, count),
    ]
