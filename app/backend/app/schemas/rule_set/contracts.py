"""Rule-set draft, publish and published-version contracts (sql-review 001-rule-management).

Named rule groups and the rules' group memberships: sql-review 007-rule-group-selection.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from app.domain.models.rule_set import RULE_GROUP_DESCRIPTION_MAX_LENGTH

RuleSetVersionSourceValue = Literal["arayuz", "ice-aktarim"]

# Transport bounds only; the service applies the rule limits (8,000 characters after trimming,
# 200 rules, 80-character group names, 50 groups) with their own error codes. Blank rules are
# dropped before the limits apply.
_TRANSPORT_TEXT_MAX_LENGTH = 16_000
_TRANSPORT_GROUP_MAX_ITEMS = 400
_TRANSPORT_GROUP_NAME_MAX_LENGTH = 160
_TRANSPORT_RULE_GROUPS_MAX_ITEMS = 100
_GROUP_ID_MAX_LENGTH = 64
_TRANSPORT_SUMMARY_MAX_LENGTH = 400


class RuleGroupItem(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=_GROUP_ID_MAX_LENGTH,
        description=(
            "Public identifier of the group; the client generates a UUID for a new group so the "
            "same request can assign rules to it."
        ),
    )
    name: str = Field(max_length=_TRANSPORT_GROUP_NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=RULE_GROUP_DESCRIPTION_MAX_LENGTH)


class RuleItem(BaseModel):
    id: str = Field(max_length=32, description="KuralNN code.")
    text: str = Field(max_length=_TRANSPORT_TEXT_MAX_LENGTH)
    summary: str = Field(
        default="",
        max_length=_TRANSPORT_SUMMARY_MAX_LENGTH,
        description=(
            "One-sentence summary shown instead of the text to everyone but the super admin, "
            "at most 200 characters on one line; empty when not given (rule-management "
            "Requirement 12)."
        ),
    )
    requires_metadata: StrictBool = False
    rule_group_ids: list[Annotated[str, StringConstraints(max_length=_GROUP_ID_MAX_LENGTH)]] = (
        Field(
            default_factory=list,
            max_length=_TRANSPORT_RULE_GROUPS_MAX_ITEMS,
            description=(
                "The rule's named groups in the draft's or version's group order; empty for an "
                "ungrouped rule. A rule may belong to several groups."
            ),
        )
    )


class RuleSetVersionSummary(BaseModel):
    number: int
    published_at: datetime
    published_by_name: str | None = Field(
        description="Display name of the publishing rule manager; empty for the import."
    )
    source: RuleSetVersionSourceValue
    critical_count: int
    normal_count: int


class RuleSetVersionDetail(RuleSetVersionSummary):
    critical: list[RuleItem]
    normal: list[RuleItem]
    groups: list[RuleGroupItem] = Field(description="Named rule groups frozen in the version.")


class RuleSetVersionPage(BaseModel):
    items: list[RuleSetVersionSummary]
    page: int
    page_size: int
    total: int


class RuleSetWorkspace(BaseModel):
    """The draft of the tenant together with the latest published version."""

    revision: int = Field(description="Draft change counter; save and publish must send it.")
    critical: list[RuleItem]
    normal: list[RuleItem]
    groups: list[RuleGroupItem] = Field(description="Named rule groups of the draft, in order.")
    latest_version: RuleSetVersionSummary | None
    draft_differs: bool = Field(description="True when the draft differs from latest_version.")
    next_rule_id: str = Field(description="First free KuralNN code for a new rule.")


class RuleSetDraftUpdate(BaseModel):
    base_revision: int = Field(ge=0)
    critical: list[RuleItem] = Field(default_factory=list, max_length=_TRANSPORT_GROUP_MAX_ITEMS)
    normal: list[RuleItem] = Field(default_factory=list, max_length=_TRANSPORT_GROUP_MAX_ITEMS)
    groups: list[RuleGroupItem] = Field(
        default_factory=list,
        max_length=_TRANSPORT_RULE_GROUPS_MAX_ITEMS,
        description="The whole set of named groups; a group left out is removed from the draft.",
    )


class RuleSetPublishRequest(BaseModel):
    base_revision: int = Field(ge=0)
