"""Review runs restricted to selected rule groups and single rules, through HTTP and PostgreSQL.

sql-review/PRDs/007-rule-group-selection Requirement 4-7 and Decision 1, 6 (Acceptance 1 and 3):
only the selected groups' rules and the selected single rules reach the LLM, each once; an empty
selection runs every rule; the selection and each result's group names are stored with the run;
invalid selections stop before the stream.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.domain.models.review import (
    ReviewRuleResult,
    ReviewRunObject,
    ReviewRunRule,
    ReviewRunRuleGroup,
)
from tests.fakes.review_ports import rule_code_of
from tests.integration.conftest import ReviewEnv, RoleSession, sse_events
from tests.integration.review_helpers import run_of

pytestmark = pytest.mark.integration

PERFORMANCE = {"id": str(uuid4()), "name": "Performans", "description": ""}
SECURITY = {"id": str(uuid4()), "name": "Güvenlik", "description": ""}
EMPTY = {"id": str(uuid4()), "name": "Boş grup", "description": ""}
SCRIPT = "SELECT *\nFROM dbo.Musteri"


@pytest.fixture
async def grouped(
    review_env: ReviewEnv,
) -> AsyncIterator[tuple[RoleSession, list[str]]]:
    """Publish: critical [perf, sec+perf, ungrouped], normal [perf]; ungroup the draft after."""

    manager = await review_env.sessions.rule_manager()
    _, codes = await review_env.publish(
        manager,
        [
            ("Yıldız kullanma.", False),
            ("NOLOCK kullanma.", False),
            ("Yorum yaz.", False),
        ],
        [("Ad kuralı.", False)],
        groups=[PERFORMANCE, SECURITY, EMPTY],
        membership={
            0: PERFORMANCE["id"],
            1: [SECURITY["id"], PERFORMANCE["id"]],
            3: PERFORMANCE["id"],
        },
    )
    try:
        yield await review_env.sessions.reviewer(), codes
    finally:
        client = review_env.auth.client
        workspace = (
            await client.get(f"{review_env.prefix}/rule-set", headers=manager.headers)
        ).json()
        ungrouped = {
            priority: [{**rule, "rule_group_ids": []} for rule in workspace[priority]]
            for priority in ("critical", "normal")
        }
        saved = await client.put(
            f"{review_env.prefix}/rule-set/draft",
            json={"base_revision": workspace["revision"], "groups": [], **ungrouped},
            headers=manager.headers,
        )
        assert saved.status_code == 200, saved.text


def _event(events: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    return next(event for event in events if event["phase"] == phase)


async def _stored(
    run_public_id: str,
) -> tuple[list[tuple[str, str]], list[str], dict[str, list[str]]]:
    run = await run_of(run_public_id)
    async with async_session_factory() as session:
        groups = (
            await session.execute(
                select(ReviewRunRuleGroup.rule_group_public_id, ReviewRunRuleGroup.name)
                .where(ReviewRunRuleGroup.review_run_id == run.review_run_id)
                .order_by(ReviewRunRuleGroup.position)
            )
        ).all()
        rules = await session.scalars(
            select(ReviewRunRule.rule_code)
            .where(ReviewRunRule.review_run_id == run.review_run_id)
            .order_by(ReviewRunRule.position)
        )
        results = (
            await session.execute(
                select(ReviewRuleResult.rule_code, ReviewRuleResult.rule_group_names)
                .join(ReviewRunObject)
                .where(ReviewRunObject.review_run_id == run.review_run_id)
            )
        ).all()
    return (
        [(str(g), str(n)) for g, n in groups],
        list(rules),
        {str(c): list(n) for c, n in results},
    )


async def test_a_group_selection_sends_only_its_rules_and_stores_every_group_name(
    review_env: ReviewEnv, grouped: tuple[RoleSession, list[str]]
) -> None:
    reviewer, codes = grouped

    response = await review_env.script_review(reviewer, SCRIPT, rule_group_ids=[PERFORMANCE["id"]])

    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    started = _event(events, "run_started")
    assert started["selected_rule_groups"] == [{"id": PERFORMANCE["id"], "name": "Performans"}]
    assert started["selected_rule_codes"] == []
    assert started["all_rules"] is False
    assert sorted(rule_code_of(call.request) for call in review_env.llm.calls) == sorted(
        [codes[0], codes[1], codes[3]]
    )
    complete = _event(events, "complete")
    results = complete["results"][0]["rule_results"]
    assert [result["rule_id"] for result in results] == [codes[0], codes[1], codes[3]]
    assert results[1]["rule_group_names"] == ["Performans", "Güvenlik"]

    groups, rules, stored = await _stored(started["run_id"])
    assert groups == [(PERFORMANCE["id"], "Performans")]
    assert rules == []
    assert stored == {
        codes[0]: ["Performans"],
        codes[1]: ["Performans", "Güvenlik"],
        codes[3]: ["Performans"],
    }


async def test_without_a_selection_every_rule_runs(
    review_env: ReviewEnv, grouped: tuple[RoleSession, list[str]]
) -> None:
    reviewer, codes = grouped

    response = await review_env.script_review(reviewer, SCRIPT)

    events = sse_events(response.text)
    started = _event(events, "run_started")
    assert started["selected_rule_groups"] == []
    assert started["selected_rule_codes"] == []
    assert started["all_rules"] is True
    assert {rule_code_of(call.request) for call in review_env.llm.calls} == set(codes)
    groups, rules, stored = await _stored(started["run_id"])
    assert (groups, rules) == ([], [])
    assert stored[codes[2]] == []


async def test_groups_and_single_rules_run_their_union_once_in_critical_first_order(
    review_env: ReviewEnv, grouped: tuple[RoleSession, list[str]]
) -> None:
    """Decision 6: single rules join the groups; a rule in two selected groups runs once."""

    reviewer, codes = grouped
    review_env.catalog.definitions[("DWH", "dbo", "usp_Load")] = (
        "CREATE PROCEDURE dbo.usp_Load AS SELECT 1"
    )

    response = await review_env.object_review(
        reviewer,
        [{"database": "DWH", "schema": "dbo", "name": "usp_Load", "type_code": "P"}],
        rule_group_ids=[SECURITY["id"], PERFORMANCE["id"]],
        rule_codes=[codes[2], codes[1]],
    )

    events = sse_events(response.text)
    started = _event(events, "run_started")
    assert [group["name"] for group in started["selected_rule_groups"]] == [
        "Performans",
        "Güvenlik",
    ]
    assert started["selected_rule_codes"] == [codes[1], codes[2]]
    results = _event(events, "complete")["results"][0]["rule_results"]
    assert [result["rule_id"] for result in results] == codes
    assert len(review_env.llm.calls) == len(codes)


async def test_a_rule_only_selection_runs_just_those_rules(
    review_env: ReviewEnv, grouped: tuple[RoleSession, list[str]]
) -> None:
    reviewer, codes = grouped

    response = await review_env.script_review(reviewer, SCRIPT, rule_codes=[codes[3], codes[2]])

    events = sse_events(response.text)
    started = _event(events, "run_started")
    assert started["selected_rule_groups"] == []
    assert started["selected_rule_codes"] == [codes[2], codes[3]]
    assert started["all_rules"] is False
    assert {rule_code_of(call.request) for call in review_env.llm.calls} == {codes[2], codes[3]}
    _, rules, _ = await _stored(started["run_id"])
    assert rules == [codes[2], codes[3]]


@pytest.mark.parametrize(
    ("groups", "rules", "code"),
    [
        (["yok"], [], "rule_group_unknown"),
        ([], ["Kural999"], "rule_unknown"),
        (["EMPTY"], [], "rule_group_selection_empty"),
    ],
)
async def test_invalid_selections_stop_before_the_stream(
    review_env: ReviewEnv,
    grouped: tuple[RoleSession, list[str]],
    groups: list[str],
    rules: list[str],
    code: str,
) -> None:
    reviewer, _ = grouped
    selection = [EMPTY["id"] if group == "EMPTY" else group for group in groups]

    response = await review_env.script_review(
        reviewer, SCRIPT, rule_group_ids=selection, rule_codes=rules
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    assert review_env.llm.calls == []


async def test_history_detail_and_csv_show_the_selection_and_group_names(
    review_env: ReviewEnv, grouped: tuple[RoleSession, list[str]]
) -> None:
    """rule-group-selection Requirement 7; review-history-export Requirement 7, Decision 9."""

    reviewer, codes = grouped
    started = _event(
        sse_events(
            (
                await review_env.script_review(
                    reviewer, SCRIPT, rule_group_ids=[SECURITY["id"]], rule_codes=[codes[3]]
                )
            ).text
        ),
        "run_started",
    )
    every_run = _event(
        sse_events((await review_env.script_review(reviewer, SCRIPT)).text), "run_started"
    )["run_id"]
    client, prefix = review_env.auth.client, review_env.prefix

    detail = await client.get(f"{prefix}/review-runs/{started['run_id']}", headers=reviewer.headers)
    every = await client.get(f"{prefix}/review-runs/{every_run}", headers=reviewer.headers)
    csv = await client.get(
        f"{prefix}/review-runs/{started['run_id']}/exports/csv", headers=reviewer.headers
    )

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["selected_rule_groups"] == [{"id": SECURITY["id"], "name": "Güvenlik"}]
    assert body["selected_rule_codes"] == [codes[3]]
    assert body["all_rules"] is False
    assert [r["rule_group_names"] for r in body["results"][0]["rule_results"]] == [
        ["Performans", "Güvenlik"],
        ["Performans"],
    ]
    assert every.json()["all_rules"] is True
    assert every.json()["selected_rule_codes"] == []
    rows = csv.text.split("\r\n")
    assert rows[0].endswith(",false_positive,rule_group")
    assert rows[1].endswith(",Performans; Güvenlik")
    assert rows[2].endswith(",Performans")
