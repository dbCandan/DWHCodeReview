"""Run one rule on a piece of SQL without the catalog (rule test endpoint, rule assistant)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.llm import LlmConfig
from app.services.rule_engine import (
    EngineFinding,
    RuleError,
    RuleSpec,
    applies_to,
    default_context,
    precondition_met,
    run_rule,
)

METADATA_NOTE = "Bu kural katalog metadatası gerektirir; tam sonuç için analiz çalıştırın."
LLM_MISSING = "LLM ayarları etkin değil veya eksik."
DEFAULT_OBJECT_NAME = "dbo.TestNesnesi"


@dataclass(slots=True)
class TestOutcome:
    findings: list[EngineFinding] = field(default_factory=list)
    error: str | None = None


def test_sql(
    rule: RuleSpec,
    sql: str,
    object_name: str | None = None,
    object_type: str | None = None,
    database: str | None = None,
    llm_config: LlmConfig | None = None,
) -> TestOutcome:
    """Same semantics as `POST /api/rules/test` (exceptions are not applied)."""
    if object_type and not applies_to(rule, object_type):
        return TestOutcome(error="Kural bu nesne tipine uygulanmıyor (object_types).")
    if database and not applies_to(rule, None, database):
        return TestOutcome(error="Kural bu veritabanına uygulanmıyor (databases).")
    if object_name and not applies_to(rule, None, None, object_name):
        return TestOutcome(error="Kural bu nesne adına uygulanmıyor (name_pattern).")
    try:
        if not precondition_met(rule, sql):
            return TestOutcome(
                error="Ön koşul (precondition) eşleşmedi; kural bu SQL için çalışmaz."
            )
    except RuleError as error:
        return TestOutcome(error=str(error))
    if rule.kind == "llm" and llm_config is None:
        return TestOutcome(error=LLM_MISSING)
    name = object_name or DEFAULT_OBJECT_NAME
    context = default_context(name, database or "")
    try:
        found = run_rule(rule, sql, name, llm_config, context)
    except RuleError as error:
        return TestOutcome(findings=list(error.findings), error=str(error))
    return TestOutcome(found, METADATA_NOTE if rule.needs_metadata else None)
