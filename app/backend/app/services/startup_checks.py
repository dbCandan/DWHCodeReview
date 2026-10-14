"""Start-up refusal of unsafe integration settings.

sql-review/PRDs/002-sql-server-connection Requirement 1 (Decision 6 and 11) and
006-llm-connection Requirement 1 and 2: in nonprod the SQL Server connection must be encrypted;
whether the server certificate is verified is the recorded exception of Decision 6 and does not
stop the process. An incomplete connection only leaves the SQL Server area not configured. The LLM
endpoint must be https with a model. In nonprod a configured OpenTelemetry collector endpoint
must be https as well. In every environment configured values must be well formed, the SMTP
relay and recipient domains of 008-scheduled-review-email included. Only setting names are
reported, never values.
"""

import re
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.domain.llm import LlmEndpointInvalid, resolve_chat_url, validate_endpoint_url
from app.domain.models.llm_call import LlmChatApi
from app.infrastructure.sql_server.connection_string import (
    InvalidConnectionValue,
    validate_server,
    validate_user,
)

_DOMAIN = re.compile(
    r"^[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)+$"
)
_SENDER = re.compile(r"^[a-z0-9._%+'\-]{1,64}@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+$")


def _smtp_errors(settings: Settings) -> list[str]:
    errors: list[str] = []
    host = settings.smtp_host.strip()
    if host and (
        any(marker in host for marker in ("://", "/", "@", ":"))
        or any(character.isspace() for character in host)
    ):
        errors.append("DWHCODEREVIEW_SMTP_HOST")
    sender = settings.smtp_sender.strip()
    if sender and not _SENDER.fullmatch(sender.lower()):
        errors.append("DWHCODEREVIEW_SMTP_SENDER")
    if settings.smtp_ca_bundle and not Path(settings.smtp_ca_bundle).is_file():
        errors.append("DWHCODEREVIEW_SMTP_CA_BUNDLE")
    if not all(_DOMAIN.fullmatch(domain) for domain in settings.mail_allowed_domain_list):
        errors.append("DWHCODEREVIEW_MAIL_ALLOWED_DOMAINS")
    return errors


def _url_is_valid(url: str, *, allow_http: bool) -> bool:
    try:
        validate_endpoint_url(url, allow_http=allow_http)
    except LlmEndpointInvalid:
        return False
    return True


def integration_setting_errors(settings: Settings) -> list[str]:
    """Names of settings that stop the process; empty when start-up may continue."""

    errors: list[str] = []
    local = settings.runtime_environment == "local"
    try:
        validate_server(settings.mssql_server)
    except InvalidConnectionValue:
        errors.append("DWHCODEREVIEW_MSSQL_SERVER")
    try:
        validate_user(settings.mssql_user)
    except InvalidConnectionValue:
        errors.append("DWHCODEREVIEW_MSSQL_USER")
    for name, url in (
        ("DWHCODEREVIEW_LLM_BASE_URL", settings.llm_base_url),
        ("DWHCODEREVIEW_LLM_CHAT_URL", settings.llm_chat_url),
    ):
        if url.strip() and not _url_is_valid(url, allow_http=local):
            errors.append(name)
    if settings.llm_ca_bundle and not Path(settings.llm_ca_bundle).is_file():
        errors.append("DWHCODEREVIEW_LLM_CA_BUNDLE")
    errors += _smtp_errors(settings)
    if local:
        return errors

    # Decision 6 holds whether or not the deployment supplies the connection (Decision 11).
    if not settings.mssql_encrypt:
        errors.append("DWHCODEREVIEW_MSSQL_ENCRYPT")
    resolved = resolve_chat_url(
        LlmChatApi(settings.llm_chat_api), settings.llm_base_url, settings.llm_chat_url
    )
    if (
        not settings.llm_base_url.strip()
        or not _url_is_valid(settings.llm_base_url, allow_http=False)
        or resolved is None
        or not _url_is_valid(resolved, allow_http=False)
    ):
        errors.append("DWHCODEREVIEW_LLM_BASE_URL")
    if not settings.llm_model.strip():
        errors.append("DWHCODEREVIEW_LLM_MODEL")
    telemetry_endpoint = settings.otel_exporter_otlp_endpoint
    if telemetry_endpoint and urlsplit(telemetry_endpoint).scheme != "https":
        errors.append("DWHCODEREVIEW_OTEL_EXPORTER_OTLP_ENDPOINT")
    return sorted(set(errors))
