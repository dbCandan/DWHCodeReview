"""FastAPI application factory for the neutral platform baseline."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.integrations import close_integrations, get_review_registry
from app.api.router import (
    local_environment_router,
    router,
    stored_sql_connection_router,
)
from app.api.scheduled_reviews.runner import build_scheduler
from app.core.config import Settings, get_settings
from app.core.errors import ApplicationError, application_error_handler
from app.core.logging import configure_logging, log_event
from app.core.telemetry import configure_telemetry, instrument_engine
from app.db.readiness import packaged_schema
from app.db.session import async_session_factory, engine
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.tenant_context import TenantContextMiddleware
from app.services.llm_call_summary_service import run_llm_call_retention
from app.services.review_history_service import run_review_history_retention
from app.services.review_run_service import interrupt_stale_runs
from app.services.sql_connection_service import SqlConnectionMode, sql_connection_mode
from app.services.startup_checks import integration_setting_errors
from app.services.super_admin_service import run_super_admin_bootstrap

logger = logging.getLogger("app.startup")


class UnsafeIntegrationSettings(RuntimeError):
    """The process refuses to start; the message names settings, never their values."""


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # application-foundation 002 Requirement 4: readiness compares the database with the
        # migration head shipped in this image; reading it here stops an image without its
        # migrations before it serves.
        packaged_schema()
        invalid = integration_setting_errors(settings)
        if invalid:
            log_event(logger, "startup.integration_settings_invalid", settings=",".join(invalid))
            raise UnsafeIntegrationSettings("unsafe integration settings: " + ", ".join(invalid))
        mode = sql_connection_mode(settings)
        log_event(
            logger,
            "startup.sql_connection_mode",
            mode=mode.value,
            # In the stored mode the saved connection decides; sql_connection.updated reports it.
            trust_server_certificate=(
                None
                if mode is SqlConnectionMode.STORED
                else settings.mssql_trust_server_certificate
            ),
        )
        telemetry_export = configure_telemetry(settings)
        instrument_engine(engine.sync_engine)
        # sql-review 003 Requirement 16: runs this process never finished were cut off.
        await interrupt_stale_runs(async_session_factory)
        background = [
            asyncio.create_task(run_llm_call_retention(async_session_factory)),
            asyncio.create_task(
                run_review_history_retention(
                    async_session_factory,
                    retention_days=settings.review_history_retention_days,
                )
            ),
            # application-foundation 001 Requirement 14: creates the configured super admin once;
            # it retries in the background while a first installation is still migrating.
            asyncio.create_task(run_super_admin_bootstrap(async_session_factory, settings)),
        ]
        # sql-review 008 Decision 2: the scheduler is a module of this process, off by default.
        if settings.scheduler_enabled:
            background.append(asyncio.create_task(build_scheduler(settings).run_forever()))
        log_event(logger, "startup.scheduler", enabled=settings.scheduler_enabled)
        try:
            yield
        finally:
            await get_review_registry().shutdown()
            for task in background:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            close_integrations()
            await engine.dispose()
            if telemetry_export is not None:
                telemetry_export.shutdown()

    return lifespan


def create_application(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        description="Platform API for dwhcodereview",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=_lifespan(settings),
    )
    # Register tenant context first; Starlette makes the later CORS middleware outermost,
    # so even authorization failures receive the browser-facing CORS headers.
    application.add_middleware(TenantContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["WWW-Authenticate", "X-Request-ID"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_exception_handler(ApplicationError, application_error_handler)
    application.include_router(router)
    if settings.runtime_environment == "local":
        application.include_router(local_environment_router(settings.api_prefix))
    elif sql_connection_mode(settings) is SqlConnectionMode.STORED:
        application.include_router(stored_sql_connection_router(settings.api_prefix))
    return application


app = create_application()
