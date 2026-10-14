"""Rule-set rules that need no persistence (sql-review/PRDs/001-rule-management).

Normalization and identifier checks of a submitted draft, the canonical content digest that
decides whether a publish creates a new version, and the published rule set that review runs
pin when they start. Named rule groups, multiple group membership and the run's group and rule
selection belong to sql-review/PRDs/007-rule-group-selection. Rule text is never logged; the dataclasses
keep it out of their repr.
"""

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.domain.models.rule_set import (
    RULE_CODE_PATTERN,
    RULE_GROUP_NAME_MAX_LENGTH,
    RULE_GROUPS_MAX,
    RULE_SET_MAX_RULES,
    RULE_SUMMARY_MAX_LENGTH,
    RULE_TEXT_MAX_LENGTH,
    RulePriorityGroup,
)

_RULE_CODE = re.compile(RULE_CODE_PATTERN)


@dataclass(frozen=True, slots=True)
class Rule:
    """One review rule: its KuralNN code, text, object-metadata flag, named groups and summary.

    ``rule_group_ids`` are the public identifiers of the named groups the rule belongs to, in the
    draft's or version's group order; empty for an ungrouped rule (rule-group-selection
    Decision 1). ``summary`` is the one-sentence summary shown instead of the text, empty when not
    given (rule-management Requirement 12); only the text reaches the LLM.
    """

    code: str
    text: str = field(repr=False)
    requires_metadata: bool = False
    rule_group_ids: tuple[str, ...] = ()
    summary: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class RuleGroup:
    """A named rule group; independent of the critical/normal priority (Decision 2)."""

    public_id: str
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class RuleGroups:
    """Rules of a draft or version in their two priority groups, in LLM order.

    ``rule_groups`` are the named group definitions of the same draft or version.
    """

    critical: tuple[Rule, ...] = ()
    normal: tuple[Rule, ...] = ()
    rule_groups: tuple[RuleGroup, ...] = ()

    def grouped(self) -> Iterable[tuple[RulePriorityGroup, tuple[Rule, ...]]]:
        yield RulePriorityGroup.CRITICAL, self.critical
        yield RulePriorityGroup.NORMAL, self.normal

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(rule.code for rule in (*self.critical, *self.normal))

    @property
    def is_empty(self) -> bool:
        return not self.critical and not self.normal

    def group_names_of(self, code: str) -> tuple[str, ...]:
        """Names of the named groups of the rule with this code, in group order."""

        for rule in (*self.critical, *self.normal):
            if rule.code == code:
                return self.names_of(rule)
        return ()

    def names_of(self, rule: Rule) -> tuple[str, ...]:
        """Names of the given rule's groups, in group order; unknown identifiers are skipped."""

        names = {group.public_id: group.name for group in self.rule_groups}
        return tuple(names[group_id] for group_id in rule.rule_group_ids if group_id in names)


@dataclass(frozen=True, slots=True)
class PublishedRuleSet:
    """The latest published version a review run pins once, at its start (Requirement 7)."""

    version_id: int
    number: int
    rules: RuleGroups

    def select(
        self, rule_group_ids: Sequence[str], rule_codes: Sequence[str] = ()
    ) -> "PublishedRuleSet":
        """The pinned version restricted to the selected groups and rules (rule-group-selection).

        Raises ``RuleSetValidationError`` for an unknown group or rule, or an empty union.
        """

        return PublishedRuleSet(
            self.version_id, self.number, select_rules(self.rules, rule_group_ids, rule_codes)
        )


class RuleSetValidationError(Exception):
    """A rejected draft; the code and Turkish message form the 422 error envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def format_rule_code(number: int) -> str:
    """Kural01 ... Kural99, then Kural100 ...; numbers start at 1."""

    if number < 1:
        raise ValueError("rule numbers start at 1")
    return f"Kural{number:02d}"


def rule_number(code: str) -> int | None:
    """The number of a well-formed KuralNN code, otherwise None."""

    match = _RULE_CODE.fullmatch(code)
    return int(match.group(1)) if match else None


def normalize_summary(summary: str) -> str:
    """Trim a rule summary; blank means not given (rule-management Requirement 2).

    A summary is one sentence on one line: more than 200 characters or a line break is rejected.
    """

    trimmed = summary.strip()
    if len(trimmed) > RULE_SUMMARY_MAX_LENGTH or "\n" in trimmed or "\r" in trimmed:
        raise RuleSetValidationError(
            "rule_summary_invalid",
            "Kural özeti tek satırda en çok 200 karakterlik bir cümle olmalıdır.",
        )
    return trimmed


def normalize_rule_groups(groups: Sequence[RuleGroup]) -> tuple[RuleGroup, ...]:
    """Trim names and descriptions and enforce the group limits (rule-group-selection Req. 1).

    Names are unique case-insensitively in Turkish; a draft holds at most 50 groups.
    """

    if len(groups) > RULE_GROUPS_MAX:
        raise RuleSetValidationError(
            "rule_group_too_many", "Bir sürümde en çok 50 kural grubu olur."
        )
    kept: list[RuleGroup] = []
    ids: set[str] = set()
    names: set[str] = set()
    for group in groups:
        name = group.name.strip()
        description = group.description.strip()
        if not group.public_id or group.public_id in ids:
            raise RuleSetValidationError("rule_group_name_invalid", "Kural grubu kimliği geçersiz.")
        if not 1 <= len(name) <= RULE_GROUP_NAME_MAX_LENGTH:
            raise RuleSetValidationError(
                "rule_group_name_invalid", "Kural grubu adı 1-80 karakter olmalıdır."
            )
        folded = fold_group_name(name)
        if folded in names:
            raise RuleSetValidationError(
                "rule_group_name_duplicate", "Aynı adla iki kural grubu tanımlanamaz."
            )
        ids.add(group.public_id)
        names.add(folded)
        kept.append(RuleGroup(group.public_id, name, description))
    return tuple(kept)


def normalize_draft(
    critical: Sequence[Rule],
    normal: Sequence[Rule],
    *,
    rule_groups: Sequence[RuleGroup] = (),
) -> RuleGroups:
    """Trim texts, drop blank rules and enforce the format, uniqueness and size limits.

    Requirement 2 and the format/duplicate half of Requirement 3; whether a new code was used
    before needs the stored history and is checked by ``next_rule_number_after``. A rule may
    belong only to groups defined in the same draft, each at most once; its memberships are kept
    in the draft's group order (rule-group-selection Requirement 2, Decision 1).
    """

    definitions = normalize_rule_groups(rule_groups)
    order = {group.public_id: position for position, group in enumerate(definitions)}
    groups: list[tuple[Rule, ...]] = []
    seen: set[str] = set()
    for submitted in (critical, normal):
        kept: list[Rule] = []
        for rule in submitted:
            text = rule.text.strip()
            if not text:
                continue
            if rule_number(rule.code) is None:
                raise RuleSetValidationError(
                    "rule_id_invalid", "Kural kimliği KuralNN biçiminde olmalıdır."
                )
            if rule.code in seen:
                raise RuleSetValidationError(
                    "rule_id_duplicate", "Aynı kural kimliği birden çok kurala verilemez."
                )
            if len(text) > RULE_TEXT_MAX_LENGTH:
                raise RuleSetValidationError(
                    "rule_text_too_long", "Kural metni en çok 8.000 karakter olabilir."
                )
            summary = normalize_summary(rule.summary)
            memberships = set(rule.rule_group_ids)
            if len(memberships) != len(rule.rule_group_ids) or not memberships <= order.keys():
                raise RuleSetValidationError(
                    "rule_group_unknown_membership",
                    "Kural, taslakta tanımlı olmayan bir gruba veya aynı gruba iki kez atanamaz.",
                )
            seen.add(rule.code)
            kept.append(
                Rule(
                    rule.code,
                    text,
                    rule.requires_metadata,
                    tuple(sorted(memberships, key=order.__getitem__)),
                    summary,
                )
            )
        groups.append(tuple(kept))
    if len(seen) > RULE_SET_MAX_RULES:
        raise RuleSetValidationError("rule_set_too_large", "Taslak en çok 200 kural içerebilir.")
    return RuleGroups(critical=groups[0], normal=groups[1], rule_groups=definitions)


def select_rules(
    rules: RuleGroups, rule_group_ids: Sequence[str], rule_codes: Sequence[str] = ()
) -> RuleGroups:
    """The rules a run uses (rule-group-selection Requirement 4, Decision 6).

    An empty selection runs every rule. Otherwise the union of the selected groups' rules and the
    selected single rules runs once each, in the pinned version's critical-first order. The group
    definitions stay those of the whole version so every result keeps its group names.
    """

    if not rule_group_ids and not rule_codes:
        return rules
    groups = set(rule_group_ids)
    if not groups <= {group.public_id for group in rules.rule_groups}:
        raise RuleSetValidationError(
            "rule_group_unknown", "Seçilen kural grubu yayımlanmış sürümde yok."
        )
    codes = set(rule_codes)
    if not codes <= rules.codes:
        raise RuleSetValidationError("rule_unknown", "Seçilen kural yayımlanmış sürümde yok.")

    def chosen(rule: Rule) -> bool:
        return rule.code in codes or not groups.isdisjoint(rule.rule_group_ids)

    critical = tuple(rule for rule in rules.critical if chosen(rule))
    normal = tuple(rule for rule in rules.normal if chosen(rule))
    if not critical and not normal:
        raise RuleSetValidationError(
            "rule_group_selection_empty", "Seçilen kural gruplarında hiç kural yok."
        )
    return RuleGroups(critical=critical, normal=normal, rule_groups=rules.rule_groups)


def fold_group_name(name: str) -> str:
    """Turkish-aware case folding for group name uniqueness (I/ı, İ/i)."""

    return name.replace("I", "ı").replace("İ", "i").lower()


def next_rule_number_after(
    draft: RuleGroups,
    *,
    current_codes: frozenset[str],
    used_codes: frozenset[str],
    next_rule_number: int,
) -> int:
    """Validate the new codes of a normalized draft and return the updated first free number.

    A code already in the current draft keeps its rule. Any other code is a new rule and must be
    at least the first free number and never used in any draft or version of the tenant
    (Requirement 3); numbers below the first free one count as used.
    """

    highest = next_rule_number - 1
    for code in draft.codes - current_codes:
        number = rule_number(code)
        if number is None:  # pragma: no cover - normalize_draft rejects malformed codes first
            raise RuleSetValidationError(
                "rule_id_invalid", "Kural kimliği KuralNN biçiminde olmalıdır."
            )
        if code in used_codes or number < next_rule_number:
            raise RuleSetValidationError(
                "rule_id_reused",
                "Bu kural kimliği daha önce kullanıldı; yeni bir kurala verilemez.",
            )
        highest = max(highest, number)
    return highest + 1


def content_sha256(rules: RuleGroups) -> str:
    """Lower-case SHA-256 of the canonical content: groups, order, codes, texts and flags.

    Named groups and memberships enter the canonical form only when the rule set defines at
    least one group, and a summary only when it is given, so the digest of a rule set without
    them keeps its earlier value and an unchanged draft does not create a new version
    (rule-group-selection and rule-management plans).
    """

    def entry(rule: Rule) -> list[object]:
        values: list[object] = [rule.code, rule.text, rule.requires_metadata]
        if rules.rule_groups:
            values.append(list(rule.rule_group_ids))
        if rule.summary:
            values.append({"summary": rule.summary})
        return values

    canonical: dict[str, object] = {
        group.value: [entry(rule) for rule in members] for group, members in rules.grouped()
    }
    if rules.rule_groups:
        canonical["rule_groups"] = [
            [group.public_id, group.name, group.description] for group in rules.rule_groups
        ]
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
