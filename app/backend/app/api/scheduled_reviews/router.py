"""Scheduled review definitions, their run history and the setting (sql-review 008 API contract).

Every endpoint needs a signed-in reviewer or rule manager; the service checks ownership on each
request and answers 404 for a definition the caller may not see. "Şimdi çalıştır" and the
concurrency setting belong to the super admin. The scheduler's internal trigger is not an HTTP
endpoint.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.dependencies import (
    CurrentContext,
    require_any_role,
    require_super_admin,
)
from app.api.validation import envelope_validation_route
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.domain.models.role import ROLE_REVIEWER, ROLE_RULE_MANAGER
from app.schemas.scheduled_reviews.contracts import (
    ScheduledReviewDetail,
    ScheduledReviewPage,
    ScheduledReviewSettings,
    ScheduledReviewWrite,
    ScheduledRunPage,
    ScheduledRunQueued,
)
from app.services.scheduled_review_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ScheduledReviewService,
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Rol yetkisi yok"},
}
_NOT_FOUND: dict[int | str, dict[str, object]] = {
    404: {"description": "Tanım yok veya görme yetkisi yok"}
}
_INVALID: dict[int | str, dict[str, object]] = {
    422: {
        "description": (
            "schedule_invalid, recipient_invalid, recipient_domain_not_allowed, "
            "schedule_name_duplicate, rule_group_unknown veya rule_group_selection_empty"
        )
    }
}
_RUNNING: dict[int | str, dict[str, object]] = {
    409: {"description": "scheduled_review_running: koşum sırada veya sürüyor"}
}

router = APIRouter(
    prefix="/scheduled-reviews",
    tags=["scheduled-reviews"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    dependencies=[Depends(require_any_role(ROLE_REVIEWER, ROLE_RULE_MANAGER))],
    responses=_RESPONSES,
)
settings_router = APIRouter(
    prefix="/scheduled-review-settings",
    tags=["scheduled-reviews"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    dependencies=[Depends(require_super_admin())],
    responses=_RESPONSES,
)


def get_scheduled_review_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScheduledReviewService:
    return ScheduledReviewService(session, allowed_domains=settings.mail_allowed_domain_list)


Service = Annotated[ScheduledReviewService, Depends(get_scheduled_review_service)]
ScheduleId = Annotated[str, Path(min_length=1, max_length=64)]


@router.get("", response_model=ScheduledReviewPage)
async def list_scheduled_reviews(
    context: CurrentContext,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ScheduledReviewPage:
    """Own definitions; the super admin sees every definition of the tenant (Decision 3)."""

    return await service.list_definitions(context, page=page, page_size=page_size)


@router.post(
    "",
    response_model=ScheduledReviewDetail,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_scheduled_review(
    body: ScheduledReviewWrite, context: CurrentContext, service: Service
) -> ScheduledReviewDetail:
    """Create an active definition; its first due time follows from the period."""

    return await service.create(context, body)


@router.get("/{schedule_id}", response_model=ScheduledReviewDetail, responses=_NOT_FOUND)
async def read_scheduled_review(
    schedule_id: ScheduleId, context: CurrentContext, service: Service
) -> ScheduledReviewDetail:
    return await service.detail(context, schedule_id)


@router.put(
    "/{schedule_id}",
    response_model=ScheduledReviewDetail,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_scheduled_review(
    schedule_id: ScheduleId,
    body: ScheduledReviewWrite,
    context: CurrentContext,
    service: Service,
) -> ScheduledReviewDetail:
    return await service.update(context, schedule_id, body)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_RUNNING},
)
async def delete_scheduled_review(
    schedule_id: ScheduleId, context: CurrentContext, service: Service
) -> Response:
    """Delete the definition with its run history and recipient list; reports stay."""

    await service.delete(context, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{schedule_id}/pause", response_model=ScheduledReviewDetail, responses=_NOT_FOUND)
async def pause_scheduled_review(
    schedule_id: ScheduleId, context: CurrentContext, service: Service
) -> ScheduledReviewDetail:
    return await service.set_paused(context, schedule_id, paused=True)


@router.post("/{schedule_id}/resume", response_model=ScheduledReviewDetail, responses=_NOT_FOUND)
async def resume_scheduled_review(
    schedule_id: ScheduleId, context: CurrentContext, service: Service
) -> ScheduledReviewDetail:
    """Resume from the next due time after now; paused time is not caught up."""

    return await service.set_paused(context, schedule_id, paused=False)


@router.post(
    "/{schedule_id}/run",
    response_model=ScheduledRunQueued,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_RUNNING, 403: {"description": "Yalnız süper yönetici"}},
)
async def run_scheduled_review_now(
    schedule_id: ScheduleId, context: CurrentContext, service: Service
) -> ScheduledRunQueued:
    """Şimdi çalıştır: queue a manual run that starts like a due one (Decision 9)."""

    return await service.run_now(context, schedule_id)


@router.get("/{schedule_id}/runs", response_model=ScheduledRunPage, responses=_NOT_FOUND)
async def list_scheduled_review_runs(
    schedule_id: ScheduleId,
    context: CurrentContext,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ScheduledRunPage:
    """Run history newest first; reports open with the review-history endpoints."""

    return await service.runs(context, schedule_id, page=page, page_size=page_size)


@settings_router.get("", response_model=ScheduledReviewSettings)
async def read_scheduled_review_settings(
    context: CurrentContext, service: Service
) -> ScheduledReviewSettings:
    return await service.settings(context)


@settings_router.put(
    "",
    response_model=ScheduledReviewSettings,
    responses={422: {"description": "setting_out_of_range"}},
)
async def update_scheduled_review_settings(
    body: ScheduledReviewSettings, context: CurrentContext, service: Service
) -> ScheduledReviewSettings:
    return await service.update_settings(context, body)
