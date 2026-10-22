"""Scheduled review definitions and the setting through HTTP and PostgreSQL.

sql-review/PRDs/008-scheduled-review-email Requirement 1, 2, 8, 9 and Decision 3, 5, 8, 9
(Acceptance 3): the owner manages a definition and the super admin every definition; anyone else
gets 404; periods, recipients and names are validated with their own codes; "Şimdi çalıştır" and
the concurrency setting belong to the super admin; events carry no name or address.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import engine
from tests.integration.conftest import (
    AuthHarness,
    RecordingHandler,
    RoleSessions,
    SuperAdmin,
)

pytestmark = pytest.mark.integration

DOMAIN = "kurum.example"


@pytest.fixture
async def schedules(auth: AuthHarness) -> AsyncIterator[AuthHarness]:
    auth.use_settings(mail_allowed_domains=f"{DOMAIN}, ornek.example")
    try:
        yield auth
    finally:
        async with engine.begin() as connection:
            for table in (
                "scheduled_review_run",
                "scheduled_review",
                "scheduled_review_setting",
            ):
                await connection.execute(text(f"DELETE FROM {table}"))


def _url(auth: AuthHarness, path: str = "") -> str:
    return f"{auth.prefix}/scheduled-reviews{path}"


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Gece taraması {uuid4().hex[:6]}",
        "selection": {"mode": "filter", "filter": {"database": "DWH", "type_code": "P"}},
        "rule_group_ids": [],
        "period": {"frequency": "daily", "hour": 7, "minute": 30, "timezone": "Europe/Istanbul"},
        "recipients": [f"Ayse.Yilmaz@{DOMAIN.upper()}", f"ali@{DOMAIN}"],
    }
    body.update(overrides)
    return body


async def _admin_headers(auth: AuthHarness, admin: SuperAdmin) -> dict[str, str]:
    response = await auth.login(admin.username, admin.password)
    assert response.status_code == 200, response.text
    return auth.auth_headers(response.json())


async def test_the_owner_creates_lists_reads_and_updates_a_definition(
    schedules: AuthHarness, role_sessions: RoleSessions
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    created = await auth.client.post(_url(auth), json=_body(), headers=owner.headers)
    assert created.status_code == 201, created.text
    definition = created.json()
    assert definition["status"] == "active"
    assert definition["recipients"] == [f"ayse.yilmaz@{DOMAIN}", f"ali@{DOMAIN}"]
    assert definition["recipient_count"] == 2
    assert definition["selection_summary"] == "DWH · tür: P"
    assert definition["owned"] and definition["can_edit"] and not definition["can_run_now"]
    assert definition["last_run"] is None
    due = datetime.fromisoformat(definition["next_run_at"])
    # 07:30 in Istanbul (UTC+3, no daylight saving) is 04:30 UTC.
    assert (due.hour, due.minute) == (4, 30)

    listed = (await auth.client.get(_url(auth), headers=owner.headers)).json()
    assert [item["id"] for item in listed["items"]] == [definition["id"]]
    assert "recipients" not in listed["items"][0]

    weekly = _body(
        name=definition["name"],
        period={
            "frequency": "weekly",
            "hour": 9,
            "minute": 0,
            "timezone": "Europe/Istanbul",
            "weekday": 0,
        },
    )
    updated = await auth.client.put(
        _url(auth, f"/{definition['id']}"), json=weekly, headers=owner.headers
    )
    assert updated.status_code == 200, updated.text
    assert datetime.fromisoformat(updated.json()["next_run_at"]).weekday() == 0


@pytest.mark.parametrize(
    ("change", "code"),
    [
        # A free cron expression is outside the closed frequency list of the contract itself.
        ({"period": {"frequency": "*/5 * * * *", "hour": 1, "minute": 0}}, "invalid_request"),
        ({"period": {"frequency": "daily", "hour": 25, "minute": 0}}, "schedule_invalid"),
        ({"period": {"frequency": "weekly", "hour": 1, "minute": 0}}, "schedule_invalid"),
        ({"name": "   "}, "schedule_invalid"),
        ({"selection": {"mode": "list", "items": []}}, "schedule_invalid"),
        ({"recipients": ["ayse@gmail.com"]}, "recipient_domain_not_allowed"),
        ({"recipients": ["ayse"]}, "recipient_invalid"),
        ({"recipients": []}, "recipient_invalid"),
        ({"rule_group_ids": ["olmayan-grup"]}, "rule_group_unknown"),
    ],
)
async def test_invalid_definitions_are_refused_with_their_code(
    schedules: AuthHarness, role_sessions: RoleSessions, change: dict[str, Any], code: str
) -> None:
    owner = await role_sessions.reviewer()
    response = await schedules.client.post(
        _url(schedules), json=_body(**change), headers=owner.headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code


async def test_a_name_is_unique_per_owner_with_turkish_case_folding(
    schedules: AuthHarness, role_sessions: RoleSessions
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    other = await role_sessions.reviewer()
    first = await auth.client.post(
        _url(auth), json=_body(name="Gece taraması"), headers=owner.headers
    )
    assert first.status_code == 201, first.text
    again = await auth.client.post(
        _url(auth), json=_body(name="GECE TARAMASI"), headers=owner.headers
    )
    assert again.status_code == 422
    assert again.json()["detail"]["code"] == "schedule_name_duplicate"
    elsewhere = await auth.client.post(
        _url(auth), json=_body(name="Gece taraması"), headers=other.headers
    )
    assert elsewhere.status_code == 201, elsewhere.text


async def test_only_the_owner_and_the_super_admin_see_and_change_a_definition(
    schedules: AuthHarness, role_sessions: RoleSessions, super_admin: SuperAdmin
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    definition = (await auth.client.post(_url(auth), json=_body(), headers=owner.headers)).json()
    path = f"/{definition['id']}"
    for stranger in (await role_sessions.reviewer(), await role_sessions.reviewer()):
        assert (
            await auth.client.get(_url(auth, path), headers=stranger.headers)
        ).status_code == 404
        put = await auth.client.put(_url(auth, path), json=_body(), headers=stranger.headers)
        assert put.status_code == 404
        pause = await auth.client.post(_url(auth, f"{path}/pause"), headers=stranger.headers)
        assert pause.status_code == 404
        runs = await auth.client.get(_url(auth, f"{path}/runs"), headers=stranger.headers)
        assert runs.status_code == 404
        delete = await auth.client.delete(_url(auth, path), headers=stranger.headers)
        assert delete.status_code == 404
        listed = (await auth.client.get(_url(auth), headers=stranger.headers)).json()
        assert definition["id"] not in [item["id"] for item in listed["items"]]

    admin = await _admin_headers(auth, super_admin)
    listed = (await auth.client.get(_url(auth), headers=admin)).json()
    seen = next(item for item in listed["items"] if item["id"] == definition["id"])
    assert (seen["owned"], seen["can_edit"], seen["can_run_now"]) == (False, True, True)
    assert seen["owner_display_name"] == owner.display_name
    paused = await auth.client.post(_url(auth, f"{path}/pause"), headers=admin)
    assert paused.status_code == 200
    deleted = await auth.client.delete(_url(auth, path), headers=owner.headers)
    assert deleted.status_code == 204
    assert (await auth.client.get(_url(auth, path), headers=owner.headers)).status_code == 404


async def test_pause_hides_the_next_run_and_resume_computes_it_again(
    schedules: AuthHarness, role_sessions: RoleSessions
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    definition = (await auth.client.post(_url(auth), json=_body(), headers=owner.headers)).json()
    path = f"/{definition['id']}"
    paused = (await auth.client.post(_url(auth, f"{path}/pause"), headers=owner.headers)).json()
    assert (paused["status"], paused["next_run_at"]) == ("paused", None)
    resumed = (await auth.client.post(_url(auth, f"{path}/resume"), headers=owner.headers)).json()
    assert resumed["status"] == "active"
    assert resumed["next_run_at"] is not None


async def test_only_the_super_admin_runs_a_definition_now_and_never_twice_at_once(
    schedules: AuthHarness, role_sessions: RoleSessions, super_admin: SuperAdmin
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    definition = (await auth.client.post(_url(auth), json=_body(), headers=owner.headers)).json()
    run_path = _url(auth, f"/{definition['id']}/run")
    refused = await auth.client.post(run_path, headers=owner.headers)
    assert refused.status_code == 403

    admin = await _admin_headers(auth, super_admin)
    queued = await auth.client.post(run_path, headers=admin)
    assert queued.status_code == 202, queued.text
    assert queued.json()["state"] == "queued"
    again = await auth.client.post(run_path, headers=admin)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "scheduled_review_running"
    blocked = await auth.client.delete(_url(auth, f"/{definition['id']}"), headers=owner.headers)
    assert blocked.status_code == 409

    history = (
        await auth.client.get(_url(auth, f"/{definition['id']}/runs"), headers=owner.headers)
    ).json()
    [record] = history["items"]
    assert (record["trigger"], record["state"], record["review_run_id"]) == (
        "manual",
        "queued",
        None,
    )
    assert record["triggered_by_name"]


async def test_the_owner_stops_a_queued_run_and_nothing_else_is_stopped(
    schedules: AuthHarness, role_sessions: RoleSessions, super_admin: SuperAdmin
) -> None:
    # Requirement 11: "Durdur" ends the queued or running run of a definition.
    auth = schedules
    owner = await role_sessions.reviewer()
    definition = (await auth.client.post(_url(auth), json=_body(), headers=owner.headers)).json()
    stop_path = _url(auth, f"/{definition['id']}/stop")
    idle = await auth.client.post(stop_path, headers=owner.headers)
    assert idle.status_code == 409
    assert idle.json()["detail"]["code"] == "scheduled_review_not_running"

    admin = await _admin_headers(auth, super_admin)
    queued = (await auth.client.post(_url(auth, f"/{definition['id']}/run"), headers=admin)).json()
    stranger = await role_sessions.reviewer()
    assert (await auth.client.post(stop_path, headers=stranger.headers)).status_code == 404
    stopped = await auth.client.post(stop_path, headers=owner.headers)
    assert stopped.status_code == 202, stopped.text
    assert stopped.json() == {"id": queued["id"], "state": "cancelled"}

    history = (
        await auth.client.get(_url(auth, f"/{definition['id']}/runs"), headers=owner.headers)
    ).json()
    assert [record["state"] for record in history["items"]] == ["cancelled"]
    # The definition stays active and can run again.
    detail = (
        await auth.client.get(_url(auth, f"/{definition['id']}"), headers=owner.headers)
    ).json()
    assert detail["status"] == "active"
    again = await auth.client.post(_url(auth, f"/{definition['id']}/run"), headers=admin)
    assert again.status_code == 202


async def test_the_concurrency_setting_is_the_super_admins_and_stays_in_range(
    schedules: AuthHarness, role_sessions: RoleSessions, super_admin: SuperAdmin
) -> None:
    auth = schedules
    url = f"{auth.prefix}/scheduled-review-settings"
    reviewer = await role_sessions.reviewer()
    assert (await auth.client.get(url, headers=reviewer.headers)).status_code == 403
    denied = await auth.client.put(url, json={"max_concurrent_runs": 3}, headers=reviewer.headers)
    assert denied.status_code == 403

    admin = await _admin_headers(auth, super_admin)
    assert (await auth.client.get(url, headers=admin)).json() == {"max_concurrent_runs": 2}
    for value in (0, 11):
        response = await auth.client.put(url, json={"max_concurrent_runs": value}, headers=admin)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "setting_out_of_range"
    changed = await auth.client.put(url, json={"max_concurrent_runs": 4}, headers=admin)
    assert changed.status_code == 200
    assert (await auth.client.get(url, headers=admin)).json() == {"max_concurrent_runs": 4}


async def test_events_carry_identifiers_but_no_name_or_address(
    schedules: AuthHarness, role_sessions: RoleSessions, recorded_logs: RecordingHandler
) -> None:
    auth = schedules
    owner = await role_sessions.reviewer()
    body = _body(name="Gizli tanım adı")
    definition = (await auth.client.post(_url(auth), json=body, headers=owner.headers)).json()
    await auth.client.post(_url(auth, f"/{definition['id']}/pause"), headers=owner.headers)

    [created] = recorded_logs.events("scheduled_review.created")
    assert created["schedule_public_id"] == definition["id"]
    assert created["user_public_id"] == owner.public_id
    assert recorded_logs.events("scheduled_review.paused")
    text = " ".join(str(record.__dict__) for record in recorded_logs.records)
    assert "Gizli tanım adı" not in text
    assert DOMAIN not in text
