"""Request and response models (see API_CONTRACT.md)."""

from datetime import date, datetime
import typing
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer

Severity = Literal["critical", "high", "medium", "low", "info"]
RuleKind = Literal["regex", "llm", "builtin"]
BuiltinCheck = Literal[
    "nolock_physical_tables",
    "derived_view_consistency",
    "left_then_inner_join",
    "select_list_subquery",
    "tablock_physical_insert",
    "join_column_type_mismatch",
    "non_sargable_predicates",
    "or_in_predicates",
    "scalar_udf_in_query",
    "window_order_by_type",
    "date_variable_type_mismatch",
    "personnel_flag_view_source",
    "id_literal_filter",
    "calendar_date_predicate",
]
MetadataPrecondition = Literal["references_scd_table", "references_partitioned_table"]
MatchMode = Literal["match", "absent"]
RuleTarget = Literal["definition", "name"]
ObjectType = Literal["PROCEDURE", "VIEW", "FUNCTION_SCALAR", "FUNCTION_INLINE", "FUNCTION_TABLE"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ObjectStatus = Literal["pending", "running", "done", "error"]

SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
BUILTIN_CHECKS: tuple[str, ...] = typing.get_args(BuiltinCheck)
METADATA_PRECONDITIONS: tuple[str, ...] = (
    "references_scd_table",
    "references_partitioned_table",
)
OBJECT_TYPES: tuple[str, ...] = (
    "PROCEDURE",
    "VIEW",
    "FUNCTION_SCALAR",
    "FUNCTION_INLINE",
    "FUNCTION_TABLE",
)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


UtcDatetime = Annotated[datetime, PlainSerializer(iso_utc, return_type=str)]


# ---------------------------------------------------------------- rules
class RuleInput(BaseModel):
    code: str
    name: str
    description: str = ""
    recommendation: str = ""
    severity: Severity = "medium"
    kind: RuleKind = "regex"
    pattern: str | None = None
    match_mode: MatchMode = "match"
    target: RuleTarget = "definition"
    ignore_case: bool = True
    ignore_comments: bool = True
    llm_prompt: str | None = None
    object_types: list[ObjectType] = Field(default_factory=list)
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)
    # v1.1 rule engine (validated in the router with Turkish messages)
    builtin_check: str | None = None
    precondition: str | None = None
    metadata_precondition: str | None = None
    requires_metadata: bool = False
    databases: list[str] = Field(default_factory=list)
    name_pattern: str | None = None
    # live-tester sample (editor test panel)
    sample_sql: str | None = None
    sample_object_name: str | None = None
    sample_object_type: ObjectType | None = None
    sample_database: str | None = None


class RuleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str
    recommendation: str
    severity: Severity
    kind: RuleKind
    pattern: str | None
    match_mode: MatchMode
    target: RuleTarget
    ignore_case: bool
    ignore_comments: bool
    llm_prompt: str | None
    object_types: list[ObjectType]
    enabled: bool
    group_ids: list[int]
    builtin_check: BuiltinCheck | None
    precondition: str | None
    metadata_precondition: MetadataPrecondition | None
    requires_metadata: bool
    databases: list[str]
    name_pattern: str | None
    sample_sql: str | None = None
    sample_object_name: str | None = None
    sample_object_type: ObjectType | None = None
    sample_database: str | None = None
    exception_count: int = 0
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RuleExceptionInput(BaseModel):
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    object_name: str | None = None
    snippet_pattern: str | None = None
    reason: str = ""

    model_config = {"populate_by_name": True}


class RuleExceptionOut(BaseModel):
    id: int
    rule_id: int
    rule_code: str
    database: str | None
    schema_: str | None = Field(serialization_alias="schema")
    object_name: str | None
    snippet_pattern: str | None
    reason: str
    created_at: UtcDatetime


class RuleTestRule(BaseModel):
    """Lenient rule body for the test endpoint (an unsaved form may lack a code)."""

    code: str = "TEST"
    name: str = "Test"
    description: str = ""
    recommendation: str = ""
    severity: Severity = "medium"
    kind: RuleKind = "regex"
    pattern: str | None = None
    match_mode: MatchMode = "match"
    target: RuleTarget = "definition"
    ignore_case: bool = True
    ignore_comments: bool = True
    llm_prompt: str | None = None
    object_types: list[ObjectType] = Field(default_factory=list)
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)
    # v1.1 rule engine (validated in the router with Turkish messages)
    builtin_check: str | None = None
    precondition: str | None = None
    metadata_precondition: str | None = None
    requires_metadata: bool = False
    databases: list[str] = Field(default_factory=list)
    name_pattern: str | None = None
    # live-tester sample (editor test panel)
    sample_sql: str | None = None
    sample_object_name: str | None = None
    sample_object_type: ObjectType | None = None
    sample_database: str | None = None


class RuleTestRequest(BaseModel):
    rule: RuleTestRule
    sql: str = ""
    object_name: str | None = None
    object_type: ObjectType | None = None
    database: str | None = None


class RuleTestFinding(BaseModel):
    line: int | None
    snippet: str
    message: str


class RuleTestResponse(BaseModel):
    findings: list[RuleTestFinding]
    error: str | None


# ---------------------------------------------------------------- groups
class RuleGroupInput(BaseModel):
    name: str
    description: str = ""
    color: str = "#2563EB"
    rule_ids: list[int] = Field(default_factory=list)


class RuleGroupOut(BaseModel):
    id: int
    name: str
    description: str
    color: str
    rule_ids: list[int]
    created_at: UtcDatetime
    updated_at: UtcDatetime


# ---------------------------------------------------------------- connections
class ConnectionInput(BaseModel):
    name: str
    server: str
    port: int = 1433
    username: str
    password: str | None = None
    encrypt: bool = True
    trust_server_certificate: bool = True


class ConnectionTestInput(BaseModel):
    id: int | None = None
    name: str = ""
    server: str = ""
    port: int = 1433
    username: str = ""
    password: str | None = None
    encrypt: bool = True
    trust_server_certificate: bool = True


class ConnectionOut(BaseModel):
    id: int
    name: str
    server: str
    port: int
    username: str
    has_password: bool
    encrypt: bool
    trust_server_certificate: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    server_version: str | None = None
    database_count: int | None = None


class SchemaInfo(BaseModel):
    database: str
    schema_: str = Field(serialization_alias="schema")
    object_count: int


class ObjectFilter(BaseModel):
    databases: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    types: list[ObjectType] = Field(default_factory=list)
    created_from: date | None = None
    created_to: date | None = None
    modified_from: date | None = None
    modified_to: date | None = None
    search: str | None = None


class DbObject(BaseModel):
    database: str
    schema_: str = Field(serialization_alias="schema")
    name: str
    type: ObjectType
    create_date: UtcDatetime | None = None
    modify_date: UtcDatetime | None = None


class ObjectListResponse(BaseModel):
    items: list[DbObject]
    total: int


# ---------------------------------------------------------------- LLM settings
class LlmSettingsInput(BaseModel):
    enabled: bool = False
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    temperature: float = 0.0
    timeout_seconds: int = 120
    chunk_lines: int = 250


class LlmSettingsOut(BaseModel):
    enabled: bool
    base_url: str
    model: str
    has_api_key: bool
    temperature: float
    timeout_seconds: int
    chunk_lines: int


class LlmTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None


class LlmModelList(BaseModel):
    models: list[str] = []
    error: str | None = None


# ---------------------------------------------------------------- analyses
class AnalysisObjectInput(BaseModel):
    database: str
    schema_: str = Field(alias="schema")
    name: str
    type: ObjectType
    create_date: datetime | None = None
    modify_date: datetime | None = None


class AnalysisCreate(BaseModel):
    name: str | None = None
    connection_id: int
    objects: list[AnalysisObjectInput] = Field(default_factory=list)
    rule_ids: list[int] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class AnalysisSummary(BaseModel):
    id: int
    name: str
    connection_id: int | None
    connection_name: str
    status: RunStatus
    object_count: int
    rule_count: int
    total_checks: int
    completed_checks: int
    finding_count: int
    suppressed_count: int = 0
    severity_counts: dict[str, int]
    error: str | None
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    duration_ms: int | None
    schedule_id: int | None = None
    schedule_name: str | None = None
    schedule_run_id: int | None = None


class AnalysisObjectOut(BaseModel):
    id: int
    database: str
    schema_: str = Field(serialization_alias="schema")
    name: str
    type: ObjectType
    create_date: UtcDatetime | None
    modify_date: UtcDatetime | None
    status: ObjectStatus
    error: str | None
    finding_count: int
    suppressed_count: int = 0
    line_count: int


class AnalysisRuleRef(BaseModel):
    id: int | None
    code: str
    name: str
    severity: Severity
    kind: RuleKind


class AnalysisDetail(AnalysisSummary):
    filters: dict[str, Any]
    rules: list[AnalysisRuleRef]
    objects: list[AnalysisObjectOut]


class FindingOut(BaseModel):
    id: int
    object_id: int
    object_label: str
    rule_code: str
    rule_name: str
    severity: Severity
    kind: RuleKind
    line: int | None
    snippet: str
    message: str
    recommendation: str


class ObjectSource(BaseModel):
    definition: str | None
    findings: list[FindingOut]


# ---------------------------------------------------------------- dashboard
class TopRule(BaseModel):
    code: str
    name: str
    severity: Severity
    count: int


class Dashboard(BaseModel):
    rule_count: int
    enabled_rule_count: int
    group_count: int
    connection_count: int
    analysis_count: int
    total_findings: int
    severity_counts: dict[str, int]
    recent_analyses: list[AnalysisSummary]
    top_rules: list[TopRule]
    upcoming_schedules: list["UpcomingSchedule"] = Field(default_factory=list)


class Health(BaseModel):
    status: str
    version: str


# ---------------------------------------------------------------- rule assistant (v1.6)
AssistantStatus = Literal["running", "ready", "failed", "saved", "cancelled"]
AssistantStage = Literal["matching", "drafting", "validating", "refining", "noise", "done"]


class AssistantExample(BaseModel):
    sql: str
    note: str | None = None
    object_type: ObjectType | None = None
    object_name: str | None = None
    database: str | None = None


class AssistantNoiseRequest(BaseModel):
    connection_id: int
    databases: list[str] = Field(default_factory=list)
    object_types: list[ObjectType] = Field(default_factory=list)
    sample_size: int = 50


class AssistantRequest(BaseModel):
    description: str
    positive_examples: list[AssistantExample] = Field(default_factory=list)
    negative_examples: list[AssistantExample] = Field(default_factory=list)
    preferred_kind: RuleKind | None = None
    severity_hint: Severity | None = None
    noise: AssistantNoiseRequest | None = None


class AssistantLogLine(BaseModel):
    at: str
    stage: AssistantStage
    message: str


class AssistantCaseFinding(BaseModel):
    line: int | None
    snippet: str
    message: str


class AssistantCaseResult(BaseModel):
    kind: Literal["positive", "negative"]
    index: int
    passed: bool
    findings: list[AssistantCaseFinding]
    error: str | None
    old_passed: bool | None = None


class AssistantValidation(BaseModel):
    iterations: int
    passed: bool
    cases: list[AssistantCaseResult]


class AssistantNoiseExample(BaseModel):
    object_label: str
    line: int | None
    snippet: str
    message: str


class AssistantNoise(BaseModel):
    status: Literal["skipped", "running", "done", "failed"]
    sampled: int = 0
    objects_with_findings: int = 0
    findings: int = 0
    old_findings: int | None = None
    examples: list[AssistantNoiseExample] = Field(default_factory=list)
    llm_calls: int = 0
    duration_ms: int | None = None
    note: str | None = None


class AssistantSession(BaseModel):
    id: int
    status: AssistantStatus
    stage: AssistantStage
    log: list[AssistantLogLine]
    request: dict[str, Any]
    decision: Literal["extend", "new"] | None
    target_rule_id: int | None
    target_rule_code: str | None
    rationale: str | None
    change_summary: str | None
    builtin_needed: bool
    builtin_note: str | None
    proposal: dict[str, Any] | None
    original: dict[str, Any] | None
    validation: AssistantValidation | None
    noise: AssistantNoise | None
    saved_rule_id: int | None
    error: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AssistantRevalidate(BaseModel):
    proposal: RuleInput
    run_noise: bool = False


class AssistantSave(BaseModel):
    proposal: RuleInput


class AssistantSaveResult(BaseModel):
    rule: RuleOut
    session: AssistantSession


# ---------------------------------------------------------------- scheduled analyses (v1.7)
class ObjectQueryFilter(BaseModel):
    schemas: list[str] = Field(default_factory=list)
    types: list[ObjectType] = Field(default_factory=list)
    created_from: date | None = None
    created_to: date | None = None
    modified_from: date | None = None
    modified_to: date | None = None
    search: str | None = None


class ScheduleScope(BaseModel):
    databases: list[str] = Field(default_factory=list)
    queries: list[ObjectQueryFilter] = Field(default_factory=list)


class RuleSelection(BaseModel):
    mode: Literal["all_enabled", "groups", "rules"] = "all_enabled"
    group_ids: list[int] = Field(default_factory=list)
    rule_ids: list[int] = Field(default_factory=list)


class ScheduleSpec(BaseModel):
    kind: Literal["daily", "weekly", "monthly", "interval"] = "daily"
    time: str = "02:00"
    weekdays: list[int] = Field(default_factory=list)
    month_day: int = 1
    interval_hours: int = 24


class ScheduledAnalysisInput(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    connection_id: int
    scope: ScheduleScope
    rule_selection: RuleSelection = Field(default_factory=RuleSelection)
    schedule: ScheduleSpec = Field(default_factory=ScheduleSpec)
    incremental: bool = True
    first_run_full: bool = True


class ScheduledRunOut(BaseModel):
    id: int
    schedule_id: int
    trigger: Literal["schedule", "manual", "catch_up"]
    status: Literal["running", "completed", "skipped", "failed"]
    reason: str | None
    analysis_id: int | None
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    object_count: int
    changed_object_count: int
    finding_count: int
    new_count: int
    resolved_count: int
    unchanged_count: int


class ScheduledAnalysisOut(BaseModel):
    id: int
    name: str
    description: str
    enabled: bool
    connection_id: int
    connection_name: str
    scope: ScheduleScope
    rule_selection: RuleSelection
    schedule: ScheduleSpec
    incremental: bool
    first_run_full: bool
    schedule_text: str
    next_run_at: UtcDatetime | None
    last_run_at: UtcDatetime | None
    last_run: ScheduledRunOut | None
    watermark_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RunDiffFinding(BaseModel):
    object_label: str
    rule_code: str
    rule_name: str
    severity: Severity
    line: int | None
    snippet: str
    message: str
    finding_id: int | None


class RunDiff(BaseModel):
    new: list[RunDiffFinding]
    resolved: list[RunDiffFinding]
    compared_objects: int


class SchedulePreview(BaseModel):
    object_count: int
    changed_count: int | None
    rule_count: int
    llm_rule_count: int
    estimated_checks: int
    estimated_llm_checks: int
    next_runs: list[UtcDatetime]


class UpcomingSchedule(BaseModel):
    id: int
    name: str
    next_run_at: UtcDatetime | None
    schedule_text: str


Dashboard.model_rebuild()
