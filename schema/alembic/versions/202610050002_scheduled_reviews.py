"""Add scheduled review definitions, their run history, run recipients and the setting.

Expand-only: four new tables, a nullable review_run.scheduled_review_id column and a wider
review_run.kind check that also allows 'scheduled'. Existing rows are unchanged and the previous
application version keeps working with the new schema; it never writes the new kind. Downgrade
refuses to run while any definition, scheduled run record, run recipient, setting or scheduled
review run is stored, so this data is never dropped silently; it restores the previous checks
and drops the new objects once they are empty.

Spec: sql-review/PRDs/008-scheduled-review-email (Veri ve geçiş).

Revision ID: 202610050002
Revises: 202610050001
Create Date: 2026-10-07 16:00:19.509598
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202610050002"
down_revision: str | None = "202610050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows whose loss a downgrade would hide.
_STORED_SCHEDULED_DATA = (
    "SELECT (SELECT count(*) FROM scheduled_review) "
    "+ (SELECT count(*) FROM scheduled_review_run) "
    "+ (SELECT count(*) FROM review_run_recipient) "
    "+ (SELECT count(*) FROM scheduled_review_setting) "
    "+ (SELECT count(*) FROM review_run WHERE kind = 'scheduled')"
)


def upgrade() -> None:
    op.create_table(
        "scheduled_review_setting",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Tenant; references tenant.tenant_id.",
        ),
        sa.Column(
            "max_concurrent_runs",
            sa.Integer(),
            nullable=False,
            comment="Scheduled runs allowed to run at the same time in the tenant, 1-10.",
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
            "max_concurrent_runs BETWEEN 1 AND 10",
            name=op.f("ck_scheduled_review_setting_max_concurrent_runs_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_scheduled_review_setting_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_scheduled_review_setting")),
        comment="Per-tenant scheduled review setting changed by the super admin (Decision 8). Without a row the limit is 2.",
    )
    op.create_index(
        "ix_scheduled_review_setting_active_tenant",
        "scheduled_review_setting",
        ["tenant_id"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "scheduled_review",
        sa.Column(
            "scheduled_review_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning tenant; references tenant.tenant_id.",
        ),
        sa.Column(
            "owner_user_id",
            sa.BigInteger(),
            nullable=False,
            comment="User who owns the definition and its runs; references app_user.user_id.",
        ),
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            comment="Definition name, 1-120 characters; unique per owner regardless of letter case.",
        ),
        sa.Column(
            "selection_mode",
            sa.String(length=8),
            nullable=False,
            comment="How objects are chosen; code reflection app.domain.models.scheduled_review.SelectionMode: 'filter' = database/search/type/date filter evaluated at every run, 'list' = an explicit object list.",
        ),
        sa.Column(
            "selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Object selection: for 'filter' {database, query, type_code, from_date}; for 'list' {items: [{database, schema, name, type_code}]}. Holds object names, never SQL text.",
        ),
        sa.Column(
            "rule_group_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Public identifiers of the selected named rule groups (sql-review rule-group-selection); empty runs every rule.",
        ),
        sa.Column(
            "frequency",
            sa.String(length=8),
            nullable=False,
            comment="Period; code reflection app.domain.scheduled_review.Frequency: 'daily', 'weekly', 'monthly'. No free cron expression is stored.",
        ),
        sa.Column(
            "weekday",
            sa.SmallInteger(),
            nullable=True,
            comment="0 = Monday to 6 = Sunday; set only for weekly runs.",
        ),
        sa.Column(
            "day_of_month",
            sa.SmallInteger(),
            nullable=True,
            comment="Day 1-28 of the month; set only for monthly runs.",
        ),
        sa.Column(
            "run_hour",
            sa.SmallInteger(),
            nullable=False,
            comment="Local hour 0-23 in the definition's time zone.",
        ),
        sa.Column(
            "run_minute",
            sa.SmallInteger(),
            nullable=False,
            comment="Local minute 0-59 in the definition's time zone.",
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            comment="IANA time zone of the run time, e.g. Europe/Istanbul.",
        ),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Lower-cased recipient addresses in allowed corporate domains (personal data; never logged). Removed with the definition.",
        ),
        sa.Column(
            "status",
            sa.String(length=8),
            server_default=sa.text("'active'"),
            nullable=False,
            comment="Code reflection app.domain.models.scheduled_review.ScheduledReviewStatus: 'active' = etkin, 'paused' = duraklatıldı.",
        ),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time of the next due run; recomputed when the definition is resumed.",
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC due time of the last trigger, missed or skipped ones included.",
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
            "(frequency = 'monthly') = (day_of_month IS NOT NULL) AND (day_of_month IS NULL OR day_of_month BETWEEN 1 AND 28)",
            name=op.f("ck_scheduled_review_day_of_month_only_for_monthly"),
        ),
        sa.CheckConstraint(
            "(frequency = 'weekly') = (weekday IS NOT NULL) AND (weekday IS NULL OR weekday BETWEEN 0 AND 6)",
            name=op.f("ck_scheduled_review_weekday_only_for_weekly"),
        ),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')",
            name=op.f("ck_scheduled_review_frequency_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(recipients) = 'array'", name=op.f("ck_scheduled_review_recipients_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rule_group_ids) = 'array'",
            name=op.f("ck_scheduled_review_rule_group_ids_array"),
        ),
        sa.CheckConstraint(
            "selection_mode IN ('filter', 'list')",
            name=op.f("ck_scheduled_review_selection_mode_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused')", name=op.f("ck_scheduled_review_status_allowed")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name=op.f("ck_scheduled_review_name_length")
        ),
        sa.CheckConstraint(
            "run_hour BETWEEN 0 AND 23", name=op.f("ck_scheduled_review_run_hour_range")
        ),
        sa.CheckConstraint(
            "run_minute BETWEEN 0 AND 59", name=op.f("ck_scheduled_review_run_minute_range")
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_scheduled_review_owner_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_scheduled_review_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("scheduled_review_id", name=op.f("pk_scheduled_review")),
        sa.UniqueConstraint("public_id", name=op.f("uq_scheduled_review_public_id")),
        comment="A scheduled review definition (sql-review scheduled-review-email): which objects are reviewed with which rule groups, when, and who receives the summary e-mail. Only the owner and the super admin manage it. Deleted physically together with its run history so recipient addresses do not outlive it.",
    )
    op.create_index(
        "ix_scheduled_review_active_due",
        "scheduled_review",
        ["status", "next_run_at"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        op.f("ix_scheduled_review_owner_user_id"),
        "scheduled_review",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index("ix_scheduled_review_tenant", "scheduled_review", ["tenant_id"], unique=False)
    op.create_index(
        "uq_scheduled_review_owner_name",
        "scheduled_review",
        ["owner_user_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "review_run_recipient",
        sa.Column(
            "review_run_id",
            sa.BigInteger(),
            nullable=False,
            comment="Run; references review_run.review_run_id and is deleted with it.",
        ),
        sa.Column(
            "email",
            sa.String(length=254),
            nullable=False,
            comment="Lower-cased recipient address; never logged.",
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
            "email = lower(email) AND char_length(email) BETWEEN 3 AND 254",
            name=op.f("ck_review_run_recipient_email_lower_length"),
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_run.review_run_id"],
            name=op.f("fk_review_run_recipient_review_run_id_review_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("review_run_id", "email", name=op.f("pk_review_run_recipient")),
        comment="Recipient addresses of a scheduled review run, copied from the definition when the run starts (sql-review scheduled-review-email Requirement 6). An application user whose e-mail matches may read the run's report (review-history-export Decision 8). Personal data; deleted with the run.",
    )
    op.create_index(
        "ix_review_run_recipient_active_email",
        "review_run_recipient",
        ["email"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "scheduled_review_run",
        sa.Column(
            "scheduled_review_run_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column(
            "scheduled_review_id",
            sa.BigInteger(),
            nullable=False,
            comment="Definition; references scheduled_review.scheduled_review_id, deleted with it.",
        ),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owning tenant; references tenant.tenant_id.",
        ),
        sa.Column(
            "review_run_id",
            sa.BigInteger(),
            nullable=True,
            comment="Review run started by this trigger; empty until it starts, for a skip or a missed time, and after the run is deleted. References review_run.review_run_id.",
        ),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="UTC due time of a scheduled or missed trigger; the request time of a manual one.",
        ),
        sa.Column(
            "trigger",
            sa.String(length=16),
            nullable=False,
            comment="Code reflection app.domain.models.scheduled_review.ScheduledRunTrigger: 'scheduled' = periyot, 'manual' = elle tetiklendi, 'missed' = kaçırıldı.",
        ),
        sa.Column(
            "triggered_by_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="Super admin who used Şimdi çalıştır; empty otherwise. References app_user.user_id.",
        ),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            comment="Code reflection app.domain.models.scheduled_review.ScheduledRunState: 'queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted', 'missed', 'skipped'.",
        ),
        sa.Column(
            "skip_reason",
            sa.String(length=32),
            nullable=True,
            comment="Why a trigger was skipped; code reflection app.domain.models.scheduled_review.SkipReason: 'previous_running', 'no_published_rule_set', 'no_objects'.",
        ),
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
            comment="Stable code when the run could not start or ended with an error, for example 'llm_not_configured' or 'rule_group_unknown'; empty otherwise.",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time the review run started.",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time the review run ended.",
        ),
        sa.Column(
            "email_status",
            sa.String(length=16),
            nullable=True,
            comment="Summary e-mail state; code reflection app.domain.models.scheduled_review.EmailStatus: 'pending', 'sent', 'failed' = e-posta gönderilemedi, 'not_configured' = SMTP yok. Empty when no run finished.",
        ),
        sa.Column(
            "email_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Send attempts made: the first one and at most three retries (Decision 7).",
        ),
        sa.Column(
            "next_email_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC time of the next send attempt while email_status is 'pending'.",
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
            "(state = 'skipped') = (skip_reason IS NOT NULL)",
            name=op.f("ck_scheduled_review_run_skip_reason_only_when_skipped"),
        ),
        sa.CheckConstraint(
            "email_status IS NULL OR email_status IN ('pending', 'sent', 'failed', 'not_configured')",
            name=op.f("ck_scheduled_review_run_email_status_allowed"),
        ),
        sa.CheckConstraint(
            "skip_reason IS NULL OR skip_reason IN ('previous_running', 'no_published_rule_set', 'no_objects')",
            name=op.f("ck_scheduled_review_run_skip_reason_allowed"),
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted', 'missed', 'skipped')",
            name=op.f("ck_scheduled_review_run_state_allowed"),
        ),
        sa.CheckConstraint(
            "trigger = 'manual' OR triggered_by_user_id IS NULL",
            name=op.f("ck_scheduled_review_run_trigger_user_only_manual"),
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual', 'missed')",
            name=op.f("ck_scheduled_review_run_trigger_allowed"),
        ),
        sa.CheckConstraint(
            "email_attempts BETWEEN 0 AND 4",
            name=op.f("ck_scheduled_review_run_email_attempts_range"),
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_run.review_run_id"],
            name=op.f("fk_scheduled_review_run_review_run_id_review_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_review_id"],
            ["scheduled_review.scheduled_review_id"],
            name=op.f("fk_scheduled_review_run_scheduled_review_id_scheduled_review"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
            name=op.f("fk_scheduled_review_run_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_scheduled_review_run_triggered_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("scheduled_review_run_id", name=op.f("pk_scheduled_review_run")),
        sa.UniqueConstraint("public_id", name=op.f("uq_scheduled_review_run_public_id")),
        comment="One trigger of a scheduled review definition and its outcome: the review run it started, a skip or a missed due time, and the summary e-mail state. Deleted with the definition.",
    )
    op.create_index(
        "ix_scheduled_review_run_active_definition_due",
        "scheduled_review_run",
        ["scheduled_review_id", "due_at"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_scheduled_review_run_email_due",
        "scheduled_review_run",
        ["next_email_at"],
        unique=False,
        postgresql_where=sa.text("email_status = 'pending'"),
    )
    op.create_index(
        op.f("ix_scheduled_review_run_review_run_id"),
        "scheduled_review_run",
        ["review_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_review_run_state", "scheduled_review_run", ["state"], unique=False
    )
    op.add_column(
        "review_run",
        sa.Column(
            "scheduled_review_id",
            sa.BigInteger(),
            nullable=True,
            comment="Scheduled review definition that started a scheduled run; empty for other runs and after the definition is deleted. References scheduled_review.scheduled_review_id.",
        ),
    )
    op.alter_column(
        "review_run",
        "kind",
        existing_type=sa.VARCHAR(length=16),
        comment="Run kind; code reflection app.domain.models.review.ReviewRunKind: 'object' = SQL Server objects (nesne), 'script' = pasted SQL text (metin), 'scheduled' = objects reviewed by a scheduled review definition (zamanlanmış).",
        existing_comment="Run kind; code reflection app.domain.models.review.ReviewRunKind: 'object' = SQL Server objects (nesne), 'script' = pasted SQL text (metin).",
        existing_nullable=False,
    )
    op.create_index(
        op.f("ix_review_run_scheduled_review_id"),
        "review_run",
        ["scheduled_review_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_review_run_scheduled_review_id_scheduled_review"),
        "review_run",
        "scheduled_review",
        ["scheduled_review_id"],
        ["scheduled_review_id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_review_run_scheduled_review_only_for_scheduled"),
        "review_run",
        "kind = 'scheduled' OR scheduled_review_id IS NULL",
    )
    # A scheduled run reviews objects: the kind check learns the new value and only a script run
    # is limited to one object.
    _replace_check("ck_review_run_kind_allowed", "kind IN ('object', 'script', 'scheduled')")
    _replace_check("ck_review_run_script_has_one_object", "kind <> 'script' OR object_count = 1")


def _replace_check(name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), "review_run", type_="check")
    op.create_check_constraint(op.f(name), "review_run", condition)


def downgrade() -> None:
    stored = op.get_bind().execute(sa.text(_STORED_SCHEDULED_DATA)).scalar_one()
    if stored:
        raise RuntimeError(
            "scheduled review data is stored (definitions, run records, run recipients, the "
            "setting or scheduled runs); remove it before downgrading, it is not dropped silently"
        )
    _replace_check("ck_review_run_script_has_one_object", "kind = 'object' OR object_count = 1")
    _replace_check("ck_review_run_kind_allowed", "kind IN ('object', 'script')")
    op.drop_constraint(
        op.f("ck_review_run_scheduled_review_only_for_scheduled"), "review_run", type_="check"
    )
    op.drop_constraint(
        op.f("fk_review_run_scheduled_review_id_scheduled_review"), "review_run", type_="foreignkey"
    )
    op.drop_index(op.f("ix_review_run_scheduled_review_id"), table_name="review_run")
    op.alter_column(
        "review_run",
        "kind",
        existing_type=sa.VARCHAR(length=16),
        comment="Run kind; code reflection app.domain.models.review.ReviewRunKind: 'object' = SQL Server objects (nesne), 'script' = pasted SQL text (metin).",
        existing_comment="Run kind; code reflection app.domain.models.review.ReviewRunKind: 'object' = SQL Server objects (nesne), 'script' = pasted SQL text (metin), 'scheduled' = objects reviewed by a scheduled review definition (zamanlanmış).",
        existing_nullable=False,
    )
    op.drop_column("review_run", "scheduled_review_id")
    op.drop_index("ix_scheduled_review_run_state", table_name="scheduled_review_run")
    op.drop_index(op.f("ix_scheduled_review_run_review_run_id"), table_name="scheduled_review_run")
    op.drop_index(
        "ix_scheduled_review_run_email_due",
        table_name="scheduled_review_run",
        postgresql_where=sa.text("email_status = 'pending'"),
    )
    op.drop_index(
        "ix_scheduled_review_run_active_definition_due",
        table_name="scheduled_review_run",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("scheduled_review_run")
    op.drop_index(
        "ix_review_run_recipient_active_email",
        table_name="review_run_recipient",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("review_run_recipient")
    op.drop_index("uq_scheduled_review_owner_name", table_name="scheduled_review")
    op.drop_index("ix_scheduled_review_tenant", table_name="scheduled_review")
    op.drop_index(op.f("ix_scheduled_review_owner_user_id"), table_name="scheduled_review")
    op.drop_index(
        "ix_scheduled_review_active_due",
        table_name="scheduled_review",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("scheduled_review")
    op.drop_index(
        "ix_scheduled_review_setting_active_tenant",
        table_name="scheduled_review_setting",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("scheduled_review_setting")
