"""LLM connection settings and call summaries (sql-review/PRDs/006-llm-connection API contract).

``router`` is registered in every environment; ``local_router`` only in the local environment,
so in nonprod the settings write endpoint does not exist (Requirement 13).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.dependencies import (
    CurrentContext,
    require_super_admin,
)
from app.api.integrations import get_llm_connection_store, get_llm_resolver
from app.api.route_classes import MethodScopedRoute
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.infrastructure.llm.network import Resolver
from app.schemas.llm.contracts import (
    LlmCallSummaryItem,
    LlmCallSummaryPage,
    LlmConnectionUpdate,
    LlmConnectionView,
)
from app.services.llm_call_summary_service import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    LlmCallSummaryService,
)
from app.services.llm_connection_service import LlmConnectionService, LlmConnectionStore

_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Süper yönetici değil"},
}


def get_llm_connection_service(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[LlmConnectionStore, Depends(get_llm_connection_store)],
    resolver: Annotated[Resolver, Depends(get_llm_resolver)],
) -> LlmConnectionService:
    return LlmConnectionService(settings=settings, store=store, resolver=resolver)


def get_llm_call_summary_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LlmCallSummaryService:
    return LlmCallSummaryService(session)


ConnectionService = Annotated[LlmConnectionService, Depends(get_llm_connection_service)]
SummaryService = Annotated[LlmCallSummaryService, Depends(get_llm_call_summary_service)]


def _router() -> APIRouter:
    return APIRouter(
        tags=["llm"],
        route_class=MethodScopedRoute,
        dependencies=[Depends(require_super_admin())],
        responses=_RESPONSES,
    )


router = _router()
local_router = _router()


@router.get("/llm-connection", response_model=LlmConnectionView, response_model_exclude_none=True)
async def read_llm_connection(service: ConnectionService) -> LlmConnectionView:
    """Format and model; addresses and key state only in the local environment."""

    return service.view()


@local_router.put(
    "/llm-connection",
    response_model=LlmConnectionView,
    response_model_exclude_none=True,
    responses={422: {"description": "Geçersiz adres veya kurum ağı dışı hedef"}},
)
async def update_llm_connection(
    body: LlmConnectionUpdate, service: ConnectionService
) -> LlmConnectionView:
    """Change the values of this process only; nothing is written to a file (local only)."""

    return await service.update(body)


@router.get("/llm-calls", response_model=LlmCallSummaryPage)
async def list_llm_calls(
    context: CurrentContext,
    service: SummaryService,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> LlmCallSummaryPage:
    """Latest call summaries, newest first; metadata only."""

    return await service.list_recent(context, limit=limit)


@router.get(
    "/llm-calls/{public_id}",
    response_model=LlmCallSummaryItem,
    responses={404: {"description": "Özet yok"}},
)
async def read_llm_call(
    public_id: Annotated[str, Path(max_length=64)], context: CurrentContext, service: SummaryService
) -> LlmCallSummaryItem:
    """One call summary with the same fields as the list."""

    return await service.get(context, public_id)
