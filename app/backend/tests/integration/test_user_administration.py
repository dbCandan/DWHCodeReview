"""Super-admin user list, role assignment and activation against real PostgreSQL.

application-foundation/PRDs/001-directory-login Requirement 5, 11 and 12 (Acceptance 1).
"""

import secrets
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.domain.models.role import Role, UserRole
from app.domain.models.user import User
from app.scripts.create_local_user import LocalUserRefused, ensure_local_user
from tests.integration.conftest import AuthHarness, RecordingHandler, SuperAdmin

pytestmark = pytest.mark.integration


async def _admin_session(auth: AuthHarness, admin: SuperAdmin) -> dict[str, str]:
    response = await auth.login(admin.username, admin.password)
    assert response.status_code == 200, response.text
    return auth.auth_headers(response.json())


async def _directory_user(auth: AuthHarness) -> tuple[dict[str, Any], str, str, str]:
    name = f"kisi{uuid4().hex[:8]}"
    _, password, _ = auth.directory.add(name)
    response = await auth.login(name, password)
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    return response.json(), name, password, cookie


async def test_list_is_paged_sorted_and_filtered(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    headers = await _admin_session(auth, super_admin)
    marker = uuid4().hex[:8]
    for letter in ("c", "a", "b"):
        _, password, _ = auth.directory.add(f"{letter}{marker}")
        assert (await auth.login(f"{letter}{marker}", password)).status_code == 200

    page = await auth.client.get(
        f"{auth.prefix}/admin/users", params={"q": marker, "size": 2}, headers=headers
    )

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 3
    assert body["page"] == 1 and body["size"] == 2
    assert [item["username"].split("@")[0] for item in body["items"]] == [
        f"a{marker}",
        f"b{marker}",
    ]
    assert {item["role"] for item in body["items"]} == {"inceleyici"}
    second = await auth.client.get(
        f"{auth.prefix}/admin/users", params={"q": marker, "size": 2, "page": 2}, headers=headers
    )
    assert [item["username"].split("@")[0] for item in second.json()["items"]] == [f"c{marker}"]
    wildcard = await auth.client.get(
        f"{auth.prefix}/admin/users", params={"q": "%"}, headers=headers
    )
    assert wildcard.json()["total"] == 0


@pytest.mark.parametrize("params", ({"size": 201}, {"size": 0}, {"page": 0}))
async def test_invalid_paging_is_a_bad_request(
    auth: AuthHarness, super_admin: SuperAdmin, params: dict[str, int]
) -> None:
    headers = await _admin_session(auth, super_admin)
    response = await auth.client.get(f"{auth.prefix}/admin/users", params=params, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"


async def test_admin_endpoints_need_a_session_and_the_super_admin(auth: AuthHarness) -> None:
    body, *_ = await _directory_user(auth)
    reviewer = auth.auth_headers(body)
    tenant_only = {auth.settings.tenant_header: body["user"]["tenant_id"]}
    target = body["user"]["public_id"]
    requests = (
        ("GET", "/admin/users", None),
        ("PUT", f"/admin/users/{target}/active", {"active": False}),
    )
    for method, path, payload in requests:
        anonymous = await auth.client.request(
            method, f"{auth.prefix}{path}", json=payload, headers=tenant_only
        )
        assert anonymous.status_code == 401
        forbidden = await auth.client.request(
            method, f"{auth.prefix}{path}", json=payload, headers=reviewer
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "forbidden"


async def test_deactivation_blocks_login_and_reactivation_restores_it(
    auth: AuthHarness, super_admin: SuperAdmin, recorded_logs: RecordingHandler
) -> None:
    headers = await _admin_session(auth, super_admin)
    body, name, password, _ = await _directory_user(auth)
    url = f"{auth.prefix}/admin/users/{body['user']['public_id']}/active"

    off = await auth.client.put(url, json={"active": False}, headers=headers)
    again = await auth.client.put(url, json={"active": False}, headers=headers)
    blocked = await auth.login(name, password)
    on = await auth.client.put(url, json={"active": True}, headers=headers)
    allowed = await auth.login(name, password)

    assert off.json() == again.json() == {"active": False}
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "user_inactive"
    assert on.json() == {"active": True}
    assert allowed.status_code == 200
    async with async_session_factory() as session:
        changes = (
            await session.execute(
                text(
                    "SELECT changed_field, old_value, new_value FROM app_user_change c "
                    "JOIN app_user u ON u.user_id = c.target_user_id WHERE u.public_id = :p "
                    "ORDER BY c.app_user_change_id"
                ),
                {"p": body["user"]["public_id"]},
            )
        ).all()
    assert [tuple(row) for row in changes] == [
        ("active", "true", "false"),
        ("active", "false", "true"),
    ]
    assert len(recorded_logs.events("admin.user.active_changed")) >= 2


@pytest.mark.parametrize("value", ("yes", 1, None))
async def test_activation_accepts_only_booleans(
    auth: AuthHarness, super_admin: SuperAdmin, value: Any
) -> None:
    headers = await _admin_session(auth, super_admin)
    body, *_ = await _directory_user(auth)
    response = await auth.client.put(
        f"{auth.prefix}/admin/users/{body['user']['public_id']}/active",
        json={"active": value},
        headers=headers,
    )
    assert response.status_code == 400


async def test_super_admin_cannot_deactivate_its_own_account(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    headers = await _admin_session(auth, super_admin)
    response = await auth.client.put(
        f"{auth.prefix}/admin/users/{super_admin.public_id}/active",
        json={"active": False},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "own_account"


async def test_an_admin_change_rereads_the_callers_authority(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    headers = await _admin_session(auth, super_admin)
    body, *_ = await _directory_user(auth)
    async with async_session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.public_id == str(super_admin.public_id)))
        ).scalar_one()
        await session.execute(
            update(UserRole).where(UserRole.user_id == admin.user_id).values(is_deleted=True)
        )
        await session.commit()

    # The access token still says super_admin, but the database no longer does.
    response = await auth.client.put(
        f"{auth.prefix}/admin/users/{body['user']['public_id']}/active",
        json={"active": False},
        headers=headers,
    )
    assert response.status_code == 403


async def test_local_test_accounts_are_refused_while_the_directory_is_enabled(
    migrated_database: None,
) -> None:
    settings = get_settings().model_copy(
        update={
            "environment": "development",
            "directory_enabled": True,
            "directory_upn_suffix": "corp.example.test",
        }
    )
    async with async_session_factory() as session:
        with pytest.raises(LocalUserRefused, match="dizin"):
            await ensure_local_user(
                session,
                settings,
                username=f"deneme-{uuid4().hex[:6]}",
                password=secrets.token_urlsafe(24),
                role_code="inceleyici",
            )


async def test_local_test_accounts_are_refused_outside_the_local_environment(
    migrated_database: None,
) -> None:
    settings = get_settings().model_copy(update={"environment": "staging"})
    async with async_session_factory() as session:
        with pytest.raises(LocalUserRefused, match="yerel ortam"):
            await ensure_local_user(
                session,
                settings,
                username=f"deneme-{uuid4().hex[:6]}",
                password=secrets.token_urlsafe(24),
                role_code="inceleyici",
            )


async def test_local_test_account_creation_is_idempotent(
    migrated_database: None,
) -> None:
    settings = get_settings().model_copy(update={"environment": "development"})
    name = f"deneme-{uuid4().hex[:6]}"
    async with async_session_factory() as session:
        first = await ensure_local_user(
            session,
            settings,
            username=name,
            password=secrets.token_urlsafe(24),
            role_code="inceleyici",
        )
    async with async_session_factory() as session:
        second = await ensure_local_user(
            session,
            settings,
            username=name,
            password=secrets.token_urlsafe(24),
            role_code="inceleyici",
        )
        roles = (
            await session.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.role_id)
                .join(User, User.user_id == UserRole.user_id)
                .where(User.username == name, UserRole.is_deleted.is_(False))
            )
        ).all()
    assert first.created is True and second.created is False
    assert first.user_public_id == second.user_public_id
    assert roles == ["inceleyici"]
