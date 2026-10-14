"""Typed application settings; this is the only application environment boundary."""

import os
import re
from functools import cached_property, lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secret_cipher import decode_encryption_key

_RSA_MINIMUM_KEY_BITS = 2048

RuntimeEnvironment = Literal["local", "nonprod"]
# specs/application-foundation/DOMAIN.md: only this value is the developer machine; every other,
# unknown or unreadable value behaves as nonprod, the closed side.
_LOCAL_ENVIRONMENT_VALUE = "development"
_DEFAULT_LLM_USER_AGENT = "DWHCodeReview-Backend/1.0 (internal SQL review; httpx)"
_SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

JwtSigningKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey
JwtVerificationKey = ec.EllipticCurvePublicKey | rsa.RSAPublicKey

# LangChain's langsmith and langgraph-sdk clients reach the paid hosted LangSmith and LangGraph
# services only through these process variables; technology-profile.yml#llm_orchestration forbids
# those services, so a configured key, endpoint or tracing switch stops startup.
_HOSTED_LLM_SERVICE_VARIABLES = (
    "LANGSMITH_API_KEY",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_RUNS_ENDPOINTS",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_ENDPOINT",
    "LANGGRAPH_API_KEY",
)
_HOSTED_LLM_TRACING_VARIABLES = (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
)


class MigrationSettings(BaseSettings):
    """Least-privilege configuration for the schema migration process."""

    model_config = SettingsConfigDict(
        env_prefix="DWHCODEREVIEW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Validation errors would otherwise echo raw inputs such as the signing key or database
        # credentials into startup logs.
        hide_input_in_errors=True,
    )

    # Required, like in Settings: the connection carries credentials, so no default exists.
    database_url: str

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value


class Settings(BaseSettings):
    """Configuration loaded from prefixed environment variables and an optional .env."""

    model_config = SettingsConfigDict(
        env_prefix="DWHCODEREVIEW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Validation errors would otherwise echo raw inputs such as the signing key or database
        # credentials into startup logs.
        hide_input_in_errors=True,
    )

    # Mapped by runtime_environment: "development" is local, everything else nonprod.
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    project_name: str = "dwhcodereview"

    api_prefix: str = "/api/dwhcodereview/v1"
    tenant_header: str = "x-tenant-id"
    cors_allow_origins: str = "http://localhost:3000,http://localhost:8080"
    # The exact browser origin of the application; cookie-authenticated session endpoints accept a
    # state-changing request only when its Origin header equals this value.
    public_origin: str = "http://localhost:8080"
    # Comma-separated addresses or networks of the ingress controller. X-Forwarded-For is honoured
    # only on a request whose peer is inside one of them; otherwise the header is ignored.
    trusted_proxy_cidrs: str = ""

    # Required in every process because the connection carries credentials. Local Compose builds it
    # from the disposable password of scripts/dev-secrets.sh; with the in-chart database the
    # deployment supplies the DML-only runtime connection through the <release>-database Secret.
    database_url: str

    # Required in every process. rules/58 fixes the asymmetric RS256/ES256 profile: the PEM private
    # key signs, its derived public key verifies. Local Compose receives a disposable development
    # key from scripts/dev-secrets.sh; a missing key in the deployment Secret stops startup instead
    # of enabling a known signing key.
    jwt_private_key: SecretStr
    jwt_algorithm: Literal["ES256", "RS256"] = "ES256"
    jwt_issuer: str = "dwhcodereview"
    jwt_audience: str = "dwhcodereview-api"
    access_token_expire_minutes: int = 15
    refresh_session_idle_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    refresh_session_absolute_hours: Annotated[int, Field(ge=1, le=24)] = 8
    # Nonprod always limits local password login to the super admin; this switch can only add the
    # same limit to the local environment, never lift it.
    local_login_super_admin_only_enforced: bool = False

    # Login-only Active Directory over verified LDAPS. None of these values is a secret: the user
    # binds with their own credentials and no service account exists.
    directory_enabled: bool = False
    directory_host: str = ""
    directory_port: Annotated[int, Field(ge=1, le=65535)] = 636
    directory_base_dn: str = ""
    directory_upn_suffix: str = ""
    directory_ca_bundle_path: str = ""
    # Lowers only the cipher security level; CA and host-name verification always stay on.
    directory_tls_legacy_compatibility: bool = False
    directory_connect_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 5
    directory_read_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 10

    # Read-only SQL Server catalog connection (sql-review 002-sql-server-connection).
    mssql_server: str = ""
    mssql_port: Annotated[int, Field(ge=1, le=65535)] = 1433
    mssql_user: str = ""
    mssql_password: SecretStr | None = None
    mssql_encrypt: bool = True
    mssql_trust_server_certificate: bool = False
    mssql_login_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 15
    mssql_query_timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    mssql_max_concurrency: Annotated[int, Field(ge=1, le=16)] = 4
    # Encrypts the SQL Server password the super admin saves in nonprod (sql-review 002 Requirement
    # 10): standard base64 of 32 random bytes. The deployment hook generates it once into the
    # runtime Secret; without it the connection cannot be saved from the interface.
    settings_encryption_key: SecretStr | None = None

    # Approved internal LLM endpoint (sql-review 006-llm-connection).
    llm_chat_api: Literal["openai", "api_v1_chat"] = "api_v1_chat"
    llm_base_url: str = ""
    llm_chat_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    # Empty uses the image's system trust store, which carries the organization root CA.
    llm_ca_bundle: str = ""
    llm_read_timeout_seconds: Annotated[int, Field(ge=60, le=3600)] = 900
    llm_request_retries: Annotated[int, Field(ge=0, le=5)] = 2
    llm_max_concurrent_calls: Annotated[int, Field(ge=1, le=32)] = 6
    llm_process_max_concurrent_calls: Annotated[int, Field(ge=1, le=128)] = 12
    llm_user_agent: str = _DEFAULT_LLM_USER_AGENT

    # Review runs (sql-review 003-object-review, 004-script-review, 005-review-history-export).
    review_max_sql_chars: Annotated[int, Field(ge=1, le=1_000_000)] = 120_000
    review_two_part_threshold_chars: Annotated[int, Field(ge=1, le=1_000_000)] = 45_000
    review_rate_limit_window_seconds: Annotated[int, Field(ge=1, le=3600)] = 60
    review_rate_limit_max_requests: Annotated[int, Field(ge=1, le=10_000)] = 30
    review_history_retention_days: Annotated[int, Field(ge=1, le=365)] = 90

    # Scheduled reviews (sql-review 008-scheduled-review-email). The scheduler is a module of
    # this process (Decision 2), off unless enabled; the chart gains no workload for it.
    scheduler_enabled: bool = False
    scheduler_tick_seconds: Annotated[int, Field(ge=5, le=3600)] = 60
    # Corporate SMTP relay of the summary e-mail. Without host or sender the scheduler still
    # runs and stores reports; the e-mail is then recorded as not configured. Only verified TLS
    # is used (STARTTLS or implicit TLS); empty CA bundle uses the image's system trust store.
    # The password is a runtime secret only.
    smtp_host: str = ""
    smtp_port: Annotated[int, Field(ge=1, le=65535)] = 587
    smtp_security: Literal["starttls", "tls"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_sender: str = ""
    smtp_ca_bundle: str = ""
    smtp_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 30
    # Comma-separated corporate e-mail domains a recipient may use (Decision 5); empty
    # refuses every recipient.
    mail_allowed_domains: str = ""

    # OpenTelemetry traces and metrics over OTLP/gRPC (app/core/telemetry.py). Empty disables
    # export; the local observability Compose overlay points it at its collector. Only these typed
    # settings configure telemetry: a process variable starting with OTEL_ stops startup.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "dwhcodereview-backend"
    otel_traces_sample_ratio: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    otel_metric_export_interval_seconds: Annotated[int, Field(ge=5, le=300)] = 60

    # The local super admin (application-foundation 001 Requirement 14). The operator command
    # creates or resets this account; when the deployment Secret carries the start-up password
    # the backend start creates it once and never changes an existing account. The command reads
    # its own password only from its prompt or standard input.
    bootstrap_super_admin_email: str = "admin@example.invalid"
    bootstrap_super_admin_username: str = "super-admin"
    bootstrap_super_admin_password: SecretStr | None = None

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("/"):
            raise ValueError("api_prefix must begin with '/'")
        return normalized

    @field_validator("tenant_header")
    @classmethod
    def validate_tenant_header(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or "_" in normalized:
            raise ValueError("tenant_header must be a non-empty HTTP header name using hyphens")
        return normalized

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value

    @field_validator("access_token_expire_minutes")
    @classmethod
    def validate_access_token_expiry(cls, value: int) -> int:
        if not 1 <= value <= 1440:
            raise ValueError("access_token_expire_minutes must be between 1 and 1440")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise ValueError("public_origin must be an exact scheme://host[:port] origin")
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        try:
            _parse_networks(value)
        except ValueError:
            raise ValueError("trusted_proxy_cidrs must list IP addresses or networks") from None
        return value

    @field_validator(
        "mssql_password",
        "llm_api_key",
        "bootstrap_super_admin_password",
        "settings_encryption_key",
        mode="before",
    )
    @classmethod
    def empty_optional_secret_is_absent(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("settings_encryption_key")
    @classmethod
    def validate_settings_encryption_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                decode_encryption_key(value.get_secret_value())
            except ValueError:
                raise ValueError("settings_encryption_key must be base64 of 32 bytes") from None
        return value

    @field_validator("otel_exporter_otlp_endpoint")
    @classmethod
    def validate_otel_exporter_otlp_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            return endpoint
        parts = urlsplit(endpoint)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "otel_exporter_otlp_endpoint must be an http(s)://host[:port] collector address"
            )
        return endpoint

    @field_validator("otel_service_name")
    @classmethod
    def validate_otel_service_name(cls, value: str) -> str:
        if _SERVICE_NAME_RE.fullmatch(value) is None:
            raise ValueError("otel_service_name must be a lowercase name of letters, digits and -")
        return value

    @field_validator("directory_host")
    @classmethod
    def validate_directory_host(cls, value: str) -> str:
        host = value.strip().lower()
        if not host:
            return host
        if (
            any(marker in host for marker in ("://", "/", ":", "@"))
            or any(character.isspace() for character in host)
            or "." not in host.strip(".")
            or _is_ip_address(host)
        ):
            raise ValueError(
                "directory_host must be the fully qualified host name in the server certificate"
            )
        return host

    @field_validator("directory_upn_suffix")
    @classmethod
    def validate_directory_upn_suffix(cls, value: str) -> str:
        suffix = value.strip().casefold()
        if suffix and (
            suffix.startswith("@")
            or "." not in suffix.strip(".")
            or any(character.isspace() for character in suffix)
        ):
            raise ValueError("directory_upn_suffix must be a DNS suffix without '@'")
        return suffix

    @model_validator(mode="after")
    def require_complete_directory_when_enabled(self) -> "Settings":
        if not self.directory_enabled:
            return self
        required = {
            "directory_host": self.directory_host,
            "directory_base_dn": self.directory_base_dn,
            "directory_upn_suffix": self.directory_upn_suffix,
            "directory_ca_bundle_path": self.directory_ca_bundle_path,
        }
        missing = sorted(name for name, value in required.items() if not value.strip())
        if missing:
            raise ValueError(
                "the directory is enabled but required settings are blank: " + ", ".join(missing)
            )
        bundle = Path(self.directory_ca_bundle_path)
        try:
            with bundle.open("rb") as handle:
                handle.read(1)
        except OSError:
            raise ValueError(
                "directory_ca_bundle_path must reference a readable CA bundle file"
            ) from None
        return self

    @property
    def runtime_environment(self) -> RuntimeEnvironment:
        if self.environment.strip().lower() == _LOCAL_ENVIRONMENT_VALUE:
            return "local"
        return "nonprod"

    @property
    def local_login_super_admin_only(self) -> bool:
        return self.runtime_environment == "nonprod" or self.local_login_super_admin_only_enforced

    @property
    def mail_allowed_domain_list(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    domain.strip().lower()
                    for domain in self.mail_allowed_domains.split(",")
                    if domain.strip()
                }
            )
        )

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_sender.strip())

    @property
    def mssql_connection_complete(self) -> bool:
        """True when the deployment itself supplies server, user and password."""

        return bool(
            self.mssql_server.strip()
            and self.mssql_user.strip()
            and self.mssql_password is not None
        )

    @property
    def trusted_proxy_networks(self) -> tuple[IPv4Network | IPv6Network, ...]:
        return _parse_networks(self.trusted_proxy_cidrs)

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @cached_property
    def jwt_signing_key(self) -> JwtSigningKey:
        return _load_signing_key(self.jwt_private_key)

    @cached_property
    def jwt_verification_key(self) -> JwtVerificationKey:
        return self.jwt_signing_key.public_key()

    @model_validator(mode="after")
    def require_key_matching_the_algorithm(self) -> "Settings":
        key = self.jwt_signing_key
        if self.jwt_algorithm == "ES256":
            if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
                raise ValueError("jwt_algorithm ES256 requires a P-256 elliptic-curve private key")
        elif not isinstance(key, rsa.RSAPrivateKey) or key.key_size < _RSA_MINIMUM_KEY_BITS:
            raise ValueError(
                f"jwt_algorithm RS256 requires an RSA private key of at least "
                f"{_RSA_MINIMUM_KEY_BITS} bits"
            )
        return self

    @model_validator(mode="after")
    def reject_hosted_llm_services(self) -> "Settings":
        configured = [name for name in _HOSTED_LLM_SERVICE_VARIABLES if os.environ.get(name)]
        configured += [
            name
            for name in _HOSTED_LLM_TRACING_VARIABLES
            if os.environ.get(name, "").strip().lower() not in {"", "0", "false"}
        ]
        if configured:
            raise ValueError(
                "hosted LangSmith and LangGraph services are not allowed: "
                + ", ".join(sorted(configured))
            )
        return self

    @model_validator(mode="after")
    def reject_untyped_telemetry_configuration(self) -> "Settings":
        # The OpenTelemetry SDK would otherwise read exporter headers, endpoints, certificates and
        # resource attributes from OTEL_* process variables behind the typed settings.
        configured = sorted(name for name in os.environ if name.upper().startswith("OTEL_"))
        if configured:
            raise ValueError(
                "telemetry is configured only through DWHCODEREVIEW_OTEL_* settings: "
                + ", ".join(configured)
            )
        return self


def _parse_networks(value: str) -> tuple[IPv4Network | IPv6Network, ...]:
    return tuple(
        ip_network(item.strip(), strict=False) for item in value.split(",") if item.strip()
    )


def _is_ip_address(value: str) -> bool:
    try:
        ip_address(value.strip("[]"))
    except ValueError:
        return False
    return True


def _load_signing_key(value: SecretStr) -> JwtSigningKey:
    try:
        key = load_pem_private_key(value.get_secret_value().encode("utf-8"), password=None)
    except (TypeError, ValueError, UnsupportedAlgorithm):
        raise ValueError("jwt_private_key must be an unencrypted PEM private key") from None
    if isinstance(key, (ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey)):
        return key
    raise ValueError("jwt_private_key must be an elliptic-curve or RSA private key")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings view."""

    # BaseSettings resolves the required secret from its configured environment source at runtime;
    # static type checkers cannot model that source injection.
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_migration_settings() -> MigrationSettings:
    """Return the DB-only settings view used by Alembic jobs."""

    # As in get_settings, the required database URL comes from the environment source at runtime.
    return MigrationSettings()  # type: ignore[call-arg]
