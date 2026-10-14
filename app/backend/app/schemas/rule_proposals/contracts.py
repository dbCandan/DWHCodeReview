"""Rule proposal, publish request and proposal permission contracts (sql-review 009-rule-proposals).

Transport bounds only; the service applies the business limits (200-character summary, 8,000-
character text, 80-character group name, 1-500 character rejection reason) with their own codes.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool

from app.domain.models.rule_set import RULE_GROUP_DESCRIPTION_MAX_LENGTH
from app.schemas.rule_set.contracts import RuleGroupItem, RuleItem

ProposalKindValue = Literal["rule", "group"]
ProposalStatusValue = Literal["bekliyor", "onaylandi", "reddedildi", "geri_cekildi"]
PublishRequestStatusValue = Literal["bekliyor", "onaylandi", "reddedildi", "gecersiz"]
PriorityValue = Literal["critical", "normal"]
ProposalScopeValue = Literal["mine", "pending", "all"]

_TRANSPORT_TEXT_MAX_LENGTH = 16_000
_TRANSPORT_SUMMARY_MAX_LENGTH = 400
_TRANSPORT_GROUP_NAME_MAX_LENGTH = 160
_TRANSPORT_REASON_MAX_LENGTH = 1_000
_RATIONALE_MAX_LENGTH = 500

GroupId = Annotated[str, Field(min_length=1, max_length=64)]
RuleCode = Annotated[str, Field(min_length=1, max_length=16)]


class RuleProposalCapabilities(BaseModel):
    can_propose: bool = Field(description="The caller may send rule and group proposals.")
    can_decide: bool = Field(description="The caller decides proposals and publish requests.")


class RuleProposalCreate(BaseModel):
    """A new-rule (``kind=rule``) or new-group (``kind=group``) proposal; fields by kind."""

    kind: ProposalKindValue
    summary: str = Field(
        default="",
        max_length=_TRANSPORT_SUMMARY_MAX_LENGTH,
        description="Rule: one-sentence summary, 1-200 characters on one line.",
    )
    text: str = Field(
        default="",
        max_length=_TRANSPORT_TEXT_MAX_LENGTH,
        description="Rule: detailed rule text sent to the LLM once approved, 1-8000 characters.",
    )
    priority: PriorityValue = "normal"
    requires_metadata: StrictBool = False
    rule_group_ids: list[GroupId] = Field(
        default_factory=list,
        max_length=50,
        description="Rule: published groups the new rule joins.",
    )
    group_name: str = Field(default="", max_length=_TRANSPORT_GROUP_NAME_MAX_LENGTH)
    group_description: str = Field(default="", max_length=RULE_GROUP_DESCRIPTION_MAX_LENGTH)
    rule_codes: list[RuleCode] = Field(
        default_factory=list,
        max_length=200,
        description="Group: KuralNN codes of the latest published version the group holds.",
    )
    rationale: str = Field(
        default="",
        max_length=_RATIONALE_MAX_LENGTH,
        description="Optional short reason; it must not contain personal data or passwords.",
    )


class RuleProposalItem(BaseModel):
    id: str = Field(description="public_id of the proposal.")
    kind: ProposalKindValue
    status: ProposalStatusValue
    proposer_name: str
    created_at: datetime
    summary: str = Field(description="Rule: the proposed summary; empty for a group.")
    group_name: str = Field(description="Group: the proposed name; empty for a rule.")
    decided_by_name: str | None
    decided_at: datetime | None
    rejection_reason: str | None
    published_version_number: int | None
    new_rule_id: str | None = Field(description="KuralNN code an approved rule received.")
    owned: bool = Field(description="True when the caller sent the proposal.")


class RuleProposalDetail(RuleProposalItem):
    text: str
    priority: PriorityValue | None
    requires_metadata: bool
    rule_group_ids: list[str]
    group_description: str
    rule_codes: list[str]
    rationale: str


class RuleProposalPage(BaseModel):
    items: list[RuleProposalItem]
    page: int
    page_size: int
    total: int


class DecisionReason(BaseModel):
    reason: str = Field(
        max_length=_TRANSPORT_REASON_MAX_LENGTH,
        description="Rejection reason, 1-500 characters after trimming; shown to the requester.",
    )


class PublishRequestCreate(BaseModel):
    base_revision: int = Field(ge=0, description="The draft revision the rule manager saw.")


class DiffRuleItem(RuleItem):
    priority: PriorityValue


class ChangedRule(BaseModel):
    before: DiffRuleItem
    after: DiffRuleItem


class ChangedGroup(BaseModel):
    before: RuleGroupItem
    after: RuleGroupItem


class RuleSetDiffView(BaseModel):
    """The draft against the latest published version (rule-proposals Requirement 6)."""

    added_rules: list[DiffRuleItem]
    changed_rules: list[ChangedRule]
    removed_rules: list[DiffRuleItem]
    added_groups: list[RuleGroupItem]
    changed_groups: list[ChangedGroup]
    removed_groups: list[RuleGroupItem]


class PublishRequestItem(BaseModel):
    id: str = Field(description="public_id of the publish request.")
    status: PublishRequestStatusValue
    requester_name: str
    created_at: datetime
    draft_revision: int
    draft_changed: bool = Field(
        description="True while pending when the draft changed after the request; approving fails."
    )
    decided_by_name: str | None
    decided_at: datetime | None
    rejection_reason: str | None
    published_version_number: int | None
    owned: bool


class PublishRequestDetail(PublishRequestItem):
    diff: RuleSetDiffView | None = Field(
        description="Draft against the latest version while the request is pending; else empty."
    )


class PublishRequestPage(BaseModel):
    items: list[PublishRequestItem]
    page: int
    page_size: int
    total: int


class RuleProposerItem(BaseModel):
    user_id: str = Field(description="public_id of the user.")
    username: str
    display_name: str
    granted_by_name: str | None
    granted_at: datetime


class RuleProposerList(BaseModel):
    items: list[RuleProposerItem]
