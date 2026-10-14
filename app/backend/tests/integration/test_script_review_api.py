"""Script review runs through the real HTTP application and PostgreSQL.

sql-review/PRDs/004-script-review Requirement 1-10 and 12 (Acceptance 1 and 2): no SQL Server
access, the metadata note, label rules, event fields, the 120,000-character limit, the shared
rate-limit counter, cancellation and the pasted text stored only with the run.
"""

import asyncio
import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.domain.models.review import ReviewRun, ReviewRunObject
from app.domain.sql_server import SqlServerError, SqlServerErrorClass
from tests.fakes.review_ports import rule_code_of
from tests.integration.conftest import ReviewEnv, RoleSession, sse_events
from tests.integration.review_helpers import result_counts, run_of, stream_until

pytestmark = pytest.mark.integration

MARKER = f"GIZLI-{uuid4().hex}"
LABEL_MARKER = f"ETIKET-{uuid4().hex}"
SCRIPT = f"SELECT *\nFROM dbo.Musteri -- {MARKER}\nWHERE Kimlik IS NULL"


@pytest.fixture
def all_logs() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Handler(level=logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


async def _ready(env: ReviewEnv) -> tuple[RoleSession, int, list[str]]:
    manager = await env.sessions.rule_manager()
    version, codes = await env.publish(
        manager, [("Şema doğrula.", True)], [("Yıldız kullanma.", False)]
    )
    # Every SQL Server call fails: a script review must never make one.
    env.catalog.failure = SqlServerError(SqlServerErrorClass.UNREACHABLE)
    return await env.sessions.reviewer(), version, codes


async def _stored_object(run: ReviewRun) -> ReviewRunObject:
    async with async_session_factory() as session:
        item = await session.scalar(
            select(ReviewRunObject).where(ReviewRunObject.review_run_id == run.review_run_id)
        )
        assert item is not None
        return item


async def test_a_script_review_never_touches_sql_server_and_stores_the_text(
    review_env: ReviewEnv, all_logs: list[logging.LogRecord]
) -> None:
    reviewer, version, codes = await _ready(review_env)

    response = await review_env.script_review(reviewer, f"\n  {SCRIPT}  \n", f"  {LABEL_MARKER} ")

    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    assert events[0] == {
        "phase": "run_started",
        "run_id": events[0]["run_id"],
        "kind": "script",
        "rule_version": version,
        "objects_total": 1,
        # rule-group-selection: no group was selected, so the run uses every rule.
        "selected_rule_groups": [],
        "selected_rule_codes": [],
        "all_rules": True,
    }
    phases = [event["phase"] for event in events if event["phase"] != "llm_stream"]
    assert phases[:4] == ["run_started", "object_start", "sql_ready", "rules_batch_start"]
    assert phases[-2:] == ["object_done", "complete"]
    assert "definition_fetch" not in phases and "metadata_fetch" not in phases
    for event in events[1:-1]:
        assert {
            key: event[key]
            for key in ("kind", "database", "object_index", "objects_total", "schema", "type_code")
        } == {
            "kind": "script",
            "database": "",
            "object_index": 0,
            "objects_total": 1,
            "schema": "sql",
            "type_code": "SCRIPT",
        }
        assert event["name"] == LABEL_MARKER
        assert event["object_label"] == f"{LABEL_MARKER} (SCRIPT)"
    assert next(e for e in events if e["phase"] == "sql_ready")["sql_length"] == len(SCRIPT)
    (result,) = events[-1]["results"]
    assert (result["database"], result["schema"], result["name"], result["object_type"]) == (
        "",
        "sql",
        LABEL_MARKER,
        "SCRIPT",
    )
    assert result["source_sql"] == SCRIPT
    assert review_env.catalog.calls == []

    prompts = {rule_code_of(c.request): c.request.user_content for c in review_env.llm.calls}
    assert "yapıştırılan SQL veya bağlantı olmadığı" in prompts[codes[0]]
    assert "KATALOG METADATASI" not in prompts[codes[1]]
    assert {c.target.object_label for c in review_env.llm.calls} == {f"{LABEL_MARKER} (SCRIPT)"}

    run = await run_of(events[0]["run_id"])
    assert (run.status, run.kind, run.label, run.object_count) == (
        "completed",
        "script",
        LABEL_MARKER,
        1,
    )
    stored = await _stored_object(run)
    assert (stored.source_sql, stored.database_name, stored.type_code) == (SCRIPT, None, "SCRIPT")

    logged = "\n".join(
        f"{record.getMessage()} {getattr(record, 'structured_fields', '')}" for record in all_logs
    )
    assert MARKER not in logged and LABEL_MARKER not in logged
    completed = [
        record.structured_fields  # type: ignore[attr-defined]
        for record in all_logs
        if record.getMessage() == "review_run.completed"
    ]
    assert completed[0]["sql_length"] == len(SCRIPT) and completed[0]["two_part"] is False


async def test_a_blank_label_becomes_the_default(review_env: ReviewEnv) -> None:
    reviewer, _, _ = await _ready(review_env)
    events = sse_events((await review_env.script_review(reviewer, "SELECT 1", "   ")).text)
    assert events[-1]["results"][0]["name"] == "Yapıştırılan SQL"
    assert (await run_of(events[0]["run_id"])).label == "Yapıştırılan SQL"


async def test_text_and_label_limits_are_checked_before_the_stream(review_env: ReviewEnv) -> None:
    reviewer, _, _ = await _ready(review_env)
    cases: list[tuple[dict[str, Any], str]] = [
        ({"sql": " \n\t "}, "sql_text_empty"),
        ({"sql": "x" * 120_001}, "sql_text_too_long"),
        ({"sql": "SELECT 1", "label": "e" * 201}, "label_too_long"),
        ({"label": "etiket"}, "invalid_request"),
    ]
    for body, code in cases:
        response = await review_env.auth.client.post(
            f"{review_env.prefix}/script-reviews", json=body, headers=reviewer.headers
        )
        assert response.status_code == 422, (code, response.text)
        assert response.json()["detail"]["code"] == code
    too_long = await review_env.script_review(reviewer, "y" * 120_001)
    assert "120.000" in too_long.json()["detail"]["message"]
    assert "yyyy" not in too_long.text
    assert review_env.llm.calls == []

    at_limit = await review_env.script_review(reviewer, "x" * 120_000, "e" * 200)
    assert at_limit.status_code == 200
    events = sse_events(at_limit.text)
    assert events[-1]["phase"] == "complete"
    assert "Metnin yalnız" not in (events[-1]["results"][0]["parse_warning"] or "")


async def test_long_text_is_reviewed_in_two_parts(review_env: ReviewEnv) -> None:
    reviewer, _, codes = await _ready(review_env)
    review_env.auth.use_settings(review_two_part_threshold_chars=10)
    events = sse_events((await review_env.script_review(reviewer, SCRIPT)).text)
    assert all(e["sql_two_part"] for e in events if e["phase"] == "rule_start")
    assert sorted((rule_code_of(c.request), c.target.part_index) for c in review_env.llm.calls) == (
        sorted((code, part) for code in codes for part in (1, 2))
    )


async def test_a_stopped_script_review_keeps_no_text(review_env: ReviewEnv) -> None:
    reviewer, _, _ = await _ready(review_env)
    review_env.llm.gate = asyncio.Event()
    events, _ = await stream_until(
        review_env,
        reviewer,
        "/script-reviews",
        {"sql": SCRIPT, "label": "durdurulacak"},
        lambda event: event["phase"] == "rule_start",
    )
    run_id = events[0]["run_id"]
    for _ in range(200):
        run = await run_of(run_id)
        if run.status != "running":
            break
        await asyncio.sleep(0.025)
    await review_env.settle()
    assert run.status == "cancelled"
    assert (await _stored_object(run)).source_sql is None
    assert await result_counts(run) == (0, 0)
