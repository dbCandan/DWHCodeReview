"""Add named rule groups, the rules' group memberships and a review run's rule selection.

Expand-only: new tables and one defaulted column, no change to existing rows, so the previous
application version keeps working with the new schema. Existing versions stay ungrouped and
existing runs read as "every rule". Downgrade refuses to run while any group definition, group
membership, run selection or result group name is stored, so group data is never dropped
silently; it drops the tables and the column once they are empty.

Spec: sql-review/PRDs/007-rule-group-selection (Veri ve geçiş, Decision 1, 4 and 6).

Revision ID: 202610050001
Revises: 202610020001
Create Date: 2026-10-06 09:44:14.335999
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202610050001"
down_revision: str | None = "202610020001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows whose loss a downgrade would hide (Decision 4).
_STORED_GROUP_DATA = (
    "SELECT (SELECT count(*) FROM rule_set_draft_group) "
    "+ (SELECT count(*) FROM rule_set_version_group) "
    "+ (SELECT count(*) FROM rule_set_draft_rule_group) "
    "+ (SELECT count(*) FROM rule_set_version_rule_group) "
    "+ (SELECT count(*) FROM review_run_rule_group) "
    "+ (SELECT count(*) FROM review_run_rule) "
    "+ (SELECT count(*) FROM review_rule_result WHERE rule_group_names <> '[]'::jsonb)"
)


def upgrade() -> None:
    op.create_table(
        "rule_set_draft_group",
        sa.Column(
            "rule_set_draft_group_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column(
            "public_id",
            sa.Text(),
            nullable=False,
            comment="Public identifier of the named rule group. A group keeps the same identifier in the draft and in every version it is published into, so a review run can select it by this value.",
        ),
        sa.Column(
            "rule_set_draft_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning draft; references rule_set_draft.rule_set_draft_id.",
        ),
        sa.Column(
            "name",
            sa.String(length=80),
            nullable=False,
            comment="Group name shown to reviewers, 1-80 characters; unique inside the draft or version regardless of letter case.",
        ),
        sa.Column(
            "description",
            sa.String(length=500),
            server_default=sa.text("''"),
            nullable=False,
            comment="Optional explanation of the group, at most 500 characters; empty when unset.",
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            comment="Zero-based display order of the group in the rule-set screens.",
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
            "char_length(description) <= 500",
            name=op.f("ck_rule_set_draft_group_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name=op.f("ck_rule_set_draft_group_name_length"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_rule_set_draft_group_position_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_draft_id"],
            ["rule_set_draft.rule_set_draft_id"],
            name=op.f("fk_rule_set_draft_group_rule_set_draft_id_rule_set_draft"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_set_draft_group_id", name=op.f("pk_rule_set_draft_group")),
        sa.UniqueConstraint("public_id", name=op.f("uq_rule_set_draft_group_public_id")),
        sa.UniqueConstraint(
            "rule_set_draft_id",
            "rule_set_draft_group_id",
            name="uq_rule_set_draft_group_draft_group",
        ),
        comment="A named rule group of the tenant draft (sql-review rule-group-selection). A save soft-deletes groups removed from the draft together with their memberships.",
    )
    op.create_index(
        "ix_rule_set_draft_group_active_draft",
        "rule_set_draft_group",
        ["rule_set_draft_id", "position"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "rule_set_version_group",
        sa.Column(
            "rule_set_version_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning version; references rule_set_version.rule_set_version_id.",
        ),
        sa.Column(
            "rule_group_public_id",
            sa.Text(),
            nullable=False,
            comment="Public identifier of the named rule group. A group keeps the same identifier in the draft and in every version it is published into, so a review run can select it by this value.",
        ),
        sa.Column(
            "name",
            sa.String(length=80),
            nullable=False,
            comment="Group name shown to reviewers, 1-80 characters; unique inside the draft or version regardless of letter case.",
        ),
        sa.Column(
            "description",
            sa.String(length=500),
            server_default=sa.text("''"),
            nullable=False,
            comment="Group explanation as published, at most 500 characters; empty when unset.",
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            comment="Zero-based display order of the group in the rule-set screens.",
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
            "char_length(description) <= 500",
            name=op.f("ck_rule_set_version_group_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name=op.f("ck_rule_set_version_group_name_length"),
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_rule_set_version_group_position_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_version_id"],
            ["rule_set_version.rule_set_version_id"],
            name=op.f("fk_rule_set_version_group_rule_set_version_id_rule_set_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "rule_set_version_id",
            "rule_group_public_id",
            name=op.f("pk_rule_set_version_group"),
        ),
        comment="A named rule group frozen inside a published version (sql-review rule-group-selection); inserted with its version and never changed.",
    )
    op.create_index(
        "ix_rule_set_version_group_active_version",
        "rule_set_version_group",
        ["rule_set_version_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "review_run_rule_group",
        sa.Column(
            "review_run_id",
            sa.BigInteger(),
            nullable=False,
            comment="Run; references review_run.review_run_id and is deleted with it.",
        ),
        sa.Column(
            "rule_group_public_id",
            sa.Text(),
            nullable=False,
            comment="Public identifier of the selected group, as in rule_set_version_group.rule_group_public_id of the pinned version.",
        ),
        sa.Column(
            "name",
            sa.String(length=80),
            nullable=False,
            comment="Group name in the pinned version.",
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            comment="Zero-based order of the group in the pinned version.",
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
            "position >= 0", name=op.f("ck_review_run_rule_group_position_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_run.review_run_id"],
            name=op.f("fk_review_run_rule_group_review_run_id_review_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "review_run_id",
            "rule_group_public_id",
            name=op.f("pk_review_run_rule_group"),
        ),
        comment="A named rule group a review run was started with (sql-review rule-group-selection), copied from the pinned version. A run without rows used every rule. Inserted with the run and deleted with it.",
    )
    op.create_index(
        "ix_review_run_rule_group_active_run",
        "review_run_rule_group",
        ["review_run_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "review_run_rule",
        sa.Column(
            "review_run_id",
            sa.BigInteger(),
            nullable=False,
            comment="Run; references review_run.review_run_id and is deleted with it.",
        ),
        sa.Column(
            "rule_code",
            sa.String(length=16),
            nullable=False,
            comment="Selected KuralNN code of the pinned version.",
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            comment="Zero-based order of the rule in the pinned version, critical rules first.",
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
        sa.CheckConstraint("position >= 0", name=op.f("ck_review_run_rule_position_not_negative")),
        sa.CheckConstraint(
            "rule_code ~ '^Kural(0[1-9]|[1-9][0-9]+)$'",
            name=op.f("ck_review_run_rule_rule_code_format"),
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_run.review_run_id"],
            name=op.f("fk_review_run_rule_review_run_id_review_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("review_run_id", "rule_code", name=op.f("pk_review_run_rule")),
        comment="A single rule a review run was started with besides its groups (sql-review rule-group-selection Decision 6). A run without rows here and in review_run_rule_group used every rule. Inserted with the run and deleted with it.",
    )
    op.create_index(
        "ix_review_run_rule_active_run",
        "review_run_rule",
        ["review_run_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "rule_set_draft_rule_group",
        sa.Column(
            "rule_set_draft_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning draft; references rule_set_draft_rule and rule_set_draft_group together with the rule code and the group, so both belong to the same draft.",
        ),
        sa.Column(
            "rule_code",
            sa.String(length=16),
            nullable=False,
            comment="Member rule; references rule_set_draft_rule.rule_code with rule_set_draft_id.",
        ),
        sa.Column(
            "rule_set_draft_group_id",
            sa.BigInteger(),
            nullable=False,
            comment="Group; references rule_set_draft_group.rule_set_draft_group_id with rule_set_draft_id.",
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
            ["rule_set_draft_id", "rule_code"],
            ["rule_set_draft_rule.rule_set_draft_id", "rule_set_draft_rule.rule_code"],
            name="fk_rule_set_draft_rule_group_rule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_draft_id", "rule_set_draft_group_id"],
            [
                "rule_set_draft_group.rule_set_draft_id",
                "rule_set_draft_group.rule_set_draft_group_id",
            ],
            name="fk_rule_set_draft_rule_group_group",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "rule_set_draft_id",
            "rule_code",
            "rule_set_draft_group_id",
            name=op.f("pk_rule_set_draft_rule_group"),
        ),
        comment="Membership of a draft rule in a named group of the same draft (sql-review rule-group-selection); a rule may belong to several groups. A save soft-deletes memberships left out and revives a membership added back.",
    )
    op.create_index(
        "ix_rule_set_draft_rule_group_active_draft",
        "rule_set_draft_rule_group",
        ["rule_set_draft_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_rule_set_draft_rule_group_group",
        "rule_set_draft_rule_group",
        ["rule_set_draft_group_id"],
        unique=False,
    )
    op.create_table(
        "rule_set_version_rule_group",
        sa.Column(
            "rule_set_version_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning version; references rule_set_version_rule and rule_set_version_group together with the rule code and the group, so both belong to the same version.",
        ),
        sa.Column(
            "rule_code",
            sa.String(length=16),
            nullable=False,
            comment="Member rule; references rule_set_version_rule.rule_code with the version.",
        ),
        sa.Column(
            "rule_group_public_id",
            sa.Text(),
            nullable=False,
            comment="Group; references rule_set_version_group.rule_group_public_id with the version.",
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
            ["rule_set_version_id", "rule_code"],
            ["rule_set_version_rule.rule_set_version_id", "rule_set_version_rule.rule_code"],
            name="fk_rule_set_version_rule_group_rule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_version_id", "rule_group_public_id"],
            [
                "rule_set_version_group.rule_set_version_id",
                "rule_set_version_group.rule_group_public_id",
            ],
            name="fk_rule_set_version_rule_group_group",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "rule_set_version_id",
            "rule_code",
            "rule_group_public_id",
            name=op.f("pk_rule_set_version_rule_group"),
        ),
        comment="Membership of a published rule in a named group of the same version (sql-review rule-group-selection); inserted with its version and never changed.",
    )
    op.create_index(
        "ix_rule_set_version_rule_group_active_version",
        "rule_set_version_rule_group",
        ["rule_set_version_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.add_column(
        "review_rule_result",
        sa.Column(
            "rule_group_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="JSON array of the names of the rule's named groups in the version the run pinned, in group order (sql-review rule-group-selection); empty for an ungrouped rule. Reports and exports show it.",
        ),
    )


def downgrade() -> None:
    stored = op.get_bind().execute(sa.text(_STORED_GROUP_DATA)).scalar_one()
    if stored:
        raise RuntimeError(
            "rule group data is stored (group definitions, memberships, run selections or "
            "result group names); remove it before downgrading, it is not dropped silently"
        )
    op.drop_column("review_rule_result", "rule_group_names")
    op.drop_index(
        "ix_rule_set_version_rule_group_active_version",
        table_name="rule_set_version_rule_group",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_set_version_rule_group")
    op.drop_index("ix_rule_set_draft_rule_group_group", table_name="rule_set_draft_rule_group")
    op.drop_index(
        "ix_rule_set_draft_rule_group_active_draft",
        table_name="rule_set_draft_rule_group",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_set_draft_rule_group")
    op.drop_index(
        "ix_review_run_rule_active_run",
        table_name="review_run_rule",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("review_run_rule")
    op.drop_index(
        "ix_review_run_rule_group_active_run",
        table_name="review_run_rule_group",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("review_run_rule_group")
    op.drop_index(
        "ix_rule_set_version_group_active_version",
        table_name="rule_set_version_group",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_set_version_group")
    op.drop_index(
        "ix_rule_set_draft_group_active_draft",
        table_name="rule_set_draft_group",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("rule_set_draft_group")
