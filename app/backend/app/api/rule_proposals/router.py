"""Rule proposal, publish request and proposal permission endpoints (sql-review 009-rule-proposals).

Every endpoint checks the caller on the server: proposals need the proposal permission, decisions
and the permission list need the super admin, publish requests need the rule manager role.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import dependencies
from app.api.auth.dependencies import CurrentContext, require_any_role
from app.api.validation import envelope_validation_route
from app.db.session import get_db
from app.domain.models.role import ROLE_REVIEWER, ROLE_RULE_MANAGER
from app.domain.models.rule_proposal import PublishRequestStatus
from app.schemas.rule_proposals.contracts import (
    DecisionReason,
    ProposalScopeValue,
    PublishRequestCreate,
    PublishRequestDetail,
    PublishRequestPage,
    PublishRequestStatusValue,
    RuleProposalCapabilities,
    RuleProposalCreate,
    RuleProposalDetail,
    RuleProposalPage,
    RuleProposerList,
)
from app.services.rule_proposal_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    RuleProposalService,
)

_ERRORS: dict[int | str, dict[str, str]] = {
    401: {"description": "Oturum yok"},
    403: {"description": "Yetki yok"},
}
_ROUTE = envelope_validation_route(status.HTTP_422_UNPROCESSABLE_CONTENT)

proposals_router = APIRouter(
    prefix="/rule-proposals", tags=["rule-proposals"], route_class=_ROUTE, responses=_ERRORS
)
requests_router = APIRouter(
    prefix="/rule-set/publish-requests",
    tags=["rule-proposals"],
    route_class=_ROUTE,
    responses=_ERRORS,
)
proposers_router = APIRouter(
    prefix="/rule-proposers", tags=["rule-proposals"], route_class=_ROUTE, responses=_ERRORS
)

AnyReviewRole = [Depends(require_any_role(ROLE_REVIEWER, ROLE_RULE_MANAGER))]
RuleManager = [Depends(require_any_role(ROLE_RULE_MANAGER))]
SuperAdmin = [Depends(dependencies.require_super_admin())]
ProposalId = Annotated[str, Path(min_length=1, max_length=64)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


def get_rule_proposal_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RuleProposalService:
    return RuleProposalService(session)


Service = Annotated[RuleProposalService, Depends(get_rule_proposal_service)]


# --- Proposals ------------------------------------------------------------------------------------


@proposals_router.get(
    "/capabilities", response_model=RuleProposalCapabilities, dependencies=AnyReviewRole
)
async def read_capabilities(context: CurrentContext, service: Service) -> RuleProposalCapabilities:
    """Whether the caller may propose and decide; the menu uses it (Requirement 7)."""

    return await service.capabilities(context)


@proposals_router.get("", response_model=RuleProposalPage, dependencies=AnyReviewRole)
async def list_proposals(
    context: CurrentContext,
    service: Service,
    scope: ProposalScopeValue = "mine",
    page: Page = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
) -> RuleProposalPage:
    """The caller's proposals; ``pending`` and ``all`` are the super admin's."""

    return await service.list_proposals(context, scope=scope, page=page, page_size=page_size)


@proposals_router.post(
    "",
    response_model=RuleProposalDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=AnyReviewRole,
)
async def create_proposal(
    body: RuleProposalCreate, context: CurrentContext, service: Service
) -> RuleProposalDetail:
    """Propose a new rule or a new group of published rules (Requirement 2, 3)."""

    return await service.create_proposal(context, body)


@proposals_router.get(
    "/{proposal_id}", response_model=RuleProposalDetail, dependencies=AnyReviewRole
)
async def read_proposal(
    proposal_id: ProposalId, context: CurrentContext, service: Service
) -> RuleProposalDetail:
    """One proposal; only its proposer and the super admin see it."""

    return await service.proposal(context, proposal_id)


@proposals_router.post(
    "/{proposal_id}/withdraw", response_model=RuleProposalDetail, dependencies=AnyReviewRole
)
async def withdraw_proposal(
    proposal_id: ProposalId, context: CurrentContext, service: Service
) -> RuleProposalDetail:
    """The proposer withdraws a pending proposal (Requirement 4)."""

    return await service.withdraw(context, proposal_id)


@proposals_router.post(
    "/{proposal_id}/approve", response_model=RuleProposalDetail, dependencies=SuperAdmin
)
async def approve_proposal(
    proposal_id: ProposalId, context: CurrentContext, service: Service
) -> RuleProposalDetail:
    """Publish the proposal as a new version and write it to the draft (Requirement 5)."""

    return await service.approve(context, proposal_id)


@proposals_router.post(
    "/{proposal_id}/reject", response_model=RuleProposalDetail, dependencies=SuperAdmin
)
async def reject_proposal(
    proposal_id: ProposalId, body: DecisionReason, context: CurrentContext, service: Service
) -> RuleProposalDetail:
    """Reject a pending proposal with a reason its proposer sees (Requirement 5)."""

    return await service.reject(context, proposal_id, body.reason)


# --- Publish requests -----------------------------------------------------------------------------


@requests_router.post(
    "",
    response_model=PublishRequestDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=RuleManager,
)
async def create_publish_request(
    body: PublishRequestCreate, context: CurrentContext, service: Service
) -> PublishRequestDetail:
    """Send the current draft revision for approval; it replaces a pending request."""

    return await service.create_request(context, body.base_revision)


@requests_router.get("", response_model=PublishRequestPage, dependencies=RuleManager)
async def list_publish_requests(
    context: CurrentContext,
    service: Service,
    status_filter: Annotated[PublishRequestStatusValue | None, Query(alias="status")] = None,
    page: Page = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
) -> PublishRequestPage:
    """Publish requests: all for the super admin, the caller's own for a rule manager."""

    return await service.list_requests(
        context,
        status_filter=None if status_filter is None else PublishRequestStatus(status_filter),
        page=page,
        page_size=page_size,
    )


@requests_router.get("/{request_id}", response_model=PublishRequestDetail, dependencies=RuleManager)
async def read_publish_request(
    request_id: ProposalId, context: CurrentContext, service: Service
) -> PublishRequestDetail:
    """One request with the draft's difference from the latest version while pending."""

    return await service.request(context, request_id)


@requests_router.post(
    "/{request_id}/approve", response_model=PublishRequestDetail, dependencies=SuperAdmin
)
async def approve_publish_request(
    request_id: ProposalId, context: CurrentContext, service: Service
) -> PublishRequestDetail:
    """Publish the requested draft revision; a changed draft makes the request stale."""

    return await service.approve_request(context, request_id)


@requests_router.post(
    "/{request_id}/reject", response_model=PublishRequestDetail, dependencies=SuperAdmin
)
async def reject_publish_request(
    request_id: ProposalId, body: DecisionReason, context: CurrentContext, service: Service
) -> PublishRequestDetail:
    """Reject a pending publish request with a reason the rule manager sees."""

    return await service.reject_request(context, request_id, body.reason)


# --- Proposal permission --------------------------------------------------------------------------


@proposers_router.get("", response_model=RuleProposerList, dependencies=SuperAdmin)
async def list_proposers(context: CurrentContext, service: Service) -> RuleProposerList:
    """Users holding the "kural önerebilir" permission (Requirement 1)."""

    return await service.proposers(context)


@proposers_router.put("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SuperAdmin)
async def grant_proposer(user_id: UUID, context: CurrentContext, service: Service) -> Response:
    """Grant the permission to an active user of the tenant."""

    await service.set_proposer(context, user_id, granted=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@proposers_router.delete(
    "/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SuperAdmin
)
async def revoke_proposer(user_id: UUID, context: CurrentContext, service: Service) -> Response:
    """Revoke the permission; the user's pending proposals stay for a decision."""

    await service.set_proposer(context, user_id, granted=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
