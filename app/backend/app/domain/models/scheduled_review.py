"""Scheduled review definitions, their run history, run recipients and the concurrency setting.

sql-review/PRDs/008-scheduled-review-email owns these tables. A definition and its recipient list
are deleted physically, so the addresses (personal data) do not outlive it; the recipient copy of
a run lives as long as the run (review-history-export retention).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.domain.models.mixins import AuditSoftDeleteMixin, new_public_id

SCHEDULED_REVIEW_NAME_MAX_LENGTH = 120
RECIPIENT_EMAIL_MAX_LENGTH = 254
MAX_CONCURRENT_RUNS_MIN = 1
MAX_CONCURRENT_RUNS_MAX = 10
MAX_CONCURRENT_RUNS_DEFAULT = 2


class ScheduledReviewStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class SelectionMode(StrEnum):
    FILTER = "filter"
    LIST = "list"


class ScheduledRunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    MISSED = "missed"


class ScheduledRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    MISSED = "missed"
    SKIPPED = "skipped"


class SkipReason(StrEnum):
    PREVIOUS_RUNNING = "previous_running"
    NO_PUBLISHED_RULE_SET = "no_published_rule_set"
    NO_OBJECTS = "no_objects"


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


def _values(kind: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in kind)


class ScheduledReview(AuditSoftDeleteMixin, Base):
    __tablename__ = "scheduled_review"
    __table_args__ = (
        Index(
            "uq_scheduled_review_owner_name",
            "owner_user_id",
            func.lower(text("name")),
            unique=True,
        ),
        Index(
            "ix_scheduled_review_active_due",
            "status",
            "next_run_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_scheduled_review_tenant", "tenant_id"),
        CheckConstraint(
            f"char_length(name) BETWEEN 1 AND {SCHEDULED_REVIEW_NAME_MAX_LENGTH}",
            name="name_length",
        ),
        CheckConstraint(
            f"selection_mode IN ({_values(SelectionMode)})", name="selection_mode_allowed"
        ),
        CheckConstraint(f"status IN ({_values(ScheduledReviewStatus)})", name="status_allowed"),
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="frequency_allowed"),
        CheckConstraint("run_hour BETWEEN 0 AND 23", name="run_hour_range"),
        CheckConstraint("run_minute BETWEEN 0 AND 59", name="run_minute_range"),
        CheckConstraint(
            "(frequency = 'weekly') = (weekday IS NOT NULL) AND "
            "(weekday IS NULL OR weekday BETWEEN 0 AND 6)",
            name="weekday_only_for_weekly",
        ),
        CheckConstraint(
            "(frequency = 'monthly') = (day_of_month IS NOT NULL) AND "
            "(day_of_month IS NULL OR day_of_month BETWEEN 1 AND 28)",
            name="day_of_month_only_for_monthly",
        ),
        CheckConstraint("jsonb_typeof(rule_group_ids) = 'array'", name="rule_group_ids_array"),
        CheckConstraint("jsonb_typeof(recipients) = 'array'", name="recipients_array"),
        {
            "comment": (
                "A scheduled review definition (sql-review scheduled-review-email): which objects "
                "are reviewed with which rule groups, when, and who receives the summary e-mail. "
                "Only the owner and the super admin manage it. Deleted physically together with "
                "its run history so recipient addresses do not outlive it."
            )
        },
    )

    scheduled_review_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(Text, default=new_public_id, nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Owning tenant; references tenant.tenant_id.",
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User who owns the definition and its runs; references app_user.user_id.",
    )
    name: Mapped[str] = mapped_column(
        String(SCHEDULED_REVIEW_NAME_MAX_LENGTH),
        nullable=False,
        comment="Definition name, 1-120 characters; unique per owner regardless of letter case.",
    )
    selection_mode: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment=(
            "How objects are chosen; code reflection app.domain.models.scheduled_review."
            "SelectionMode: 'filter' = database/search/type/date filter evaluated at every run, "
            "'list' = an explicit object list."
        ),
    )
    selection: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment=(
            "Object selection: for 'filter' {database, query, type_code, from_date}; for 'list' "
            "{items: [{database, schema, name, type_code}]}. Holds object names, never SQL text."
        ),
    )
    rule_group_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment=(
            "Public identifiers of the selected named rule groups (sql-review "
            "rule-group-selection); empty runs every rule."
        ),
    )
    frequency: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment=(
            "Period; code reflection app.domain.scheduled_review.Frequency: 'daily', 'weekly', "
            "'monthly'. No free cron expression is stored."
        ),
    )
    weekday: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, comment="0 = Monday to 6 = Sunday; set only for weekly runs."
    )
    day_of_month: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, comment="Day 1-28 of the month; set only for monthly runs."
    )
    run_hour: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="Local hour 0-23 in the definition's time zone."
    )
    run_minute: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="Local minute 0-59 in the definition's time zone."
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="IANA time zone of the run time, e.g. Europe/Istanbul."
    )
    recipients: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        comment=(
            "Lower-cased recipient addresses in allowed corporate domains (personal data; never "
            "logged). Removed with the definition."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=ScheduledReviewStatus.ACTIVE.value,
        server_default=text("'active'"),
        comment=(
            "Code reflection app.domain.models.scheduled_review.ScheduledReviewStatus: "
            "'active' = etkin, 'paused' = duraklatıldı."
        ),
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC time of the next due run; recomputed when the definition is resumed.",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC due time of the last trigger, missed or skipped ones included.",
    )


class ScheduledReviewRun(AuditSoftDeleteMixin, Base):
    __tablename__ = "scheduled_review_run"
    __table_args__ = (
        Index(
            "ix_scheduled_review_run_active_definition_due",
            "scheduled_review_id",
            "due_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_scheduled_review_run_state", "state"),
        Index(
            "ix_scheduled_review_run_email_due",
            "next_email_at",
            postgresql_where=text("email_status = 'pending'"),
        ),
        CheckConstraint(f"trigger IN ({_values(ScheduledRunTrigger)})", name="trigger_allowed"),
        CheckConstraint(f"state IN ({_values(ScheduledRunState)})", name="state_allowed"),
        CheckConstraint(
            f"skip_reason IS NULL OR skip_reason IN ({_values(SkipReason)})",
            name="skip_reason_allowed",
        ),
        CheckConstraint(
            "(state = 'skipped') = (skip_reason IS NOT NULL)", name="skip_reason_only_when_skipped"
        ),
        CheckConstraint(
            f"email_status IS NULL OR email_status IN ({_values(EmailStatus)})",
            name="email_status_allowed",
        ),
        CheckConstraint("email_attempts BETWEEN 0 AND 4", name="email_attempts_range"),
        CheckConstraint(
            "trigger = 'manual' OR triggered_by_user_id IS NULL", name="trigger_user_only_manual"
        ),
        {
            "comment": (
                "One trigger of a scheduled review definition and its outcome: the review run it "
                "started, a skip or a missed due time, and the summary e-mail state. Deleted with "
                "the definition."
            )
        },
    )

    scheduled_review_run_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(Text, default=new_public_id, nullable=False, unique=True)
    scheduled_review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("scheduled_review.scheduled_review_id", ondelete="CASCADE"),
        nullable=False,
        comment="Definition; references scheduled_review.scheduled_review_id, deleted with it.",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Owning tenant; references tenant.tenant_id.",
    )
    review_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("review_run.review_run_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Review run started by this trigger; empty until it starts, for a skip or a missed "
            "time, and after the run is deleted. References review_run.review_run_id."
        ),
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC due time of a scheduled or missed trigger; the request time of a manual one.",
    )
    trigger: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment=(
            "Code reflection app.domain.models.scheduled_review.ScheduledRunTrigger: "
            "'scheduled' = periyot, 'manual' = elle tetiklendi, 'missed' = kaçırıldı."
        ),
    )
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=True,
        comment="Super admin who used Şimdi çalıştır; empty otherwise. References app_user.user_id.",
    )
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment=(
            "Code reflection app.domain.models.scheduled_review.ScheduledRunState: 'queued', "
            "'running', 'completed', 'failed', 'cancelled', 'interrupted', 'missed', 'skipped'."
        ),
    )
    skip_reason: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment=(
            "Why a trigger was skipped; code reflection app.domain.models.scheduled_review."
            "SkipReason: 'previous_running', 'no_published_rule_set', 'no_objects'."
        ),
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment=(
            "Stable code when the run could not start or ended with an error, for example "
            "'llm_not_configured' or 'rule_group_unknown'; empty otherwise."
        ),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="UTC time the review run started."
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="UTC time the review run ended."
    )
    email_status: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment=(
            "Summary e-mail state; code reflection app.domain.models.scheduled_review.EmailStatus: "
            "'pending', 'sent', 'failed' = e-posta gönderilemedi, 'not_configured' = SMTP yok. "
            "Empty when no run finished."
        ),
    )
    email_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="Send attempts made: the first one and at most three retries (Decision 7).",
    )
    next_email_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC time of the next send attempt while email_status is 'pending'.",
    )


class ReviewRunRecipient(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_run_recipient"
    __table_args__ = (
        Index(
            "ix_review_run_recipient_active_email",
            "email",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            f"email = lower(email) AND char_length(email) BETWEEN 3 AND {RECIPIENT_EMAIL_MAX_LENGTH}",
            name="email_lower_length",
        ),
        {
            "comment": (
                "Recipient addresses of a scheduled review run, copied from the definition when "
                "the run starts (sql-review scheduled-review-email Requirement 6). An application "
                "user whose e-mail matches may read the run's report (review-history-export "
                "Decision 8). Personal data; deleted with the run."
            )
        },
    )

    review_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_run.review_run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="Run; references review_run.review_run_id and is deleted with it.",
    )
    email: Mapped[str] = mapped_column(
        String(RECIPIENT_EMAIL_MAX_LENGTH),
        primary_key=True,
        comment="Lower-cased recipient address; never logged.",
    )


class ScheduledReviewSetting(AuditSoftDeleteMixin, Base):
    __tablename__ = "scheduled_review_setting"
    __table_args__ = (
        Index(
            "ix_scheduled_review_setting_active_tenant",
            "tenant_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            f"max_concurrent_runs BETWEEN {MAX_CONCURRENT_RUNS_MIN} AND {MAX_CONCURRENT_RUNS_MAX}",
            name="max_concurrent_runs_range",
        ),
        {
            "comment": (
                "Per-tenant scheduled review setting changed by the super admin (Decision 8). "
                "Without a row the limit is 2."
            )
        },
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Tenant; references tenant.tenant_id.",
    )
    max_concurrent_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Scheduled runs allowed to run at the same time in the tenant, 1-10.",
    )
