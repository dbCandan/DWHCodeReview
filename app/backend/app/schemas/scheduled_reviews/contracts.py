"""Scheduled review definitions, their run history and the concurrency setting.

sql-review/PRDs/008-scheduled-review-email API contract. Lengths here are transport bounds only;
the service applies the product limits with their own error codes (schedule_invalid,
recipient_invalid, recipient_domain_not_allowed, schedule_name_duplicate, setting_out_of_range).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.reviews.contracts import (
    SELECTION_TECHNICAL_MAX_ITEMS,
    ObjectSelectionItem,
    RuleGroupId,
)

FrequencyValue = Literal["daily", "weekly", "monthly"]
SelectionModeValue = Literal["filter", "list"]
ScheduledReviewStatusValue = Literal["active", "paused"]
ScheduledRunTriggerValue = Literal["scheduled", "manual", "missed"]
ScheduledRunStateValue = Literal[
    "queued", "running", "completed", "failed", "cancelled", "interrupted", "missed", "skipped"
]
SkipReasonValue = Literal["previous_running", "no_published_rule_set", "no_objects"]
EmailStatusValue = Literal["pending", "sent", "failed", "not_configured"]

_TRANSPORT_TEXT_MAX_LENGTH = 1_000
_TRANSPORT_RECIPIENTS_MAX_ITEMS = 200


class ObjectFilter(BaseModel):
    """The object page's filter, evaluated again at every run so new objects are included."""

    database: str = Field(min_length=1, max_length=128)
    query: str | None = Field(default=None, max_length=200)
    type_code: str | None = Field(default=None, min_length=1, max_length=8)
    from_date: date | None = Field(
        default=None, description="Only objects created or modified on or after this day."
    )


class ObjectSelection(BaseModel):
    mode: SelectionModeValue = Field(
        default="filter", description="'filter' is the default (Decision 4)."
    )
    filter: ObjectFilter | None = Field(default=None, description="Set only for 'filter'.")
    items: list[ObjectSelectionItem] = Field(
        default_factory=list,
        max_length=SELECTION_TECHNICAL_MAX_ITEMS,
        description="Set only for 'list'; bounded only technically like a review request.",
    )


class SchedulePeriod(BaseModel):
    frequency: FrequencyValue
    hour: int = Field(description="Local hour 0-23.")
    minute: int = Field(description="Local minute 0-59.")
    timezone: str = Field(default="Europe/Istanbul", max_length=_TRANSPORT_TEXT_MAX_LENGTH)
    weekday: int | None = Field(
        default=None, description="0 = Monday to 6 = Sunday; only for weekly."
    )
    day_of_month: int | None = Field(default=None, description="1-28; only for monthly.")


class ScheduledReviewWrite(BaseModel):
    name: str = Field(max_length=_TRANSPORT_TEXT_MAX_LENGTH)
    selection: ObjectSelection
    rule_group_ids: list[RuleGroupId] = Field(
        default_factory=list,
        max_length=50,
        description="Named groups of the latest published version; empty runs every rule.",
    )
    period: SchedulePeriod
    recipients: list[str] = Field(max_length=_TRANSPORT_RECIPIENTS_MAX_ITEMS)


class ScheduledRuleGroup(BaseModel):
    id: str
    name: str | None = Field(
        description="Name in the latest published version; empty when the group no longer exists."
    )


class LastScheduledRun(BaseModel):
    due_at: datetime
    trigger: ScheduledRunTriggerValue
    state: ScheduledRunStateValue
    email_status: EmailStatusValue | None
    error_code: str | None = Field(
        default=None, description="Stable code when the run could not start or failed."
    )
    finding_count: int | None = Field(description="Set when the review run is still stored.")
    review_run_id: str | None = Field(description="public_id of the review run, if stored.")


class ScheduledReviewItem(BaseModel):
    id: str
    name: str
    owner_display_name: str
    owned: bool = Field(description="True when the caller owns the definition.")
    selection: ObjectSelection
    selection_summary: str
    rule_groups: list[ScheduledRuleGroup]
    period: SchedulePeriod
    recipient_count: int
    status: ScheduledReviewStatusValue
    next_run_at: datetime | None
    last_run: LastScheduledRun | None
    missed: bool = Field(description="The last trigger was missed (kaçırıldı).")
    email_failed: bool = Field(description="The last summary e-mail could not be sent.")
    can_edit: bool
    can_run_now: bool = Field(description="Only the super admin may trigger a run (Decision 9).")


class ScheduledReviewDetail(ScheduledReviewItem):
    recipients: list[str]


class ScheduledReviewPage(BaseModel):
    items: list[ScheduledReviewItem]
    page: int
    page_size: int
    total: int


class ScheduledRunItem(BaseModel):
    id: str
    review_run_id: str | None = Field(
        description="public_id of the review run; the report opens with the history endpoints."
    )
    due_at: datetime
    trigger: ScheduledRunTriggerValue
    triggered_by_name: str | None = Field(description="Super admin of a manual trigger.")
    state: ScheduledRunStateValue
    skip_reason: SkipReasonValue | None
    error_code: str | None = Field(
        default=None,
        description=(
            "Stable code when the run could not start or failed, for example "
            "'sql_connection_not_configured' or 'llm_not_configured'."
        ),
    )
    started_at: datetime | None
    finished_at: datetime | None
    finding_count: int | None
    email_status: EmailStatusValue | None
    email_attempts: int


class ScheduledRunPage(BaseModel):
    items: list[ScheduledRunItem]
    page: int
    page_size: int
    total: int


class ScheduledRunQueued(BaseModel):
    id: str = Field(description="public_id of the queued run record.")
    state: Literal["queued"] = "queued"


class ScheduledReviewSettings(BaseModel):
    max_concurrent_runs: int = Field(
        description="Scheduled runs allowed at the same time in the tenant, 1-10 (Decision 8)."
    )
