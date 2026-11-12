"""ORM models."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

rule_group_members = Table(
    "rule_group_members",
    Base.metadata,
    Column("rule_id", ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("rule_groups.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RuleEngineMixin:
    """v1.1 rule engine fields, shared by live rules and their analysis snapshots."""

    builtin_check: Mapped[str | None] = mapped_column(String(64), nullable=True)
    precondition: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_precondition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requires_metadata: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    databases: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    name_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)


class Rule(TimestampMixin, RuleEngineMixin, Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_mode: Mapped[str] = mapped_column(String(16), default="match")
    target: Mapped[str] = mapped_column(String(16), default="definition")
    ignore_case: Mapped[bool] = mapped_column(Boolean, default=True)
    ignore_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    groups: Mapped[list["RuleGroup"]] = relationship(
        secondary=rule_group_members, back_populates="rules"
    )
    # Live-tester sample (editor "test" panel); not part of analysis snapshots.
    sample_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_object_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sample_object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sample_database: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exceptions: Mapped[list["RuleException"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", passive_deletes=True,
        order_by="RuleException.id",
    )


class RuleException(Base):
    """Finding suppression: matching findings of the rule are not stored, only counted."""

    __tablename__ = "rule_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), index=True)
    database: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schema: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snippet_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    rule: Mapped[Rule] = relationship(back_populates="exceptions")


class RuleGroup(TimestampMixin, Base):
    __tablename__ = "rule_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(7), default="#2563EB")

    rules: Mapped[list[Rule]] = relationship(
        secondary=rule_group_members, back_populates="groups"
    )


class AppMeta(Base):
    """Key/value store for schema and ruleset versions."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Connection(TimestampMixin, Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    server: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=1433)
    username: Mapped[str] = mapped_column(String(128))
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypt: Mapped[bool] = mapped_column(Boolean, default=True)
    trust_server_certificate: Mapped[bool] = mapped_column(Boolean, default=True)


class LlmSettings(Base):
    """Single row (id=1)."""

    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(500), default="https://api.openai.com/v1")
    model: Mapped[str] = mapped_column(String(200), default="")
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    chunk_lines: Mapped[int] = mapped_column(Integer, default=250, server_default="250")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    connection_name: Mapped[str] = mapped_column(String(100), default="")
    # set when the analysis was started by a scheduled analysis (v1.7); no FK, nulled on delete
    schedule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    schedule_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_count: Mapped[int] = mapped_column(Integer, default=0)
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    completed_checks: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    rules: Mapped[list["AnalysisRule"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="AnalysisRule.id"
    )
    objects: Mapped[list["AnalysisObject"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="AnalysisObject.id"
    )


class AnalysisRule(RuleEngineMixin, Base):
    """Snapshot of a rule at analysis creation; later rule edits do not change history."""

    __tablename__ = "analysis_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_mode: Mapped[str] = mapped_column(String(16), default="match")
    target: Mapped[str] = mapped_column(String(16), default="definition")
    ignore_case: Mapped[bool] = mapped_column(Boolean, default=True)
    ignore_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_types: Mapped[list[str]] = mapped_column(JSON, default=list)


class AnalysisObject(Base):
    __tablename__ = "analysis_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    database: Mapped[str] = mapped_column(String(128))
    schema: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    create_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modify_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def label(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    object_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_objects.id", ondelete="CASCADE"), index=True
    )
    object_label: Mapped[str] = mapped_column(String(400))
    rule_code: Mapped[str] = mapped_column(String(32), index=True)
    rule_name: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")


class RuleAssistantSession(Base):
    """LLM rule assistant run (RULE_ASSISTANT_SPEC v1.6); JSON columns hold the API shapes."""

    __tablename__ = "rule_assistant_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    stage: Mapped[str] = mapped_column(String(16), default="matching")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_rule_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    builtin_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    original: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    noise: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    saved_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduledAnalysis(Base):
    """Periodic analysis definition (SCHEDULED_SPEC v1.7)."""

    __tablename__ = "scheduled_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id", ondelete="RESTRICT"))
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rule_selection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    incremental: Mapped[bool] = mapped_column(Boolean, default=True)
    first_run_full: Mapped[bool] = mapped_column(Boolean, default=True)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    connection: Mapped[Connection] = relationship()
    runs: Mapped[list["ScheduledRun"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="ScheduledRun.id"
    )


class ScheduledRun(Base):
    __tablename__ = "scheduled_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_analyses.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")
    status: Mapped[str] = mapped_column(String(16), default="running")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_object_count: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
