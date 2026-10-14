"""Rule and group proposals and the proposal permission against real PostgreSQL.

sql-review/PRDs/009-rule-proposals Requirement 1-5 (Acceptance 2, 3). The platform tenant's draft
is shared by the tests, so each test reads the current revision before changing it and leaves the
draft without groups afterwards, as the other rule-set tests expect.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from tests.integration.conftest import AuthHarness, RoleSessions
from tests.integration.rule_proposal_helpers import Proposals, rule_item

pytestmark = pytest.mark.integration


@pytest.fixture
async def proposals(auth: AuthHarness, role_sessions: RoleSessions) -> AsyncIterator[Proposals]:
    helper = Proposals(auth, role_sessions)
    try:
        yield helper
    finally:
        await helper.ungroup()


# --- Permission (Requirement 1) ---------------------------------------------------------------


async def test_the_super_admin_grants_lists_and_revokes_the_permission(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    admin = await role_sessions.super_admin()
    reviewer = await role_sessions.reviewer()

    before = await proposals.call("GET", "/rule-proposals/capabilities", reviewer)
    assert before.json() == {"can_propose": False, "can_decide": False}
    refused = await proposals.propose_rule(reviewer)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "proposal_forbidden"

    granted = await proposals.call("PUT", f"/rule-proposers/{reviewer.public_id}", admin)
    again = await proposals.call("PUT", f"/rule-proposers/{reviewer.public_id}", admin)
    assert (granted.status_code, again.status_code) == (204, 204)
    listed = await proposals.call("GET", "/rule-proposers", admin)
    assert reviewer.public_id in [item["user_id"] for item in listed.json()["items"]]
    after = await proposals.call("GET", "/rule-proposals/capabilities", reviewer)
    assert after.json() == {"can_propose": True, "can_decide": False}
    decider = await proposals.call("GET", "/rule-proposals/capabilities", admin)
    assert decider.json() == {"can_propose": True, "can_decide": True}

    revoked = await proposals.call("DELETE", f"/rule-proposers/{reviewer.public_id}", admin)
    assert revoked.status_code == 204
    assert (await proposals.propose_rule(reviewer)).status_code == 403
    listed = await proposals.call("GET", "/rule-proposers", admin)
    assert reviewer.public_id not in [item["user_id"] for item in listed.json()["items"]]

    unknown = await proposals.call("PUT", f"/rule-proposers/{uuid4()}", admin)
    assert unknown.status_code == 404
    for method in ("GET", "PUT"):
        path = "/rule-proposers" if method == "GET" else f"/rule-proposers/{reviewer.public_id}"
        forbidden = await proposals.call(method, path, reviewer)
        assert forbidden.status_code == 403


# --- Proposals (Requirement 2-4) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"summary": ""}, "rule_summary_invalid"),
        ({"summary": "iki\nsatır"}, "rule_summary_invalid"),
        ({"text": "  "}, "rule_text_invalid"),
        ({"text": "x" * 8001}, "rule_text_too_long"),
        ({"rule_group_ids": ["yok"]}, "rule_group_unknown"),
    ],
)
async def test_invalid_rule_proposals_are_rejected(
    proposals: Proposals, changes: dict[str, Any], code: str
) -> None:
    proposer = await proposals.proposer()

    response = await proposals.propose_rule(proposer, **changes)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code


async def test_invalid_group_proposals_are_rejected(proposals: Proposals) -> None:
    group = {"id": str(uuid4()), "name": f"Güvenlik {uuid4().hex[:6]}", "description": ""}
    version = await proposals.publish_fresh([group])
    codes = [rule["id"] for rule in version["critical"]]
    proposer = await proposals.proposer()

    cases = [
        (await proposals.propose_group(proposer, "Yeni", ["Kural9999"]), "rule_unknown"),
        (await proposals.propose_group(proposer, "Yeni", []), "proposal_rules_empty"),
        (await proposals.propose_group(proposer, " ", codes), "rule_group_name_invalid"),
        (
            await proposals.propose_group(
                proposer, group["name"].replace("Güvenlik", "GÜVENLİK"), codes
            ),
            "rule_group_name_duplicate",
        ),
    ]
    for response, code in cases:
        assert response.status_code == 422, (code, response.text)
        assert response.json()["detail"]["code"] == code


async def test_a_proposer_sees_withdraws_and_cannot_see_others_proposals(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    proposer = await proposals.proposer()
    other = await proposals.proposer()
    admin = await role_sessions.super_admin()
    created = await proposals.propose_rule(proposer)
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["status"] == "bekliyor"
    assert proposal["summary"] == "Geçici tablolar silinmelidir."
    assert proposal["owned"] is True

    mine = await proposals.call("GET", "/rule-proposals", proposer, scope="mine")
    assert proposal["id"] in [item["id"] for item in mine.json()["items"]]
    assert (
        await proposals.call("GET", f"/rule-proposals/{proposal['id']}", other)
    ).status_code == 404
    assert (
        await proposals.call("GET", f"/rule-proposals/{proposal['id']}", admin)
    ).status_code == 200
    pending = await proposals.call("GET", "/rule-proposals", proposer, scope="pending")
    assert pending.status_code == 403
    queue = await proposals.call("GET", "/rule-proposals", admin, scope="pending", page_size=100)
    assert proposal["id"] in [item["id"] for item in queue.json()["items"]]

    foreign = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/withdraw", other)
    withdrawn = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/withdraw", proposer)
    twice = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/withdraw", proposer)
    assert foreign.status_code == 404
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "geri_cekildi"
    assert twice.status_code == 409
    assert twice.json()["detail"]["code"] == "proposal_not_pending"


# --- Approval and rejection (Requirement 5, Decision 2) ---------------------------------------


async def test_an_approved_rule_is_published_at_once_and_written_to_the_draft(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    group = {"id": str(uuid4()), "name": f"Performans {uuid4().hex[:6]}", "description": ""}
    version = await proposals.publish_fresh([group])
    manager = await role_sessions.rule_manager()
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    created = await proposals.propose_rule(
        proposer, priority="critical", rule_group_ids=[group["id"]], requires_metadata=True
    )
    proposal = created.json()
    # An unpublished draft change must not ride along with the approval.
    workspace = await proposals.workspace()
    unpublished = rule_item(workspace["next_rule_id"], f"Yayımlanmamış {uuid4().hex}")
    saved = await proposals.call(
        "PUT",
        "/rule-set/draft",
        manager,
        {
            "base_revision": workspace["revision"],
            "critical": workspace["critical"],
            "normal": [*workspace["normal"], unpublished],
            "groups": workspace["groups"],
        },
    )
    assert saved.status_code == 200, saved.text

    by_manager = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/approve", manager)
    approved = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/approve", admin)

    assert by_manager.status_code == 403
    assert approved.status_code == 200, approved.text
    decision = approved.json()
    assert decision["status"] == "onaylandi"
    assert decision["published_version_number"] == version["number"] + 1
    new_code = decision["new_rule_id"]
    # The new code is the draft's next free one, after the unpublished rule's.
    assert int(new_code.removeprefix("Kural")) > int(unpublished["id"].removeprefix("Kural"))
    latest = (await proposals.call("GET", "/rule-set/versions/latest", proposer)).json()
    assert latest["number"] == decision["published_version_number"]
    added = latest["critical"][-1]
    assert added["id"] == new_code
    assert added["summary"] == "Geçici tablolar silinmelidir."
    assert added["requires_metadata"] is True
    assert added["rule_group_ids"] == [group["id"]]
    assert unpublished["id"] not in [rule["id"] for rule in latest["normal"]]
    draft = await proposals.workspace()
    assert draft["critical"][-1]["id"] == new_code
    assert unpublished["id"] in [rule["id"] for rule in draft["normal"]]
    assert draft["revision"] == saved.json()["revision"] + 1
    again = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/approve", admin)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "proposal_not_pending"


async def test_an_approved_group_is_published_with_its_rules(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    version = await proposals.publish_fresh()
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    codes = [version["critical"][1]["id"], version["normal"][0]["id"]]
    name = f"Veri kalitesi {uuid4().hex[:6]}"
    proposal = (await proposals.propose_group(proposer, name, codes)).json()

    approved = await proposals.call("POST", f"/rule-proposals/{proposal['id']}/approve", admin)

    assert approved.status_code == 200, approved.text
    latest = (await proposals.call("GET", "/rule-set/versions/latest", proposer)).json()
    group = next(item for item in latest["groups"] if item["name"] == name)
    members = [
        rule["id"]
        for rule in (*latest["critical"], *latest["normal"])
        if group["id"] in rule["rule_group_ids"]
    ]
    assert members == codes
    draft = await proposals.workspace()
    assert group["id"] in [item["id"] for item in draft["groups"]]


async def test_a_rejection_needs_a_reason_the_proposer_sees(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    proposal = (await proposals.propose_rule(proposer)).json()

    blank = await proposals.call(
        "POST", f"/rule-proposals/{proposal['id']}/reject", admin, {"reason": "  "}
    )
    by_proposer = await proposals.call(
        "POST", f"/rule-proposals/{proposal['id']}/reject", proposer, {"reason": "x"}
    )
    rejected = await proposals.call(
        "POST",
        f"/rule-proposals/{proposal['id']}/reject",
        admin,
        {"reason": " Mevcut Kural03 ile aynı. "},
    )

    assert blank.status_code == 422
    assert blank.json()["detail"]["code"] == "rejection_reason_invalid"
    assert by_proposer.status_code == 403
    assert rejected.status_code == 200, rejected.text
    seen = (await proposals.call("GET", f"/rule-proposals/{proposal['id']}", proposer)).json()
    assert seen["status"] == "reddedildi"
    assert seen["rejection_reason"] == "Mevcut Kural03 ile aynı."
    assert seen["published_version_number"] is None


async def test_an_approval_that_no_longer_fits_is_a_conflict_and_stays_pending(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    version = await proposals.publish_fresh()
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    name = f"Çakışan {uuid4().hex[:6]}"
    codes = [version["critical"][0]["id"]]
    first = (await proposals.propose_group(proposer, name, codes)).json()
    second = (await proposals.propose_group(proposer, name, codes)).json()
    assert (
        await proposals.call("POST", f"/rule-proposals/{first['id']}/approve", admin)
    ).status_code == 200

    conflict = await proposals.call("POST", f"/rule-proposals/{second['id']}/approve", admin)

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "proposal_conflict"
    still = (await proposals.call("GET", f"/rule-proposals/{second['id']}", admin)).json()
    assert still["status"] == "bekliyor"


async def test_concurrent_approvals_publish_distinct_versions(
    proposals: Proposals, role_sessions: RoleSessions
) -> None:
    version = await proposals.publish_fresh()
    admin = await role_sessions.super_admin()
    proposer = await proposals.proposer()
    ids = [(await proposals.propose_rule(proposer)).json()["id"] for _ in range(2)]

    responses = await asyncio.gather(
        *(proposals.call("POST", f"/rule-proposals/{item}/approve", admin) for item in ids)
    )

    assert [response.status_code for response in responses] == [200, 200]
    numbers = sorted(response.json()["published_version_number"] for response in responses)
    assert numbers == [version["number"] + 1, version["number"] + 2]
    codes = {response.json()["new_rule_id"] for response in responses}
    latest = (await proposals.call("GET", "/rule-set/versions/latest", proposer)).json()
    assert codes <= {rule["id"] for rule in latest["normal"]}
