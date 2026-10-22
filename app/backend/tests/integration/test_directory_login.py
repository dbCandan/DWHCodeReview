"""Directory and local login, refresh rotation and logout against real PostgreSQL.

application-foundation/PRDs/001-directory-login Acceptance 1: Requirement 1-4, 9-12 negative
paths and Requirement 6-8 session behaviour with a fake directory adapter (no real directory).
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select, text, update

from app.core.security import refresh_token_digest
from app.db.session import async_session_factory
from app.domain.directory import DirectoryUnavailable
from app.domain.models.refresh_session import RefreshSession
from app.domain.models.user import User
from app.scripts.create_local_user import ensure_local_user
from tests.integration.conftest import (
    UPN_SUFFIX,
    AuthHarness,
    RecordingHandler,
    SuperAdmin,
)

pytestmark = pytest.mark.integration

REFRESH_COOKIE = "dwhcodereview_refresh"


def _cookie_value(response: Any) -> str:
    header = response.headers["set-cookie"]
    return header.split(";", 1)[0].split("=", 1)[1]


def _cookie_header(token: str) -> dict[str, str]:
    return {"cookie": f"{REFRESH_COOKIE}={token}"}


async def _user_by_guid(guid: Any) -> User:
    async with async_session_factory() as session:
        return (
            await session.execute(select(User).where(User.directory_object_guid == guid))
        ).scalar_one()


async def test_first_directory_login_creates_a_reviewer_and_a_session(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    name = f"ad.soyad{uuid4().hex[:8]}"
    upn, password, account = auth.directory.add(name, display_name="Ad Soyad")

    response = await auth.login(name.upper(), password)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["expires_in"] == 900
    assert body["user"]["role"] == "inceleyici"
    assert body["user"]["account_type"] == "directory"
    assert body["user"]["username"] == upn
    assert body["user"]["display_name"] == "Ad Soyad"
    assert body["user"]["is_super_admin"] is False
    # One bind with exactly one normalized UPN; no retry with another form.
    assert auth.directory.calls == [(upn, password)]

    cookie = response.headers["set-cookie"]
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/dwhcodereview/v1/auth"):
        assert attribute.lower() in cookie.lower()

    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 900
    assert {"sub", "tenant_id", "roles", "iss", "aud", "iat", "exp"} <= set(claims)
    assert password not in json.dumps(claims)
    assert str(account.object_guid) not in json.dumps(claims)

    user = await _user_by_guid(account.object_guid)
    assert user.account_type == "directory"
    assert user.password_hash is None
    assert user.last_login_at is not None
    assert user.email == upn

    me = await auth.client.get(f"{auth.prefix}/auth/me", headers=auth.auth_headers(body))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "inceleyici"
    assert me.json()["account_type"] == "directory"

    created = recorded_logs.events("auth.user.created")
    assert created and created[-1]["user_public_id"] == user.public_id
    assert created[-1]["role"] == "inceleyici"
    succeeded = recorded_logs.events("auth.login.succeeded")
    assert succeeded[-1] == {
        "event": "auth.login.succeeded",
        "user_public_id": user.public_id,
        "account_type": "directory",
    }


async def test_later_logins_update_the_profile_without_a_second_record(auth: AuthHarness) -> None:
    name = f"tekrar{uuid4().hex[:8]}"
    _, password, account = auth.directory.add(name, display_name="Eski Ad")
    assert (await auth.login(name, password)).status_code == 200
    first = await _user_by_guid(account.object_guid)

    auth.directory.add(
        name,
        password=password,
        object_guid=account.object_guid,
        display_name="Yeni Ad",
        mail=f"yeni.{name}@{UPN_SUFFIX}",
    )
    second = await auth.login(f"{name}@{UPN_SUFFIX}", password)

    assert second.status_code == 200, second.text
    updated = await _user_by_guid(account.object_guid)
    assert updated.user_id == first.user_id
    assert updated.display_name == "Yeni Ad"
    assert updated.email == f"yeni.{name}@{UPN_SUFFIX}"
    assert updated.last_login_at is not None and first.last_login_at is not None
    assert updated.last_login_at >= first.last_login_at


async def test_wrong_password_and_unknown_name_look_the_same(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    name = f"yanlis{uuid4().hex[:8]}"
    auth.directory.add(name)
    wrong = await auth.login(name, "definitely-not-the-password")
    unknown = await auth.login(f"yok{uuid4().hex[:8]}", "definitely-not-the-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["detail"]["code"] == "invalid_credentials"
    failed = recorded_logs.events("auth.login.failed")
    assert failed[-1]["reason"] == "invalid_credentials"
    assert len(failed[-1]["name_digest"]) == 16
    serialized = json.dumps(
        [record.__dict__.get("structured_fields") for record in recorded_logs.records]
    )
    assert name not in serialized
    assert "definitely-not-the-password" not in serialized


@pytest.mark.parametrize(
    "username",
    ("", "ad.soyad@other.example.test", "ad soyad", "DOMAIN\\ad.soyad"),
)
async def test_invalid_names_and_empty_passwords_never_reach_the_directory(
    auth: AuthHarness, username: str
) -> None:
    response = await auth.login(username or "ad.soyad", "" if not username else "some-password")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert auth.directory.calls == []


@pytest.mark.parametrize("reason", ("tls", "transport", "timeout", "incomplete"))
async def test_unreachable_directory_is_503_and_never_success(
    auth: AuthHarness, recorded_logs: RecordingHandler, reason: Any
) -> None:
    auth.directory.failure = DirectoryUnavailable(reason)
    response = await auth.login("ad.soyad", "some-password-value")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "directory_unavailable"
    assert recorded_logs.events("auth.directory.unavailable")[-1]["reason"] == reason


@pytest.mark.parametrize(
    ("enabled", "is_human", "reason"),
    ((False, True, "account_disabled"), (True, False, "invalid_credentials")),
)
async def test_disabled_and_non_human_accounts_are_refused(
    auth: AuthHarness,
    recorded_logs: RecordingHandler,
    enabled: bool,
    is_human: bool,
    reason: str,
) -> None:
    name = f"hesap{uuid4().hex[:8]}"
    _, password, account = auth.directory.add(name, enabled=enabled, is_human=is_human)
    response = await auth.login(name, password)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert recorded_logs.events("auth.login.failed")[-1]["reason"] == reason
    async with async_session_factory() as session:
        created = await session.execute(
            select(User).where(User.directory_object_guid == account.object_guid)
        )
        assert created.scalar_one_or_none() is None


async def test_inactive_directory_user_is_forbidden_even_with_the_right_password(
    auth: AuthHarness,
) -> None:
    name = f"pasif{uuid4().hex[:8]}"
    _, password, account = auth.directory.add(name)
    assert (await auth.login(name, password)).status_code == 200
    async with async_session_factory() as session:
        await session.execute(
            update(User)
            .where(User.directory_object_guid == account.object_guid)
            .values(is_active=False)
        )
        await session.commit()

    response = await auth.login(name, password)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "user_inactive"


async def test_directory_login_colliding_with_a_local_email_is_a_conflict(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    name = f"cakisma{uuid4().hex[:8]}"
    _, password, account = auth.directory.add(name, mail=f"{super_admin.username}@example.test")
    response = await auth.login(name, password)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "identity_conflict"
    async with async_session_factory() as session:
        created = await session.execute(
            select(User).where(User.directory_object_guid == account.object_guid)
        )
        assert created.scalar_one_or_none() is None


async def test_sixth_failure_is_rate_limited_without_asking_the_directory(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    name = f"limit{uuid4().hex[:8]}"
    auth.directory.add(name)
    for _ in range(5):
        assert (await auth.login(name, "wrong-password-value")).status_code == 401
    calls_before = len(auth.directory.calls)

    limited = await auth.login(name, "wrong-password-value")

    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) > 0
    assert len(auth.directory.calls) == calls_before
    event = recorded_logs.events("auth.login.rate_limited")[-1]
    assert event["limit"] == "user"
    assert name not in json.dumps(event)


async def test_forwarded_for_from_an_untrusted_peer_does_not_escape_the_limit(
    auth: AuthHarness,
) -> None:
    name = f"xff{uuid4().hex[:8]}"
    auth.directory.add(name)
    for index in range(5):
        spoofed = {"x-forwarded-for": f"198.51.100.{index}"}
        assert (await auth.login(name, "wrong-password-value", headers=spoofed)).status_code == 401
    limited = await auth.login(name, "wrong-password-value", headers={"x-forwarded-for": "1.1.1.1"})
    assert limited.status_code == 429


async def test_successful_login_resets_the_user_counter(auth: AuthHarness) -> None:
    name = f"sifirla{uuid4().hex[:8]}"
    _, password, _ = auth.directory.add(name)
    for _ in range(4):
        await auth.login(name, "wrong-password-value")
    assert (await auth.login(name, password)).status_code == 200
    for _ in range(4):
        assert (await auth.login(name, "wrong-password-value")).status_code == 401
    assert (await auth.login(name, password)).status_code == 200


async def _local_user(role: str) -> tuple[str, str]:
    from app.core.config import get_settings

    name = f"yerel-{uuid4().hex[:8]}"
    password = secrets.token_urlsafe(24)
    local = get_settings().model_copy(update={"environment": "development"})
    async with async_session_factory() as session:
        await ensure_local_user(session, local, username=name, password=password, role_code=role)
    return name, password


async def test_nonprod_local_password_login_is_only_for_the_super_admin(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    name, password = await _local_user("inceleyici")

    refused = await auth.login(name, password)
    admitted = await auth.login(super_admin.username, super_admin.password)

    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "invalid_credentials"
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["user"]["is_super_admin"] is True
    assert admitted.json()["user"]["account_type"] == "local"
    # A name that matches a local account is never sent to the directory.
    assert auth.directory.calls == []


async def test_local_environment_admits_every_local_account(auth: AuthHarness) -> None:
    auth.use_settings(environment="development", directory_enabled=False)
    name, password = await _local_user("inceleyici")

    response = await auth.login(name, password)

    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "inceleyici"
    unknown = await auth.login(f"yok-{uuid4().hex[:6]}", password)
    assert unknown.status_code == 401
    assert auth.directory.calls == []


async def _logged_in(auth: AuthHarness) -> tuple[dict[str, Any], str]:
    name = f"oturum{uuid4().hex[:8]}"
    _, password, _ = auth.directory.add(name)
    response = await auth.login(name, password)
    assert response.status_code == 200, response.text
    return response.json(), _cookie_value(response)


async def test_refresh_rotates_the_token_and_reuse_closes_the_family(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    body, first = await _logged_in(auth)

    refreshed = await auth.client.post(
        f"{auth.prefix}/auth/refresh",
        headers={**auth.origin_headers(), **_cookie_header(first)},
    )
    assert refreshed.status_code == 200, refreshed.text
    second = _cookie_value(refreshed)
    assert second != first
    assert refreshed.json()["user"]["public_id"] == body["user"]["public_id"]

    reused = await auth.client.post(
        f"{auth.prefix}/auth/refresh",
        headers={**auth.origin_headers(), **_cookie_header(first)},
    )
    assert reused.status_code == 401
    assert reused.json()["detail"]["code"] == "session_revoked"
    successor = await auth.client.post(
        f"{auth.prefix}/auth/refresh",
        headers={**auth.origin_headers(), **_cookie_header(second)},
    )
    assert successor.status_code == 401
    assert successor.json()["detail"]["code"] == "session_revoked"
    event = recorded_logs.events("auth.session.reuse_detected")[-1]
    assert event["user_public_id"] == body["user"]["public_id"]
    async with async_session_factory() as session:
        reasons = (
            await session.scalars(
                select(RefreshSession.revoke_reason).where(
                    RefreshSession.token_sha256.in_(
                        [refresh_token_digest(first), refresh_token_digest(second)]
                    )
                )
            )
        ).all()
    assert sorted(reasons) == ["reuse_detected", "rotated"]


@pytest.mark.parametrize("origin", (None, "https://attacker.example.test"))
async def test_cookie_endpoints_require_the_application_origin(
    auth: AuthHarness, origin: str | None
) -> None:
    _, token = await _logged_in(auth)
    headers = _cookie_header(token) | ({"origin": origin} if origin else {})
    for path in ("/auth/refresh", "/auth/logout"):
        response = await auth.client.post(f"{auth.prefix}{path}", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "origin_not_allowed"


async def test_refresh_without_a_cookie_or_after_idle_expiry_is_expired(auth: AuthHarness) -> None:
    missing = await auth.client.post(f"{auth.prefix}/auth/refresh", headers=auth.origin_headers())
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "session_expired"

    _, token = await _logged_in(auth)
    async with async_session_factory() as session:
        await session.execute(
            update(RefreshSession)
            .where(RefreshSession.token_sha256 == refresh_token_digest(token))
            .values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    expired = await auth.client.post(
        f"{auth.prefix}/auth/refresh", headers={**auth.origin_headers(), **_cookie_header(token)}
    )
    assert expired.status_code == 401
    assert expired.json()["detail"]["code"] == "session_expired"


async def test_session_family_never_outlives_its_absolute_limit(auth: AuthHarness) -> None:
    before = datetime.now(UTC)
    _, token = await _logged_in(auth)
    refreshed = await auth.client.post(
        f"{auth.prefix}/auth/refresh", headers={**auth.origin_headers(), **_cookie_header(token)}
    )
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(RefreshSession).where(
                    RefreshSession.token_sha256.in_(
                        [
                            refresh_token_digest(token),
                            refresh_token_digest(_cookie_value(refreshed)),
                        ]
                    )
                )
            )
        ).all()
    assert len(rows) == 2
    assert rows[0].family_id == rows[1].family_id
    assert rows[0].absolute_expires_at == rows[1].absolute_expires_at
    assert rows[0].absolute_expires_at <= before + timedelta(hours=8, seconds=5)
    for row in rows:
        assert row.idle_expires_at <= row.absolute_expires_at
        assert row.created_at + timedelta(minutes=61) > row.idle_expires_at


async def test_logout_closes_the_session_and_deletes_the_cookie(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    body, token = await _logged_in(auth)

    response = await auth.client.post(
        f"{auth.prefix}/auth/logout", headers={**auth.origin_headers(), **_cookie_header(token)}
    )

    assert response.status_code == 204
    assert f"{REFRESH_COOKIE}=" in response.headers["set-cookie"]
    assert "max-age=0" in response.headers["set-cookie"].lower()
    after = await auth.client.post(
        f"{auth.prefix}/auth/refresh", headers={**auth.origin_headers(), **_cookie_header(token)}
    )
    assert after.status_code == 401
    assert recorded_logs.events("auth.logout")[-1]["user_public_id"] == body["user"]["public_id"]


async def test_logout_without_a_cookie_still_answers_204(auth: AuthHarness) -> None:
    response = await auth.client.post(f"{auth.prefix}/auth/logout", headers=auth.origin_headers())
    assert response.status_code == 204


async def test_logs_never_contain_passwords_tokens_or_cookies(
    auth: AuthHarness, recorded_logs: RecordingHandler
) -> None:
    name = f"gizli{uuid4().hex[:8]}"
    _, password, _ = auth.directory.add(name, password=f"Marker-{uuid4().hex}")
    response = await auth.login(name, password)
    token = _cookie_value(response)
    await auth.client.post(
        f"{auth.prefix}/auth/refresh", headers={**auth.origin_headers(), **_cookie_header(token)}
    )
    await auth.login(name, "Wrong-" + password)

    emitted = json.dumps(
        [
            {"message": record.getMessage(), **dict(getattr(record, "structured_fields", {}))}
            for record in recorded_logs.records
        ]
    )
    for secret_value in (password, token, response.json()["access_token"]):
        assert secret_value not in emitted


async def test_expired_sessions_are_purged_after_seven_days(auth: AuthHarness) -> None:
    _, token = await _logged_in(auth)
    digest = refresh_token_digest(token)
    old = datetime.now(UTC) - timedelta(days=8)
    async with async_session_factory() as session:
        await session.execute(
            text(
                "UPDATE auth_refresh_session SET idle_expires_at = :old, "
                "absolute_expires_at = :old WHERE token_sha256 = :digest"
            ),
            {"old": old, "digest": digest},
        )
        await session.commit()

    await _logged_in(auth)

    async with async_session_factory() as session:
        remaining = await session.scalar(
            select(RefreshSession.auth_refresh_session_id).where(
                RefreshSession.token_sha256 == digest
            )
        )
    assert remaining is None
