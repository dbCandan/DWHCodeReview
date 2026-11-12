"""v3 regex rules and preconditions against the ✔/✘ examples of RULES_SPEC_v13.md."""

import pytest

from app.seed import SEED_RULES, V3_RULES
from app.services.rule_engine import RuleSpec, precondition_met, run_regex

SEED = {data["code"]: data for data in SEED_RULES}


def spec(code: str) -> RuleSpec:
    return RuleSpec.from_obj(type("R", (), SEED[code])())


POSITIVE = {
    "DWH-NOLOCK-02": ["FROM #tmp WITH (NOLOCK)", "JOIN #x x (NOLOCK)", "FROM #n AS n WITH(TABLOCK)",
                      "FROM ##g WITH (READUNCOMMITTED)"],
    "DWH-HINT-01": ["OPTION (MAXDOP 1)", "OPTION(RECOMPILE)", "INNER HASH JOIN", "LEFT MERGE JOIN",
                    "WITH (NOLOCK, INDEX(IX_A))", "WITH (FORCESEEK)"],
    "DWH-INS-02": ["INSERT INTO #tmp (A, B) SELECT", "INSERT INTO #tmp SELECT * FROM x",
                   "insert #t exec dbo.p", "INSERT INTO ##g(A)", "INSERT INTO #t WITH (NOLOCK) (A)"],
    "DWH-PERF-02": ["CONVERT(DATE, SystemDate) AS DataDate,", "CAST(a.SystemDate AS DATE) AS DataDate\nFROM",
                    "CONVERT(DATE, T.SystemDate) DataDate,", "CAST(b.BranchNk AS INT) AS BranchId,",
                    # v4 (spec 7b): date derivations of a column
                    "CONVERT(VARCHAR(6), t.TranDate, 112) AS Period,", "FORMAT(t.TranDate,'yyyyMM') AS Period",
                    "YEAR(t.D)*100+MONTH(t.D) AS Period", "YEAR(t.D) AS Yil,", "EOMONTH(t.D) AS AySonu\nFROM",
                    "DATEADD(DAY, -1, t.D) AS Onceki,", "DATEPART(QUARTER, t.D) Ceyrek,",
                    "CAST(CONVERT(VARCHAR(6), t.TranDate, 112) AS INT) AS Period,"],
    "DWH-PERF-04": ["WHERE a.Name LIKE '%abc'", "AND x LIKE N'%y%'"],
    "DWH-PERF-05": ["DECLARE c CURSOR LOCAL FOR SELECT 1", "DECLARE @c CURSOR",
                    "SET @c = CURSOR FAST_FORWARD FOR SELECT 1"],
    "DWH-PERF-06": ["WHERE a.Id NOT IN (SELECT b.Id FROM b)", "AND x not in(select 1)"],
    "DWH-SQL-04": ["SELECT COUNT(*) FROM t", "SELECT COUNT_BIG ( * ) FROM t"],
    "DWH-PF-02": ["JOIN EDWUTIL.DTG.LKPCustomerParty l ON 1=1", "FROM [EDWUTIL].[DTG].[LKPPersonPartyHistory]"],
    "DWH-PF-03": ["INSERT INTO EDWDM.TRX.X (A, EdwEtlDate) SELECT",
                  "INSERT INTO [TRX].[X] WITH (TABLOCK) (A, B, PersonnelFlag)"],
}
NEGATIVE = {
    "DWH-NOLOCK-02": ["INSERT INTO #t WITH (TABLOCK)", "FROM #tmp t", "FROM EDW.CON.Account A WITH (NOLOCK)",
                      "SELECT * INTO #t FROM x"],
    "DWH-HINT-01": ["MERGE INTO t USING s", "WITH (NOLOCK)", "WITH (TABLOCK)", "-- OPTION (MAXDOP 1)"],
    "DWH-INS-02": ["INSERT INTO #tmp WITH (TABLOCK) (A, B) SELECT", "INSERT INTO #t WITH(TABLOCKX)(A)",
                   "INSERT INTO #t WITH (TABLOCK, HOLDLOCK) SELECT", "SELECT a INTO #t FROM x",
                   "INSERT INTO @t (A) SELECT", "INSERT INTO EDW.CON.X (A)", "FROM #t WITH (TABLOCK)"],
    "DWH-PERF-02": ["CAST(NULL AS int) AS X,", "CONVERT(VARCHAR(6), @d, 112)", "CONVERT(DATE, GETDATE()) AS D,",
                    "WHERE CAST(a.x AS INT) = 5", "@Period AS Period,", "YEAR(@d) AS Yil,",
                    "DATEADD(DAY, -1, GETDATE()) AS D,", "FORMAT(@d, 'yyyyMM') AS P,",
                    "WHERE YEAR(t.D) = 2024"],
    "DWH-PERF-04": ["WHERE a.Name LIKE 'abc%'", "AND x LIKE @p"],
    "DWH-PERF-05": ["SELECT CURSOR_STATUS('local', 'c')", "-- DECLARE c CURSOR"],
    "DWH-PERF-06": ["WHERE a.Id NOT IN (1, 2)", "WHERE NOT EXISTS (SELECT 1 FROM b)"],
    "DWH-SQL-04": ["SELECT COUNT(1) FROM t", "SELECT COUNT(a.Id) FROM t"],
    "DWH-PF-02": ["FROM EDWUTIL.DTG.MaskingExecutionLog", "-- JOIN EDWUTIL.DTG.LKPCustomerParty"],
    "DWH-PF-03": ["INSERT INTO #t (A, PersonnelFlag)", "INSERT INTO TRX.X (A, B) SELECT a, PersonnelFlag FROM",
                  "SELECT PersonnelFlag INTO #t"],
}


@pytest.mark.parametrize(("code", "sql"), [(c, s) for c, items in POSITIVE.items() for s in items])
def test_positive(code: str, sql: str) -> None:
    assert len(run_regex(spec(code), sql)) == 1, (code, sql)


@pytest.mark.parametrize(("code", "sql"), [(c, s) for c, items in NEGATIVE.items() for s in items])
def test_negative(code: str, sql: str) -> None:
    assert run_regex(spec(code), sql) == [], (code, sql)


def test_every_v3_regex_rule_has_examples() -> None:
    regex_codes = {r["code"] for r in V3_RULES if r["kind"] == "regex"} | {"DWH-NOLOCK-02"}
    assert {"DWH-ID-01", "DWH-CAL-01"}.isdisjoint(regex_codes)  # builtins since v4
    assert regex_codes == set(POSITIVE) == set(NEGATIVE)


def test_v3_rule_settings() -> None:
    assert len(V3_RULES) == 24
    assert all(r["enabled"] for r in V3_RULES)
    assert [r["code"] for r in V3_RULES if r["severity"] != "high"] == ["DWH-CAL-01"]
    assert SEED["DWH-CAL-01"]["severity"] == "low"
    builtins = {r["code"]: r["builtin_check"] for r in V3_RULES if r["kind"] == "builtin"}
    assert len(builtins) == 12 and all(builtins.values())
    assert builtins["DWH-ID-01"] == "id_literal_filter" and SEED["DWH-ID-01"]["pattern"] is None
    assert builtins["DWH-CAL-01"] == "calendar_date_predicate"
    assert SEED["DWH-PF-01"]["name_pattern"] == SEED["DWH-DM-01"]["name_pattern"]
    assert SEED["DWH-PF-02"]["databases"] == ["EDWDM"]
    assert SEED["DWH-INS-01"]["object_types"] == ["PROCEDURE"]
    assert SEED["DWH-PERF-02"]["object_types"] == ["VIEW"]
    assert SEED["DWH-NOLOCK-02"]["severity"] == "critical"


def test_llm_rule_preconditions() -> None:
    assert precondition_met(spec("DWH-SQL-01"), "SELECT DISTINCT a FROM t")
    assert not precondition_met(spec("DWH-SQL-01"), "SELECT a FROM t -- DISTINCT")
    sql3 = "SELECT a INTO #t FROM s\nINSERT INTO EDW.TRX.X SELECT * FROM #t"
    assert precondition_met(spec("DWH-SQL-03"), sql3)
    assert not precondition_met(spec("DWH-SQL-03"), "SELECT a INTO #t FROM s\nINSERT INTO #u SELECT 1")
    assert precondition_met(spec("DWH-SQL-05"), "SELECT 1 UNION SELECT 2")
    assert not precondition_met(spec("DWH-SQL-05"), "SELECT 1 UNION ALL SELECT 2")
