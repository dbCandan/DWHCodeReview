"""Rule and group proposals, publish requests and the proposal permission.

sql-review/PRDs/009-rule-proposals Requirement 1-7. Every approval locks the tenant draft row
first, the same lock a direct publish takes, so two approvals never publish the same version
number; an approved proposal is added to the latest published content, published and written to
the draft in one transaction (Decision 2). Texts, summaries, group names and reasons never reach
the log.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.core.request_context import RequestContext
from app.domain.models.mixins import new_public_id
from app.domain.models.rule_proposal import (
    PROPOSAL_REASON_MAX_LENGTH,
    ProposalStatus,
    PublishRequestStatus,
    RuleProposal,
    RuleProposalKind,
    RulePublishRequest,
)
from app.domain.models.rule_set import RulePriorityGroup
from app.domain.models.tenant import Tenant
from app.domain.models.user import User
from app.domain.rule_proposal import (
    ProposalConflictError,
    ProposedGroup,
    ProposedRule,
    RuleSetDiff,
    diff_rule_sets,
    validate_group_proposal,
    validate_rule_proposal,
    with_group_proposal,
    with_rule_proposal,
)
from app.domain.rule_set import (
    Rule,
    RuleGroups,
    RuleSetValidationError,
    fold_group_name,
    format_rule_code,
)
from app.infrastructure.repositories.rule_proposal_repository import (
    ProposalRow,
    PublishRequestRow,
    RuleProposalRepository,
)
from app.infrastructure.repositories.rule_set_repository import RuleSetRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.schemas.rule_proposals.contracts import (
    ChangedGroup,
    ChangedRule,
    DiffRuleItem,
    ProposalScopeValue,
    PublishRequestDetail,
    PublishRequestItem,
    PublishRequestPage,
    RuleProposalCapabilities,
    RuleProposalCreate,
    RuleProposalDetail,
    RuleProposalItem,
    RuleProposalPage,
    RuleProposerItem,
    RuleProposerList,
    RuleSetDiffView,
)
from app.schemas.rule_set.contracts import RuleGroupItem
from app.services.request_scope import acting_user, active_tenant
from app.services.rule_set_service import RuleSetService, draft_conflict, rule_set_empty

logger = logging.getLogger("app.rule_proposals")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def _unprocessable(code: str, message: str) -> ApplicationError:
    return ApplicationError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def _forbidden_proposal() -> ApplicationError:
    return ApplicationError(
        status.HTTP_403_FORBIDDEN,
        "proposal_forbidden",
        "Kural önerme yetkiniz yok; süper yöneticiden yetki isteyin.",
    )


def _decision_forbidden() -> ApplicationError:
    return ApplicationError(status.HTTP_403_FORBIDDEN, "forbidden", "Bu işlem için yetkiniz yok.")


def _proposal_not_found() -> ApplicationError:
    return ApplicationError(
        status.HTTP_404_NOT_FOUND, "rule_proposal_not_found", "Kural önerisi bulunamadı."
    )


def _request_not_found() -> ApplicationError:
    return ApplicationError(
        status.HTTP_404_NOT_FOUND, "publish_request_not_found", "Yayın isteği bulunamadı."
    )


def _proposal_not_pending() -> ApplicationError:
    return ApplicationError(
        status.HTTP_409_CONFLICT,
        "proposal_not_pending",
        "Öneri artık beklemiyor; sayfayı yenileyin.",
    )


def _reason(value: str) -> str:
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= PROPOSAL_REASON_MAX_LENGTH:
        raise _unprocessable("rejection_reason_invalid", "Ret gerekçesi 1-500 karakter olmalıdır.")
    return trimmed


def _proposal_item(row: ProposalRow, actor: User) -> dict[str, object]:
    proposal = row.proposal
    return {
        "id": proposal.public_id,
        "kind": proposal.kind,
        "status": proposal.status,
        "proposer_name": row.proposer_name,
        "created_at": proposal.created_at,
        "summary": proposal.summary,
        "group_name": proposal.group_name,
        "decided_by_name": row.decided_by_name,
        "decided_at": proposal.decided_at,
        "rejection_reason": proposal.rejection_reason,
        "published_version_number": proposal.published_version_number,
        "new_rule_id": proposal.new_rule_code,
        "owned": proposal.proposer_user_id == actor.user_id,
    }


def _proposal_detail(row: ProposalRow, actor: User) -> RuleProposalDetail:
    proposal = row.proposal
    return RuleProposalDetail.model_validate(
        {
            **_proposal_item(row, actor),
            "text": proposal.rule_text,
            "priority": proposal.priority_group,
            "requires_metadata": proposal.requires_metadata,
            "rule_group_ids": list(proposal.rule_group_ids),
            "group_description": proposal.group_description,
            "rule_codes": list(proposal.rule_codes),
            "rationale": proposal.rationale,
        }
    )


def _diff_rule(tier: RulePriorityGroup, rule: Rule) -> DiffRuleItem:
    return DiffRuleItem(
        id=rule.code,
        text=rule.text,
        summary=rule.summary,
        requires_metadata=rule.requires_metadata,
        rule_group_ids=list(rule.rule_group_ids),
        priority=tier.value,
    )


def _group_item(group_id: str, name: str, description: str) -> RuleGroupItem:
    return RuleGroupItem(id=group_id, name=name, description=description)


def _diff_view(diff: RuleSetDiff) -> RuleSetDiffView:
    return RuleSetDiffView(
        added_rules=[_diff_rule(tier, rule) for tier, rule in diff.added_rules],
        changed_rules=[
            ChangedRule(before=_diff_rule(old_tier, old), after=_diff_rule(new_tier, new))
            for old_tier, old, new_tier, new in diff.changed_rules
        ],
        removed_rules=[_diff_rule(tier, rule) for tier, rule in diff.removed_rules],
        added_groups=[_group_item(g.public_id, g.name, g.description) for g in diff.added_groups],
        changed_groups=[
            ChangedGroup(
                before=_group_item(old.public_id, old.name, old.description),
                after=_group_item(new.public_id, new.name, new.description),
            )
            for old, new in diff.changed_groups
        ],
        removed_groups=[
            _group_item(g.public_id, g.name, g.description) for g in diff.removed_groups
        ],
    )


class RuleProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.proposals = RuleProposalRepository(session)
        self.rules = RuleSetRepository(session)
        self.users = UserRepository(session)
        self.rule_sets = RuleSetService(session)

    async def _scope(self, context: RequestContext) -> tuple[Tenant, User]:
        return await active_tenant(self.users, context), await acting_user(self.users, context)

    async def _can_propose(self, context: RequestContext, tenant: Tenant, actor: User) -> bool:
        return context.is_super_admin or await self.proposals.is_proposer(
            tenant.tenant_id, actor.user_id
        )

    async def _latest_rules(self, tenant_id: int) -> tuple[int | None, RuleGroups]:
        latest = await self.rules.latest_version(tenant_id)
        if latest is None:
            return None, RuleGroups()
        return latest.number, await self.rules.version_rules(latest)

    # --- Capabilities and permission (Requirement 1, 7) ----------------------------------------

    async def capabilities(self, context: RequestContext) -> RuleProposalCapabilities:
        tenant, actor = await self._scope(context)
        return RuleProposalCapabilities(
            can_propose=await self._can_propose(context, tenant, actor),
            can_decide=context.is_super_admin,
        )

    async def proposers(self, context: RequestContext) -> RuleProposerList:
        tenant, _ = await self._scope(context)
        rows = await self.proposals.proposers(tenant.tenant_id)
        return RuleProposerList(
            items=[
                RuleProposerItem(
                    user_id=row.user.public_id,
                    username=row.user.username,
                    display_name=row.user.display_name,
                    granted_by_name=row.granted_by_name,
                    granted_at=row.proposer.created_at,
                )
                for row in rows
            ]
        )

    async def set_proposer(self, context: RequestContext, user_id: UUID, *, granted: bool) -> None:
        tenant, actor = await self._scope(context)
        user = await self.users.get_in_tenant_for_update(user_id, tenant.tenant_id)
        if user is None or (granted and not user.is_active):
            raise ApplicationError(
                status.HTTP_404_NOT_FOUND, "user_not_found", "Kullanıcı bulunamadı."
            )
        now = datetime.now(UTC)
        if granted:
            changed = await self.proposals.grant(
                tenant.tenant_id, user.user_id, actor_user_id=actor.user_id, now=now
            )
        else:
            changed = await self.proposals.revoke(
                tenant.tenant_id, user.user_id, actor_user_id=actor.user_id, now=now
            )
        if changed:
            log_event(
                logger,
                "rule_proposer.granted" if granted else "rule_proposer.revoked",
                user_public_id=user.public_id,
                actor_public_id=actor.public_id,
            )

    # --- Proposals (Requirement 2-5) -----------------------------------------------------------

    async def create_proposal(
        self, context: RequestContext, body: RuleProposalCreate
    ) -> RuleProposalDetail:
        tenant, actor = await self._scope(context)
        if not await self._can_propose(context, tenant, actor):
            raise _forbidden_proposal()
        _, latest = await self._latest_rules(tenant.tenant_id)
        try:
            if body.kind == RuleProposalKind.RULE.value:
                proposal = self._new_rule_proposal(body, latest)
            else:
                proposal = await self._new_group_proposal(tenant, body, latest)
        except RuleSetValidationError as error:
            raise _unprocessable(error.code, error.message) from None
        proposal.tenant_id = tenant.tenant_id
        proposal.proposer_user_id = actor.user_id
        proposal.rationale = body.rationale.strip()
        proposal.created_by = actor.user_id
        proposal.updated_by = actor.user_id
        await self.proposals.add_proposal(proposal)
        log_event(
            logger,
            "rule_proposal.created",
            proposal_public_id=proposal.public_id,
            kind=proposal.kind,
            user_public_id=actor.public_id,
        )
        return await self._detail(tenant, actor, proposal.public_id)

    def _new_rule_proposal(self, body: RuleProposalCreate, latest: RuleGroups) -> RuleProposal:
        valid = validate_rule_proposal(
            summary=body.summary,
            text=body.text,
            priority=RulePriorityGroup(body.priority),
            requires_metadata=body.requires_metadata,
            rule_group_ids=body.rule_group_ids,
        )
        known = {group.public_id for group in latest.rule_groups}
        if not set(valid.rule_group_ids) <= known:
            raise RuleSetValidationError(
                "rule_group_unknown", "Seçilen kural grubu yayımlanmış sürümde yok."
            )
        return RuleProposal(
            public_id=new_public_id(),
            kind=RuleProposalKind.RULE.value,
            summary=valid.summary,
            rule_text=valid.text,
            priority_group=valid.priority.value,
            requires_metadata=valid.requires_metadata,
            rule_group_ids=list(valid.rule_group_ids),
        )

    async def _new_group_proposal(
        self, tenant: Tenant, body: RuleProposalCreate, latest: RuleGroups
    ) -> RuleProposal:
        valid = validate_group_proposal(body.group_name, body.group_description, body.rule_codes)
        if not set(valid.rule_codes) <= latest.codes:
            raise RuleSetValidationError("rule_unknown", "Seçilen kural yayımlanmış sürümde yok.")
        draft = await self.rules.get_draft(tenant.tenant_id)
        draft_groups = () if draft is None else (await self.rules.draft_rules(draft)).rule_groups
        folded = fold_group_name(valid.name)
        if any(fold_group_name(g.name) == folded for g in (*latest.rule_groups, *draft_groups)):
            raise RuleSetValidationError(
                "rule_group_name_duplicate", "Aynı adla bir kural grubu zaten var."
            )
        return RuleProposal(
            public_id=new_public_id(),
            kind=RuleProposalKind.GROUP.value,
            group_name=valid.name,
            group_description=valid.description,
            rule_codes=list(valid.rule_codes),
        )

    async def list_proposals(
        self,
        context: RequestContext,
        *,
        scope: ProposalScopeValue,
        page: int,
        page_size: int,
    ) -> RuleProposalPage:
        tenant, actor = await self._scope(context)
        if scope != "mine" and not context.is_super_admin:
            raise _decision_forbidden()
        rows, total = await self.proposals.list_proposals(
            tenant.tenant_id,
            proposer_user_id=actor.user_id if scope == "mine" else None,
            status=ProposalStatus.PENDING if scope == "pending" else None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return RuleProposalPage(
            items=[RuleProposalItem.model_validate(_proposal_item(row, actor)) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def proposal(self, context: RequestContext, proposal_id: str) -> RuleProposalDetail:
        tenant, actor = await self._scope(context)
        return await self._detail(tenant, actor, proposal_id, context=context)

    async def _detail(
        self,
        tenant: Tenant,
        actor: User,
        proposal_id: str,
        *,
        context: RequestContext | None = None,
    ) -> RuleProposalDetail:
        row = await self.proposals.proposal_row(tenant.tenant_id, proposal_id)
        if row is None:
            raise _proposal_not_found()
        visible = row.proposal.proposer_user_id == actor.user_id or (
            context is None or context.is_super_admin
        )
        if not visible:
            raise _proposal_not_found()
        return _proposal_detail(row, actor)

    async def withdraw(self, context: RequestContext, proposal_id: str) -> RuleProposalDetail:
        tenant, actor = await self._scope(context)
        proposal = await self.proposals.lock_proposal(tenant.tenant_id, proposal_id)
        if proposal is None or proposal.proposer_user_id != actor.user_id:
            raise _proposal_not_found()
        if proposal.status != ProposalStatus.PENDING.value:
            raise _proposal_not_pending()
        proposal.status = ProposalStatus.WITHDRAWN.value
        proposal.decided_at = datetime.now(UTC)
        proposal.updated_by = actor.user_id
        await self.session.flush()
        log_event(
            logger,
            "rule_proposal.withdrawn",
            proposal_public_id=proposal.public_id,
            kind=proposal.kind,
            user_public_id=actor.public_id,
        )
        return await self._detail(tenant, actor, proposal_id)

    async def approve(self, context: RequestContext, proposal_id: str) -> RuleProposalDetail:
        """Publish the proposal on the latest version and write it to the draft (Decision 2)."""

        tenant, actor = await self._scope(context)
        draft = await self.rules.lock_draft(tenant.tenant_id, actor_user_id=actor.user_id)
        proposal = await self.proposals.lock_proposal(tenant.tenant_id, proposal_id)
        if proposal is None:
            raise _proposal_not_found()
        if proposal.status != ProposalStatus.PENDING.value:
            raise _proposal_not_pending()
        _, latest = await self._latest_rules(tenant.tenant_id)
        current = await self.rules.draft_rules(draft)
        code: str | None = None
        group_id: str | None = None
        try:
            if proposal.kind == RuleProposalKind.RULE.value:
                rule = ProposedRule(
                    proposal.summary,
                    proposal.rule_text,
                    RulePriorityGroup(proposal.priority_group or RulePriorityGroup.NORMAL.value),
                    proposal.requires_metadata,
                    tuple(str(value) for value in proposal.rule_group_ids),
                )
                code = format_rule_code(draft.next_rule_number)
                published = with_rule_proposal(latest, rule, code)
                drafted = with_rule_proposal(current, rule, code, strict=False)
            else:
                group = ProposedGroup(
                    proposal.group_name,
                    proposal.group_description,
                    tuple(str(value) for value in proposal.rule_codes),
                )
                group_id = new_public_id()
                published = with_group_proposal(latest, group, group_id)
                drafted = with_group_proposal(current, group, group_id, strict=False)
        except ProposalConflictError as error:
            raise ApplicationError(status.HTTP_409_CONFLICT, error.code, error.message) from None
        version, _ = await self.rule_sets.publish_rules(tenant.tenant_id, actor, published)
        now = datetime.now(UTC)
        await self.rules.replace_draft_rules(draft, drafted, actor_user_id=actor.user_id, now=now)
        draft.revision += 1
        if code is not None:
            draft.next_rule_number += 1
        draft.updated_by = actor.user_id
        draft.updated_at = now
        proposal.status = ProposalStatus.APPROVED.value
        proposal.decided_by_user_id = actor.user_id
        proposal.decided_at = now
        proposal.published_version_number = version.number
        proposal.new_rule_code = code
        proposal.new_rule_group_public_id = group_id
        proposal.updated_by = actor.user_id
        await self.session.flush()
        log_event(
            logger,
            "rule_proposal.approved",
            proposal_public_id=proposal.public_id,
            kind=proposal.kind,
            number=version.number,
            user_public_id=actor.public_id,
        )
        return await self._detail(tenant, actor, proposal_id)

    async def reject(
        self, context: RequestContext, proposal_id: str, reason: str
    ) -> RuleProposalDetail:
        tenant, actor = await self._scope(context)
        text = _reason(reason)
        proposal = await self.proposals.lock_proposal(tenant.tenant_id, proposal_id)
        if proposal is None:
            raise _proposal_not_found()
        if proposal.status != ProposalStatus.PENDING.value:
            raise _proposal_not_pending()
        proposal.status = ProposalStatus.REJECTED.value
        proposal.decided_by_user_id = actor.user_id
        proposal.decided_at = datetime.now(UTC)
        proposal.rejection_reason = text
        proposal.updated_by = actor.user_id
        await self.session.flush()
        log_event(
            logger,
            "rule_proposal.rejected",
            proposal_public_id=proposal.public_id,
            kind=proposal.kind,
            user_public_id=actor.public_id,
        )
        return await self._detail(tenant, actor, proposal_id)

    # --- Publish requests (Requirement 6) ------------------------------------------------------

    async def create_request(
        self, context: RequestContext, base_revision: int
    ) -> PublishRequestDetail:
        tenant, actor = await self._scope(context)
        draft = await self.rules.lock_draft(tenant.tenant_id, actor_user_id=actor.user_id)
        if draft.revision != base_revision:
            raise draft_conflict()
        if (await self.rules.draft_rules(draft)).is_empty:
            raise rule_set_empty()
        now = datetime.now(UTC)
        for replaced in await self.proposals.invalidate_pending_requests(
            tenant.tenant_id, actor_user_id=actor.user_id, now=now
        ):
            log_event(logger, "rule_publish_request.stale", request_public_id=replaced)
        request = await self.proposals.add_request(
            RulePublishRequest(
                public_id=new_public_id(),
                tenant_id=tenant.tenant_id,
                requester_user_id=actor.user_id,
                draft_revision=draft.revision,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
        )
        log_event(
            logger,
            "rule_publish_request.created",
            request_public_id=request.public_id,
            revision=draft.revision,
            user_public_id=actor.public_id,
        )
        return await self._request_detail(tenant, actor, request.public_id, context)

    async def list_requests(
        self,
        context: RequestContext,
        *,
        status_filter: PublishRequestStatus | None,
        page: int,
        page_size: int,
    ) -> PublishRequestPage:
        tenant, actor = await self._scope(context)
        rows, total = await self.proposals.list_requests(
            tenant.tenant_id,
            requester_user_id=None if context.is_super_admin else actor.user_id,
            status=status_filter,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        draft = await self.rules.get_draft(tenant.tenant_id)
        revision = None if draft is None else draft.revision
        return PublishRequestPage(
            items=[
                PublishRequestItem.model_validate(self._request_item(row, actor, revision))
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    @staticmethod
    def _request_item(
        row: PublishRequestRow, actor: User, revision: int | None
    ) -> dict[str, object]:
        request = row.request
        pending = request.status == PublishRequestStatus.PENDING.value
        return {
            "id": request.public_id,
            "status": request.status,
            "requester_name": row.requester_name,
            "created_at": request.created_at,
            "draft_revision": request.draft_revision,
            "draft_changed": pending and revision != request.draft_revision,
            "decided_by_name": row.decided_by_name,
            "decided_at": request.decided_at,
            "rejection_reason": request.rejection_reason,
            "published_version_number": request.published_version_number,
            "owned": request.requester_user_id == actor.user_id,
        }

    async def request(self, context: RequestContext, request_id: str) -> PublishRequestDetail:
        tenant, actor = await self._scope(context)
        return await self._request_detail(tenant, actor, request_id, context)

    async def _request_detail(
        self, tenant: Tenant, actor: User, request_id: str, context: RequestContext
    ) -> PublishRequestDetail:
        row = await self.proposals.request_row(tenant.tenant_id, request_id)
        if row is None or not (
            context.is_super_admin or row.request.requester_user_id == actor.user_id
        ):
            raise _request_not_found()
        draft = await self.rules.get_draft(tenant.tenant_id)
        revision = None if draft is None else draft.revision
        diff = None
        if row.request.status == PublishRequestStatus.PENDING.value and draft is not None:
            latest_number, latest = await self._latest_rules(tenant.tenant_id)
            diff = _diff_view(
                diff_rule_sets(
                    None if latest_number is None else latest, await self.rules.draft_rules(draft)
                )
            )
        return PublishRequestDetail.model_validate(
            {**self._request_item(row, actor, revision), "diff": diff}
        )

    async def approve_request(
        self, context: RequestContext, request_id: str
    ) -> PublishRequestDetail:
        tenant, actor = await self._scope(context)
        draft = await self.rules.lock_draft(tenant.tenant_id, actor_user_id=actor.user_id)
        request = await self.proposals.lock_request(tenant.tenant_id, request_id)
        if request is None:
            raise _request_not_found()
        if request.status != PublishRequestStatus.PENDING.value:
            raise ApplicationError(
                status.HTTP_409_CONFLICT,
                "publish_request_not_pending",
                "Yayın isteği artık beklemiyor; sayfayı yenileyin.",
            )
        now = datetime.now(UTC)
        if draft.revision != request.draft_revision:
            request.status = PublishRequestStatus.INVALID.value
            request.decided_at = now
            request.updated_by = actor.user_id
            # The request stays invalid although the approval is refused.
            await self.session.commit()
            log_event(logger, "rule_publish_request.stale", request_public_id=request_id)
            raise ApplicationError(
                status.HTTP_409_CONFLICT,
                "publish_request_stale",
                "Taslak istekten sonra değişti; kural yöneticisi yeniden onaya göndermelidir.",
            )
        rules = await self.rules.draft_rules(draft)
        if rules.is_empty:
            raise rule_set_empty()
        version, _ = await self.rule_sets.publish_rules(tenant.tenant_id, actor, rules)
        request.status = PublishRequestStatus.APPROVED.value
        request.decided_by_user_id = actor.user_id
        request.decided_at = now
        request.published_version_number = version.number
        request.updated_by = actor.user_id
        await self.session.flush()
        log_event(
            logger,
            "rule_publish_request.approved",
            request_public_id=request.public_id,
            number=version.number,
            user_public_id=actor.public_id,
        )
        return await self._request_detail(tenant, actor, request_id, context)

    async def reject_request(
        self, context: RequestContext, request_id: str, reason: str
    ) -> PublishRequestDetail:
        tenant, actor = await self._scope(context)
        text = _reason(reason)
        request = await self.proposals.lock_request(tenant.tenant_id, request_id)
        if request is None:
            raise _request_not_found()
        if request.status != PublishRequestStatus.PENDING.value:
            raise ApplicationError(
                status.HTTP_409_CONFLICT,
                "publish_request_not_pending",
                "Yayın isteği artık beklemiyor; sayfayı yenileyin.",
            )
        request.status = PublishRequestStatus.REJECTED.value
        request.decided_by_user_id = actor.user_id
        request.decided_at = datetime.now(UTC)
        request.rejection_reason = text
        request.updated_by = actor.user_id
        await self.session.flush()
        log_event(
            logger,
            "rule_publish_request.rejected",
            request_public_id=request.public_id,
            user_public_id=actor.public_id,
        )
        return await self._request_detail(tenant, actor, request_id, context)
