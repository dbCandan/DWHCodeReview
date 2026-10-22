"""SQL Server connection settings (sql-review/PRDs/002-sql-server-connection API contract).

``router`` is registered in every environment. The write and test endpoints are registered only
where the connection is editable (Requirement 5): ``local_router`` in the local environment for
the rule manager, ``stored_router`` in a nonprod environment that keeps the connection in
PostgreSQL, for the super admin only. Elsewhere those requests find no route.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.params import Depends as DependsParameter

from app.api.auth.dependencies import (
    CurrentContext,
    require_super_admin,
)
from app.api.integrations import (
    get_sql_catalog,
    get_sql_connection_storage,
    get_sql_connection_store,
)
from app.api.route_classes import MethodScopedRoute
from app.core.config import Settings, get_settings
from app.domain.sql_server import SqlConnectionProbe
from app.schemas.sql_connection.contracts import (
    SqlConnectionChange,
    SqlConnectionTestResult,
    SqlConnectionView,
)
from app.services.sql_connection_service import (
    SqlConnectionService,
    SqlConnectionStore,
    StoredSqlConnection,
)

_READ_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Süper yönetici değil"},
}
_WRITE_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Süper yönetici değil"},
    404: {"description": "Bağlantı bu ortamda dağıtımla yönetilir"},
}
_INVALID: dict[int | str, dict[str, str]] = {
    422: {"description": "Geçersiz sunucu veya kullanıcı adı ya da bu ortamda sabit ayar"}
}


def get_sql_connection_service(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[SqlConnectionStore, Depends(get_sql_connection_store)],
    catalog: Annotated[SqlConnectionProbe, Depends(get_sql_catalog)],
    storage: Annotated[StoredSqlConnection | None, Depends(get_sql_connection_storage)],
) -> SqlConnectionService:
    return SqlConnectionService(settings=settings, store=store, probe=catalog, storage=storage)


Service = Annotated[SqlConnectionService, Depends(get_sql_connection_service)]

router = APIRouter(
    prefix="/sql-connection",
    tags=["sql-connection"],
    route_class=MethodScopedRoute,
    dependencies=[Depends(require_super_admin())],
    responses=_READ_RESPONSES,
)


@router.get("", response_model=SqlConnectionView, response_model_exclude_none=True)
async def read_sql_connection(context: CurrentContext, service: Service) -> SqlConnectionView:
    """Environment and state; server, user and options only for the caller who may edit them."""

    return await service.view(context)


async def update_sql_connection(
    body: SqlConnectionChange, context: CurrentContext, service: Service
) -> SqlConnectionView:
    """Save the connection: locally in this process only, in nonprod in PostgreSQL."""

    return await service.update(context, body)


async def test_sql_connection(
    body: SqlConnectionChange, context: CurrentContext, service: Service
) -> SqlConnectionTestResult:
    """Log in to master with the form values without saving them."""

    return await service.test(context, body)


def _write_router(guard: DependsParameter) -> APIRouter:
    writer = APIRouter(
        prefix="/sql-connection",
        tags=["sql-connection"],
        route_class=MethodScopedRoute,
        dependencies=[guard],
        responses=_WRITE_RESPONSES,
    )
    writer.add_api_route(
        "",
        update_sql_connection,
        methods=["PUT"],
        response_model=SqlConnectionView,
        response_model_exclude_none=True,
        responses={**_INVALID, 409: {"description": "Aynı anda başka bir kayıt yapıldı"}},
    )
    writer.add_api_route(
        "/test",
        test_sql_connection,
        methods=["POST"],
        response_model=SqlConnectionTestResult,
        responses=dict(_INVALID),
    )
    return writer


local_router = _write_router(Depends(require_super_admin()))
stored_router = _write_router(Depends(require_super_admin()))
