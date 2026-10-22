"""Rule and group proposals, publish requests and the proposal permission (retired).

sql-review/PRDs/009-rule-proposals Decision 8 removed the proposals: no route reads or writes
these tables any more. They stay in place so earlier records are not dropped silently
(rules/41); the mapping keeps the schema check aligned with the migrations.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.domain.models.mixins import AuditSoftDeleteMixin, new_public_id
from app.domain.models.rule_set import (
    RULE_CODE_PATTERN,
    RULE_GROUP_DESCRIPTION_MAX_LENGTH,
    RULE_GROUP_NAME_MAX_LENGTH,
    RULE_SUMMARY_MAX_LENGTH,
    RULE_TEXT_MAX_LENGTH,
)

PROPOSAL_REASON_MAX_LENGTH = 500


class RuleProposalKind(StrEnum):
    RULE = "rule"
    GROUP = "group"


class ProposalStatus(StrEnum):
    PENDING = "bekliyor"
    APPROVED = "onaylandi"
    REJECTED = "reddedildi"
    WITHDRAWN = "geri_cekildi"


class PublishRequestStatus(StrEnum):
    PENDING = "bekliyor"
    APPROVED = "onaylandi"
    REJECTED = "reddedildi"
    INVALID = "gecersiz"


def _values(kind: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in kind)


_DECIDED_BY_COMMENT = "Deciding super admin; empty while pending. References app_user.user_id."
_REJECTION_COMMENT = (
    "Reason the super admin gave for a rejection, 1-500 characters; shown to the requester and "
    "never logged. Empty unless rejected."
)


class RuleProposal(AuditSoftDeleteMixin, Base):
    __tablename__ = "rule_proposal"
    __table_args__ = (
        Index(
            "ix_rule_proposal_active_tenant_status",
            "tenant_id",
            "status",
            "created_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_rule_proposal_proposer", "proposer_user_id", "created_at"),
        CheckConstraint(f"kind IN ({_values(RuleProposalKind)})", name="kind_allowed"),
        CheckConstraint(f"status IN ({_values(ProposalStatus)})", name="status_allowed"),
        CheckConstraint(
            "kind <> 'rule' OR (char_length(summary) BETWEEN 1 AND "
            f"{RULE_SUMMARY_MAX_LENGTH} AND char_length(rule_text) BETWEEN 1 AND "
            f"{RULE_TEXT_MAX_LENGTH} AND priority_group IN ('critical', 'normal'))",
            name="rule_fields_present",
        ),
        CheckConstraint(
            "kind <> 'group' OR (char_length(group_name) BETWEEN 1 AND "
            f"{RULE_GROUP_NAME_MAX_LENGTH} AND jsonb_array_length(rule_codes) >= 1)",
            name="group_fields_present",
        ),
        CheckConstraint("jsonb_typeof(rule_group_ids) = 'array'", name="rule_group_ids_array"),
        CheckConstraint("jsonb_typeof(rule_codes) = 'array'", name="rule_codes_array"),
        CheckConstraint(
            f"char_length(group_description) <= {RULE_GROUP_DESCRIPTION_MAX_LENGTH}",
            name="group_description_length",
        ),
        CheckConstraint(
            f"char_length(rationale) <= {PROPOSAL_REASON_MAX_LENGTH}", name="rationale_length"
        ),
        CheckConstraint(
            "(status = 'bekliyor') = (decided_at IS NULL)", name="decided_at_matches_status"
        ),
        CheckConstraint(
            "(status IN ('onaylandi', 'reddedildi')) = (decided_by_user_id IS NOT NULL)",
            name="decider_matches_status",
        ),
        CheckConstraint(
            "(status = 'reddedildi') = (rejection_reason IS NOT NULL) AND (rejection_reason IS "
            f"NULL OR char_length(rejection_reason) BETWEEN 1 AND {PROPOSAL_REASON_MAX_LENGTH})",
            name="rejection_reason_matches_status",
        ),
        CheckConstraint(
            "(status = 'onaylandi') = (published_version_number IS NOT NULL)",
            name="published_version_matches_status",
        ),
        CheckConstraint(
            f"new_rule_code IS NULL OR new_rule_code ~ '{RULE_CODE_PATTERN}'",
            name="new_rule_code_format",
        ),
        {
            "comment": (
                "A proposal of a new rule or a new rule group awaiting the super admin's decision "
                "(sql-review rule-proposals). An approved proposal is published as a new version "
                "in the same transaction; a decided proposal never changes again."
            )
        },
    )

    rule_proposal_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(Text, default=new_public_id, nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Owning tenant; references tenant.tenant_id.",
    )
    kind: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment=(
            "Proposal kind; code reflection app.domain.models.rule_proposal.RuleProposalKind: "
            "'rule' = a new rule, 'group' = a new rule group of published rules."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ProposalStatus.PENDING.value,
        server_default=text("'bekliyor'"),
        comment=(
            "Lifecycle; code reflection app.domain.models.rule_proposal.ProposalStatus: "
            "'bekliyor' = awaiting a decision, 'onaylandi' = approved and published, "
            "'reddedildi' = rejected with a reason, 'geri_cekildi' = withdrawn by the proposer."
        ),
    )
    proposer_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Proposing user; references app_user.user_id.",
    )
    summary: Mapped[str] = mapped_column(
        String(RULE_SUMMARY_MAX_LENGTH),
        nullable=False,
        default="",
        server_default=text("''"),
        comment="One-sentence summary of a proposed rule; empty for a group proposal.",
    )
    rule_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
        comment="Detailed text of a proposed rule, sent to the LLM once approved; empty for a group.",
    )
    priority_group: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Priority of a proposed rule: 'critical' or 'normal'; empty for a group.",
    )
    requires_metadata: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    rule_group_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment=(
            "JSON array of public identifiers of published rule groups a proposed rule joins "
            "(rule_set_version_group.rule_group_public_id)."
        ),
    )
    group_name: Mapped[str] = mapped_column(
        String(RULE_GROUP_NAME_MAX_LENGTH),
        nullable=False,
        default="",
        server_default=text("''"),
        comment="Name of a proposed group, unique in the tenant once approved; empty for a rule.",
    )
    group_description: Mapped[str] = mapped_column(
        String(RULE_GROUP_DESCRIPTION_MAX_LENGTH),
        nullable=False,
        default="",
        server_default=text("''"),
    )
    rule_codes: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="JSON array of KuralNN codes of the latest published version a proposed group holds.",
    )
    rationale: Mapped[str] = mapped_column(
        String(PROPOSAL_REASON_MAX_LENGTH),
        nullable=False,
        default="",
        server_default=text("''"),
        comment="Optional short reason of the proposer, at most 500 characters; never logged.",
    )
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=True,
        comment=_DECIDED_BY_COMMENT,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC time of the decision or the withdrawal; empty while pending.",
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(PROPOSAL_REASON_MAX_LENGTH), nullable=True, comment=_REJECTION_COMMENT
    )
    published_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of the version the approval published (rule_set_version.number).",
    )
    new_rule_code: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="KuralNN code an approved rule proposal received."
    )
    new_rule_group_public_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Public identifier an approved group proposal received (rule_set_version_group).",
    )


class RulePublishRequest(AuditSoftDeleteMixin, Base):
    __tablename__ = "rule_publish_request"
    __table_args__ = (
        Index(
            "ix_rule_publish_request_active_tenant_status",
            "tenant_id",
            "status",
            "created_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_rule_publish_request_one_pending",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'bekliyor' AND is_deleted = false"),
        ),
        CheckConstraint(f"status IN ({_values(PublishRequestStatus)})", name="status_allowed"),
        CheckConstraint("draft_revision >= 0", name="draft_revision_not_negative"),
        CheckConstraint(
            "(status = 'bekliyor') = (decided_at IS NULL)", name="decided_at_matches_status"
        ),
        CheckConstraint(
            "(status IN ('onaylandi', 'reddedildi')) = (decided_by_user_id IS NOT NULL)",
            name="decider_matches_status",
        ),
        CheckConstraint(
            "(status = 'reddedildi') = (rejection_reason IS NOT NULL) AND (rejection_reason IS "
            f"NULL OR char_length(rejection_reason) BETWEEN 1 AND {PROPOSAL_REASON_MAX_LENGTH})",
            name="rejection_reason_matches_status",
        ),
        CheckConstraint(
            "(status = 'onaylandi') = (published_version_number IS NOT NULL)",
            name="published_version_matches_status",
        ),
        {
            "comment": (
                "A rule manager's request to publish one revision of the draft (sql-review "
                "rule-proposals Requirement 6). At most one is pending per tenant; a newer request "
                "or a changed draft makes it invalid."
            )
        },
    )

    rule_publish_request_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[str] = mapped_column(Text, default=new_public_id, nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Owning tenant; references tenant.tenant_id.",
    )
    requester_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Requesting rule manager; references app_user.user_id.",
    )
    draft_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Draft revision (rule_set_draft.revision) the request publishes once approved.",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=PublishRequestStatus.PENDING.value,
        server_default=text("'bekliyor'"),
        comment=(
            "Lifecycle; code reflection app.domain.models.rule_proposal.PublishRequestStatus: "
            "'bekliyor' = awaiting a decision, 'onaylandi' = approved and published, "
            "'reddedildi' = rejected with a reason, 'gecersiz' = replaced by a newer request or "
            "made stale by a draft change."
        ),
    )
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=True,
        comment=_DECIDED_BY_COMMENT,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC time of the decision or of becoming invalid; empty while pending.",
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(PROPOSAL_REASON_MAX_LENGTH), nullable=True, comment=_REJECTION_COMMENT
    )
    published_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of the version the approval published (rule_set_version.number).",
    )


class RuleProposer(AuditSoftDeleteMixin, Base):
    __tablename__ = "rule_proposer"
    __table_args__ = (
        Index(
            "ix_rule_proposer_active_tenant",
            "tenant_id",
            postgresql_where=text("is_deleted = false"),
        ),
        {
            "comment": (
                "The 'kural önerebilir' permission the super admin gives a user (sql-review "
                "rule-proposals Requirement 1). Revoking soft-deletes the row; granting again "
                "revives it."
            )
        },
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.tenant_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Tenant the permission holds in; references tenant.tenant_id.",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="User who may propose rules and groups; references app_user.user_id.",
    )
    granted_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.user_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Super admin who last granted the permission; references app_user.user_id.",
    )
