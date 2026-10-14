"""Start-up refusal of unsafe integration settings and environment-dependent routes.

sql-review/PRDs/002-sql-server-connection Requirement 1 and 5 (Decision 5, 6, 10, 11) and
006-llm-connection Requirement 1, 2 and 13 (Acceptance 1); the SMTP relay and recipient
domains of 008-scheduled-review-email.
"""

import base64
import os
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.request_context import RequestContext
from app.domain.sql_server import SqlServerConnectionConfig
from app.main import UnsafeIntegrationSettings, create_application
from app.services.sql_connection_service import (
    SqlConnectionService,
    SqlConnectionStore,
    initial_sql_connection,
)
from app.services.startup_checks import integration_setting_errors

pytestmark = pytest.mark.unit

_KEPT_VARIABLES = {"DWHCODEREVIEW_JWT_PRIVATE_KEY", "DWHCODEREVIEW_DATABASE_URL"}
_KEY = base64.b64encode(os.urandom(32)).decode()
NONPROD_OK: dict[str, Any] = {
    "environment": "staging",
    "mssql_server": "sql-dwh.corp.example.test",
    "mssql_user": "dwh_okuyucu",
    "mssql_password": "yalniz-test-parolasi",
    "mssql_encrypt": True,
    "mssql_trust_server_certificate": False,
    "llm_chat_api": "openai",
    "llm_base_url": "https://llm.corp.example.test/inference/model/v1",
    "llm_model": "/data/models--Test",
}


@pytest.fixture(autouse=True)
def _defaults_only(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("DWHCODEREVIEW_") and name not in _KEPT_VARIABLES:
            monkeypatch.delenv(name)


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)


def test_complete_nonprod_settings_start() -> None:
    assert integration_setting_errors(_settings(**NONPROD_OK)) == []


def test_empty_local_settings_start_unconfigured() -> None:
    assert integration_setting_errors(_settings(environment="development")) == []


_SQL_SERVER_CONNECTION = {
    "mssql_server": "",
    "mssql_user": "",
    "mssql_password": "",
}


@pytest.mark.parametrize(
    "blank",
    [
        tuple(_SQL_SERVER_CONNECTION),
        ("mssql_server", "mssql_user"),
        ("mssql_user", "mssql_password"),
        ("mssql_password",),
        ("mssql_server",),
    ],
)
def test_nonprod_without_a_complete_sql_server_connection_starts_unconfigured(
    blank: tuple[str, ...],
) -> None:
    # Owner decision 2026-09-27: nonprod starts without operator-supplied SQL Server credentials
    # or address; the SQL Server area then reports "not configured".
    settings = _settings(**{**NONPROD_OK, **{name: "" for name in blank}})
    assert integration_setting_errors(settings) == []


def test_a_complete_nonprod_connection_needs_no_database_list() -> None:
    # Decision 5: the account's permissions decide what can be read; no list is configured, and a
    # leftover variable of the removed setting is not a setting any more.
    assert "mssql_allowed_databases" not in Settings.model_fields
    assert integration_setting_errors(_settings(**NONPROD_OK)) == []
    settings = Settings(_env_file=None, **NONPROD_OK, mssql_allowed_databases="master")
    assert integration_setting_errors(settings) == []


def test_nonprod_may_start_without_certificate_verification_but_never_unencrypted() -> None:
    # Decision 6 and its recorded exception: the certificate option does not stop the process in
    # either nonprod path; encryption always does.
    trusting = _settings(**{**NONPROD_OK, "mssql_trust_server_certificate": True})
    assert integration_setting_errors(trusting) == []
    assert initial_sql_connection(trusting).trust_server_certificate is True
    unencrypted = {**NONPROD_OK, "mssql_trust_server_certificate": True, "mssql_encrypt": False}
    assert integration_setting_errors(_settings(**unencrypted)) == ["DWHCODEREVIEW_MSSQL_ENCRYPT"]


async def test_nonprod_without_sql_server_credentials_reports_not_configured() -> None:
    settings = _settings(**{**NONPROD_OK, **_SQL_SERVER_CONNECTION})
    application = create_application(settings)
    async with application.router.lifespan_context(application):
        view = await SqlConnectionService(
            settings=settings,
            store=SqlConnectionStore(initial_sql_connection(settings)),
            probe=_UnusedProbe(),
        ).view(RequestContext(is_super_admin=True))
    assert (view.environment, view.editable, view.configured) == ("nonprod", False, False)
    assert view.managed_by == "deployment"


class _UnusedProbe:
    async def probe(
        self, config: SqlServerConnectionConfig
    ) -> list[str]:  # pragma: no cover - never called
        raise AssertionError("a deployment-managed nonprod never probes")


@pytest.mark.parametrize(
    ("change", "setting"),
    [
        ({"mssql_encrypt": False}, "DWHCODEREVIEW_MSSQL_ENCRYPT"),
        ({"llm_base_url": ""}, "DWHCODEREVIEW_LLM_BASE_URL"),
        ({"llm_base_url": "http://llm.corp.example.test/v1"}, "DWHCODEREVIEW_LLM_BASE_URL"),
        ({"llm_chat_url": "http://llm.corp.example.test/chat"}, "DWHCODEREVIEW_LLM_CHAT_URL"),
        ({"llm_model": " "}, "DWHCODEREVIEW_LLM_MODEL"),
        (
            {"otel_exporter_otlp_endpoint": "http://otel-collector:4317"},
            "DWHCODEREVIEW_OTEL_EXPORTER_OTLP_ENDPOINT",
        ),
        ({"environment": "unknown-value", "mssql_encrypt": False}, "DWHCODEREVIEW_MSSQL_ENCRYPT"),
    ],
)
def test_unsafe_nonprod_settings_stop_start_up(change: dict[str, Any], setting: str) -> None:
    errors = integration_setting_errors(_settings(**{**NONPROD_OK, **change}))
    assert setting in errors


@pytest.mark.parametrize(
    ("change", "setting"),
    [
        ({"mssql_server": "sql;Encrypt=no"}, "DWHCODEREVIEW_MSSQL_SERVER"),
        ({"mssql_user": "okuyucu\n"}, "DWHCODEREVIEW_MSSQL_USER"),
        ({"llm_base_url": "http://user:pass@llm.local/v1"}, "DWHCODEREVIEW_LLM_BASE_URL"),
        ({"llm_chat_url": "https://llm.local/v1#x"}, "DWHCODEREVIEW_LLM_CHAT_URL"),
        ({"llm_base_url": "ftp://llm.local/v1"}, "DWHCODEREVIEW_LLM_BASE_URL"),
        ({"llm_ca_bundle": "/nonexistent/ca.pem"}, "DWHCODEREVIEW_LLM_CA_BUNDLE"),
        ({"smtp_host": "smtp://relay.corp.example.test"}, "DWHCODEREVIEW_SMTP_HOST"),
        ({"smtp_host": "relay.corp.example.test:587"}, "DWHCODEREVIEW_SMTP_HOST"),
        ({"smtp_sender": "ReviewX <reviewx@corp.example.test>"}, "DWHCODEREVIEW_SMTP_SENDER"),
        ({"smtp_ca_bundle": "/nonexistent/ca.pem"}, "DWHCODEREVIEW_SMTP_CA_BUNDLE"),
        (
            {"mail_allowed_domains": "corp.example.test, @dis.com"},
            "DWHCODEREVIEW_MAIL_ALLOWED_DOMAINS",
        ),
    ],
)
def test_malformed_values_stop_start_up_in_every_environment(
    change: dict[str, Any], setting: str
) -> None:
    assert setting in integration_setting_errors(_settings(environment="development", **change))
    assert setting in integration_setting_errors(_settings(**{**NONPROD_OK, **change}))


def test_http_is_accepted_only_locally() -> None:
    url = {"llm_base_url": "http://127.0.0.1:1234/v1"}
    assert integration_setting_errors(_settings(environment="development", **url)) == []


def test_a_plaintext_collector_is_accepted_only_locally() -> None:
    collector = {"otel_exporter_otlp_endpoint": "http://otel-collector:4317"}
    assert integration_setting_errors(_settings(environment="development", **collector)) == []
    tls = {"otel_exporter_otlp_endpoint": "https://otel-collector.corp.example.test:4317"}
    assert integration_setting_errors(_settings(**{**NONPROD_OK, **tls})) == []


async def test_the_process_refuses_to_start_with_unsafe_settings() -> None:
    application = create_application(_settings(**{**NONPROD_OK, "mssql_encrypt": False}))
    with pytest.raises(UnsafeIntegrationSettings) as raised:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - start-up must not reach the body
    assert "DWHCODEREVIEW_MSSQL_ENCRYPT" in str(raised.value)
    assert NONPROD_OK["mssql_password"] not in str(raised.value)


def _routes(application: Any) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in application.openapi()["paths"].items()
        for method in operations
    }


def test_write_and_test_endpoints_exist_only_where_the_connection_is_editable() -> None:
    prefix = _settings().api_prefix
    sql_writes = {("PUT", f"{prefix}/sql-connection"), ("POST", f"{prefix}/sql-connection/test")}
    local_only = sql_writes | {("PUT", f"{prefix}/llm-connection")}
    readable = {
        ("GET", f"{prefix}/sql-connection"),
        ("GET", f"{prefix}/llm-connection"),
        ("GET", f"{prefix}/llm-calls"),
    }
    local = _routes(create_application(_settings(environment="development")))
    for environment in ("staging", "unknown-value"):
        nonprod = _routes(
            create_application(_settings(**{**NONPROD_OK, "environment": environment}))
        )
        assert not local_only & nonprod
        assert readable <= nonprod
        # 002 Requirement 5: without a complete deployment connection and with the encryption key
        # the SQL connection endpoints exist for the super admin; the LLM endpoint never does.
        stored = {**NONPROD_OK, **_SQL_SERVER_CONNECTION, "environment": environment}
        with_key = _routes(create_application(_settings(**stored, settings_encryption_key=_KEY)))
        without_key = _routes(create_application(_settings(**stored)))
        assert local_only & with_key == sql_writes
        assert not local_only & without_key
    assert local_only | readable <= local


@pytest.mark.parametrize(
    "values",
    [
        NONPROD_OK,
        {**NONPROD_OK, "settings_encryption_key": _KEY},
        {**NONPROD_OK, **_SQL_SERVER_CONNECTION},
    ],
    ids=["deployment-connection", "deployment-connection-and-key", "no-connection-no-key"],
)
async def test_nonprod_write_requests_find_no_route(values: dict[str, Any]) -> None:
    settings = _settings(**values)
    application = create_application(settings)
    headers = {settings.tenant_header: "00000000-0000-4000-8000-000000000010"}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as client:
        for method, path in (
            ("PUT", "/sql-connection"),
            ("POST", "/sql-connection/test"),
            ("PUT", "/llm-connection"),
        ):
            response = await client.request(
                method, f"{settings.api_prefix}{path}", json={}, headers=headers
            )
            assert response.status_code == 404, path


async def test_a_stored_nonprod_asks_for_a_session_before_it_saves_or_tests() -> None:
    settings = _settings(
        **{**NONPROD_OK, **_SQL_SERVER_CONNECTION, "settings_encryption_key": _KEY}
    )
    application = create_application(settings)
    headers = {settings.tenant_header: "00000000-0000-4000-8000-000000000010"}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as client:
        for method, path in (("PUT", "/sql-connection"), ("POST", "/sql-connection/test")):
            response = await client.request(
                method, f"{settings.api_prefix}{path}", json={}, headers=headers
            )
            assert response.status_code == 401, path
        llm = await client.put(f"{settings.api_prefix}/llm-connection", json={}, headers=headers)
        assert llm.status_code == 404


def test_a_well_formed_smtp_relay_starts_and_counts_as_configured() -> None:
    relay = {
        "smtp_host": "relay.corp.example.test",
        "smtp_sender": "reviewx@corp.example.test",
        "mail_allowed_domains": " Corp.Example.Test ,corp.example.test,diger.example.test",
    }
    settings = _settings(**{**NONPROD_OK, **relay})
    assert integration_setting_errors(settings) == []
    assert settings.smtp_configured
    assert settings.mail_allowed_domain_list == ("corp.example.test", "diger.example.test")


def test_without_host_or_sender_the_e_mail_is_not_configured_and_start_up_continues() -> None:
    settings = _settings(**{**NONPROD_OK, "smtp_host": "relay.corp.example.test"})
    assert integration_setting_errors(settings) == []
    assert not settings.smtp_configured
    assert not _settings(**NONPROD_OK).scheduler_enabled
