"""Named rule groups: definitions, multiple membership, run selection and the content digest.

sql-review/PRDs/007-rule-group-selection Requirement 1, 3, 4 and Decision 1, 6 (Acceptance 1).
"""

import hashlib
import json

import pytest

from app.domain.rule_set import (
    Rule,
    RuleGroup,
    RuleGroups,
    RuleSetValidationError,
    content_sha256,
    normalize_draft,
    normalize_rule_groups,
    select_rules,
)

pytestmark = pytest.mark.unit

PERFORMANCE = RuleGroup("grp-perf", "Performans", "Sorgu maliyeti")
SECURITY = RuleGroup("grp-sec", "Güvenlik")


def _draft() -> RuleGroups:
    return normalize_draft(
        [
            Rule("Kural01", "NOLOCK yok", rule_group_ids=(SECURITY.public_id,)),
            Rule(
                "Kural03",
                "SELECT * yok",
                rule_group_ids=(SECURITY.public_id, PERFORMANCE.public_id),
            ),
            Rule("Kural05", "geçici tablo silinir"),
        ],
        [Rule("Kural09", "adlandırma", rule_group_ids=(PERFORMANCE.public_id,))],
        rule_groups=[PERFORMANCE, SECURITY],
    )


def test_group_names_and_descriptions_are_trimmed_and_order_is_kept() -> None:
    groups = normalize_rule_groups(
        [
            RuleGroup("a", "  Performans  ", "  açıklama "),
            RuleGroup("b", "Güvenlik", "   "),
        ]
    )

    assert groups == (
        RuleGroup("a", "Performans", "açıklama"),
        RuleGroup("b", "Güvenlik", ""),
    )


@pytest.mark.parametrize(
    ("groups", "code"),
    [
        ([RuleGroup("a", "   ")], "rule_group_name_invalid"),
        ([RuleGroup("a", "x" * 81)], "rule_group_name_invalid"),
        (
            [RuleGroup("a", "Güvenlik"), RuleGroup("b", "güvenlik ")],
            "rule_group_name_duplicate",
        ),
        ([RuleGroup("a", "Bir"), RuleGroup("a", "İki")], "rule_group_name_invalid"),
        ([RuleGroup(f"g{n}", f"Grup {n}") for n in range(51)], "rule_group_too_many"),
    ],
)
def test_malformed_group_definitions_are_rejected(groups: list[RuleGroup], code: str) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        normalize_rule_groups(groups)
    assert raised.value.code == code
    assert raised.value.message


def test_fifty_groups_are_accepted() -> None:
    assert len(normalize_rule_groups([RuleGroup(f"g{n}", f"Grup {n}") for n in range(50)])) == 50


def test_a_rule_belongs_to_several_groups_in_definition_order() -> None:
    draft = _draft()

    assert draft.rule_groups == (PERFORMANCE, SECURITY)
    # Kural03 was submitted as (security, performance) and is kept in the draft's group order.
    assert [rule.rule_group_ids for rule in draft.critical] == [
        ("grp-sec",),
        ("grp-perf", "grp-sec"),
        (),
    ]
    assert draft.normal[0].rule_group_ids == ("grp-perf",)
    assert draft.group_names_of("Kural03") == ("Performans", "Güvenlik")
    assert draft.group_names_of("Kural05") == ()
    assert draft.group_names_of("Kural99") == ()


@pytest.mark.parametrize("memberships", [("yok",), ("grp-sec", "grp-sec")])
def test_an_undefined_or_repeated_membership_is_rejected(memberships: tuple[str, ...]) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        normalize_draft(
            [Rule("Kural01", "x", rule_group_ids=memberships)], [], rule_groups=[SECURITY]
        )
    assert raised.value.code == "rule_group_unknown_membership"


def test_an_empty_selection_runs_every_rule() -> None:
    draft = _draft()

    assert select_rules(draft, []) == draft
    assert select_rules(draft, [], []) == draft


def test_a_group_selection_runs_the_union_of_its_groups_in_critical_first_order() -> None:
    selected = select_rules(_draft(), ["grp-perf"])

    assert [rule.code for rule in selected.critical] == ["Kural03"]
    assert [rule.code for rule in selected.normal] == ["Kural09"]
    assert selected.rule_groups == (PERFORMANCE, SECURITY)

    both = select_rules(_draft(), ["grp-sec", "grp-perf"])
    # Kural03 is in both groups and runs once.
    assert [rule.code for rule in both.critical] == ["Kural01", "Kural03"]
    assert both.rule_groups == (PERFORMANCE, SECURITY)


def test_single_rules_join_the_group_selection_once() -> None:
    selected = select_rules(_draft(), ["grp-sec"], ["Kural09", "Kural05", "Kural01"])

    assert [rule.code for rule in selected.critical] == ["Kural01", "Kural03", "Kural05"]
    assert [rule.code for rule in selected.normal] == ["Kural09"]
    # The group definitions stay those of the whole version so results keep their group names.
    assert selected.rule_groups == (PERFORMANCE, SECURITY)


def test_a_rule_only_selection_runs_just_those_rules() -> None:
    selected = select_rules(_draft(), [], ["Kural05"])

    assert selected.codes == frozenset({"Kural05"})
    assert selected.normal == ()


def test_ungrouped_rules_run_with_a_group_selection_only_when_picked() -> None:
    assert "Kural05" not in select_rules(_draft(), ["grp-sec", "grp-perf"]).codes


@pytest.mark.parametrize(
    ("group_ids", "codes", "code"),
    [
        (["grp-perf", "yok"], [], "rule_group_unknown"),
        ([], ["Kural77"], "rule_unknown"),
        (["yok"], ["Kural77"], "rule_group_unknown"),
    ],
)
def test_an_unknown_group_or_rule_is_rejected(
    group_ids: list[str], codes: list[str], code: str
) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        select_rules(_draft(), group_ids, codes)
    assert raised.value.code == code


def test_a_selection_without_any_rule_is_rejected() -> None:
    empty_group = RuleGroup("grp-bos", "Boş")
    draft = normalize_draft([Rule("Kural01", "x")], [], rule_groups=[empty_group])

    with pytest.raises(RuleSetValidationError) as raised:
        select_rules(draft, ["grp-bos"])
    assert raised.value.code == "rule_group_selection_empty"


def test_the_digest_of_an_ungrouped_rule_set_is_unchanged() -> None:
    """Versions published before groups existed keep their digest (plan: digest compatibility)."""

    ungrouped = normalize_draft([Rule("Kural01", "bir", True)], [Rule("Kural02", "iki")])
    # The canonical form before named groups existed: priority groups of [code, text, flag].
    before_groups = json.dumps(
        {"critical": [["Kural01", "bir", True]], "normal": [["Kural02", "iki", False]]},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert content_sha256(ungrouped) == hashlib.sha256(before_groups.encode("utf-8")).hexdigest()


def test_groups_and_memberships_change_the_digest() -> None:
    draft = _draft()
    regrouped = normalize_draft(
        [
            Rule("Kural01", "NOLOCK yok", rule_group_ids=(SECURITY.public_id,)),
            Rule("Kural03", "SELECT * yok", rule_group_ids=(SECURITY.public_id,)),
            Rule("Kural05", "geçici tablo silinir"),
        ],
        [Rule("Kural09", "adlandırma", rule_group_ids=(PERFORMANCE.public_id,))],
        rule_groups=[PERFORMANCE, SECURITY],
    )
    renamed = normalize_draft(
        list(draft.critical),
        list(draft.normal),
        rule_groups=[RuleGroup("grp-perf", "Hız", "Sorgu maliyeti"), SECURITY],
    )

    assert len({content_sha256(draft), content_sha256(regrouped), content_sha256(renamed)}) == 3


def test_membership_order_does_not_change_the_digest() -> None:
    reordered = normalize_draft(
        [
            Rule("Kural01", "NOLOCK yok", rule_group_ids=(SECURITY.public_id,)),
            Rule(
                "Kural03",
                "SELECT * yok",
                rule_group_ids=(PERFORMANCE.public_id, SECURITY.public_id),
            ),
            Rule("Kural05", "geçici tablo silinir"),
        ],
        [Rule("Kural09", "adlandırma", rule_group_ids=(PERFORMANCE.public_id,))],
        rule_groups=[PERFORMANCE, SECURITY],
    )

    assert content_sha256(reordered) == content_sha256(_draft())
