"""CSV and fix-comment SQL exports (sql-review 005 Requirement 7-10, Acceptance 2).

The ``PREVIOUS_*`` CSV bytes below were produced by running the previous application's own
``buildReviewResultsCsv`` (``frontend/src/components/ExportMenu.tsx``) under Node on the same
input with the clock fixed at 2026-09-26T10:11:12.345Z. The current file is those bytes with one
more last column, ``rule_group`` (005 Decision 9, sql-review/PRDs/007-rule-group-selection).
"""

import re

import pytest

from app.services.review_export import (
    ExportFinding,
    ExportObject,
    ExportRuleResult,
    build_results_csv,
    build_sql_export,
    shift_line_reference,
)

pytestmark = pytest.mark.unit

GENERATED_AT = "2026-09-26T10:11:12.345Z"
PREVIOUS_HEADER = (
    "﻿generated_at,database,schema,name,object_type,rule_id,tier,status,severity,"
    "description,line_reference,code_snippet,false_positive"
)
HEADER = PREVIOUS_HEADER + ",rule_group"
WARNING = "[Kural04] LLM sunucusu hata döndürdü (HTTP 500)."


def _result(
    rule_id: str,
    tier: str,
    status: str,
    severity: str = "",
    description: str = "",
    line_reference: str = "",
    code_snippet: str = "",
    false_positive: bool = False,
) -> ExportRuleResult:
    return ExportRuleResult(
        rule_id, tier, status, severity, description, line_reference, code_snippet, false_positive
    )


def _finding(
    rule_id: str,
    description: str,
    line_reference: str = "",
    code_snippet: str = "",
    false_positive: bool = False,
    severity: str = "HIGH",
) -> ExportFinding:
    return ExportFinding(
        rule_id, severity, description, line_reference, code_snippet, false_positive
    )


OBJECT_RUN = [
    ExportObject(
        database="DWH",
        schema="dbo",
        name="usp_A",
        object_type="PROCEDURE",
        error="",
        parse_warning=WARNING,
        rule_results=[
            _result("Kural01", "critical", "FAIL", "HIGH", "ilk neden", "Satır 3", "SELECT *"),
            _result("Kural02", "normal", "PASS", "", "İhlal bulunmadı."),
            _result(
                "Kural03",
                "normal",
                "FAIL",
                "LOW",
                'kural "tek" satır, virgüllü',
                "Satır 9–11",
                "UPDATE t\nSET a = 1",
                false_positive=True,
            ),
            _result("Kural04", "normal", "UNKNOWN", "", "LLM sunucusu hata döndürdü (HTTP 500)."),
        ],
        findings=[
            _finding("Kural01", 'usp_A: ilk neden, "alıntı"', "Satır 3", "SELECT *\r\nFROM t"),
            _finding("Kural01", "ikinci neden", "Satır 5, 7", "WHERE x IS NULL", True),
        ],
    ),
    ExportObject(
        database="DWH2",
        schema="sales",
        name="vw_B",
        object_type="VIEW",
        error="Tanım alınamadı (nesne yok veya yetki yok).",
        parse_warning="",
        rule_results=[],
        findings=[],
    ),
]

PREVIOUS_OBJECT_CSV = (
    PREVIOUS_HEADER + "\r\n"
    '2026-09-26T10:11:12.345Z,DWH,dbo,usp_A,PROCEDURE,Kural01,,FAIL,HIGH,"[Kural04] LLM '
    'sunucusu hata döndürdü (HTTP 500). — usp_A: ilk neden, ""alıntı""",Satır 3,"SELECT *\r\n'
    'FROM t",false\r\n'
    "2026-09-26T10:11:12.345Z,DWH,dbo,usp_A,PROCEDURE,Kural01,,FAIL,HIGH,[Kural04] LLM sunucusu "
    'hata döndürdü (HTTP 500). — ikinci neden,"Satır 5, 7",WHERE x IS NULL,true\r\n'
    "2026-09-26T10:11:12.345Z,DWH,dbo,usp_A,PROCEDURE,Kural02,normal,PASS,,[Kural04] LLM sunucusu "
    "hata döndürdü (HTTP 500). — İhlal bulunmadı.,,,false\r\n"
    '2026-09-26T10:11:12.345Z,DWH,dbo,usp_A,PROCEDURE,Kural03,normal,FAIL,LOW,"[Kural04] LLM '
    'sunucusu hata döndürdü (HTTP 500). — kural ""tek"" satır, virgüllü",Satır 9–11,"UPDATE t\n'
    'SET a = 1",true\r\n'
    "2026-09-26T10:11:12.345Z,DWH,dbo,usp_A,PROCEDURE,Kural04,normal,UNKNOWN,,[Kural04] LLM "
    "sunucusu hata döndürdü (HTTP 500). — LLM sunucusu hata döndürdü (HTTP 500).,,,false\r\n"
    "2026-09-26T10:11:12.345Z,DWH2,sales,vw_B,VIEW,,,,,Tanım alınamadı (nesne yok veya yetki "
    "yok).,,,false"
)


def _with_rule_group(previous: str, groups: list[str] | None = None) -> str:
    """The previous builder's bytes with the rule_group column appended to every record.

    Records end at a CRLF outside quotes; ``groups`` gives each data row's value (default empty).
    """

    values = iter(groups or [])
    out: list[str] = []
    quoted = False
    first = True
    for index, char in enumerate(previous):
        if char == '"':
            quoted = not quoted
        if not quoted and previous.startswith("\r\n", index):
            out.append(",rule_group" if first else "," + next(values, ""))
            first = False
        out.append(char)
    out.append(",rule_group" if first else "," + next(values, ""))
    return "".join(out)


EXPECTED_OBJECT_CSV = _with_rule_group(PREVIOUS_OBJECT_CSV)


def test_csv_bytes_equal_the_previous_builder_for_an_object_run() -> None:
    csv = build_results_csv(
        OBJECT_RUN, generated_at=GENERATED_AT, database="2 veritabanı (DWH, DWH2)"
    )
    assert csv == EXPECTED_OBJECT_CSV
    assert csv.encode("utf-8").startswith(b"\xef\xbb\xbf")


def test_csv_bytes_equal_the_previous_builder_for_a_script_run() -> None:
    script = [
        ExportObject(
            database="",
            schema="sql",
            name="Etiketim",
            object_type="SCRIPT",
            error="",
            parse_warning="",
            rule_results=[_result("Kural01", "critical", "NOT_APPLICABLE", "", "kapsam dışı")],
            findings=[],
        )
    ]
    assert build_results_csv(script, generated_at=GENERATED_AT) == (
        HEADER + "\r\n2026-09-26T10:11:12.345Z,,sql,Etiketim,SCRIPT,Kural01,critical,"
        "NOT_APPLICABLE,,kapsam dışı,,,false,"
    )


def test_csv_of_a_run_without_results_is_one_error_row() -> None:
    csv = build_results_csv(
        [], generated_at=GENERATED_AT, database="DWH", review_error="İnceleme tamamlanamadı."
    )
    assert csv == (
        HEADER + "\r\n2026-09-26T10:11:12.345Z,DWH,,,,,,,,İnceleme tamamlanamadı.,,,false,"
    )
    assert build_results_csv([], generated_at=GENERATED_AT) == HEADER


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_cells_that_would_run_as_a_formula_get_a_leading_quote(prefix: str) -> None:
    item = ExportObject(
        database="DWH",
        schema="dbo",
        name=f"{prefix}HYPERLINK(1)",
        object_type="VIEW",
        error="",
        parse_warning="",
        rule_results=[_result("Kural01", "critical", "FAIL", "HIGH", "d", "", "x")],
        findings=[_finding("Kural01", "açıklama", "", f"{prefix}1+1")],
    )
    row = build_results_csv([item], generated_at=GENERATED_AT).split("\r\n")[1]
    assert f",'{prefix}HYPERLINK(1)," in row or f',"\'{prefix}HYPERLINK(1)",' in row
    assert f"'{prefix}1+1" in row
    assert not re.search(rf",{re.escape(prefix)}", row.replace(f"'{prefix}", ""))


def test_a_comment_snippet_is_protected_too() -> None:
    item = ExportObject(
        database="DWH",
        schema="dbo",
        name="p",
        object_type="VIEW",
        error="",
        parse_warning="",
        rule_results=[_result("Kural01", "critical", "FAIL", "HIGH", "d")],
        findings=[_finding("Kural01", "yorum", "", "-- yorum satırı")],
    )
    assert ",'-- yorum satırı," in build_results_csv([item], generated_at=GENERATED_AT)


# --- SQL export -------------------------------------------------------------------------------

DEFINITION_A = (
    "\r\n\r\nCREATE PROCEDURE dbo.usp_A\r\nAS\r\nBEGIN\r\n    SELECT *\r\n  FROM t\r\nEND\r\n"
)
DEFINITION_B = "CREATE VIEW sales.vw_B AS\nSELECT a\nFROM b\nWHERE c IS NULL"


def _sql_object(
    database: str, schema: str, name: str, source: str, findings: list[ExportFinding]
) -> ExportObject:
    return ExportObject(
        database=database,
        schema=schema,
        name=name,
        object_type="PROCEDURE" if name.startswith("usp") else "VIEW",
        error="",
        parse_warning="",
        rule_results=[_result("Kural01", "critical", "FAIL", "HIGH", "d")] if findings else [],
        findings=findings,
        source_sql=source,
    )


def _line_of(content: str, number: int) -> str:
    return content.split("\n")[number - 1].rstrip("\r")


def _numbers(comment_line: str) -> list[int]:
    location = comment_line.split(" — ")[1]
    return [int(value) for value in re.findall(r"\d+", location)]


def test_every_satir_value_is_the_real_line_of_the_downloaded_file() -> None:
    objects = [
        _sql_object(
            "DWH",
            "dbo",
            "usp_A",
            DEFINITION_A,
            [
                _finding("Kural01", "yıldız | seçim", "Satır 6", "SELECT *"),
                _finding("Kural02", "tablo", "Satır 6–7", "FROM t"),
                _finding("Kural03", "yanlış pozitif", "Satır 3", "", True),
            ],
        ),
        _sql_object(
            "DWH2",
            "sales",
            "vw_B",
            DEFINITION_B,
            [_finding("Kural05", "NULL\n karşılaştırma", "Satır 2, 4", "WHERE c IS NULL")],
        ),
    ]
    content = build_sql_export(objects, script=False)
    assert content is not None
    lines = content.split("\n")
    assert lines[:3] == [
        "/*",
        "SQL Review - Duzeltilmesi Gereken Yerler",
        (
            'Not: Asagidaki "Satir" degerleri bu dosyadaki mutlak satir numaralaridir '
            "(SSMS satir no ile ayni)."
        ),
    ]
    comments = [line for line in lines if line.startswith("- ")]
    assert len(comments) == 3
    assert "yanlış pozitif" not in content
    first, second, third = comments
    assert first.startswith("- Kural01 — Satır ") and first.endswith(" — yıldız ¦ seçim")
    assert third.endswith(" — NULL karşılaştırma")
    [select_line] = _numbers(first)
    assert _line_of(content, select_line) == "    SELECT *"
    start, end = _numbers(second)
    assert [_line_of(content, n) for n in (start, end)] == ["    SELECT *", "  FROM t"]
    select_b, where_b = _numbers(third)
    assert _line_of(content, select_b) == "SELECT a"
    assert _line_of(content, where_b) == "WHERE c IS NULL"
    assert "-- [DWH] dbo.usp_A (PROCEDURE)\nCREATE PROCEDURE" in content
    assert "END\n\nGO\n\n-- [DWH2] sales.vw_B (VIEW)\nCREATE VIEW" in content.replace("\r", "")


def test_a_script_is_written_as_is_under_the_comment_block() -> None:
    script = "SELECT 1;\nSELECT *\n  FROM dbo.T;"
    item = ExportObject(
        database="",
        schema="sql",
        name="Etiket",
        object_type="SCRIPT",
        error="",
        parse_warning="",
        rule_results=[_result("Kural01", "critical", "FAIL", "HIGH", "d")],
        findings=[_finding("Kural01", "yıldız", "Satır 2", "SELECT *")],
        source_sql=script,
    )
    content = build_sql_export([item], script=True)
    assert content is not None
    assert content.endswith("*/\n" + script)
    assert "sql.Etiket (SCRIPT)" in content
    comment = next(line for line in content.split("\n") if line.startswith("- "))
    assert _line_of(content, _numbers(comment)[0]) == "SELECT *"


def test_rule_results_are_listed_when_an_object_has_no_findings() -> None:
    item = ExportObject(
        database="DWH",
        schema="dbo",
        name="p",
        object_type="VIEW",
        error="",
        parse_warning="",
        rule_results=[
            _result("Kural01", "critical", "FAIL", "HIGH", "kural düzeyi", "Satır 1"),
            _result("Kural02", "normal", "FAIL", "LOW", "işaretli", "Satır 1", false_positive=True),
            _result("Kural03", "normal", "PASS"),
        ],
        findings=[],
        source_sql="SELECT 1",
    )
    content = build_sql_export([item], script=False)
    assert content is not None
    comments = [line for line in content.split("\n") if line.startswith("- ")]
    assert len(comments) == 1
    assert comments[0].startswith("- Kural01 — Satır ")
    assert _line_of(content, _numbers(comments[0])[0]) == "SELECT 1"


def test_no_items_writes_the_empty_note_and_missing_lines_stay_marked() -> None:
    item = _sql_object("DWH", "dbo", "usp_A", DEFINITION_A, [])
    content = build_sql_export([item], script=False)
    assert content is not None
    assert "\n\nTespit edilen duzeltme maddesi yok.\n*/\n-- [DWH] dbo.usp_A" in content

    marked = _sql_object("DWH", "dbo", "usp_A", DEFINITION_A, [_finding("Kural01", "d")])
    assert "- Kural01 — Satir bilgisi yok — d" in (build_sql_export([marked], script=False) or "")


def test_no_stored_text_means_no_sql_file() -> None:
    assert build_sql_export([_sql_object("DWH", "dbo", "p", "  \n ", [])], script=False) is None
    assert build_sql_export([], script=True) is None


def test_every_number_of_a_range_or_list_is_moved_once() -> None:
    assert shift_line_reference("Satır 3–5, 8 ve Satir 9", lambda n: n + 10) == (
        "Satır 13–15, 18 ve Satir 19"
    )
    assert shift_line_reference("line 3", lambda n: n + 10) == "line 3"


# --- Rule groups (005 Decision 9, sql-review/PRDs/007-rule-group-selection Requirement 7) ------


def test_the_rule_group_is_the_last_csv_column_of_result_and_finding_rows() -> None:
    item = ExportObject(
        database="DWH",
        schema="dbo",
        name="usp_A",
        object_type="PROCEDURE",
        error="",
        parse_warning="",
        rule_results=[
            ExportRuleResult(
                "Kural01",
                "critical",
                "FAIL",
                "HIGH",
                "d",
                "",
                "",
                False,
                rule_groups=("Güvenlik", "Performans"),
            ),
            ExportRuleResult("Kural02", "normal", "PASS", "", "uyumlu", "", "", False),
        ],
        findings=[
            ExportFinding(
                "Kural01", "HIGH", "neden", "Satır 3", "x", False, rule_groups=("Güvenlik",)
            )
        ],
    )

    rows = build_results_csv([item], generated_at=GENERATED_AT).split("\r\n")

    assert rows[0] == HEADER
    assert rows[1].endswith(",false,Güvenlik")
    assert rows[2].endswith(",false,")


def test_several_groups_of_a_rule_are_joined_with_a_semicolon_in_the_csv() -> None:
    item = ExportObject(
        database="DWH",
        schema="dbo",
        name="usp_A",
        object_type="PROCEDURE",
        error="",
        parse_warning="",
        rule_results=[
            ExportRuleResult(
                "Kural01",
                "critical",
                "PASS",
                "",
                "uyumlu",
                "",
                "",
                False,
                rule_groups=("Güvenlik", "Performans"),
            )
        ],
        findings=[],
    )

    rows = build_results_csv([item], generated_at=GENERATED_AT).split("\r\n")

    assert rows[1].endswith(",false,Güvenlik; Performans")


def test_the_sql_comment_names_the_rule_group_next_to_the_rule() -> None:
    grouped = _sql_object(
        "DWH",
        "dbo",
        "usp_A",
        DEFINITION_A,
        [
            ExportFinding(
                "Kural01",
                "HIGH",
                "neden",
                "Satır 2",
                "",
                False,
                rule_groups=("Güvenlik", "Performans"),
            )
        ],
    )
    ungrouped = _sql_object(
        "DWH", "sales", "vw_B", DEFINITION_B, [_finding("Kural02", "başka", "Satır 1")]
    )

    content = build_sql_export([grouped, ungrouped], script=False)

    assert content is not None
    lines = content.split("\n")
    assert any(line.startswith("- Kural01 (Güvenlik, Performans) — ") for line in lines)
    assert any(line.startswith("- Kural02 — ") for line in lines)
