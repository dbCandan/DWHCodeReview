"""Live progress events of object and script reviews (sql-review 003 and 004 API contract).

Each event travels as one ``data:`` line holding the JSON of one of these models; ``phase``
names the event. ``llm_stream`` carries counters only, never model text.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.reviews.contracts import (
    LiveObjectResultItem,
    ReviewKindValue,
    TierValue,
)


class SelectedRuleGroup(BaseModel):
    id: str = Field(description="Public identifier of the named rule group.")
    name: str


class RunStartedEvent(BaseModel):
    phase: Literal["run_started"] = "run_started"
    run_id: str
    kind: ReviewKindValue
    rule_version: int
    objects_total: int
    selected_rule_groups: list[SelectedRuleGroup] = Field(
        default_factory=list,
        description="Groups the run reviews with, in version order; empty with all_rules.",
    )
    selected_rule_codes: list[str] = Field(
        default_factory=list,
        description="Single rules selected besides the groups, in version order.",
    )
    all_rules: bool = Field(
        default=True, description="True when neither a group nor a rule was selected."
    )


class _ObjectFields(BaseModel):
    kind: ReviewKindValue
    database: str = Field(description="Empty for a script run.")
    object_index: int
    objects_total: int
    object_label: str
    schema_: str = Field(alias="schema", serialization_alias="schema")
    name: str
    type_code: str

    model_config = {"populate_by_name": True}


class ObjectStartEvent(_ObjectFields):
    phase: Literal["object_start"] = "object_start"


class DefinitionFetchEvent(_ObjectFields):
    phase: Literal["definition_fetch"] = "definition_fetch"


class SqlReadyEvent(_ObjectFields):
    phase: Literal["sql_ready"] = "sql_ready"
    sql_length: int


class MetadataFetchEvent(_ObjectFields):
    phase: Literal["metadata_fetch"] = "metadata_fetch"


class MetadataReadyEvent(_ObjectFields):
    phase: Literal["metadata_ready"] = "metadata_ready"


class ObjectErrorEvent(_ObjectFields):
    phase: Literal["object_error"] = "object_error"
    code: str
    message: str


class ObjectDoneEvent(_ObjectFields):
    phase: Literal["object_done"] = "object_done"


class RulesBatchStartEvent(_ObjectFields):
    phase: Literal["rules_batch_start"] = "rules_batch_start"
    rules_total: int


class RuleStartEvent(_ObjectFields):
    phase: Literal["rule_start"] = "rule_start"
    rule_id: str
    tier: TierValue
    rule_index: int
    rules_total: int
    sql_two_part: bool


class LlmStreamEvent(_ObjectFields):
    phase: Literal["llm_stream"] = "llm_stream"
    rule_id: str
    completion_tokens: int | None
    total_chars: int


class RuleDoneEvent(_ObjectFields):
    phase: Literal["rule_done"] = "rule_done"
    rule_id: str
    tier: TierValue
    rule_index: int
    rules_total: int
    ok: bool
    sql_two_part: bool
    completion_tokens: int | None
    total_chars: int | None


class CompleteEvent(BaseModel):
    phase: Literal["complete"] = "complete"
    run_id: str
    results: list[LiveObjectResultItem]
    results_omitted: bool = Field(
        default=False,
        description=(
            "True when the run has more objects than one result page: results stays empty and "
            "the stored run is read page by page from the review run detail."
        ),
    )


class ErrorEvent(BaseModel):
    phase: Literal["error"] = "error"
    code: str
    message: str


ReviewEvent = (
    RunStartedEvent
    | ObjectStartEvent
    | DefinitionFetchEvent
    | SqlReadyEvent
    | MetadataFetchEvent
    | MetadataReadyEvent
    | ObjectErrorEvent
    | ObjectDoneEvent
    | RulesBatchStartEvent
    | RuleStartEvent
    | LlmStreamEvent
    | RuleDoneEvent
    | CompleteEvent
    | ErrorEvent
)
