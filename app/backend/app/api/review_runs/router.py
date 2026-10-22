"""Review history, false-positive marks, deletion and exports (sql-review 005 API contract).

Every endpoint needs a signed-in reviewer or rule manager; the service checks ownership on each
request. Exports are generated on the server and downloaded with the session header, never with
a token in the URL.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.dependencies import CurrentContext, require_any_role
from app.api.integrations import get_review_registry
from app.api.validation import envelope_validation_route
from app.db.session import get_db
from app.domain.models.role import ROLE_REVIEWER
from app.schemas.review_runs.contracts import (
    DeletedRuns,
    FalsePositiveState,
    FalsePositiveUpdate,
    ReviewRunDetail,
    ReviewRunPage,
    ReviewRunScopeValue,
    RunCancelled,
)
from app.services.review_history_service import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_RESULTS_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_RESULTS_PAGE_SIZE,
    ExportFile,
    ReviewHistoryService,
)
from app.services.review_run_service import ReviewRunRegistry

router = APIRouter(
    prefix="/review-runs",
    tags=["review-runs"],
    route_class=envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT),
    dependencies=[Depends(require_any_role(ROLE_REVIEWER))],
    responses={401: {"description": "Oturum yok"}, 403: {"description": "Rol yetkisi yok"}},
)

_NOT_FOUND: dict[int | str, dict[str, object]] = {
    404: {"description": "Koşum yok, süresi dolmuş veya görme yetkisi yok"}
}
_OWNER_ONLY: dict[int | str, dict[str, object]] = {
    **_NOT_FOUND,
    403: {"description": "Koşumun sahibi değil"},
}


def get_history_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ReviewHistoryService:
    return ReviewHistoryService(session)


Service = Annotated[ReviewHistoryService, Depends(get_history_service)]
RunId = Annotated[str, Path(min_length=1, max_length=64)]


def _download(file: ExportFile) -> Response:
    return Response(
        content=file.content.encode("utf-8"),
        media_type=f"{file.media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )


@router.get("", response_model=ReviewRunPage)
async def list_review_runs(
    context: CurrentContext,
    service: Service,
    scope: Annotated[ReviewRunScopeValue, Query()] = "mine",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ReviewRunPage:
    """Runs newest first; ``scope=all`` is for the rule manager (Requirement 1-2)."""

    return await service.list_runs(context, scope=scope, page=page, page_size=page_size)


@router.delete("", response_model=DeletedRuns)
async def delete_own_review_runs(
    context: CurrentContext,
    service: Service,
    scope: Annotated[Literal["mine"], Query()],
) -> DeletedRuns:
    """Delete every finished run of the caller; other people's runs are untouched."""

    return await service.delete_own_runs(context)


@router.get("/{run_id}", response_model=ReviewRunDetail, responses=_NOT_FOUND)
async def read_review_run(
    run_id: RunId,
    context: CurrentContext,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_RESULTS_PAGE_SIZE)] = DEFAULT_RESULTS_PAGE_SIZE,
    with_sql: Annotated[bool, Query()] = False,
) -> ReviewRunDetail:
    """One page of the stored objects with their results and false-positive marks.

    The SQL text only with ``with_sql`` (Requirement 3, 13), for the code view; whoever reads
    the run may download the same text as the SQL export. ``object_count`` is the total.
    """

    return await service.detail(context, run_id, page=page, page_size=page_size, with_sql=with_sql)


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_OWNER_ONLY, 409: {"description": "Koşum sürüyor"}},
)
async def delete_review_run(run_id: RunId, context: CurrentContext, service: Service) -> Response:
    """Physically delete one run of the caller with everything stored for it."""

    await service.delete_run(context, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{run_id}/cancel",
    response_model=RunCancelled,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_OWNER_ONLY,
        409: {"description": "review_run_not_running: koşum bitmiş"},
    },
)
async def cancel_review_run(
    run_id: RunId,
    context: CurrentContext,
    service: Service,
    registry: Annotated[ReviewRunRegistry, Depends(get_review_registry)],
) -> RunCancelled:
    """ "Analizi durdur": stop a running run of the caller (the super admin: any run)."""

    return await service.cancel_run(context, run_id, registry)


@router.put(
    "/{run_id}/findings/{finding_id}/false-positive",
    response_model=FalsePositiveState,
    responses=_OWNER_ONLY,
)
async def mark_finding(
    run_id: RunId,
    finding_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: FalsePositiveUpdate,
    context: CurrentContext,
    service: Service,
) -> FalsePositiveState:
    """Set or clear the false-positive mark of a finding; repeating a value changes nothing."""

    return await service.set_finding_false_positive(
        context, run_id, finding_id, body.false_positive
    )


@router.put(
    "/{run_id}/rule-results/{rule_result_id}/false-positive",
    response_model=FalsePositiveState,
    responses={**_OWNER_ONLY, 409: {"description": "Kural sonucu işaretlenemez"}},
)
async def mark_rule_result(
    run_id: RunId,
    rule_result_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: FalsePositiveUpdate,
    context: CurrentContext,
    service: Service,
) -> FalsePositiveState:
    """Mark a failed rule result that has no findings."""

    return await service.set_rule_result_false_positive(
        context, run_id, rule_result_id, body.false_positive
    )


@router.get(
    "/{run_id}/exports/csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {"schema": {"type": "string"}}}},
        **_NOT_FOUND,
    },
)
async def export_csv(run_id: RunId, context: CurrentContext, service: Service) -> Response:
    """The results as a CSV file (Requirement 7 and 9)."""

    return _download(await service.export_csv(context, run_id))


@router.get(
    "/{run_id}/exports/sql",
    response_class=Response,
    responses={
        200: {"content": {"application/sql": {"schema": {"type": "string"}}}},
        **_NOT_FOUND,
        409: {"description": "Saklanmış SQL metni yok"},
    },
)
async def export_sql(run_id: RunId, context: CurrentContext, service: Service) -> Response:
    """The reviewed SQL under a fix-comment block (Requirement 8-10)."""

    return _download(await service.export_sql(context, run_id))
