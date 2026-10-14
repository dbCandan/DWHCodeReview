"""Draft normalization, identifier rules and the content digest.

sql-review/PRDs/001-rule-management Requirement 2, 3 and 5 (Acceptance 1).
"""

import pytest

from app.domain.rule_set import (
    Rule,
    RuleGroups,
    RuleSetValidationError,
    content_sha256,
    format_rule_code,
    next_rule_number_after,
    normalize_draft,
    rule_number,
)

pytestmark = pytest.mark.unit


def test_rule_codes_use_two_digits_until_99_then_grow() -> None:
    assert format_rule_code(1) == "Kural01"
    assert format_rule_code(99) == "Kural99"
    assert format_rule_code(100) == "Kural100"
    assert rule_number("Kural07") == 7
    assert rule_number("Kural100") == 100
    for malformed in ("Kural00", "Kural7", "kural07", "Rule07", "Kural007", "Kural07 ", ""):
        assert rule_number(malformed) is None


def test_normalization_trims_drops_blank_rules_and_keeps_group_order() -> None:
    draft = normalize_draft(
        [Rule("Kural03", "  üçüncü  "), Rule("Kural09", "   "), Rule("Kural01", "bir", True)],
        [Rule("Kural05", "\tbeş\n")],
    )

    assert draft.critical == (Rule("Kural03", "üçüncü"), Rule("Kural01", "bir", True))
    assert draft.normal == (Rule("Kural05", "beş"),)


def test_a_blank_rule_is_dropped_before_its_code_is_checked() -> None:
    assert normalize_draft([Rule("yanlis", " ")], []).is_empty


@pytest.mark.parametrize(
    ("critical", "normal", "code"),
    [
        ([Rule("Kural1", "x")], [], "rule_id_invalid"),
        ([Rule("Kural00", "x")], [], "rule_id_invalid"),
        ([Rule("Kural01", "x")], [Rule("Kural01", "y")], "rule_id_duplicate"),
        ([Rule("Kural01", "x" * 8001)], [], "rule_text_too_long"),
        ([Rule(format_rule_code(n), "x") for n in range(1, 202)], [], "rule_set_too_large"),
    ],
)
def test_malformed_drafts_are_rejected(critical: list[Rule], normal: list[Rule], code: str) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        normalize_draft(critical, normal)
    assert raised.value.code == code
    assert raised.value.message


def test_limits_are_inclusive() -> None:
    padded = " " + "x" * 8000 + " "
    rules = [Rule(format_rule_code(n), padded) for n in range(1, 201)]
    assert len(normalize_draft(rules, []).critical) == 200


def test_new_codes_must_be_fresh_and_advance_the_first_free_number() -> None:
    draft = normalize_draft([Rule("Kural01", "x"), Rule("Kural14", "y")], [Rule("Kural13", "z")])

    number = next_rule_number_after(
        draft,
        current_codes=frozenset({"Kural01"}),
        used_codes=frozenset({"Kural01", "Kural12"}),
        next_rule_number=13,
    )

    assert number == 15


def test_keeping_only_existing_rules_keeps_the_first_free_number() -> None:
    draft = normalize_draft([Rule("Kural01", "x")], [])
    assert (
        next_rule_number_after(
            draft,
            current_codes=frozenset({"Kural01", "Kural02"}),
            used_codes=frozenset({"Kural01", "Kural02"}),
            next_rule_number=3,
        )
        == 3
    )


@pytest.mark.parametrize(
    ("code", "used"),
    [
        ("Kural12", frozenset({"Kural12"})),  # deleted from the draft earlier
        ("Kural02", frozenset()),  # below the first free number, even if never stored
        ("Kural20", frozenset({"Kural20"})),  # used in a published version only
    ],
)
def test_used_codes_are_never_given_to_a_new_rule(code: str, used: frozenset[str]) -> None:
    draft = normalize_draft([Rule(code, "yeni")], [])
    with pytest.raises(RuleSetValidationError) as raised:
        next_rule_number_after(
            draft, current_codes=frozenset(), used_codes=used, next_rule_number=13
        )
    assert raised.value.code == "rule_id_reused"


def test_content_digest_changes_with_order_group_text_and_flag() -> None:
    base = RuleGroups((Rule("Kural01", "a"), Rule("Kural02", "b")), (Rule("Kural03", "c"),))
    variants = [
        RuleGroups((Rule("Kural02", "b"), Rule("Kural01", "a")), (Rule("Kural03", "c"),)),
        RuleGroups((Rule("Kural01", "a"),), (Rule("Kural02", "b"), Rule("Kural03", "c"))),
        RuleGroups((Rule("Kural01", "a"), Rule("Kural02", "B")), (Rule("Kural03", "c"),)),
        RuleGroups((Rule("Kural01", "a"), Rule("Kural02", "b", True)), (Rule("Kural03", "c"),)),
    ]

    digest = content_sha256(base)
    assert digest == content_sha256(
        RuleGroups((Rule("Kural01", "a"), Rule("Kural02", "b")), (Rule("Kural03", "c"),))
    )
    assert len({digest, *(content_sha256(variant) for variant in variants)}) == 5


def test_rule_text_stays_out_of_representations() -> None:
    assert "gizli-kural-metni" not in repr(Rule("Kural01", "gizli-kural-metni"))


# --- Rule summary (rule-management Requirement 2, 12 and Decision 5) ---------------------------


def test_a_summary_is_trimmed_and_a_blank_one_counts_as_not_given() -> None:
    draft = normalize_draft(
        [Rule("Kural01", "metin", summary="  Tek cümle.  "), Rule("Kural02", "iki", summary="  ")],
        [],
    )

    assert [rule.summary for rule in draft.critical] == ["Tek cümle.", ""]


@pytest.mark.parametrize("summary", ["x" * 201, "bir\nsatır", "bir\r\nsatır"])
def test_a_long_or_multi_line_summary_is_rejected(summary: str) -> None:
    with pytest.raises(RuleSetValidationError) as raised:
        normalize_draft([Rule("Kural01", "metin", summary=summary)], [])
    assert raised.value.code == "rule_summary_invalid"
    assert raised.value.message


def test_a_two_hundred_character_summary_is_accepted() -> None:
    draft = normalize_draft([Rule("Kural01", "metin", summary=" " + "x" * 200 + " ")], [])
    assert len(draft.critical[0].summary) == 200


def test_a_summary_enters_the_digest_only_when_given() -> None:
    without = RuleGroups((Rule("Kural01", "a"),), ())
    blank = RuleGroups((Rule("Kural01", "a", summary=""),), ())
    given = RuleGroups((Rule("Kural01", "a", summary="Özet."),), ())
    other = RuleGroups((Rule("Kural01", "a", summary="Başka özet."),), ())

    assert content_sha256(without) == content_sha256(blank)
    assert len({content_sha256(without), content_sha256(given), content_sha256(other)}) == 3


def test_the_summary_stays_out_of_representations() -> None:
    assert "gizli-ozet" not in repr(Rule("Kural01", "metin", summary="gizli-ozet"))
