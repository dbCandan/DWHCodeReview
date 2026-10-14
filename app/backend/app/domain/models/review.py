"""Review runs, their objects, per-rule results and findings.

sql-review/PRDs/003-object-review owns these tables; 004-script-review writes script runs into
them and 005-review-history-export owns the false-positive columns and physical deletion.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.domain.models.mixins import AuditSoftDeleteMixin, new_public_id
from app.domain.models.rule_set import RULE_CODE_PATTERN

REVIEWED_SQL_MAX_LENGTH = 120_000
RULE_RESULT_TEXT_MAX_LENGTH = 500
FINDING_TEXT_MAX_LENGTH = 4000
LINE_REFERENCE_MAX_LENGTH = 500
LABEL_MAX_LENGTH = 200


class ReviewRunKind(StrEnum):
    """What a run reviews: SQL Server objects (nesne) or pasted SQL text (metin).

    A scheduled run (sql-review scheduled-review-email) reviews objects like an object run but
    is started by a scheduled review definition in the background.
    """

    OBJECT = "object"
    SCRIPT = "script"
    SCHEDULED = "scheduled"


class ReviewRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RuleResultStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class Severity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


_SEVERITY_CHECK = "severity IN ('HIGH', 'MEDIUM', 'LOW')"
_SEVERITY_COMMENT = (
    "Severity; code reflection app.domain.models.review.Severity: 'HIGH', 'MEDIUM', 'LOW'. "
    "Critical rules report HIGH, normal rules LOW; an invalid model value becomes LOW."
)
_FALSE_POSITIVE_COMMENT = (
    "True when the run owner marked it as a false positive (sql-review review-history-export)."
)
_FALSE_POSITIVE_BY_COMMENT = (
    "User who last changed false_positive; empty until the first change. "
    "References app_user.user_id."
)
_FALSE_POSITIVE_AT_COMMENT = "UTC time false_positive last changed; empty until the first change."
_LINE_REFERENCE_COMMENT = (
    "Line reference in the original text, for example 'Satır 12' or 'Satır 12–15'; empty when "
    "none could be derived."
)


class ReviewRun(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_run"
    __table_args__ = (
        Index(
            "ix_review_run_active_owner_started",
            "tenant_id",
            "owner_user_id",
            "started_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_review_run_tenant_started", "tenant_id", "started_at"),
        Index("ix_review_run_finished_at", "finished_at"),
        CheckConstraint("kind IN ('object', 'script', 'scheduled')", name="kind_allowed"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled', 'interrupted')",
            name="status_allowed",
        ),
        CheckConstraint("object_count >= 1", name="object_count_positive"),
        CheckConstraint(
            "kind = 'script' OR label IS NULL",
            name="label_only_for_script",
        ),
        CheckConstraint("kind <> 'script' OR object_count = 1", name="script_has_one_object"),
        CheckConstraint(
            "kind = 'scheduled' OR scheduled_review_id IS NULL",
            name="scheduled_review_only_for_scheduled",
        ),
        CheckConstraint(
            f"label IS NULL OR char_length(label) BETWEEN 1 AND {LABEL_MAX_LENGTH}",
            name="label_length",
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        {
            "comment": (
                "One review run of an object selection or a pasted SQL text, pinned to one "
                "published rule-set version (sql-review object-review). Only the owner and the "
                "rule manager may read it. Deleting a run physically removes its objects, "
                "results, findings and stored SQL text in one transaction "
                "(review-history-export); runs are also deleted by the retention job once "
                "finished_at is older than the configured retention days."
            )
        },
    )

    review_run_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(
        Text,
        default=new_public_id,
        nullable=False,
        unique=True,
    )
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
        comment="User who started the run; references app_user.user_id.",
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment=(
            "Run kind; code reflection app.domain.models.review.ReviewRunKind: 'object' = "
            "SQL Server objects (nesne), 'script' = pasted SQL text (metin), 'scheduled' = "
            "objects reviewed by a scheduled review definition (zamanlanmış)."
        ),
    )
    scheduled_review_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("scheduled_review.scheduled_review_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Scheduled review definition that started a scheduled run; empty for other runs "
            "and after the definition is deleted. References "
            "scheduled_review.scheduled_review_id."
        ),
    )
    label: Mapped[str | None] = mapped_column(
        String(LABEL_MAX_LENGTH),
        nullable=True,
        comment="Label of a script run, at most 200 characters; empty for object runs.",
    )
    rule_set_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("rule_set_version.rule_set_version_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment=(
            "Published rule-set version pinned when the run started; references "
            "rule_set_version.rule_set_version_id."
        ),
    )
    object_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of selected objects, at least 1; always 1 for a script run.",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReviewRunStatus.RUNNING.value,
        server_default=text("'running'"),
        comment=(
            "Run state; code reflection app.domain.models.review.ReviewRunStatus: "
            "'running' = sürüyor, 'completed' = tamamlandı, 'failed' = hata, "
            "'cancelled' = iptal edildi (no partial result is stored), "
            "'interrupted' = yarıda kesildi (still running when the process started again)."
        ),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC start time.",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC end time; empty while running. Retention counts from this time.",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Stable error code when the run ended with an error; empty otherwise.",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Safe Turkish error message; never contains driver, SQL or endpoint details.",
    )


class ReviewRunObject(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_run_object"
    __table_args__ = (
        UniqueConstraint("review_run_id", "position", name="uq_review_run_object_run_position"),
        Index(
            "ix_review_run_object_active_run",
            "review_run_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint("position >= 0", name="position_not_negative"),
        CheckConstraint(
            f"source_sql IS NULL OR char_length(source_sql) <= {REVIEWED_SQL_MAX_LENGTH}",
            name="source_sql_length",
        ),
        {
            "comment": (
                "An object (or the single pasted text) inside a review run with the SQL text "
                "that was reviewed. The text is source code of the organization: it is kept "
                "only for the retention period, never logged, and returned only by the export "
                "endpoints to the run owner and the rule manager."
            )
        },
    )

    review_run_object_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    review_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_run.review_run_id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "Owning run; references review_run.review_run_id. Deleting the run deletes the "
            "object (accepted physical deletion)."
        ),
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Zero-based order of the object in the selection."
    )
    database_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="SQL Server database name; empty for a script run.",
    )
    schema_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="SQL Server schema name; 'sql' for a script run.",
    )
    object_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="SQL Server object name, or the label of a script run.",
    )
    type_code: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment=(
            "SQL Server object type code: 'P' procedure, 'V' view, 'FN' scalar function, "
            "'IF' inline table function, 'TF' table function, 'SF' CLR scalar function; "
            "'SCRIPT' for pasted text."
        ),
    )
    object_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SQL Server type description as listed to the user; 'SCRIPT' for pasted text.",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Stable object-level error code, for example 'object_not_found'.",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Safe Turkish object-level error message."
    )
    parse_warning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Merged '[RuleCode] warning' lines of the object, including the truncation note.",
    )
    source_sql: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Reviewed SQL text without line numbers, at most 120000 characters; empty when no "
            "definition could be read."
        ),
    )


class ReviewRuleResult(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_rule_result"
    __table_args__ = (
        UniqueConstraint(
            "review_run_object_id", "position", name="uq_review_rule_result_object_position"
        ),
        Index(
            "ix_review_rule_result_active_object",
            "review_run_object_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(f"rule_code ~ '{RULE_CODE_PATTERN}'", name="rule_code_format"),
        CheckConstraint("priority_group IN ('critical', 'normal')", name="priority_group_allowed"),
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'NOT_APPLICABLE', 'UNKNOWN')", name="status_allowed"
        ),
        CheckConstraint(_SEVERITY_CHECK, name="severity_allowed"),
        CheckConstraint(
            "(status = 'FAIL') = (severity IS NOT NULL)", name="severity_only_for_fail"
        ),
        CheckConstraint("position >= 0", name="position_not_negative"),
        CheckConstraint(
            "(false_positive_changed_at IS NULL) = (false_positive_changed_by IS NULL)",
            name="false_positive_change_is_complete",
        ),
        {
            "comment": (
                "The LLM verdict for one rule on one reviewed object, in published rule order."
            )
        },
    )

    review_rule_result_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(
        Text,
        default=new_public_id,
        nullable=False,
        unique=True,
    )
    review_run_object_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_run_object.review_run_object_id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "Reviewed object; references review_run_object.review_run_object_id and is deleted "
            "with it."
        ),
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Zero-based order: critical rules first, then normal."
    )
    rule_code: Mapped[str] = mapped_column(String(16), nullable=False, comment="KuralNN code.")
    priority_group: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Priority group of the rule: 'critical' or 'normal'.",
    )
    rule_group_names: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment=(
            "JSON array of the names of the rule's named groups in the version the run pinned, "
            "in group order (sql-review rule-group-selection); empty for an ungrouped rule. "
            "Reports and exports show it."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment=(
            "Verdict; code reflection app.domain.models.review.RuleResultStatus: 'PASS' = "
            "uyumlu, 'FAIL' = ihlal var, 'NOT_APPLICABLE' = kapsam dışı, 'UNKNOWN' = "
            "değerlendirilemedi."
        ),
    )
    severity: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        comment=(
            "Severity of a FAIL verdict; code reflection app.domain.models.review.Severity: "
            "'HIGH', 'MEDIUM', 'LOW'. Empty for every other status."
        ),
    )
    decision_basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="The model's stated basis for the verdict (karar dayanağı)."
    )
    explanation: Mapped[str | None] = mapped_column(
        String(RULE_RESULT_TEXT_MAX_LENGTH),
        nullable=True,
        comment="Explanation, at most 500 characters.",
    )
    line_reference: Mapped[str | None] = mapped_column(
        String(LINE_REFERENCE_MAX_LENGTH), nullable=True, comment=_LINE_REFERENCE_COMMENT
    )
    code_snippet: Mapped[str | None] = mapped_column(
        String(RULE_RESULT_TEXT_MAX_LENGTH),
        nullable=True,
        comment="Code excerpt, at most 500 characters; never logged.",
    )
    false_positive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment=_FALSE_POSITIVE_COMMENT,
    )
    false_positive_changed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=True,
        comment=_FALSE_POSITIVE_BY_COMMENT,
    )
    false_positive_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment=_FALSE_POSITIVE_AT_COMMENT
    )


class ReviewFinding(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_finding"
    __table_args__ = (
        UniqueConstraint(
            "review_rule_result_id", "position", name="uq_review_finding_result_position"
        ),
        Index(
            "ix_review_finding_active_result",
            "review_rule_result_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(f"rule_code ~ '{RULE_CODE_PATTERN}'", name="rule_code_format"),
        CheckConstraint(_SEVERITY_CHECK, name="severity_allowed"),
        CheckConstraint("position >= 0", name="position_not_negative"),
        CheckConstraint(
            "(false_positive_changed_at IS NULL) = (false_positive_changed_by IS NULL)",
            name="false_positive_change_is_complete",
        ),
        {
            "comment": (
                "A single violation (bulgu) reported under a rule result; its description is "
                "the correction note. No separate fix-suggestion column exists."
            )
        },
    )

    review_finding_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(
        Text,
        default=new_public_id,
        nullable=False,
        unique=True,
    )
    review_rule_result_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_rule_result.review_rule_result_id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "Rule result the finding belongs to; references "
            "review_rule_result.review_rule_result_id and is deleted with it."
        ),
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Zero-based order of the finding under its rule result."
    )
    rule_code: Mapped[str] = mapped_column(String(16), nullable=False, comment="KuralNN code.")
    severity: Mapped[str] = mapped_column(String(8), nullable=False, comment=_SEVERITY_COMMENT)
    description: Mapped[str] = mapped_column(
        String(FINDING_TEXT_MAX_LENGTH),
        nullable=False,
        comment="'object name: reason' text, at most 4000 characters; never logged.",
    )
    line_reference: Mapped[str | None] = mapped_column(
        String(LINE_REFERENCE_MAX_LENGTH), nullable=True, comment=_LINE_REFERENCE_COMMENT
    )
    code_snippet: Mapped[str | None] = mapped_column(
        String(FINDING_TEXT_MAX_LENGTH),
        nullable=True,
        comment="Code excerpt, at most 4000 characters; never logged.",
    )
    false_positive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment=_FALSE_POSITIVE_COMMENT,
    )
    false_positive_changed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=True,
        comment=_FALSE_POSITIVE_BY_COMMENT,
    )
    false_positive_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment=_FALSE_POSITIVE_AT_COMMENT
    )


class ReviewRunRuleGroup(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_run_rule_group"
    __table_args__ = (
        Index(
            "ix_review_run_rule_group_active_run",
            "review_run_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint("position >= 0", name="position_not_negative"),
        {
            "comment": (
                "A named rule group a review run was started with (sql-review "
                "rule-group-selection), copied from the pinned version. A run without rows used "
                "every rule. Inserted with the run and deleted with it."
            )
        },
    )

    review_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_run.review_run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="Run; references review_run.review_run_id and is deleted with it.",
    )
    rule_group_public_id: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        comment=(
            "Public identifier of the selected group, as in "
            "rule_set_version_group.rule_group_public_id of the pinned version."
        ),
    )
    name: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="Group name in the pinned version."
    )
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Zero-based order of the group in the pinned version.",
    )


class ReviewRunRule(AuditSoftDeleteMixin, Base):
    __tablename__ = "review_run_rule"
    __table_args__ = (
        Index(
            "ix_review_run_rule_active_run",
            "review_run_id",
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(f"rule_code ~ '{RULE_CODE_PATTERN}'", name="rule_code_format"),
        CheckConstraint("position >= 0", name="position_not_negative"),
        {
            "comment": (
                "A single rule a review run was started with besides its groups (sql-review "
                "rule-group-selection Decision 6). A run without rows here and in "
                "review_run_rule_group used every rule. Inserted with the run and deleted with it."
            )
        },
    )

    review_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_run.review_run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="Run; references review_run.review_run_id and is deleted with it.",
    )
    rule_code: Mapped[str] = mapped_column(
        String(16),
        primary_key=True,
        comment="Selected KuralNN code of the pinned version.",
    )
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Zero-based order of the rule in the pinned version, critical rules first.",
    )
