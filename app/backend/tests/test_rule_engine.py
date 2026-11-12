import pytest

from app.services.rule_engine import (
    RuleError,
    RuleSpec,
    applies_to,
    mask_sql,
    run_regex,
    run_rule,
    snippet_at,
)
from tests.legacy_rules import SEED_RULES


def rule(**kwargs) -> RuleSpec:  # type: ignore[no-untyped-def]
    defaults = {"code": "T001", "name": "Test", "description": "Açıklama"}
    defaults.update(kwargs)
    return RuleSpec(**defaults)


SEED = {data["code"]: data for data in SEED_RULES}


def seeded(code: str) -> RuleSpec:
    data = SEED[code]
    return RuleSpec(
        code=code,
        name=data["name"],
        kind=data.get("kind", "regex"),
        description=data.get("description", ""),
        pattern=data.get("pattern"),
        match_mode=data.get("match_mode", "match"),
        target=data.get("target", "definition"),
        ignore_case=data.get("ignore_case", True),
        ignore_comments=data.get("ignore_comments", True),
        object_types=tuple(data.get("object_types", ())),
    )


def lines(code: str, sql: str, name: str = "dbo.X") -> list[int | None]:
    return [f.line for f in run_regex(seeded(code), sql, name)]


# ------------------------------------------------------------------ masking
def test_mask_preserves_length_and_newlines() -> None:
    sql = "SELECT 1 -- yorum\n/* blok\n /* iç */ hâlâ */ SELECT 'a''b--c'\r\nFROM [x--y]"
    masked = mask_sql(sql)
    assert len(masked) == len(sql)
    assert [i for i, ch in enumerate(sql) if ch in "\r\n"] == [
        i for i, ch in enumerate(masked) if ch in "\r\n"
    ]
    assert "yorum" not in masked
    assert "blok" not in masked and "hâlâ" not in masked
    assert "a''b" not in masked and "--c" not in masked
    assert "[x--y]" in masked
    assert masked.count("SELECT") == 2


def test_unterminated_comment_and_string() -> None:
    assert mask_sql("SELECT /* açık").strip() == "SELECT"
    assert mask_sql("SELECT 'açık").strip() == "SELECT"


def test_comment_and_string_ignored() -> None:
    sql = "-- SELECT * FROM a\nPRINT 'SELECT * FROM b'\n/* SELECT * */\nSELECT * FROM c\n"
    findings = run_regex(rule(pattern=r"SELECT\s+\*"), sql)
    assert [f.line for f in findings] == [4]
    assert findings[0].snippet == "SELECT * FROM c"
    assert findings[0].message == "Açıklama"


def test_comments_not_ignored_when_disabled() -> None:
    sql = "-- SELECT * FROM a\nSELECT * FROM c"
    findings = run_regex(rule(pattern=r"SELECT\s+\*", ignore_comments=False), sql)
    assert [f.line for f in findings] == [1, 2]


def test_ignore_case_flag() -> None:
    sql = "select * from t"
    assert run_regex(rule(pattern="SELECT", ignore_case=True), sql)
    assert not run_regex(rule(pattern="SELECT", ignore_case=False), sql)


def test_multiline_anchor_and_dedupe_same_line() -> None:
    sql = "a NOLOCK NOLOCK\n  NOLOCK"
    findings = run_regex(rule(pattern=r"NOLOCK"), sql)
    assert [f.line for f in findings] == [1, 2]
    assert [f.line for f in run_regex(rule(pattern=r"^\s*NOLOCK"), sql)] == [2]


def test_snippet_full_line_and_truncated() -> None:
    sql = "x\n    SELECT a, b FROM t   \ny"
    start = sql.index("FROM")
    assert snippet_at(sql, start, start + 4) == "SELECT a, b FROM t"
    long_line = "SELECT " + "a" * 800
    found = run_regex(rule(pattern="SELECT"), long_line)
    assert len(found[0].snippet) == 500


def test_multiline_match_snippet() -> None:
    sql = "SELECT\n  *\nFROM t"
    found = run_regex(rule(pattern=r"SELECT\s+\*"), sql)
    assert found[0].line == 1
    assert found[0].snippet == "SELECT\n  *"


def test_absent_mode() -> None:
    absent = rule(pattern=r"SET\s+NOCOUNT\s+ON", match_mode="absent")
    missing = run_regex(absent, "CREATE PROC p AS SELECT 1")
    assert len(missing) == 1 and missing[0].line is None
    assert run_regex(absent, "CREATE PROC p AS SET NOCOUNT ON; SELECT 1") == []
    # Present only inside a comment counts as absent.
    assert len(run_regex(absent, "CREATE PROC p AS -- SET NOCOUNT ON\nSELECT 1")) == 1


def test_name_target() -> None:
    name_rule = rule(pattern=r"(?:^|\.)sp_", target="name")
    found = run_regex(name_rule, "SELECT 1", "dbo.sp_Load")
    assert len(found) == 1 and found[0].line is None and found[0].snippet == "dbo.sp_Load"
    assert run_regex(name_rule, "EXEC dbo.sp_x", "dbo.usp_Load") == []


def test_object_types_applicability() -> None:
    proc_only = rule(pattern="x", object_types=("PROCEDURE",))
    assert applies_to(proc_only, "PROCEDURE")
    assert not applies_to(proc_only, "VIEW")
    assert applies_to(rule(pattern="x"), "VIEW")


def test_invalid_regex_raises() -> None:
    with pytest.raises(RuleError, match="Geçersiz düzenli ifade"):
        run_regex(rule(pattern="(unclosed"), "x")
    with pytest.raises(RuleError):
        run_regex(rule(pattern=None), "x")


def test_llm_rule_without_config() -> None:
    with pytest.raises(RuleError, match="LLM"):
        run_rule(rule(kind="llm", llm_prompt="x"), "SELECT 1", "dbo.x", None)


# ------------------------------------------------------------------ seeded rules
def test_all_seeded_patterns_compile() -> None:
    for code, data in SEED.items():
        if data.get("kind", "regex") == "regex":
            run_regex(seeded(code), "SELECT 1", "dbo.x")


def test_seed_select_star() -> None:
    sql = (
        "SELECT * FROM a\n"
        "SELECT t.* FROM t\n"
        "SELECT TOP 10 * FROM b\n"
        "IF EXISTS (SELECT * FROM c) PRINT 1\n"
        "SELECT COUNT(*) FROM d\n"
        "SELECT DISTINCT * FROM e\n"
    )
    assert lines("DWH001", sql) == [1, 2, 3, 6]


def test_seed_nolock() -> None:
    sql = "SELECT a FROM t WITH (NOLOCK)\nSELECT b FROM u\nSET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"
    assert lines("DWH002", sql) == [1, 3]


def test_seed_cursor() -> None:
    sql = "DECLARE c CURSOR LOCAL FOR SELECT 1\nOPEN c\nSELECT CURSOR_STATUS('local','c')"
    assert lines("DWH003", sql) == [1]


def test_seed_nocount_absent() -> None:
    assert lines("DWH004", "CREATE PROCEDURE p AS SELECT 1") == [None]
    assert lines("DWH004", "CREATE PROCEDURE p AS\nSET NOCOUNT ON;") == []


def test_seed_dynamic_exec() -> None:
    sql = "EXEC (@sql)\nEXEC('SELECT ' + @col)\nEXEC sp_executesql @sql, N'@p int', @p\nEXEC dbo.usp_x"
    assert lines("DWH005", sql) == [1, 2]


def test_seed_identity() -> None:
    assert lines("DWH006", "SELECT @@IDENTITY\nSELECT SCOPE_IDENTITY()") == [1]


def test_seed_sp_prefix() -> None:
    assert lines("DWH007", "", "dbo.sp_LoadDim") == [None]
    assert lines("DWH007", "", "dbo.usp_LoadDim") == []


def test_seed_old_outer_join() -> None:
    sql = "WHERE a.id *= b.id\nWHERE a.id =* b.id\nSET @x *= 2\nSELECT a * b"
    assert lines("DWH009", sql) == [1, 2]


def test_seed_deprecated_types() -> None:
    sql = (
        "DECLARE @t TEXT\n"
        "CREATE TABLE #x (\n"
        "    Notes NTEXT NULL,\n"
        "    Pic IMAGE\n"
        ")\n"
        "SELECT CONVERT(TEXT, a), b AS Text FROM t\n"
        "SELECT Text FROM t\n"
    )
    assert lines("DWH010", sql) == [1, 3, 4, 6]


def test_seed_hardcoded_date() -> None:
    sql = "WHERE d >= '2023-01-01'\nAND d < '20240101'\nAND x = '2023'\nAND y = 'abc'"
    assert lines("DWH011", sql) == [1, 2]


def test_seed_truncate_drop() -> None:
    sql = (
        "TRUNCATE TABLE dbo.FactSales\n"
        "DROP TABLE #tmp\n"
        "DROP TABLE IF EXISTS #tmp2\n"
        "DROP TABLE dbo.Stage\n"
        "DROP TABLE IF EXISTS dbo.Stage2\n"
    )
    assert lines("DWH012", sql) == [1, 4, 5]


def test_seed_try_catch_absent() -> None:
    assert lines("DWH013", "CREATE PROC p AS UPDATE t SET a = 1") == [None]
    assert lines("DWH013", "CREATE PROC p AS BEGIN TRY UPDATE t SET a=1 END TRY BEGIN CATCH END CATCH") == []


def test_seed_view_order_by() -> None:
    assert lines("DWH014", "CREATE VIEW v AS SELECT TOP 100 PERCENT a FROM t\nORDER BY a") == [1]
    assert lines("DWH014", "CREATE VIEW v AS SELECT TOP (100) PERCENT a FROM t") == []
    assert lines("DWH014", "CREATE VIEW v AS SELECT ROW_NUMBER() OVER (ORDER BY a) rn FROM t") == []


def test_seed_distinct() -> None:
    assert lines("DWH015", "SELECT DISTINCT a FROM t\nSELECT COUNT(DISTINCT a) FROM t") == [1]


def test_seed_function_in_where() -> None:
    sql = (
        "SELECT a FROM t WHERE YEAR(OrderDate) = 2024\n"
        "  AND CONVERT(date, d) = @d\n"
        "  AND x = YEAR(@d)\n"
        "  AND ISNULL(@p, 1) = 1\n"
        "  OR UPPER(Name) = 'A'\n"
        "SELECT a FROM t WHERE OrderDate >= @start\n"
    )
    assert lines("DWH016", sql) == [1, 2, 5]


def test_seed_select_into_temp() -> None:
    sql = "SELECT a INTO #tmp FROM t\nINSERT INTO #tmp SELECT 1\nSELECT b INTO ##g FROM t"
    assert lines("DWH017", sql) == [1, 3]


def test_seed_waitfor_and_xp_cmdshell() -> None:
    assert lines("DWH018", "WAITFOR DELAY '00:00:05'") == [1]
    sql = "-- EXEC xp_cmdshell 'dir'\nEXEC master..xp_cmdshell 'dir'"
    assert lines("DWH019", sql) == [2]


def test_seed_goto() -> None:
    assert lines("DWH008", "GOTO Hata\nHata:\nPRINT 'GOTO x'") == [1]
