"""Catalog lists and review runs with live progress (sql-review 003 and 004 API contracts).

Every endpoint needs a signed-in reviewer or rule manager. The streaming endpoints check the
token, role, request, rate limit and published rule set before the first byte; failures are
ordinary JSON error envelopes. After that the body is ``text/event-stream``: each event is one
``data:`` line and a ``: ping`` comment follows every 15 seconds of silence. However the response
ends (complete, error, stop button or lost connection), the run stops with it. No token, SQL or
object text is ever part of a URL.
"""

from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import Field, RootModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.api.auth.dependencies import CurrentContext, require_any_role
from app.api.integrations import (
    get_llm_chat,
    get_llm_connection_store,
    get_review_rate_limiter,
    get_review_registry,
    get_sql_catalog,
)
from app.api.validation import envelope_validation_route
from app.core.config import Settings, get_settings
from app.core.review_throttle import ReviewRateLimiter
from app.db.session import async_session_factory, get_db
from app.domain.llm import LlmChatPort, LlmEndpoint
from app.domain.models.role import ROLE_REVIEWER
from app.domain.review import ObjectSelection
from app.domain.sql_server import SqlCatalogPort
from app.schemas.reviews.contracts import (
    CatalogObjectPage,
    DatabasePage,
    ObjectReviewRequest,
    ScriptReviewRequest,
)
from app.schemas.reviews.events import ReviewEvent
from app.services.llm_connection_service import LlmConnectionStore
from app.services.review_catalog_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ReviewCatalogService,
)
from app.services.review_engine import TextReviewer
from app.services.review_run_service import (
    ReviewExecution,
    ReviewRunRegistry,
    ReviewRunService,
    ReviewRuntime,
    review_text_limit,
)

_ERRORS: dict[int | str, dict[str, str]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Rol yetkisi yok veya veritabanı izinli değil"},
}
_REVIEW_ERRORS: dict[int | str, dict[str, object]] = {
    200: {
        "model": None,
        "description": "Canlı ilerleme: her olay tek `data:` satırında bir JSON nesnesidir.",
    },
    409: {"description": "Yayımlanmış kural yok"},
    422: {"description": "Geçersiz istek"},
    429: {"description": "Çok fazla inceleme başlatıldı"},
    503: {"description": "LLM bağlantısı yapılandırılmamış"},
}
_CATALOG_ERRORS: dict[int | str, dict[str, object]] = {
    422: {"description": "Geçersiz değer"},
    503: {"description": "SQL Server bağlantısı yok veya sunucu hatası"},
    504: {"description": "SQL Server zaman aşımı"},
}

ReviewRoles = [Depends(require_any_role(ROLE_REVIEWER))]

catalog_router = APIRouter(
    tags=["catalog"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    dependencies=ReviewRoles,
    responses=_ERRORS,
)
router = APIRouter(
    tags=["reviews"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    dependencies=ReviewRoles,
    responses=_ERRORS,
)

TypeCode = Literal["P", "V", "FN", "IF", "TF", "SF"]
KEEPALIVE_SECONDS = 15.0


class ReviewStreamEvent(RootModel[Annotated[ReviewEvent, Field(discriminator="phase")]]):
    """One event of the stream: the JSON on a single ``data:`` line, named by ``phase``."""


_REVIEW_ERRORS[200]["model"] = ReviewStreamEvent


class EventStreamContract(JSONResponse):
    """OpenAPI marker only: documents ``ReviewStreamEvent`` under ``text/event-stream``.

    The stream routes always return ``ReviewEventStream``; FastAPI uses the declared response
    class only to describe the contract.
    """

    media_type = "text/event-stream"


class ReviewEventStream(StreamingResponse):
    """``text/event-stream`` whose run stops whenever the response ends, however it ends."""

    media_type = "text/event-stream"

    def __init__(self, execution: ReviewExecution) -> None:
        super().__init__(
            _sse(execution),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self._execution = execution

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Requirement 15: a stop, a lost connection or a server shutdown ends the run.
            self._execution.cancel()


async def _sse(execution: ReviewExecution) -> AsyncIterator[str]:
    async for event in execution.events(KEEPALIVE_SECONDS):
        if event is None:
            yield ": ping\n\n"
        else:
            yield f"data: {event.model_dump_json(by_alias=True)}\n\n"


def get_catalog_service(
    catalog: Annotated[SqlCatalogPort, Depends(get_sql_catalog)],
) -> ReviewCatalogService:
    return ReviewCatalogService(catalog)


def get_review_runtime(
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[LlmChatPort, Depends(get_llm_chat)],
    registry: Annotated[ReviewRunRegistry, Depends(get_review_registry)],
) -> ReviewRuntime:
    return ReviewRuntime(
        llm=llm,
        session_factory=async_session_factory,
        registry=registry,
        reviewer=TextReviewer(two_part_threshold_chars=settings.review_two_part_threshold_chars),
        text_limit=review_text_limit(settings),
        objects_in_flight=settings.llm_max_concurrent_calls,
    )


def get_llm_endpoint_source(
    store: Annotated[LlmConnectionStore, Depends(get_llm_connection_store)],
) -> Callable[[], LlmEndpoint | None]:
    return store.endpoint


def get_object_review_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: Annotated[ReviewRuntime, Depends(get_review_runtime)],
    endpoint: Annotated[Callable[[], LlmEndpoint | None], Depends(get_llm_endpoint_source)],
    limiter: Annotated[ReviewRateLimiter, Depends(get_review_rate_limiter)],
    catalog: Annotated[SqlCatalogPort, Depends(get_sql_catalog)],
) -> ReviewRunService:
    return ReviewRunService(
        session,
        settings=settings,
        runtime=runtime,
        llm_endpoint=endpoint,
        limiter=limiter,
        catalog=catalog,
    )


def get_script_review_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: Annotated[ReviewRuntime, Depends(get_review_runtime)],
    endpoint: Annotated[Callable[[], LlmEndpoint | None], Depends(get_llm_endpoint_source)],
    limiter: Annotated[ReviewRateLimiter, Depends(get_review_rate_limiter)],
) -> ReviewRunService:
    # 004 Requirement 12: the script review never depends on the SQL Server adapter.
    return ReviewRunService(
        session,
        settings=settings,
        runtime=runtime,
        llm_endpoint=endpoint,
        limiter=limiter,
    )


CatalogService = Annotated[ReviewCatalogService, Depends(get_catalog_service)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


@catalog_router.get("/databases", response_model=DatabasePage, responses=_CATALOG_ERRORS)
async def list_databases(
    service: CatalogService, page: Page = 1, page_size: PageSize = DEFAULT_PAGE_SIZE
) -> DatabasePage:
    """Online databases the account can access, without system databases (Requirement 1)."""

    return await service.databases(page=page, page_size=page_size)


@catalog_router.get(
    "/databases/{database}/objects",
    response_model=CatalogObjectPage,
    responses=_CATALOG_ERRORS,
)
async def list_objects(
    service: CatalogService,
    database: Annotated[str, Path(min_length=1, max_length=128)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    type: Annotated[TypeCode | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    page: Page = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
) -> CatalogObjectPage:
    """User procedures, views and functions; every filter applies on the server."""

    return await service.objects(
        database,
        query=q,
        type_code=type,
        from_date=from_date,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/object-reviews",
    status_code=status.HTTP_200_OK,
    response_class=EventStreamContract,
    responses=_REVIEW_ERRORS,
)
async def start_object_review(
    body: ObjectReviewRequest,
    context: CurrentContext,
    service: Annotated[ReviewRunService, Depends(get_object_review_service)],
) -> ReviewEventStream:
    """Review the selected objects with live progress; no object limit (object-review)."""

    execution = await service.start_object_review(
        context,
        [
            ObjectSelection(item.database, item.schema_, item.name, item.type_code)
            for item in body.selections
        ],
        body.rule_group_ids,
        body.rule_codes,
    )
    execution.start()
    return ReviewEventStream(execution)


@router.post(
    "/script-reviews",
    status_code=status.HTTP_200_OK,
    response_class=EventStreamContract,
    responses=_REVIEW_ERRORS,
)
async def start_script_review(
    body: ScriptReviewRequest,
    context: CurrentContext,
    service: Annotated[ReviewRunService, Depends(get_script_review_service)],
) -> ReviewEventStream:
    """Review pasted SQL text with live progress; SQL Server is never contacted."""

    execution = await service.start_script_review(
        context, body.sql, body.label, body.rule_group_ids, body.rule_codes
    )
    execution.start()
    return ReviewEventStream(execution)
