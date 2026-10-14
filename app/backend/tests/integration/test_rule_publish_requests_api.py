"""Publish requests of the rule manager against real PostgreSQL.

sql-review/PRDs/009-rule-proposals Requirement 6 and Decision 3 (Acceptance 2, 3): the rule
manager sends the draft for approval; the super admin sees the difference and publishes or
rejects it; a draft changed after the request makes it stale.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from tests.integration.conftest import AuthHarness, RoleSession, RoleSessions
from tests.integration.rule_proposal_helpers import Proposals

pytestmark = pytest.mark.integration


@pytest.fixture
async def proposals(auth: AuthHarness, role_sessions: RoleSessions) -> AsyncIterator[Proposals]:
    helper = Proposals(auth, role_sessions)
    try:
        yield helper
    finally:
        await helper.ungroup()


async def _add_rule(proposals: Proposals, manager: RoleSession, text_value: str) -> dict[str, Any]:
    workspace = await proposals.workspace()
    rule = {
        "id": workspace["next_rule_id"],
        "text": text_value,
        "summary": "Yeni kural.",
        "requires_metadata": False,
    }
    saved = await proposals.call(
        "PUT",
        "/rule-set/draft",
        manager,
        {
            "base_revision": workspace["revision"],
            "critical": workspace["critical"],
            "normal": [*workspace["normal"], rule],
            "groups": workspace["groups"],
        },
    )
    assert saved.status_code == 200, saved.text
    body: dict[str, Any] = saved.json()
    return body


async def test_a_publish_request_shows_its_difference_and_is_published_on_approval(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    version = await proposals.publish_fresh()
    manager = await role_sessions.rule_manager()
    admin = await role_sessions.super_admin()
    reviewer = await role_sessions.reviewer()
    marker = uuid4().hex
    saved = await _add_rule(proposals, manager, f"Onaylı yayın {marker}")

    stale_base = await proposals.call(
        "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"] - 1}
    )
    by_reviewer = await proposals.call(
        "POST", "/rule-set/publish-requests", reviewer, {"base_revision": saved["revision"]}
    )
    created = await proposals.call(
        "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
    )

    assert stale_base.status_code == 409
    assert stale_base.json()["detail"]["code"] == "rule_set_draft_conflict"
    assert by_reviewer.status_code == 403
    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "bekliyor"
    assert request["draft_changed"] is False
    assert [rule["text"] for rule in request["diff"]["added_rules"]] == [f"Onaylı yayın {marker}"]
    assert request["diff"]["added_rules"][0]["priority"] == "normal"
    assert request["diff"]["removed_rules"] == []

    by_manager = await proposals.call(
        "POST", f"/rule-set/publish-requests/{request['id']}/approve", manager
    )
    approved = await proposals.call(
        "POST", f"/rule-set/publish-requests/{request['id']}/approve", admin
    )

    assert by_manager.status_code == 403
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "onaylandi"
    assert approved.json()["published_version_number"] == version["number"] + 1
    assert approved.json()["diff"] is None
    latest = (await proposals.call("GET", "/rule-set/versions/latest", reviewer)).json()
    assert latest["normal"][-1]["text"] == f"Onaylı yayın {marker}"
    assert latest["normal"][-1]["summary"] == "Yeni kural."
    twice = await proposals.call(
        "POST", f"/rule-set/publish-requests/{request['id']}/approve", admin
    )
    assert twice.status_code == 409
    assert twice.json()["detail"]["code"] == "publish_request_not_pending"


async def test_a_newer_request_replaces_the_pending_one(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    await proposals.publish_fresh()
    manager = await role_sessions.rule_manager()
    saved = await _add_rule(proposals, manager, f"İlk istek {uuid4().hex}")
    first = (
        await proposals.call(
            "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
        )
    ).json()

    second = await proposals.call(
        "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
    )

    assert second.status_code == 201, second.text
    replaced = await proposals.call("GET", f"/rule-set/publish-requests/{first['id']}", manager)
    assert replaced.json()["status"] == "gecersiz"
    pending = await proposals.call("GET", "/rule-set/publish-requests", manager, status="bekliyor")
    assert [item["id"] for item in pending.json()["items"]] == [second.json()["id"]]


async def test_a_draft_changed_after_the_request_makes_it_stale(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    await proposals.publish_fresh()
    manager = await role_sessions.rule_manager()
    admin = await role_sessions.super_admin()
    saved = await _add_rule(proposals, manager, f"Bayat {uuid4().hex}")
    request = (
        await proposals.call(
            "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
        )
    ).json()
    await _add_rule(proposals, manager, f"Sonradan {uuid4().hex}")
    listed = await proposals.call("GET", "/rule-set/publish-requests", admin, status="bekliyor")
    assert [item["draft_changed"] for item in listed.json()["items"]] == [True]

    approved = await proposals.call(
        "POST", f"/rule-set/publish-requests/{request['id']}/approve", admin
    )

    assert approved.status_code == 409
    assert approved.json()["detail"]["code"] == "publish_request_stale"
    after = await proposals.call("GET", f"/rule-set/publish-requests/{request['id']}", manager)
    assert after.json()["status"] == "gecersiz"


async def test_an_approved_proposal_makes_a_pending_request_stale(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    """PRD Riskler: the approval writes to the draft, so the request must be sent again."""

    await proposals.publish_fresh()
    manager = await role_sessions.rule_manager()
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    saved = await _add_rule(proposals, manager, f"Bekleyen {uuid4().hex}")
    request = (
        await proposals.call(
            "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
        )
    ).json()
    proposal = (await proposals.propose_rule(proposer)).json()
    assert (
        await proposals.call("POST", f"/rule-proposals/{proposal['id']}/approve", admin)
    ).status_code == 200

    approved = await proposals.call(
        "POST", f"/rule-set/publish-requests/{request['id']}/approve", admin
    )

    assert approved.status_code == 409
    assert approved.json()["detail"]["code"] == "publish_request_stale"


async def test_a_rejected_request_shows_its_reason_to_the_rule_manager_only(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    await proposals.publish_fresh()
    manager = await role_sessions.rule_manager()
    other_manager = await role_sessions.rule_manager()
    admin = await role_sessions.super_admin()
    saved = await _add_rule(proposals, manager, f"Reddedilecek {uuid4().hex}")
    request = (
        await proposals.call(
            "POST", "/rule-set/publish-requests", manager, {"base_revision": saved["revision"]}
        )
    ).json()

    rejected = await proposals.call(
        "POST",
        f"/rule-set/publish-requests/{request['id']}/reject",
        admin,
        {"reason": "Kural metni belirsiz."},
    )

    assert rejected.status_code == 200, rejected.text
    mine = await proposals.call("GET", "/rule-set/publish-requests", manager)
    item = next(entry for entry in mine.json()["items"] if entry["id"] == request["id"])
    assert (item["status"], item["rejection_reason"]) == ("reddedildi", "Kural metni belirsiz.")
    others = await proposals.call("GET", "/rule-set/publish-requests", other_manager)
    assert request["id"] not in [entry["id"] for entry in others.json()["items"]]
    hidden = await proposals.call(
        "GET", f"/rule-set/publish-requests/{request['id']}", other_manager
    )
    assert hidden.status_code == 404
