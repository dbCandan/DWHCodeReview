"""Rule and group proposals and the publish-request difference (sql-review/PRDs/009-rule-proposals).

A proposal is validated when it is sent and applied when the super admin approves it: the
approved rule or group is added to the latest published content, which becomes the next version,
and the same change is written to the draft (Decision 2). The difference of a publish request
compares the draft with the latest published version. Rule text and summaries are never logged;
the dataclasses keep them out of their repr.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.domain.models.rule_set import (
    RULE_GROUP_NAME_MAX_LENGTH,
    RULE_GROUPS_MAX,
    RULE_SET_MAX_RULES,
    RULE_TEXT_MAX_LENGTH,
    RulePriorityGroup,
)
from app.domain.rule_set import (
    Rule,
    RuleGroup,
    RuleGroups,
    RuleSetValidationError,
    fold_group_name,
    normalize_summary,
)


class ProposalConflictError(RuleSetValidationError):
    """The approval no longer fits the latest version: 409 proposal_conflict (Requirement 5)."""

    def __init__(self, message: str) -> None:
        super().__init__("proposal_conflict", message)


@dataclass(frozen=True, slots=True)
class ProposedRule:
    """A validated new-rule proposal: summary, detailed text, priority, flag and groups."""

    summary: str = field(repr=False)
    text: str = field(repr=False)
    priority: RulePriorityGroup
    requires_metadata: bool
    rule_group_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposedGroup:
    """A validated new-group proposal: name, description and member rule codes."""

    name: str = field(repr=False)
    description: str = field(repr=False)
    rule_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleSetDiff:
    """What a publish request changes against the latest published version (Requirement 6).

    Rules carry their priority; a changed rule is listed with its published and draft form.
    """

    added_rules: tuple[tuple[RulePriorityGroup, Rule], ...] = ()
    changed_rules: tuple[tuple[RulePriorityGroup, Rule, RulePriorityGroup, Rule], ...] = ()
    removed_rules: tuple[tuple[RulePriorityGroup, Rule], ...] = ()
    added_groups: tuple[RuleGroup, ...] = ()
    changed_groups: tuple[tuple[RuleGroup, RuleGroup], ...] = ()
    removed_groups: tuple[RuleGroup, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.added_rules,
                self.changed_rules,
                self.removed_rules,
                self.added_groups,
                self.changed_groups,
                self.removed_groups,
            )
        )


def validate_rule_proposal(
    *,
    summary: str,
    text: str,
    priority: RulePriorityGroup,
    requires_metadata: bool,
    rule_group_ids: Sequence[str],
) -> ProposedRule:
    """A new-rule proposal needs both a one-sentence summary and a detailed text (Decision 4)."""

    trimmed_summary = normalize_summary(summary)
    if not trimmed_summary:
        raise RuleSetValidationError(
            "rule_summary_invalid", "Kural önerisi tek cümlelik bir özet içermelidir."
        )
    trimmed_text = text.strip()
    if not trimmed_text:
        raise RuleSetValidationError("rule_text_invalid", "Ayrıntılı kural metni boş olamaz.")
    if len(trimmed_text) > RULE_TEXT_MAX_LENGTH:
        raise RuleSetValidationError(
            "rule_text_too_long", "Kural metni en çok 8.000 karakter olabilir."
        )
    return ProposedRule(
        trimmed_summary,
        trimmed_text,
        priority,
        requires_metadata,
        tuple(dict.fromkeys(rule_group_ids)),
    )


def validate_group_proposal(
    name: str, description: str, rule_codes: Sequence[str]
) -> ProposedGroup:
    """A new-group proposal needs a name and at least one rule (Requirement 3)."""

    trimmed = name.strip()
    if not 1 <= len(trimmed) <= RULE_GROUP_NAME_MAX_LENGTH:
        raise RuleSetValidationError(
            "rule_group_name_invalid", "Kural grubu adı 1-80 karakter olmalıdır."
        )
    codes = tuple(dict.fromkeys(rule_codes))
    if not codes:
        raise RuleSetValidationError(
            "proposal_rules_empty", "Grup önerisi en az bir kural içermelidir."
        )
    return ProposedGroup(trimmed, description.strip(), codes)


def with_rule_proposal(
    rules: RuleGroups, proposal: ProposedRule, code: str, *, strict: bool = True
) -> RuleGroups:
    """``rules`` with the proposed rule added at the end of its priority under ``code``.

    On the published content (``strict``) a group the version no longer has, or a full rule set,
    is a conflict. On the draft a group the draft no longer has is skipped, since the draft's
    unpublished changes are not part of this approval.
    """

    order = {group.public_id: position for position, group in enumerate(rules.rule_groups)}
    missing = [group_id for group_id in proposal.rule_group_ids if group_id not in order]
    if strict and missing:
        raise ProposalConflictError("Önerinin kural grubu en son yayımlanmış sürümde artık yok.")
    if len(rules.codes) >= RULE_SET_MAX_RULES:
        raise ProposalConflictError("Kural kümesi 200 kurala ulaştı; öneri eklenemez.")
    memberships = sorted(
        (group_id for group_id in proposal.rule_group_ids if group_id in order),
        key=order.__getitem__,
    )
    rule = Rule(
        code, proposal.text, proposal.requires_metadata, tuple(memberships), proposal.summary
    )
    if proposal.priority is RulePriorityGroup.CRITICAL:
        return replace(rules, critical=(*rules.critical, rule))
    return replace(rules, normal=(*rules.normal, rule))


def with_group_proposal(
    rules: RuleGroups, proposal: ProposedGroup, group_id: str, *, strict: bool = True
) -> RuleGroups:
    """``rules`` with the proposed group added last and its rules made members.

    A taken name (Turkish case folding) or a full group list is always a conflict. On the
    published content (``strict``) a proposed rule the version no longer has is a conflict; on
    the draft it is skipped.
    """

    if len(rules.rule_groups) >= RULE_GROUPS_MAX:
        raise ProposalConflictError("Bir sürümde en çok 50 kural grubu olur; öneri eklenemez.")
    folded = fold_group_name(proposal.name)
    if any(fold_group_name(group.name) == folded for group in rules.rule_groups):
        raise ProposalConflictError("Bu adla bir kural grubu artık var.")
    members = set(proposal.rule_codes)
    if strict and not members <= rules.codes:
        raise ProposalConflictError("Önerinin bir kuralı en son yayımlanmış sürümde artık yok.")

    def joined(rule: Rule) -> Rule:
        if rule.code not in members:
            return rule
        return replace(rule, rule_group_ids=(*rule.rule_group_ids, group_id))

    return RuleGroups(
        critical=tuple(joined(rule) for rule in rules.critical),
        normal=tuple(joined(rule) for rule in rules.normal),
        rule_groups=(*rules.rule_groups, RuleGroup(group_id, proposal.name, proposal.description)),
    )


def _by_code(rules: RuleGroups) -> dict[str, tuple[RulePriorityGroup, Rule]]:
    return {rule.code: (tier, rule) for tier, members in rules.grouped() for rule in members}


def diff_rule_sets(published: RuleGroups | None, draft: RuleGroups) -> RuleSetDiff:
    """The rules and groups a publish request adds, changes and removes (Requirement 6).

    A rule changes when its priority, text, summary, flag or group memberships differ; a move
    inside its priority alone is not listed. A group changes when its name or description differ.
    """

    before = _by_code(published or RuleGroups())
    after = _by_code(draft)
    old_groups = {group.public_id: group for group in (published or RuleGroups()).rule_groups}
    new_groups = {group.public_id: group for group in draft.rule_groups}

    def same(left: tuple[RulePriorityGroup, Rule], right: tuple[RulePriorityGroup, Rule]) -> bool:
        (left_tier, left_rule), (right_tier, right_rule) = left, right
        return left_tier is right_tier and (
            left_rule.text,
            left_rule.summary,
            left_rule.requires_metadata,
            set(left_rule.rule_group_ids),
        ) == (
            right_rule.text,
            right_rule.summary,
            right_rule.requires_metadata,
            set(right_rule.rule_group_ids),
        )

    return RuleSetDiff(
        added_rules=tuple(entry for code, entry in after.items() if code not in before),
        changed_rules=tuple(
            (*before[code], *entry)
            for code, entry in after.items()
            if code in before and not same(before[code], entry)
        ),
        removed_rules=tuple(entry for code, entry in before.items() if code not in after),
        added_groups=tuple(group for key, group in new_groups.items() if key not in old_groups),
        changed_groups=tuple(
            (old_groups[key], group)
            for key, group in new_groups.items()
            if key in old_groups
            and (old_groups[key].name, old_groups[key].description)
            != (group.name, group.description)
        ),
        removed_groups=tuple(group for key, group in old_groups.items() if key not in new_groups),
    )
