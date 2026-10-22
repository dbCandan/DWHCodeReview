"""SQL Server and LLM connection settings endpoints through the real HTTP application.

sql-review/PRDs/002-sql-server-connection Requirement 3, 4, 5, 10 and 11 and 006-llm-connection
Requirement 13 (Acceptance 1): roles, the nonprod read view, the local write and test endpoints,
the nonprod connection the super admin saves in PostgreSQL, and passwords or keys never appearing
in responses or logs.
"""

import base64
import logging
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from app.api.integrations import (
    get_llm_connection_store,
    get_llm_resolver,
    get_sql_catalog,
    get_sql_catalog_adapter,
    get_sql_connection_storage,
    get_sql_connection_store,
)
from app.core.config import get_settings
from app.core.secret_cipher import SecretCipher
from app.db.session import async_session_factory, engine
from app.domain.models.llm_call import LlmChatApi
from app.domain.sql_server import SqlServerConnectionConfig
from app.infrastructure.sql_server import queries
from app.infrastructure.sql_server.catalog_adapter import PyodbcSqlCatalog
from app.main import app, create_application
from app.services.llm_connection_service import LlmConnectionConfig, LlmConnectionStore
from app.services.sql_connection_service import SqlConnectionStore, StoredSqlConnection
from tests.integration.conftest import (
    CLIENT_ADDRESS,
    AuthHarness,
    RoleSessions,
    SuperAdmin,
)

pytestmark = pytest.mark.integration

SQL_PASSWORD = f"sql-parola-{uuid4().hex}"
LLM_KEY = f"llm-anahtar-{uuid4().hex}"


class FakeProbe:
    def __init__(self) -> None:
        self.calls: list[SqlServerConnectionConfig] = []

    async def probe(self, config: SqlServerConnectionConfig) -> list[str]:
        self.calls.append(config)
        return [f"DWH_{n}" for n in range(10)]


@dataclass
class Integrations:
    sql_store: SqlConnectionStore
    llm_store: LlmConnectionStore
    probe: FakeProbe


@pytest.fixture
def integrations(auth: AuthHarness) -> Iterator[Integrations]:
    state = Integrations(
        SqlConnectionStore(
            SqlServerConnectionConfig(
                server="sql-dev.corp.example.test", user="gelistirici", password=SQL_PASSWORD
            )
        ),
        LlmConnectionStore(
            LlmConnectionConfig(
                chat_api=LlmChatApi.OPENAI,
                base_url="https://llm.corp.example.test/v1",
                model="test-model",
                api_key=LLM_KEY,
            )
        ),
        FakeProbe(),
    )

    async def resolver(host: str, port: int) -> list[str]:
        return {"llm.corp.example.test": ["10.14.3.99"]}.get(host, ["93.184.216.34"])

    overrides = {
        get_sql_connection_store: lambda: state.sql_store,
        get_sql_catalog: lambda: state.probe,
        get_llm_connection_store: lambda: state.llm_store,
        get_llm_resolver: lambda: resolver,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield state
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)


@pytest.fixture
async def local_client(auth: AuthHarness, integrations: Integrations) -> AsyncIterator[AsyncClient]:
    """The same application built for the local environment, sharing the test overrides."""

    local_settings = auth.settings.model_copy(update={"environment": "development"})
    local_app = create_application(local_settings)
    local_app.dependency_overrides.update(app.dependency_overrides)
    local_app.dependency_overrides[get_settings] = lambda: local_settings
    transport = ASGITransport(app=local_app, client=(CLIENT_ADDRESS, 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def captured_logs() -> Iterator[list[logging.LogRecord]]:
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


def _rendered(records: list[logging.LogRecord]) -> str:
    return repr([(r.getMessage(), getattr(r, "structured_fields", None), r.args) for r in records])


async def test_settings_endpoints_require_the_rule_manager(
    auth: AuthHarness, role_sessions: RoleSessions, integrations: Integrations
) -> None:
    reviewer = await role_sessions.reviewer()
    tenant_only = {auth.settings.tenant_header: reviewer.headers[auth.settings.tenant_header]}
    for path in ("/sql-connection", "/llm-connection", "/llm-calls"):
        anonymous = await auth.client.get(f"{auth.prefix}{path}", headers=tenant_only)
        forbidden = await auth.client.get(f"{auth.prefix}{path}", headers=reviewer.headers)
        assert anonymous.status_code == 401, path
        assert forbidden.status_code == 403, path
        assert forbidden.json()["detail"]["code"] == "forbidden"


async def test_nonprod_shows_only_the_state_and_has_no_write_endpoints(
    auth: AuthHarness,
    role_sessions: RoleSessions,
    integrations: Integrations,
    super_admin: SuperAdmin,
) -> None:
    manager = await role_sessions.rule_manager()
    admin = await _admin_headers(auth, super_admin)

    sql = await auth.client.get(f"{auth.prefix}/sql-connection", headers=manager.headers)
    llm = await auth.client.get(f"{auth.prefix}/llm-connection", headers=manager.headers)
    writes = [
        await auth.client.put(
            f"{auth.prefix}/sql-connection", json={"port": 1}, headers=manager.headers
        ),
        await auth.client.post(
            f"{auth.prefix}/sql-connection/test", json={}, headers=manager.headers
        ),
        await auth.client.put(
            f"{auth.prefix}/llm-connection", json={"model": "x"}, headers=manager.headers
        ),
    ]

    closed = {
        "environment": "nonprod",
        "editable": False,
        "configured": True,
        "managed_by": "deployment",
    }
    assert sql.json() == closed
    # Without the settings encryption key the interface is closed to the super admin as well.
    as_admin = await auth.client.get(f"{auth.prefix}/sql-connection", headers=admin)
    admin_writes = [
        await auth.client.put(f"{auth.prefix}/sql-connection", json={"port": 1}, headers=admin),
        await auth.client.post(f"{auth.prefix}/sql-connection/test", json={}, headers=admin),
    ]
    assert as_admin.json() == closed
    assert [response.status_code for response in admin_writes] == [404, 404]
    assert integrations.probe.calls == []
    assert llm.json() == {
        "environment": "nonprod",
        "editable": False,
        "chat_api": "openai",
        "model": "test-model",
    }
    assert [response.status_code for response in writes] == [404, 404, 404]
    assert SQL_PASSWORD not in sql.text and LLM_KEY not in llm.text
    assert integrations.sql_store.current().port == 1433


async def test_local_sql_settings_change_in_process_and_hide_the_password(
    role_sessions: RoleSessions,
    integrations: Integrations,
    local_client: AsyncClient,
    captured_logs: list[logging.LogRecord],
) -> None:
    manager = await role_sessions.rule_manager()
    prefix = get_settings().api_prefix
    new_password = f"yeni-{uuid4().hex}"

    shown = await local_client.get(f"{prefix}/sql-connection", headers=manager.headers)
    changed = await local_client.put(
        f"{prefix}/sql-connection",
        json={"port": 14330, "password": new_password},
        headers=manager.headers,
    )
    other_server = await local_client.post(
        f"{prefix}/sql-connection/test",
        json={"server": "baska.corp.example.test"},
        headers=manager.headers,
    )
    same_server = await local_client.post(
        f"{prefix}/sql-connection/test", json={}, headers=manager.headers
    )
    free_string = await local_client.put(
        f"{prefix}/sql-connection",
        json={"connection_string": "Server=x;Trusted_Connection=yes"},
        headers=manager.headers,
    )

    assert shown.json()["password_set"] is True and "password" not in shown.json()
    assert changed.status_code == 200, changed.text
    assert changed.json()["port"] == 14330 and changed.json()["password_set"] is True
    assert changed.json()["managed_by"] == "local_process"
    assert integrations.sql_store.current().password == new_password
    assert other_server.json()["code"] == "password_required"
    assert same_server.json()["ok"] is True
    assert same_server.json()["databases"] == [f"DWH_{n}" for n in range(10)]
    assert [call.password for call in integrations.probe.calls] == [new_password]
    assert free_string.status_code == 422
    assert free_string.json()["detail"]["code"] == "invalid_request"
    for response in (shown, changed, other_server, same_server, free_string):
        assert SQL_PASSWORD not in response.text and new_password not in response.text
    rendered = _rendered(captured_logs)
    assert new_password not in rendered and SQL_PASSWORD not in rendered
    assert any(r.getMessage() == "sql_connection.updated" for r in captured_logs)


async def test_local_writes_still_require_the_rule_manager(
    role_sessions: RoleSessions, integrations: Integrations, local_client: AsyncClient
) -> None:
    reviewer = await role_sessions.reviewer()
    prefix = get_settings().api_prefix
    for method, path in (
        ("PUT", "/sql-connection"),
        ("POST", "/sql-connection/test"),
        ("PUT", "/llm-connection"),
    ):
        response = await local_client.request(
            method, f"{prefix}{path}", json={}, headers=reviewer.headers
        )
        assert response.status_code == 403, path
    assert integrations.probe.calls == []


# --- nonprod: the connection the super admin saves (002 Requirement 5, 10, 11) ------------------


async def _admin_headers(auth: AuthHarness, admin: SuperAdmin) -> dict[str, str]:
    response = await auth.login(admin.username, admin.password)
    assert response.status_code == 200, response.text
    return auth.auth_headers(response.json())


class _Driver:
    """pyodbc.connect stand-in: records connection strings and lists the online databases."""

    def __init__(self) -> None:
        self.connection_strings: list[str] = []

    def connect(self, connection_string: str, *, timeout: int, autocommit: bool) -> "_Driver":
        self.connection_strings.append(connection_string)
        return self

    timeout = 0

    def cursor(self) -> "_Driver":
        return self

    def execute(self, sql: str, *params: Any) -> None:
        assert sql == queries.LIST_DATABASES_SQL and not params

    def fetchall(self) -> list[tuple[str]]:
        return [(name,) for name in ("DWH_Risk", "DWH_Sales", "Scratch", "master", "tempdb")]

    def close(self) -> None:
        pass


def _provide(value: Any) -> Any:
    """A dependency without parameters that returns one object of a replica."""

    return lambda: value


@dataclass
class StoredReplica:
    """One nonprod backend process that keeps the connection in PostgreSQL."""

    client: AsyncClient
    store: SqlConnectionStore
    driver: _Driver = field(default_factory=_Driver)


@pytest.fixture
async def stored_replicas(auth: AuthHarness) -> AsyncIterator[tuple[StoredReplica, StoredReplica]]:
    """Two processes of the same deployment: no deployment connection, one encryption key."""

    key = os.urandom(32)
    settings = auth.settings.model_copy(
        update={"settings_encryption_key": SecretStr(base64.b64encode(key).decode())}
    )

    async def delete() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM sql_connection_setting"))

    await delete()
    replicas: list[StoredReplica] = []
    catalogs: list[PyodbcSqlCatalog] = []
    clients: list[AsyncClient] = []
    try:
        for _ in range(2):
            driver = _Driver()
            store = SqlConnectionStore(SqlServerConnectionConfig())
            storage = StoredSqlConnection(
                session_factory=async_session_factory, cipher=SecretCipher(key), store=store
            )
            catalog = PyodbcSqlCatalog(
                config=store.current,
                login_timeout_seconds=15,
                query_timeout_seconds=60,
                max_concurrency=2,
                connect=driver.connect,
            )
            catalogs.append(catalog)
            replica_app = create_application(settings)
            replica_app.dependency_overrides.update(app.dependency_overrides)
            replica_app.dependency_overrides.update(
                {
                    get_settings: lambda: settings,
                    get_sql_connection_store: _provide(store),
                    get_sql_connection_storage: _provide(storage),
                    get_sql_catalog_adapter: _provide(catalog),
                }
            )
            client = AsyncClient(
                transport=ASGITransport(app=replica_app, client=(CLIENT_ADDRESS, 50000)),
                base_url="http://test",
            )
            clients.append(client)
            replicas.append(StoredReplica(client, store, driver))
        yield replicas[0], replicas[1]
    finally:
        for client in clients:
            await client.aclose()
        for catalog in catalogs:
            catalog.close()
        await delete()


async def test_nonprod_super_admin_saves_tests_and_reads_the_connection(
    auth: AuthHarness,
    role_sessions: RoleSessions,
    super_admin: SuperAdmin,
    stored_replicas: tuple[StoredReplica, StoredReplica],
    captured_logs: list[logging.LogRecord],
) -> None:
    saving, serving = stored_replicas
    admin = await _admin_headers(auth, super_admin)
    reviewer = await role_sessions.reviewer()
    prefix = auth.prefix
    password = f"nonprod-parola-{uuid4().hex};="
    form = {"server": "sql-dwh.corp.example.test", "port": 1444, "user": "dwh_okuyucu"}
    everything = ["DWH_Risk", "DWH_Sales", "Scratch"]

    empty = await saving.client.get(f"{prefix}/sql-connection", headers=admin)
    not_yet = await serving.client.get(f"{prefix}/databases", headers=reviewer.headers)
    tested = await saving.client.post(
        f"{prefix}/sql-connection/test", json={**form, "password": password}, headers=admin
    )
    untouched = await serving.client.get(f"{prefix}/databases", headers=reviewer.headers)
    saved = await saving.client.put(
        f"{prefix}/sql-connection", json={**form, "password": password}, headers=admin
    )
    # The other process serves the next request with the saved connection, without a restart,
    # and offers every database the account can access except the system databases.
    listed = await serving.client.get(f"{prefix}/databases", headers=reviewer.headers)
    verified = serving.driver.connection_strings[-1]
    shown = await serving.client.get(f"{prefix}/sql-connection", headers=admin)
    system = await serving.client.get(
        f"{prefix}/databases/master/objects", headers=reviewer.headers
    )
    trusting = await saving.client.put(
        f"{prefix}/sql-connection", json={"trust_server_certificate": True}, headers=admin
    )
    relisted = await serving.client.get(f"{prefix}/databases", headers=reviewer.headers)
    trusted = serving.driver.connection_strings[-1]
    unencrypted = await saving.client.put(
        f"{prefix}/sql-connection", json={"encrypt": False}, headers=admin
    )
    removed = await saving.client.put(
        f"{prefix}/sql-connection", json={"password": ""}, headers=admin
    )
    closed = await serving.client.get(f"{prefix}/databases", headers=reviewer.headers)

    assert empty.json() == {
        "environment": "nonprod",
        "editable": True,
        "configured": False,
        "managed_by": "super_admin",
        "server": "",
        "port": 1433,
        "user": "",
        "encrypt": True,
        "trust_server_certificate": False,
        "password_set": False,
    }
    assert not_yet.status_code == 503
    assert not_yet.json()["detail"]["code"] == "sql_connection_not_configured"
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True and tested.json()["databases"] == everything
    assert untouched.status_code == 503  # a test never saves
    assert saved.status_code == 200, saved.text
    expected = {
        "environment": "nonprod",
        "editable": True,
        "configured": True,
        "managed_by": "super_admin",
        "server": "sql-dwh.corp.example.test",
        "port": 1444,
        "user": "dwh_okuyucu",
        "encrypt": True,
        "trust_server_certificate": False,
        "password_set": True,
    }
    assert saved.json() == expected and shown.json() == expected
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == everything and listed.json()["total"] == 3
    assert "Server=sql-dwh.corp.example.test,1444;" in verified
    assert "Encrypt=yes;TrustServerCertificate=no;" in verified
    assert system.status_code == 403
    assert system.json()["detail"]["code"] == "database_not_allowed"
    # Decision 6 exception: the super admin turns verification off; encryption stays on.
    assert trusting.status_code == 200, trusting.text
    assert trusting.json() == {**expected, "trust_server_certificate": True}
    assert relisted.json()["items"] == everything
    assert "Encrypt=yes;TrustServerCertificate=yes;" in trusted
    assert unencrypted.status_code == 422
    assert unencrypted.json()["detail"]["code"] == "sql_setting_fixed"
    assert removed.json()["configured"] is False and removed.json()["password_set"] is False
    assert removed.json()["trust_server_certificate"] is True
    assert closed.status_code == 503

    async with engine.connect() as connection:
        row = dict(
            (await connection.execute(text("SELECT * FROM sql_connection_setting"))).one()._mapping
        )
        actor = (
            await connection.execute(
                text("SELECT user_id FROM app_user WHERE public_id = :public_id"),
                {"public_id": str(super_admin.public_id)},
            )
        ).scalar_one()
    assert row["password_ciphertext"] is None and row["updated_by"] == actor
    assert row["trust_server_certificate"] is True and "allowed_databases" not in row
    for response in (empty, tested, saved, shown, trusting, removed, listed):
        assert password not in response.text and "password_ciphertext" not in response.text
        assert "allowed_databases" not in response.text
    rendered = _rendered(captured_logs)
    assert password not in rendered
    events = [
        r.structured_fields  # type: ignore[attr-defined]
        for r in captured_logs
        if r.getMessage() == "sql_connection.updated"
    ]
    assert [event["changed_fields"] for event in events] == [
        "password,port,server,user",
        "trust_server_certificate",
        "password",
    ]
    assert [event["trust_server_certificate"] for event in events] == [False, True, True]
    assert all(event["user_public_id"] == str(super_admin.public_id) for event in events)
    assert all(event["managed_by"] == "super_admin" for event in events)


async def test_nonprod_stored_password_is_ciphertext_in_postgresql(
    auth: AuthHarness,
    super_admin: SuperAdmin,
    stored_replicas: tuple[StoredReplica, StoredReplica],
) -> None:
    saving, _ = stored_replicas
    admin = await _admin_headers(auth, super_admin)
    password = f"nonprod-parola-{uuid4().hex}"

    saved = await saving.client.put(
        f"{auth.prefix}/sql-connection",
        json={
            "server": "sql-dwh.corp.example.test",
            "user": "dwh_okuyucu",
            "password": password,
        },
        headers=admin,
    )

    assert saved.status_code == 200, saved.text
    async with engine.connect() as connection:
        dumped = (
            await connection.execute(
                text("SELECT row_to_json(s)::text FROM sql_connection_setting s")
            )
        ).scalar_one()
    assert password not in dumped and '"password_ciphertext":"v1.' in dumped.replace(" ", "")


async def test_nonprod_other_roles_cannot_see_or_change_the_stored_connection(
    auth: AuthHarness,
    role_sessions: RoleSessions,
    super_admin: SuperAdmin,
    stored_replicas: tuple[StoredReplica, StoredReplica],
) -> None:
    replica, _ = stored_replicas
    admin = await _admin_headers(auth, super_admin)
    reviewer = await role_sessions.reviewer()
    prefix = auth.prefix
    tenant_only = {auth.settings.tenant_header: reviewer.headers[auth.settings.tenant_header]}
    body = {
        "server": "sql-dwh.corp.example.test",
        "user": "dwh_okuyucu",
        "password": f"parola-{uuid4().hex}",
    }
    assert (
        await replica.client.put(f"{prefix}/sql-connection", json=body, headers=admin)
    ).is_success

    as_reviewer = await replica.client.get(f"{prefix}/sql-connection", headers=reviewer.headers)
    denied = [
        await replica.client.request(
            method,
            f"{prefix}{path}",
            json={**body, "trust_server_certificate": True},
            headers=headers,
        )
        for headers in (reviewer.headers,)
        for method, path in (("PUT", "/sql-connection"), ("POST", "/sql-connection/test"))
    ]
    anonymous = [
        await replica.client.request(method, f"{prefix}{path}", json=body, headers=tenant_only)
        for method, path in (
            ("GET", "/sql-connection"),
            ("PUT", "/sql-connection"),
            ("POST", "/sql-connection/test"),
        )
    ]

    # directory-login Decision 14: no other role manages connections; a user gets 403.
    assert as_reviewer.status_code == 403
    assert [response.status_code for response in denied] == [403, 403]
    assert {response.json()["detail"]["code"] for response in denied} == {"forbidden"}
    assert [response.status_code for response in anonymous] == [401, 401, 401]
    assert replica.driver.connection_strings == []
    # The refused requests asked to turn certificate verification off; nothing changed.
    assert replica.store.current().server == "sql-dwh.corp.example.test"
    assert replica.store.current().trust_server_certificate is False


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"server": "sql;Encrypt=no"}, "sql_connection_invalid"),
        ({"user": ""}, "sql_connection_invalid"),
        ({"encrypt": False}, "sql_setting_fixed"),
        ({"encrypt": False, "trust_server_certificate": True}, "sql_setting_fixed"),
        ({"trust_server_certificate": "yes"}, "invalid_request"),
        ({"allowed_databases": ["DWH_Sales"]}, "invalid_request"),
        ({"connection_string": "Server=x"}, "invalid_request"),
    ],
)
async def test_nonprod_save_refuses_values_that_break_the_guarantees(
    auth: AuthHarness,
    super_admin: SuperAdmin,
    stored_replicas: tuple[StoredReplica, StoredReplica],
    change: dict[str, Any],
    code: str,
) -> None:
    replica, _ = stored_replicas
    admin = await _admin_headers(auth, super_admin)
    valid = {
        "server": "sql-dwh.corp.example.test",
        "user": "dwh_okuyucu",
        "password": f"parola-{uuid4().hex}",
    }
    url = f"{auth.prefix}/sql-connection"
    assert (await replica.client.put(url, json=valid, headers=admin)).is_success

    refused = await replica.client.put(url, json=change, headers=admin)
    after = await replica.client.get(url, headers=admin)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == code
    assert valid["password"] not in refused.text
    assert after.json()["trust_server_certificate"] is False
    assert after.json()["server"] == "sql-dwh.corp.example.test" and after.json()["password_set"]


async def test_local_llm_settings_change_in_process_and_hide_the_key(
    role_sessions: RoleSessions,
    integrations: Integrations,
    local_client: AsyncClient,
    captured_logs: list[logging.LogRecord],
) -> None:
    manager = await role_sessions.rule_manager()
    prefix = get_settings().api_prefix

    shown = await local_client.get(f"{prefix}/llm-connection", headers=manager.headers)
    changed = await local_client.put(
        f"{prefix}/llm-connection", json={"model": "yeni-model"}, headers=manager.headers
    )
    public = await local_client.put(
        f"{prefix}/llm-connection",
        json={"base_url": "https://public.example.com/v1"},
        headers=manager.headers,
    )
    credentials = await local_client.put(
        f"{prefix}/llm-connection",
        json={"chat_url": "https://u:p@llm.corp.example.test/v1"},
        headers=manager.headers,
    )

    assert shown.json()["api_key_set"] is True
    assert shown.json()["resolved_chat_url"] == "https://llm.corp.example.test/v1/chat/completions"
    assert changed.status_code == 200 and changed.json()["model"] == "yeni-model"
    assert integrations.llm_store.current().model == "yeni-model"
    assert public.status_code == 422
    assert public.json()["detail"]["code"] == "network_policy_denied"
    assert credentials.status_code == 422
    assert credentials.json()["detail"]["code"] == "llm_url_invalid"
    assert integrations.llm_store.current().base_url == "https://llm.corp.example.test/v1"
    for response in (shown, changed, public, credentials):
        assert LLM_KEY not in response.text
    assert LLM_KEY not in _rendered(captured_logs)
