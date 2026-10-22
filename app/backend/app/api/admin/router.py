"""User administration: list users, assign the application role, activate or deactivate."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.dependencies import CurrentContext, require_super_admin
from app.api.validation import envelope_validation_route
from app.db.session import get_db
from app.schemas.admin.users import ActiveChange, UserPage
from app.services.user_admin_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    UserAdminService,
)

# The PRD contract answers malformed admin input with 400 instead of FastAPI's 422.
BadRequestOnValidationRoute = envelope_validation_route(status.HTTP_400_BAD_REQUEST)


_ERRORS = {
    400: {"description": "Geçersiz istek değeri"},
    401: {"description": "Oturum yok"},
    403: {"description": "Süper yönetici değil"},
}

router = APIRouter(
    prefix="/admin/users",
    tags=["user-administration"],
    route_class=BadRequestOnValidationRoute,
    dependencies=[Depends(require_super_admin())],
    responses=_ERRORS,  # type: ignore[arg-type]
)


def get_user_admin_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserAdminService:
    return UserAdminService(session)


Service = Annotated[UserAdminService, Depends(get_user_admin_service)]


@router.get("", response_model=UserPage)
async def list_users(
    context: CurrentContext,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> UserPage:
    """List the tenant's users ordered by login name (UPN)."""

    return await service.list_users(context, page=page, size=size, query=q)


@router.put(
    "/{public_id}/active",
    response_model=ActiveChange,
    responses={
        404: {"description": "Kullanıcı yok"},
        409: {"description": "Kendi hesabı veya süper yönetici"},
    },
)
async def set_active(
    public_id: UUID, body: ActiveChange, context: CurrentContext, service: Service
) -> ActiveChange:
    """Deactivate or reactivate an account; repeating the same value changes nothing."""

    return ActiveChange(active=await service.set_active(context, public_id, body.active))
