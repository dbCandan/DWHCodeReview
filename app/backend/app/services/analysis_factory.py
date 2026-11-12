"""Build an Analysis record (rule snapshots + objects); shared by the API and the scheduler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app import models
from app.services.rule_engine import RuleSpec, applies_to_object


@dataclass(frozen=True, slots=True)
class ObjectRow:
    database: str
    schema: str
    name: str
    type: str
    create_date: datetime | None = None
    modify_date: datetime | None = None


def rule_snapshot(rule: models.Rule) -> models.AnalysisRule:
    return models.AnalysisRule(
        rule_id=rule.id,
        code=rule.code,
        name=rule.name,
        description=rule.description,
        recommendation=rule.recommendation,
        severity=rule.severity,
        kind=rule.kind,
        pattern=rule.pattern,
        match_mode=rule.match_mode,
        target=rule.target,
        ignore_case=rule.ignore_case,
        ignore_comments=rule.ignore_comments,
        llm_prompt=rule.llm_prompt,
        object_types=list(rule.object_types or []),
        builtin_check=rule.builtin_check,
        precondition=rule.precondition,
        metadata_precondition=rule.metadata_precondition,
        requires_metadata=bool(rule.requires_metadata),
        databases=list(rule.databases or []),
        name_pattern=rule.name_pattern,
    )


def count_checks(objects: Sequence[ObjectRow], rules: Sequence[models.Rule]) -> int:
    specs = [RuleSpec.from_obj(rule) for rule in rules]
    return sum(
        1 for o in objects for spec in specs
        if applies_to_object(spec, o.database, o.schema, o.name, o.type)
    )


def build_analysis(
    connection: models.Connection,
    objects: Sequence[ObjectRow],
    rules: Sequence[models.Rule],
    name: str = "",
    filters: dict[str, Any] | None = None,
) -> models.Analysis:
    """A queued Analysis (not added to the session); the caller names it after flush."""
    return models.Analysis(
        name=name.strip()[:200],
        connection_id=connection.id,
        connection_name=connection.name,
        status="queued",
        object_count=len(objects),
        rule_count=len(rules),
        total_checks=count_checks(objects, rules),
        completed_checks=0,
        filters=filters or {},
        rules=[rule_snapshot(rule) for rule in rules],
        objects=[
            models.AnalysisObject(
                database=o.database,
                schema=o.schema,
                name=o.name,
                type=o.type,
                create_date=o.create_date.replace(tzinfo=None) if o.create_date else None,
                modify_date=o.modify_date.replace(tzinfo=None) if o.modify_date else None,
            )
            for o in objects
        ],
    )
