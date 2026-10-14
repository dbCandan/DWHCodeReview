"""Review history, false-positive and deletion contracts (sql-review 005-review-history-export)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool

from app.schemas.reviews.contracts import ObjectResultItem, ReviewKindValue
from app.schemas.reviews.events import SelectedRuleGroup

ReviewRunStatusValue = Literal["running", "completed", "failed", "cancelled", "interrupted"]
ReviewRunScopeValue = Literal["mine", "all"]


class ReviewRunSummary(BaseModel):
    id: str = Field(description="public_id of the run.")
    kind: ReviewKindValue
    status: ReviewRunStatusValue
    started_at: datetime
    finished_at: datetime | None
    title: str
    subtitle: str | None
    error_code: str | None
    error_message: str | None
    rule_version: int
    object_count: int
    finding_count: int
    owner_display_name: str
    owned: bool = Field(description="True when the caller started the run.")


class ReviewRunPage(BaseModel):
    items: list[ReviewRunSummary]
    page: int
    page_size: int
    total: int


class ReviewRunDetail(ReviewRunSummary):
    label: str | None
    results: list[ObjectResultItem] = Field(
        description=(
            "Stored results of one page of objects in selection order; empty unless the run "
            "completed. Never carries SQL text. object_count is the total number of objects."
        )
    )
    results_page: int = Field(description="The returned page of objects, starting at 1.")
    results_page_size: int = Field(description="Objects per page of this response.")
    selected_rule_groups: list[SelectedRuleGroup] = Field(
        default_factory=list,
        description="Named rule groups the run used, in version order; empty with all_rules.",
    )
    selected_rule_codes: list[str] = Field(
        default_factory=list,
        description="Single rules the run was started with besides the groups.",
    )
    all_rules: bool = Field(
        default=True, description="True when neither a group nor a rule was selected."
    )


class FalsePositiveUpdate(BaseModel):
    false_positive: StrictBool


class FalsePositiveState(BaseModel):
    id: str
    false_positive: bool
    changed_at: datetime | None


class DeletedRuns(BaseModel):
    deleted_count: int
