"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import crypto
from app.config import ANALYSIS_WORKERS, APP_VERSION, CORS_ORIGINS, default_data_dir
from app.db import init_database
from app.routers import (
    analyses,
    assistant,
    connections,
    dashboard,
    exceptions,
    groups,
    rules,
    schedules,
    settings,
)
from app.migrations import upgrade_ruleset
from app.seed import seed
from app.services.analysis_runner import AnalysisRunner, recover_interrupted
from app.services.assistant import AssistantRunner
from app.services.catalog import get_catalog
from app.services.scheduler import Scheduler, recover_runs
from app.services.assistant import recover_interrupted as recover_assistant

logger = logging.getLogger("dwhcr")

_DEFAULT_DETAILS = {
    404: "Kaynak bulunamadı.",
    405: "Bu yöntem desteklenmiyor.",
}

_VALIDATION_MESSAGES = {
    "missing": "Zorunlu alan eksik",
    "literal_error": "Geçersiz değer",
    "enum": "Geçersiz değer",
    "json_invalid": "Geçersiz JSON",
    "string_type": "Metin bekleniyor",
    "int_parsing": "Tam sayı bekleniyor",
    "int_type": "Tam sayı bekleniyor",
    "float_parsing": "Sayı bekleniyor",
    "float_type": "Sayı bekleniyor",
    "bool_parsing": "true/false bekleniyor",
    "bool_type": "true/false bekleniyor",
    "list_type": "Liste bekleniyor",
    "dict_type": "Nesne bekleniyor",
    "model_attributes_type": "Nesne bekleniyor",
    "date_from_datetime_parsing": "Tarih YYYY-MM-DD biçiminde olmalı",
    "date_parsing": "Tarih YYYY-MM-DD biçiminde olmalı",
    "datetime_parsing": "Geçersiz tarih/saat",
    "datetime_from_date_parsing": "Geçersiz tarih/saat",
}


def _validation_detail(error: RequestValidationError) -> str:
    errors = error.errors()
    if not errors:
        return "Geçersiz istek."
    first = errors[0]
    location = ".".join(
        str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path")
    )
    message = _VALIDATION_MESSAGES.get(str(first.get("type")), "Geçersiz değer")
    return f"{message}: {location}" if location else f"{message}."


def create_app(data_dir: Path | None = None) -> FastAPI:
    directory = data_dir or default_data_dir()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        crypto.init_cipher(directory)
        database = init_database(directory)
        with database.session_factory() as session:
            seed(session)
            upgrade_ruleset(session)
            recovered = recover_interrupted(session)
            if recovered:
                logger.info("%s yarım kalan analiz başarısız olarak işaretlendi", recovered)
            recover_assistant(session)
        app.state.runner = AnalysisRunner(database.session_factory, ANALYSIS_WORKERS)
        app.state.assistant = AssistantRunner(database.session_factory)
        app.state.scheduler = Scheduler(
            database.session_factory,
            app.state.runner.submit,
            lambda: app.dependency_overrides.get(get_catalog, get_catalog)(),
        )
        app.state.runner.on_finished = app.state.scheduler.finalize_analysis
        with database.session_factory() as session:
            recover_runs(session)
        app.state.scheduler.start()
        try:
            yield
        finally:
            app.state.scheduler.shutdown()
            app.state.runner.shutdown()
            app.state.assistant.shutdown()
            database.dispose()

    app = FastAPI(title="DWH Code Review", version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if not isinstance(detail, str) or detail in ("Not Found", "Method Not Allowed"):
            detail = _DEFAULT_DETAILS.get(exc.status_code, "İstek işlenemedi.")
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": _validation_detail(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("beklenmeyen hata", exc_info=exc)
        return JSONResponse({"detail": "Beklenmeyen bir sunucu hatası oluştu."}, status_code=500)

    for module in (dashboard, assistant, rules, exceptions, groups, connections, settings,
                   analyses, schedules):
        app.include_router(module.router)
    return app


app = create_app()
