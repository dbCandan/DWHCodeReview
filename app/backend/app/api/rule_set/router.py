"""Rule-set draft, publish and published-version endpoints (sql-review 001-rule-management)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.dependencies import CurrentContext, require_any_role
from app.api.validation import envelope_validation_route
from app.db.session import get_db
from app.domain.models.role import ROLE_REVIEWER, ROLE_RULE_MANAGER
from app.schemas.rule_set.contracts import (
    RuleSetDraftUpdate,
    RuleSetPublishRequest,
    RuleSetVersionDetail,
    RuleSetVersionPage,
    RuleSetWorkspace,
)
from app.services.rule_set_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    RuleSetService,
)

router = APIRouter(
    prefix="/rule-set",
    tags=["rule-set"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    responses={401: {"description": "Oturum yok"}, 403: {"description": "Rol yetkisi yok"}},
)

RuleManager = [Depends(require_any_role(ROLE_RULE_MANAGER))]
AnyReviewRole = [Depends(require_any_role(ROLE_REVIEWER, ROLE_RULE_MANAGER))]


def get_rule_set_service(session: Annotated[AsyncSession, Depends(get_db)]) -> RuleSetService:
    return RuleSetService(session)


Service = Annotated[RuleSetService, Depends(get_rule_set_service)]


@router.get("", response_model=RuleSetWorkspace, dependencies=RuleManager)
async def read_rule_set(context: CurrentContext, service: Service) -> RuleSetWorkspace:
    """The draft, its change counter and the latest published version (Requirement 1)."""

    return await service.workspace(context)


@router.put(
    "/draft",
    response_model=RuleSetWorkspace,
    dependencies=RuleManager,
    responses={409: {"description": "Taslak başka biri tarafından değiştirildi"}},
)
async def save_draft(
    body: RuleSetDraftUpdate, context: CurrentContext, service: Service
) -> RuleSetWorkspace:
    """Save the whole draft; the request carries the revision the client saw."""

    return await service.save_draft(
        context,
        base_revision=body.base_revision,
        critical=body.critical,
        normal=body.normal,
        groups=body.groups,
    )


@router.post(
    "/versions",
    response_model=RuleSetVersionDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=RuleManager,
    responses={
        200: {"description": "Taslak en son sürümle aynı; var olan sürüm döner"},
        403: {"description": "Yalnız süper yönetici doğrudan yayımlar (publish_requires_approval)"},
        409: {"description": "Taslak başka biri tarafından değiştirildi"},
    },
)
async def publish(
    body: RuleSetPublishRequest, response: Response, context: CurrentContext, service: Service
) -> RuleSetVersionDetail:
    """Publish the draft as the next immutable version; only the super admin (rule-proposals).

    An unchanged draft returns the latest version. A rule manager sends a publish request instead.
    """

    outcome = await service.publish(context, base_revision=body.base_revision)
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    return outcome.version


@router.get("/versions", response_model=RuleSetVersionPage, dependencies=AnyReviewRole)
async def list_versions(
    context: CurrentContext,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> RuleSetVersionPage:
    """Published versions, newest first."""

    return await service.list_versions(context, page=page, page_size=page_size)


@router.get(
    "/versions/latest",
    response_model=RuleSetVersionDetail,
    dependencies=AnyReviewRole,
    responses={404: {"description": "Yayımlanmış kural yok"}},
)
async def read_latest_version(context: CurrentContext, service: Service) -> RuleSetVersionDetail:
    """The full content of the latest published version."""

    return await service.latest_version(context)


@router.get(
    "/versions/{number}",
    response_model=RuleSetVersionDetail,
    dependencies=AnyReviewRole,
    responses={404: {"description": "Sürüm yok"}},
)
async def read_version(
    number: Annotated[int, Path(ge=1)], context: CurrentContext, service: Service
) -> RuleSetVersionDetail:
    """The full content of one published version."""

    return await service.version(context, number)
