"""Catalog listing, review start and review result contracts (sql-review 003 and 004).

The result shapes are shared by the live ``complete`` event and the stored run detail of
005-review-history-export; only the live event carries the reviewed SQL text.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

RuleResultStatusValue = Literal["PASS", "FAIL", "NOT_APPLICABLE", "UNKNOWN"]
SeverityValue = Literal["HIGH", "MEDIUM", "LOW"]
TierValue = Literal["critical", "normal"]
# A scheduled run (sql-review 008-scheduled-review-email) reviews objects in the background.
ReviewKindValue = Literal["object", "script", "scheduled"]

# Transport bounds only; the services apply the review limits with their own error codes.
_TRANSPORT_SQL_MAX_LENGTH = 1_000_000
# Technical bound of one request body, not a product limit: a run has no object limit
# (003-object-review Decision 3). It keeps the request list finite, as rules/57 requires, far above
# a selection anyone reviews in one run; a longer list answers 422 invalid_request.
SELECTION_TECHNICAL_MAX_ITEMS = 10_000


class DatabasePage(BaseModel):
    items: list[str]
    page: int
    page_size: int
    total: int


class CatalogObjectItem(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    name: str
    type: str
    type_code: str
    created_at: datetime | None
    last_modified: datetime | None

    model_config = {"populate_by_name": True}


class CatalogObjectPage(BaseModel):
    items: list[CatalogObjectItem]
    page: int
    page_size: int
    total: int


class ObjectSelectionItem(BaseModel):
    database: str = Field(min_length=1, max_length=128)
    schema_: str = Field(alias="schema", serialization_alias="schema", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    type_code: str = Field(min_length=1, max_length=8)

    model_config = {"populate_by_name": True}


RuleGroupId = Annotated[str, Field(min_length=1, max_length=64)]
RuleCode = Annotated[str, Field(min_length=1, max_length=16)]
# A version holds at most 200 rules (rule-management Requirement 2).
_RULE_CODES_MAX_ITEMS = 200


class ObjectReviewRequest(BaseModel):
    selections: list[ObjectSelectionItem] = Field(
        max_length=SELECTION_TECHNICAL_MAX_ITEMS,
        description="No product limit; the list length is bounded only technically.",
    )
    rule_group_ids: list[RuleGroupId] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Named rule groups of the latest published version to review with; with rule_codes "
            "the run uses their union, both empty run every rule (rule-group-selection "
            "Requirement 4)."
        ),
    )
    rule_codes: list[RuleCode] = Field(
        default_factory=list,
        max_length=_RULE_CODES_MAX_ITEMS,
        description="Single rules of the latest published version to review with (Decision 6).",
    )


class ScriptReviewRequest(BaseModel):
    sql: str = Field(max_length=_TRANSPORT_SQL_MAX_LENGTH)
    label: str | None = Field(default=None, max_length=_TRANSPORT_SQL_MAX_LENGTH)
    rule_group_ids: list[RuleGroupId] = Field(
        default_factory=list,
        max_length=50,
        description="Named rule groups to review with; with rule_codes empty runs every rule.",
    )
    rule_codes: list[RuleCode] = Field(
        default_factory=list,
        max_length=_RULE_CODES_MAX_ITEMS,
        description="Single rules to review with besides the groups (Decision 6).",
    )


class RuleResultItem(BaseModel):
    id: str = Field(description="public_id of the rule result.")
    rule_id: str
    tier: TierValue
    status: RuleResultStatusValue
    severity: SeverityValue | None = Field(description="Set only for a FAIL verdict.")
    decision_basis: str | None
    description: str
    line_reference: str
    code_snippet: str
    false_positive: bool
    rule_group_names: list[str] = Field(
        default_factory=list,
        description="The rule's named groups in the pinned version, in group order.",
    )


class FindingItem(BaseModel):
    id: str = Field(description="public_id of the finding.")
    rule_id: str
    severity: SeverityValue
    description: str
    line_reference: str
    code_snippet: str
    false_positive: bool


class ObjectResultItem(BaseModel):
    database: str = Field(description="Empty for a script run.")
    schema_: str = Field(alias="schema", serialization_alias="schema")
    name: str
    object_type: str
    type_code: str
    error_code: str | None
    error_message: str | None
    parse_warning: str | None
    rule_results: list[RuleResultItem]
    findings: list[FindingItem]

    model_config = {"populate_by_name": True}


class LiveObjectResultItem(ObjectResultItem):
    source_sql: str | None = Field(
        description="The reviewed text for display in this session; empty on an object error."
    )
