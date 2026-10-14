"""Review values shared by the object, script and history capabilities.

sql-review/PRDs/003-object-review Requirement 13 and 20: rule results, findings, statuses and
severities are domain types; the review services build them and the repository stores them. The
text-bearing fields stay out of ``repr`` so reviewed SQL and model text never reach a log line.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.models.review import (
    FINDING_TEXT_MAX_LENGTH,
    LABEL_MAX_LENGTH,
    LINE_REFERENCE_MAX_LENGTH,
    REVIEWED_SQL_MAX_LENGTH,
    RULE_RESULT_TEXT_MAX_LENGTH,
    RuleResultStatus,
    Severity,
)
from app.domain.models.rule_set import RulePriorityGroup
from app.domain.rule_set import PublishedRuleSet

__all__ = [
    "FINDING_TEXT_MAX_LENGTH",
    "LABEL_MAX_LENGTH",
    "LINE_REFERENCE_MAX_LENGTH",
    "REVIEWED_SQL_MAX_LENGTH",
    "RULE_RESULT_TEXT_MAX_LENGTH",
    "SCRIPT_DEFAULT_LABEL",
    "SCRIPT_SCHEMA",
    "SCRIPT_TYPE",
    "Finding",
    "MetadataContext",
    "MetadataSource",
    "ObjectOutcome",
    "ObjectSelection",
    "ReviewRule",
    "RuleCheck",
    "RulePriorityGroup",
    "RuleResultStatus",
    "Severity",
    "TextReview",
    "ordered_rules",
    "severity_for_tier",
]

SCRIPT_SCHEMA = "sql"
SCRIPT_TYPE = "SCRIPT"
SCRIPT_DEFAULT_LABEL = "Yapıştırılan SQL"


@dataclass(frozen=True, slots=True)
class ReviewRule:
    """One rule of the pinned version as the review sends it: code, groups, text and flag.

    ``group_names`` are the rule's named groups in the pinned version, in group order, empty when
    ungrouped (sql-review/PRDs/007-rule-group-selection Requirement 6); they never reach the LLM.
    """

    code: str
    tier: RulePriorityGroup
    text: str = field(repr=False)
    requires_metadata: bool = False
    group_names: tuple[str, ...] = ()


def ordered_rules(rule_set: PublishedRuleSet) -> tuple[ReviewRule, ...]:
    """Critical rules first, then normal rules, each in published order (Requirement 7)."""

    return tuple(
        ReviewRule(
            rule.code,
            tier,
            rule.text,
            rule.requires_metadata,
            rule_set.rules.names_of(rule),
        )
        for tier, rules in rule_set.rules.grouped()
        for rule in rules
    )


def severity_for_tier(tier: RulePriorityGroup) -> Severity:
    """Critical rules report HIGH and normal rules LOW (Requirement 10)."""

    return Severity.HIGH if tier is RulePriorityGroup.CRITICAL else Severity.LOW


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """The verdict for one rule; ``severity`` is set only for a FAIL verdict."""

    rule_code: str
    tier: RulePriorityGroup
    status: RuleResultStatus
    severity: Severity | None = None
    decision_basis: str = ""
    description: str = field(default="", repr=False)
    line_reference: str = ""
    code_snippet: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class Finding:
    """A single violation; its description is the correction note (Decision 1)."""

    rule_code: str
    severity: Severity
    description: str = field(repr=False)
    line_reference: str = ""
    code_snippet: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class TextReview:
    """Rule checks in rule order, the findings and the merged object warning of one text."""

    checks: tuple[RuleCheck, ...]
    findings: tuple[Finding, ...]
    warning: str | None = field(default=None, repr=False)


class MetadataSource(StrEnum):
    """Where the object metadata of a flagged rule comes from (Requirement 6)."""

    # Pasted text: there is no SQL Server object, so the flagged rule gets a fixed note.
    NOT_AVAILABLE_FOR_SCRIPT = "script"
    # The catalog answered; the text may be empty when nothing was found.
    FETCHED = "fetched"
    # The catalog call failed; the flagged rule is told to rely on the SQL text only.
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MetadataContext:
    source: MetadataSource
    text: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class ObjectSelection:
    """A selected SQL Server object; the script run uses the fixed script identity."""

    database: str
    schema: str
    name: str
    type_code: str


@dataclass(frozen=True, slots=True)
class ObjectOutcome:
    """The finished review of one object or of the pasted text."""

    position: int
    source_sql: str | None = field(default=None, repr=False)
    error_code: str | None = None
    error_message: str | None = None
    review: TextReview | None = None

    @property
    def checks(self) -> Sequence[RuleCheck]:
        return () if self.review is None else self.review.checks

    @property
    def findings(self) -> Sequence[Finding]:
        return () if self.review is None else self.review.findings

    @property
    def warning(self) -> str | None:
        return None if self.review is None else self.review.warning
