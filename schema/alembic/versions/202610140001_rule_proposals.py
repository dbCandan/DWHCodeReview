"""Add rule and group proposals, publish requests, the proposal permission and rule summaries.

Expand-only: three new tables and a defaulted summary column on draft and version rules, so the
previous application version keeps working with the new schema. Existing rules keep an empty
summary and are shown with the first sentence of their text. Downgrade refuses to run while any
proposal, publish request, proposal permission or given summary is stored, so that data is never
dropped silently.

Spec: sql-review/PRDs/009-rule-proposals (Veri ve geçiş) and 001-rule-management 1.1.0
(Requirement 2, 12).

Revision ID: 202610140001
Revises: 202610050002
Create Date: 2026-10-14 13:14:14.130593
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202610140001"
down_revision: str | None = "202610050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows whose loss a downgrade would hide.
_STORED_DATA = (
    "SELECT (SELECT count(*) FROM rule_proposal) "
    "+ (SELECT count(*) FROM rule_publish_request) "
    "+ (SELECT count(*) FROM rule_proposer) "
    "+ (SELECT count(*) FROM rule_set_draft_rule WHERE summary <> '') "
    "+ (SELECT count(*) FROM rule_set_version_rule WHERE summary <> '')"
)


def upgrade() -> None:
    op.create_table(
        "rule_proposal",
        sa.Column("rule_proposal_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning tenant; references tenant.tenant_id.",
        ),
        sa.Column(
            "kind",
            sa.String(length=8),
            nullable=False,
            comment="Proposal kind; code reflection app.domain.models.rule_proposal.RuleProposalKind: 'rule' = a new rule, 'group' = a new rule group of published rules.",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'bekliyor'"),
            nullable=False,
            comment="Lifecycle; code reflection app.domain.models.rule_proposal.ProposalStatus: 'bekliyor' = awaiting a decision, 'onaylandi' = approved and published, 'reddedildi' = rejected with a reason, 'geri_cekildi' = withdrawn by the proposer.",
        ),
        sa.Column(
            "proposer_user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Proposing user; references app_user.user_id.",
        ),
        sa.Column(
            "summary",
            sa.String(length=200),
            server_default=sa.text("''"),
            nullable=False,
            comment="One-sentence summary of a proposed rule; empty for a group proposal.",
        ),
        sa.Column(
            "rule_text",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
            comment="Detailed text of a proposed rule, sent to the LLM once approved; empty for a group.",
        ),
        sa.Column(
            "priority_group",
            sa.String(length=16),
            nullable=True,
            comment="Priority of a proposed rule: 'critical' or 'normal'; empty for a group.",
        ),
        sa.Column(
            "requires_metadata", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "rule_group_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="JSON array of public identifiers of published rule groups a proposed rule joins (rule_set_version_group.rule_group_public_id).",
        ),
        sa.Column(
            "group_name",
            sa.String(length=80),
            server_default=sa.text("''"),
            nullable=False,
            comment="Name of a proposed group, unique in the tenant once approved; empty for a rule.",
        ),
        sa.Column(
            "group_description", sa.String(length=500), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "rule_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="JSON array of KuralNN codes of the latest published version a proposed group holds.",
        ),
        sa.Column(
            "rationale",
            sa.String(length=500),
            server_default=sa.text("''"),
            nullable=False,
            comment="Optional short reason of the proposer, at most 500 characters; never logged.",
        ),
        sa.Column(
            "decided_by_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="Deciding super admin; empty while pending. References app_user.user_id.",
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time of the decision or the withdrawal; empty while pending.",
        ),
        sa.Column(
            "rejection_reason",
            sa.String(length=500),
            nullable=True,
            comment="Reason the super admin gave for a rejection, 1-500 characters; shown to the requester and never logged. Empty unless rejected.",
        ),
        sa.Column(
            "published_version_number",
            sa.Integer(),
            nullable=True,
            comment="Number of the version the approval published (rule_set_version.number).",
        ),
        sa.Column(
            "new_rule_code",
            sa.String(length=16),
            nullable=True,
            comment="KuralNN code an approved rule proposal received.",
        ),
        sa.Column(
            "new_rule_group_public_id",
            sa.Text(),
            nullable=True,
            comment="Public identifier an approved group proposal received (rule_set_version_group).",
        ),
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(status = 'bekliyor') = (decided_at IS NULL)",
            name=op.f("ck_rule_proposal_decided_at_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'onaylandi') = (published_version_number IS NOT NULL)",
            name=op.f("ck_rule_proposal_published_version_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'reddedildi') = (rejection_reason IS NOT NULL) AND (rejection_reason IS NULL OR char_length(rejection_reason) BETWEEN 1 AND 500)",
            name=op.f("ck_rule_proposal_rejection_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "(status IN ('onaylandi', 'reddedildi')) = (decided_by_user_id IS NOT NULL)",
            name=op.f("ck_rule_proposal_decider_matches_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rule_codes) = 'array'", name=op.f("ck_rule_proposal_rule_codes_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rule_group_ids) = 'array'",
            name=op.f("ck_rule_proposal_rule_group_ids_array"),
        ),
        sa.CheckConstraint(
            "kind <> 'group' OR (char_length(group_name) BETWEEN 1 AND 80 AND jsonb_array_length(rule_codes) >= 1)",
            name=op.f("ck_rule_proposal_group_fields_present"),
        ),
        sa.CheckConstraint(
            "kind <> 'rule' OR (char_length(summary) BETWEEN 1 AND 200 AND char_length(rule_text) BETWEEN 1 AND 8000 AND priority_group IN ('critical', 'normal'))",
            name=op.f("ck_rule_proposal_rule_fields_present"),
        ),
        sa.CheckConstraint("kind IN ('rule', 'group')", name=op.f("ck_rule_proposal_kind_allowed")),
        sa.CheckConstraint(
            "new_rule_code IS NULL OR new_rule_code ~ '^Kural(0[1-9]|[1-9][0-9]+)$'",
            name=op.f("ck_rule_proposal_new_rule_code_format"),
        ),
        sa.CheckConstraint(
            "status IN ('bekliyor', 'onaylandi', 'reddedildi', 'geri_cekildi')",
            name=op.f("ck_rule_proposal_status_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(group_description) <= 500",
            name=op.f("ck_rule_proposal_group_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(rationale) <= 500", name=op.f("ck_rule_proposal_rationale_length")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_proposal_decided_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposer_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_proposal_proposer_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_rule_proposal_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_proposal_id", name=op.f("pk_rule_proposal")),
        sa.UniqueConstraint("public_id", name=op.f("uq_rule_proposal_public_id")),
        comment="A proposal of a new rule or a new rule group awaiting the super admin's decision (sql-review rule-proposals). An approved proposal is published as a new version in the same transaction; a decided proposal never changes again.",
    )
    op.create_index(
        "ix_rule_proposal_active_tenant_status",
        "rule_proposal",
        ["tenant_id", "status", "created_at"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_rule_proposal_proposer",
        "rule_proposal",
        ["proposer_user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "rule_proposer",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Tenant the permission holds in; references tenant.tenant_id.",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="User who may propose rules and groups; references app_user.user_id.",
        ),
        sa.Column(
            "granted_by_user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Super admin who last granted the permission; references app_user.user_id.",
        ),
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_proposer_granted_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_rule_proposer_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_proposer_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_rule_proposer")),
        comment="The 'kural önerebilir' permission the super admin gives a user (sql-review rule-proposals Requirement 1). Revoking soft-deletes the row; granting again revives it.",
    )
    op.create_index(
        "ix_rule_proposer_active_tenant",
        "rule_proposer",
        ["tenant_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "rule_publish_request",
        sa.Column(
            "rule_publish_request_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning tenant; references tenant.tenant_id.",
        ),
        sa.Column(
            "requester_user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Requesting rule manager; references app_user.user_id.",
        ),
        sa.Column(
            "draft_revision",
            sa.Integer(),
            nullable=False,
            comment="Draft revision (rule_set_draft.revision) the request publishes once approved.",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'bekliyor'"),
            nullable=False,
            comment="Lifecycle; code reflection app.domain.models.rule_proposal.PublishRequestStatus: 'bekliyor' = awaiting a decision, 'onaylandi' = approved and published, 'reddedildi' = rejected with a reason, 'gecersiz' = replaced by a newer request or made stale by a draft change.",
        ),
        sa.Column(
            "decided_by_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="Deciding super admin; empty while pending. References app_user.user_id.",
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time of the decision or of becoming invalid; empty while pending.",
        ),
        sa.Column(
            "rejection_reason",
            sa.String(length=500),
            nullable=True,
            comment="Reason the super admin gave for a rejection, 1-500 characters; shown to the requester and never logged. Empty unless rejected.",
        ),
        sa.Column(
            "published_version_number",
            sa.Integer(),
            nullable=True,
            comment="Number of the version the approval published (rule_set_version.number).",
        ),
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(status = 'bekliyor') = (decided_at IS NULL)",
            name=op.f("ck_rule_publish_request_decided_at_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'onaylandi') = (published_version_number IS NOT NULL)",
            name=op.f("ck_rule_publish_request_published_version_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'reddedildi') = (rejection_reason IS NOT NULL) AND (rejection_reason IS NULL OR char_length(rejection_reason) BETWEEN 1 AND 500)",
            name=op.f("ck_rule_publish_request_rejection_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "(status IN ('onaylandi', 'reddedildi')) = (decided_by_user_id IS NOT NULL)",
            name=op.f("ck_rule_publish_request_decider_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('bekliyor', 'onaylandi', 'reddedildi', 'gecersiz')",
            name=op.f("ck_rule_publish_request_status_allowed"),
        ),
        sa.CheckConstraint(
            "draft_revision >= 0", name=op.f("ck_rule_publish_request_draft_revision_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_publish_request_decided_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_rule_publish_request_requester_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_rule_publish_request_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_publish_request_id", name=op.f("pk_rule_publish_request")),
        sa.UniqueConstraint("public_id", name=op.f("uq_rule_publish_request_public_id")),
        comment="A rule manager's request to publish one revision of the draft (sql-review rule-proposals Requirement 6). At most one is pending per tenant; a newer request or a changed draft makes it invalid.",
    )
    op.create_index(
        "ix_rule_publish_request_active_tenant_status",
        "rule_publish_request",
        ["tenant_id", "status", "created_at"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        op.f("ix_rule_publish_request_requester_user_id"),
        "rule_publish_request",
        ["requester_user_id"],
        unique=False,
    )
    op.create_index(
        "uq_rule_publish_request_one_pending",
        "rule_publish_request",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'bekliyor' AND is_deleted = false"),
    )
    op.add_column(
        "rule_set_draft_rule",
        sa.Column(
            "summary",
            sa.String(length=200),
            server_default=sa.text("''"),
            nullable=False,
            comment="One-sentence summary shown to everyone but the super admin instead of the rule text, at most 200 characters and without a line break; empty when not given (sql-review rule-management Requirement 12). Never sent to the LLM and never logged.",
        ),
    )
    op.add_column(
        "rule_set_version_rule",
        sa.Column(
            "summary",
            sa.String(length=200),
            server_default=sa.text("''"),
            nullable=False,
            comment="One-sentence summary shown to everyone but the super admin instead of the rule text, at most 200 characters and without a line break; empty when not given (sql-review rule-management Requirement 12). Never sent to the LLM and never logged.",
        ),
    )


def downgrade() -> None:
    stored = op.get_bind().execute(sa.text(_STORED_DATA)).scalar_one()
    if stored:
        raise RuntimeError(
            "rule proposal data is stored (proposals, publish requests, proposal permissions or "
            "rule summaries); remove it before downgrading, it is not dropped silently"
        )
    op.drop_column("rule_set_version_rule", "summary")
    op.drop_column("rule_set_draft_rule", "summary")
    op.drop_index(
        "uq_rule_publish_request_one_pending",
        table_name="rule_publish_request",
        postgresql_where=sa.text("status = 'bekliyor' AND is_deleted = false"),
    )
    op.drop_index(
        op.f("ix_rule_publish_request_requester_user_id"), table_name="rule_publish_request"
    )
    op.drop_index(
        "ix_rule_publish_request_active_tenant_status",
        table_name="rule_publish_request",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_publish_request")
    op.drop_index(
        "ix_rule_proposer_active_tenant",
        table_name="rule_proposer",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_proposer")
    op.drop_index("ix_rule_proposal_proposer", table_name="rule_proposal")
    op.drop_index(
        "ix_rule_proposal_active_tenant_status",
        table_name="rule_proposal",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_proposal")
