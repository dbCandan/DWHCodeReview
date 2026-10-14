"""Rule and group proposals and the publish-request difference.

sql-review/PRDs/009-rule-proposals Requirement 2, 3, 5, 6 (Acceptance 1).
"""

import pytest

from app.domain.models.rule_set import RulePriorityGroup
from app.domain.rule_proposal import (
    ProposalConflictError,
    ProposedGroup,
    ProposedRule,
    diff_rule_sets,
    validate_group_proposal,
    validate_rule_proposal,
    with_group_proposal,
    with_rule_proposal,
)
from app.domain.rule_set import Rule, RuleGroup, RuleGroups, RuleSetValidationError

pytestmark = pytest.mark.unit

PERFORMANCE = RuleGroup("grp-perf", "Performans")
SECURITY = RuleGroup("grp-sec", "Güvenlik")


def _published() -> RuleGroups:
    return RuleGroups(
        critical=(
            Rule("Kural01", "NOLOCK yok", rule_group_ids=("grp-sec",), summary="NOLOCK yok."),
            Rule("Kural02", "SELECT * yok"),
        ),
        normal=(Rule("Kural05", "adlandırma", rule_group_ids=("grp-perf",)),),
        rule_groups=(PERFORMANCE, SECURITY),
    )


def _rule(**changes: object) -> ProposedRule:
    values: dict[str, object] = {
        "summary": "  Geçici tablolar silinmelidir.  ",
        "text": "  Geçici tablolar işlem sonunda DROP edilmelidir.  ",
        "priority": RulePriorityGroup.NORMAL,
        "requires_metadata": False,
        "rule_group_ids": ("grp-perf",),
    }
    values.update(changes)
    return validate_rule_proposal(**values)  # type: ignore[arg-type]


# --- Validation -------------------------------------------------------------------------------


def test_a_rule_proposal_is_trimmed_and_keeps_its_groups_once() -> None:
    proposal = _rule(rule_group_ids=("grp-perf", "grp-sec", "grp-perf"))

    assert proposal.summary == "Geçici tablolar silinmelidir."
    assert proposal.text == "Geçici tablolar işlem sonunda DROP edilmelidir."
    assert proposal.rule_group_ids == ("grp-perf", "grp-sec")


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"summary": "   "}, "rule_summary_invalid"),
        ({"summary": "x" * 201}, "rule_summary_invalid"),
        ({"summary": "iki\nsatır"}, "rule_summary_invalid"),
        ({"text": "  "}, "rule_text_invalid"),
        ({"text": "x" * 8001}, "rule_text_too_long"),
    ],
)
def test_a_rule_proposal_needs_a_summary_and_a_detailed_text(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        _rule(**changes)
    assert raised.value.code == code
    assert raised.value.message


def test_a_group_proposal_is_trimmed_and_keeps_its_rules_once() -> None:
    proposal = validate_group_proposal(
        "  Veri kalitesi ", "  açıklama ", ["Kural02", "Kural01", "Kural02"]
    )

    assert proposal == ProposedGroup("Veri kalitesi", "açıklama", ("Kural02", "Kural01"))


@pytest.mark.parametrize(
    ("name", "codes", "code"),
    [
        ("   ", ["Kural01"], "rule_group_name_invalid"),
        ("x" * 81, ["Kural01"], "rule_group_name_invalid"),
        ("Ad", [], "proposal_rules_empty"),
    ],
)
def test_a_group_proposal_needs_a_name_and_rules(name: str, codes: list[str], code: str) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        validate_group_proposal(name, "", codes)
    assert raised.value.code == code


# --- Adding an approved proposal (Decision 2) ---------------------------------------------------


def test_an_approved_rule_joins_the_end_of_its_priority_with_its_groups() -> None:
    published = _published()

    added = with_rule_proposal(published, _rule(rule_group_ids=("grp-sec", "grp-perf")), "Kural13")

    assert [rule.code for rule in added.critical] == ["Kural01", "Kural02"]
    assert [rule.code for rule in added.normal] == ["Kural05", "Kural13"]
    new = added.normal[-1]
    assert new.summary == "Geçici tablolar silinmelidir."
    assert new.rule_group_ids == ("grp-perf", "grp-sec")
    assert added.rule_groups == published.rule_groups


def test_a_critical_proposal_joins_the_critical_rules() -> None:
    added = with_rule_proposal(_published(), _rule(priority=RulePriorityGroup.CRITICAL), "Kural13")

    assert [rule.code for rule in added.critical] == ["Kural01", "Kural02", "Kural13"]


def test_a_rule_proposal_conflicts_with_a_missing_group_or_a_full_rule_set() -> None:
    with pytest.raises(ProposalConflictError):
        with_rule_proposal(_published(), _rule(rule_group_ids=("yok",)), "Kural13")
    full = RuleGroups(critical=tuple(Rule(f"Kural{n:02d}", "x") for n in range(1, 201)))
    with pytest.raises(ProposalConflictError):
        with_rule_proposal(full, _rule(rule_group_ids=()), "Kural201")


def test_on_the_draft_a_group_the_draft_no_longer_has_is_skipped() -> None:
    draft = RuleGroups(critical=(Rule("Kural01", "x"),), rule_groups=(PERFORMANCE,))

    added = with_rule_proposal(
        draft, _rule(rule_group_ids=("grp-perf", "grp-sec")), "Kural13", strict=False
    )

    assert added.normal[-1].rule_group_ids == ("grp-perf",)


def test_an_approved_group_is_added_with_its_rules_as_members() -> None:
    proposal = validate_group_proposal("Veri kalitesi", "", ["Kural05", "Kural01"])

    added = with_group_proposal(_published(), proposal, "grp-new")

    assert added.rule_groups[-1] == RuleGroup("grp-new", "Veri kalitesi", "")
    assert added.critical[0].rule_group_ids == ("grp-sec", "grp-new")
    assert added.critical[1].rule_group_ids == ()
    assert added.normal[0].rule_group_ids == ("grp-perf", "grp-new")


@pytest.mark.parametrize(
    ("name", "codes"),
    [("GÜVENLİK", ["Kural01"]), ("Yeni", ["Kural77"])],
)
def test_a_group_proposal_conflicts_with_a_taken_name_or_a_missing_rule(
    name: str, codes: list[str]
) -> None:
    with pytest.raises(ProposalConflictError):
        with_group_proposal(_published(), validate_group_proposal(name, "", codes), "grp-new")


def test_a_group_proposal_conflicts_when_fifty_groups_exist() -> None:
    full = RuleGroups(
        critical=(Rule("Kural01", "x"),),
        rule_groups=tuple(RuleGroup(f"g{n}", f"Grup {n}") for n in range(50)),
    )
    with pytest.raises(ProposalConflictError):
        with_group_proposal(full, validate_group_proposal("Yeni", "", ["Kural01"]), "grp-new")


def test_on_the_draft_rules_the_draft_no_longer_has_are_skipped() -> None:
    draft = RuleGroups(critical=(Rule("Kural01", "x"),))

    added = with_group_proposal(
        draft, validate_group_proposal("Yeni", "", ["Kural01", "Kural05"]), "grp-new", strict=False
    )

    assert added.critical[0].rule_group_ids == ("grp-new",)


# --- Publish request difference (Requirement 6) -------------------------------------------------


def test_the_difference_lists_added_changed_and_removed_rules_and_groups() -> None:
    published = _published()
    draft = RuleGroups(
        critical=(
            Rule("Kural01", "NOLOCK yok", rule_group_ids=("grp-sec",), summary="Kısa özet."),
            Rule("Kural13", "yeni kural"),
        ),
        normal=(
            Rule("Kural05", "adlandırma", rule_group_ids=("grp-perf",)),
            Rule("Kural02", "SELECT * yok"),
        ),
        rule_groups=(RuleGroup("grp-perf", "Hız"), RuleGroup("grp-new", "Yeni")),
    )

    diff = diff_rule_sets(published, draft)

    assert [rule.code for _, rule in diff.added_rules] == ["Kural13"]
    assert [(before.code, after.code) for _, before, _, after in diff.changed_rules] == [
        ("Kural01", "Kural01"),
        ("Kural02", "Kural02"),
    ]
    # Kural02 moved from critical to normal; Kural05 is unchanged.
    assert [(before_tier, after_tier) for before_tier, _, after_tier, _ in diff.changed_rules] == [
        (RulePriorityGroup.CRITICAL, RulePriorityGroup.CRITICAL),
        (RulePriorityGroup.CRITICAL, RulePriorityGroup.NORMAL),
    ]
    assert diff.removed_rules == ()
    assert [group.public_id for group in diff.added_groups] == ["grp-new"]
    assert [(b.name, a.name) for b, a in diff.changed_groups] == [("Performans", "Hız")]
    assert [group.public_id for group in diff.removed_groups] == ["grp-sec"]
    assert not diff.is_empty


def test_without_a_published_version_every_draft_rule_is_added() -> None:
    draft = RuleGroups(critical=(Rule("Kural01", "x"),))

    diff = diff_rule_sets(None, draft)

    assert [rule.code for _, rule in diff.added_rules] == ["Kural01"]
    assert diff_rule_sets(draft, draft).is_empty
