"""Shared PostgreSQL integration fixtures: one Alembic upgrade per run, engine per test loop."""

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from app.api.auth.endpoints import get_directory_login, get_login_rate_limiter
from app.api.integrations import (
    get_llm_chat,
    get_llm_connection_store,
    get_review_rate_limiter,
    get_review_registry,
    get_sql_catalog,
)
from app.core.config import Settings, get_settings
from app.core.login_throttle import LoginRateLimiter
from app.core.review_throttle import ReviewRateLimiter
from app.db.session import async_session_factory, engine
from app.domain.directory import (
    DirectoryAccount,
    DirectoryCredentialsRejected,
)
from app.domain.models.llm_call import LlmChatApi
from app.infrastructure.repositories.user_repository import UserRepository
from app.main import app
from app.services.llm_connection_service import LlmConnectionConfig, LlmConnectionStore
from app.services.review_run_service import ReviewRunRegistry
from app.services.super_admin_service import ensure_super_admin
from tests.fakes.review_ports import FakeCatalog, ScriptedLlm


@pytest.fixture(scope="session")
def migrated_database(postgres_database_url: str) -> Iterator[None]:
    del postgres_database_url  # the Alembic environment reads the same typed setting
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)
    yield


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test() -> AsyncIterator[None]:
    # Each test runs in its own event loop; pooled asyncpg connections must not outlive it.
    yield
    await engine.dispose()


UPN_SUFFIX = "corp.example.test"
CLIENT_ADDRESS = "10.0.0.5"


@dataclass
class DirectoryEntry:
    password: str
    account: DirectoryAccount


@dataclass
class FakeDirectory:
    """Signature-constrained DirectoryLoginPort: exact calls recorded, typed results replayed."""

    entries: dict[str, DirectoryEntry] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    failure: Exception | None = None

    def add(
        self,
        account_name: str,
        *,
        password: str | None = None,
        enabled: bool = True,
        is_human: bool = True,
        mail: str | None = None,
        display_name: str | None = None,
        object_guid: UUID | None = None,
    ) -> tuple[str, str, DirectoryAccount]:
        upn = f"{account_name}@{UPN_SUFFIX}"
        secret = password or secrets.token_urlsafe(18)
        account = DirectoryAccount(
            object_guid=object_guid or uuid4(),
            user_principal_name=upn,
            display_name=display_name or account_name.title(),
            mail=mail if mail is not None else f"{account_name}@{UPN_SUFFIX}",
            enabled=enabled,
            is_human=is_human,
        )
        self.entries[upn] = DirectoryEntry(secret, account)
        return upn, secret, account

    async def authenticate(self, user_principal_name: str, password: str) -> DirectoryAccount:
        self.calls.append((user_principal_name, password))
        if self.failure is not None:
            raise self.failure
        entry = self.entries.get(user_principal_name)
        if entry is None or entry.password != password:
            raise DirectoryCredentialsRejected()
        return entry.account


@dataclass
class AuthHarness:
    client: AsyncClient
    directory: FakeDirectory
    limiter: LoginRateLimiter
    settings: Settings
    use_settings: Callable[..., Settings]

    @property
    def prefix(self) -> str:
        return self.settings.api_prefix

    def origin_headers(self) -> dict[str, str]:
        return {"origin": self.settings.public_origin}

    def auth_headers(self, login_body: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {login_body['access_token']}",
            self.settings.tenant_header: login_body["user"]["tenant_id"],
        }

    async def login(self, username: str, password: str, **kwargs: Any) -> Any:
        return await self.client.post(
            f"{self.prefix}/auth/login",
            json={"username": username, "password": password},
            **kwargs,
        )


@pytest.fixture
async def auth(migrated_database: None) -> AsyncIterator[AuthHarness]:
    base = get_settings()
    state: dict[str, Settings] = {
        "settings": base.model_copy(
            update={
                "environment": "staging",
                "directory_enabled": True,
                "directory_upn_suffix": UPN_SUFFIX,
            }
        )
    }
    directory = FakeDirectory()
    limiter = LoginRateLimiter()

    def use_settings(**updates: Any) -> Settings:
        state["settings"] = state["settings"].model_copy(update=updates)
        return state["settings"]

    def directory_login() -> FakeDirectory | None:
        return directory if state["settings"].directory_enabled else None

    app.dependency_overrides[get_settings] = lambda: state["settings"]
    app.dependency_overrides[get_directory_login] = directory_login
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    transport = ASGITransport(app=app, client=(CLIENT_ADDRESS, 50000))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield AuthHarness(client, directory, limiter, state["settings"], use_settings)
    finally:
        for dependency in (get_settings, get_directory_login, get_login_rate_limiter):
            app.dependency_overrides.pop(dependency, None)


@dataclass(frozen=True)
class SuperAdmin:
    username: str
    password: str
    public_id: UUID


@pytest.fixture
async def super_admin(migrated_database: None) -> SuperAdmin:
    suffix = uuid4().hex[:10]
    username = f"admin-{suffix}"
    password = secrets.token_urlsafe(24)
    async with async_session_factory() as session:
        result = await ensure_super_admin(
            session,
            email=f"{username}@example.test",
            username=username,
            password=password,
        )
    return SuperAdmin(username, password, result.user_public_id)


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def events(self, name: str) -> list[dict[str, Any]]:
        return [
            dict(getattr(record, "structured_fields", {}))
            for record in self.records
            if record.getMessage() == name
        ]


@pytest.fixture
def recorded_logs() -> Iterator[RecordingHandler]:
    handler = RecordingHandler()
    names = ("app.auth", "app.admin", "app.http", "app.scheduled_review")
    loggers = [logging.getLogger(name) for name in names]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.removeHandler(handler)
            logger.setLevel(level)


@dataclass(frozen=True)
class RoleSession:
    """A directory user holding one application role, logged in through the real endpoint."""

    headers: dict[str, str]
    public_id: str
    display_name: str


class RoleSessions:
    def __init__(self, auth: AuthHarness) -> None:
        self.auth = auth
        self._super_admin: RoleSession | None = None

    async def login(self, role: str) -> RoleSession:
        name = f"kisi{uuid4().hex[:8]}"
        _, password, _ = self.auth.directory.add(name)
        first = await self.auth.login(name, password)
        assert first.status_code == 200, first.text
        user_public_id = first.json()["user"]["public_id"]
        if role != "inceleyici":
            async with async_session_factory() as session:
                users = UserRepository(session)
                user = await users.get_active_by_public_id(UUID(user_public_id))
                target_role = await users.get_role(role)
                assert user is not None and target_role is not None
                await users.set_application_role(
                    user, target_role, actor_user_id=user.user_id, now=datetime.now(UTC)
                )
                await session.commit()
        response = await self.auth.login(name, password)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user"]["role"] == role
        return RoleSession(
            self.auth.auth_headers(body),
            body["user"]["public_id"],
            body["user"]["display_name"],
        )

    async def reviewer(self) -> RoleSession:
        return await self.login("inceleyici")

    async def rule_manager(self) -> RoleSession:
        return await self.login("kural-yoneticisi")

    async def super_admin(self) -> RoleSession:
        """A local super admin; only it publishes directly (sql-review 009-rule-proposals)."""

        if self._super_admin is None:
            username = f"admin-{uuid4().hex[:10]}"
            password = secrets.token_urlsafe(24)
            async with async_session_factory() as session:
                await ensure_super_admin(
                    session,
                    email=f"{username}@example.test",
                    username=username,
                    password=password,
                )
            response = await self.auth.login(username, password)
            assert response.status_code == 200, response.text
            body = response.json()
            self._super_admin = RoleSession(
                self.auth.auth_headers(body),
                body["user"]["public_id"],
                body["user"]["display_name"],
            )
        return self._super_admin


@pytest.fixture
def role_sessions(auth: AuthHarness) -> RoleSessions:
    return RoleSessions(auth)


# --- Review runs (sql-review 003, 004, 005) ----------------------------------------------------


def sse_events(body: str) -> list[dict[str, Any]]:
    """The JSON of every ``data:`` line; comment lines are keep-alive ticks."""

    events: list[dict[str, Any]] = []
    for line in body.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
        else:
            assert line == "" or line.startswith(":"), line
    return events


@dataclass
class ReviewEnv:
    auth: AuthHarness
    sessions: RoleSessions
    llm: ScriptedLlm
    catalog: FakeCatalog
    limiter: ReviewRateLimiter
    registry: ReviewRunRegistry
    llm_store: LlmConnectionStore

    @property
    def prefix(self) -> str:
        return self.auth.prefix

    async def publish(
        self,
        manager: RoleSession,
        critical: list[tuple[str, bool]],
        normal: list[tuple[str, bool]] | None = None,
        *,
        groups: list[dict[str, str]] | None = None,
        membership: dict[int, str | list[str]] | None = None,
    ) -> tuple[int, list[str]]:
        """Publish a fresh rule set with new codes; returns the version number and codes.

        ``membership`` maps the zero-based index of a rule (critical first, then normal) to the
        id, or the list of ids, of its ``groups`` (rule-group-selection Decision 1).
        """

        client = self.auth.client
        workspace = (await client.get(f"{self.prefix}/rule-set", headers=manager.headers)).json()
        number = int(workspace["next_rule_id"].removeprefix("Kural"))
        codes: list[str] = []

        def items(rules: list[tuple[str, bool]]) -> list[dict[str, Any]]:
            built = []
            for text_value, flag in rules:
                code = f"Kural{number + len(codes):02d}"
                codes.append(code)
                group = (membership or {}).get(len(codes) - 1)
                built.append(
                    {
                        "id": code,
                        "text": text_value,
                        "requires_metadata": flag,
                        "rule_group_ids": (
                            [] if group is None else [group] if isinstance(group, str) else group
                        ),
                    }
                )
            return built

        body = {
            "base_revision": workspace["revision"],
            "critical": items(critical),
            "normal": items(normal or []),
            "groups": groups or [],
        }
        saved = await client.put(
            f"{self.prefix}/rule-set/draft", json=body, headers=manager.headers
        )
        assert saved.status_code == 200, saved.text
        # Only the super admin publishes directly (009-rule-proposals); in the caller's tenant.
        tenant_header = self.auth.settings.tenant_header
        admin = await self.sessions.super_admin()
        published = await client.post(
            f"{self.prefix}/rule-set/versions",
            json={"base_revision": saved.json()["revision"]},
            headers={**admin.headers, tenant_header: manager.headers[tenant_header]},
        )
        assert published.status_code in (200, 201), published.text
        return int(published.json()["number"]), codes

    async def object_review(
        self,
        session: RoleSession,
        selections: list[dict[str, str]],
        rule_group_ids: list[str] | None = None,
        rule_codes: list[str] | None = None,
    ) -> Any:
        return await self.auth.client.post(
            f"{self.prefix}/object-reviews",
            json={
                "selections": selections,
                "rule_group_ids": rule_group_ids or [],
                "rule_codes": rule_codes or [],
            },
            headers=session.headers,
        )

    async def script_review(
        self,
        session: RoleSession,
        sql: str,
        label: str | None = None,
        rule_group_ids: list[str] | None = None,
        rule_codes: list[str] | None = None,
    ) -> Any:
        return await self.auth.client.post(
            f"{self.prefix}/script-reviews",
            json={
                "sql": sql,
                "label": label,
                "rule_group_ids": rule_group_ids or [],
                "rule_codes": rule_codes or [],
            },
            headers=session.headers,
        )

    async def settle(self) -> None:
        """Wait until no review task of this test is running any more."""

        for _ in range(200):
            if not self.registry._tasks:
                return
            await asyncio.sleep(0.025)
        raise AssertionError("a review task did not finish")


@pytest.fixture
async def review_env(auth: AuthHarness, role_sessions: RoleSessions) -> AsyncIterator[ReviewEnv]:
    env = ReviewEnv(
        auth=auth,
        sessions=role_sessions,
        llm=ScriptedLlm(),
        catalog=FakeCatalog(),
        limiter=ReviewRateLimiter(),
        registry=ReviewRunRegistry(),
        llm_store=LlmConnectionStore(
            LlmConnectionConfig(
                chat_api=LlmChatApi.OPENAI,
                base_url="https://llm.corp.example.test/v1",
                model="test-model",
            )
        ),
    )
    overrides: dict[Any, Any] = {
        get_llm_chat: lambda: env.llm,
        get_sql_catalog: lambda: env.catalog,
        get_review_rate_limiter: lambda: env.limiter,
        get_review_registry: lambda: env.registry,
        get_llm_connection_store: lambda: env.llm_store,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield env
    finally:
        if env.llm.gate is not None:
            env.llm.gate.set()
        await env.registry.shutdown()
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)
