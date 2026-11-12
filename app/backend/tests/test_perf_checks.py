"""v3 builtin checks with fake catalog metadata."""

from app.services.builtin_checks import BUILTIN_CHECKS, ObjectRef, related_objects
from app.services.metadata import ObjectMetadata, empty_metadata, is_scd_table
from app.services.perf_checks import (
    date_variable_type_mismatch,
    join_column_type_mismatch,
    left_then_inner_join,
    non_sargable_predicates,
    or_in_predicates,
    personnel_flag_view_source,
    scalar_udf_in_query,
    select_list_subquery,
    tablock_physical_insert,
    window_order_by_type,
)
from app.services.rule_engine import mask_sql
from app.services.sql_parse import SqlDoc, type_family, variable_types
from tests.helpers import col, entry, metadata, varchar

PROC = ObjectRef("EDW", "TRX", "ins_X", "PROCEDURE")
DATETIME = col("EdwValidFrom", "datetime", 8, 23, 3)

META = metadata(
    entry("EDW", "CON", "Account", columns=[col("AccountId"), varchar("AccountNk"),
                                           col("BranchId"), col("OpenDate", "date", 3, 10, 0),
                                           DATETIME, col("EdwValidUntil", "datetime", 8, 23, 3)]),
    entry("EDW", "CHN", "Branch", columns=[col("BranchId"), varchar("BranchNk"),
                                          varchar("BranchName", 100)]),
    entry("EDWSTG", "BOAAI", "Src", columns=[varchar("PointOfServiceId", 20),
                                            col("TranDate", "date", 3, 10, 0)]),
    entry("EDW", "TRX", "Target", columns=[col("A")]),
    entry("EDW", "dbo", "fnScalar", "FN"),
    entry("EDW", "dbo", "fnTable", "IF"),
)


def run(check, sql: str, meta: ObjectMetadata = META, obj: ObjectRef = PROC) -> list[tuple]:  # type: ignore[no-untyped-def]
    return [(f.line, f.message) for f in check(sql, mask_sql(sql), obj, meta)]


def test_all_checks_registered() -> None:
    assert len(BUILTIN_CHECKS) == 14


# ------------------------------------------------------------------ DWH-JOIN-01
def test_left_then_inner_join() -> None:
    sql = (
        "SELECT 1\n"
        "FROM EDW.CON.Account a\n"
        "INNER JOIN EDW.CHN.Branch b ON b.BranchId = a.BranchId\n"
        "LEFT JOIN EDW.TRX.Target t ON t.A = a.AccountId\n"
        "INNER HASH JOIN EDW.CHN.Branch b2 ON 1 = 1\n"
        "JOIN (SELECT 1 x FROM EDW.TRX.Target t3 LEFT JOIN Y y ON 1=1) d ON 1 = 1\n"
        "CROSS JOIN Z z\n"
    )
    assert run(left_then_inner_join, sql) == [
        (5, "LEFT JOIN'den sonra INNER JOIN: EDW.CHN.Branch"),
        (6, "LEFT JOIN'den sonra INNER JOIN: (alt sorgu)"),
    ]
    # A sub-query is its own block: LEFT inside, INNER outside is not reported.
    ok = (
        "SELECT 1 FROM A a JOIN B b ON 1=1 LEFT JOIN C c ON 1=1\n"
        "SELECT 1 FROM (SELECT 1 x FROM A LEFT JOIN B ON 1=1) d INNER JOIN E e ON 1=1\n"
        "SELECT 1 FROM A a LEFT JOIN B b ON b.x = CASE WHEN a.y = 1 THEN 1 END CROSS APPLY F(a.x) f\n"
    )
    assert run(left_then_inner_join, ok) == []


# ------------------------------------------------------------------ DWH-SQL-02
def test_select_list_subquery() -> None:
    sql = (
        "SELECT a.Id,\n"
        "       (SELECT MAX(b.X) FROM B b WHERE b.Id = a.Id) AS MaxX,\n"
        "       CASE WHEN EXISTS (SELECT 1 FROM C c WHERE c.Id = a.Id) THEN 1 END Flag,\n"
        "       ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) rn\n"
        "INTO #t\n"
        "FROM A a\n"
        "WHERE a.Id IN (SELECT Id FROM D)\n"
        "INSERT INTO X SELECT (SELECT TOP 1 y FROM Y) FROM Z\n"
        "SET @v = (SELECT COUNT(1) FROM T)\n"
        "SELECT @w = (SELECT MAX(1) FROM T)\n"
    )
    found = run(select_list_subquery, sql)
    assert [line for line, _ in found] == [2, 3, 8]
    assert found[0][1].startswith("SELECT listesinde alt sorgu: (SELECT MAX(b.X) FROM B b")


# ------------------------------------------------------------------ DWH-INS-01
def test_tablock_physical_insert() -> None:
    sql = (
        "INSERT INTO EDW.TRX.Target (A) SELECT 1\n"
        "INSERT INTO EDW.TRX.Target WITH (TABLOCK) (A) SELECT 1\n"
        "INSERT EDW.TRX.Target WITH(TABLOCKX) SELECT 1\n"
        "INSERT INTO #t (A) SELECT 1\n"
        "INSERT INTO @t (A) SELECT 1\n"
        "INSERT INTO EDW.TRX.Unknown (A) SELECT 1\n"
        "INSERT INTO EDW.CHN.Branch WITH (HOLDLOCK) (BranchId) SELECT 1\n"
        "-- INSERT INTO EDW.TRX.Target SELECT 1\n"
    )
    assert run(tablock_physical_insert, sql) == [
        (1, "EDW.TRX.Target fiziksel tablo; INSERT WITH (TABLOCK) eksik"),
        (7, "EDW.CHN.Branch fiziksel tablo; INSERT WITH (TABLOCK) eksik"),
    ]
    assert run(tablock_physical_insert, sql, empty_metadata()) == []


# ------------------------------------------------------------------ DWH-JOIN-02
def test_join_column_type_mismatch() -> None:
    sql = (
        "SELECT 1 FROM EDWSTG.BOAAI.Src s\n"
        "JOIN EDW.CON.Account a ON a.AccountId = s.PointOfServiceId\n"
        "JOIN EDW.CHN.Branch b ON b.BranchId = a.BranchId AND b.BranchNk = s.PointOfServiceId\n"
        "JOIN EDW.CHN.Branch b2 ON b2.BranchId = CAST(s.PointOfServiceId AS INT)\n"
        "JOIN EDW.CHN.Branch b3 ON [b3].[BranchNk] = a.AccountId\n"
        "JOIN #t t ON t.X = a.AccountId\n"
        "JOIN EDW.CHN.Branch b4 ON s.TranDate = a.EdwValidFrom\n"
    )
    assert run(join_column_type_mismatch, sql) == [
        (2, "a.AccountId (int) = s.PointOfServiceId (varchar(20)) — tipler farklı"),
        (5, "[b3].[BranchNk] (varchar(50)) = a.AccountId (int) — tipler farklı"),
        (7, "s.TranDate (date) = a.EdwValidFrom (datetime) — tipler farklı"),
    ]


# ------------------------------------------------------------------ DWH-PERF-01
def test_non_sargable_predicates() -> None:
    sql = (
        "SELECT 1 FROM EDWSTG.BOAAI.Src STG\n"
        "JOIN EDW.CON.Account a ON CAST(STG.PointOfServiceId AS VARCHAR(50)) = a.AccountNk\n"
        "WHERE YEAR(a.OpenDate) = 2024\n"
        "  AND a.OpenDate >= CAST(@d AS DATE)\n"
        "  AND ISNULL(OpenDate, @d) = @d\n"
        "  AND a.BranchId IN (SELECT CAST(x.Id AS INT) FROM X x)\n"
        "  AND EXISTS (SELECT 1 FROM Y y WHERE LTRIM(y.Code) = a.AccountNk)\n"
        "GROUP BY a.Id HAVING MAX(LEFT(a.AccountNk, 2)) = 'x'\n"
    )
    # Line 2: CAST on a staging (EDWSTG) column is an accepted exception — staging has no indexes.
    assert run(non_sargable_predicates, sql) == [
        (3, "Filtre kolonunda fonksiyon: YEAR(a.OpenDate)"),
        (5, "Filtre kolonunda fonksiyon: ISNULL(OpenDate, @d)"),
        (7, "Filtre kolonunda fonksiyon: LTRIM(y.Code)"),
    ]


# ------------------------------------------------------------------ DWH-PERF-03
def test_or_in_predicates() -> None:
    sql = (
        "SELECT 1 FROM A a\n"
        "JOIN B b ON (b.x = a.x OR b.y = a.y)\n"
        "JOIN C c ON c.x = CASE WHEN a.k = 1 OR a.k = 2 THEN 1 ELSE 0 END\n"
        "WHERE (a.s = 1 OR a.s = 2)\n"
        "  AND (@p IS NULL OR a.t = @p)\n"
        "  AND (a.u = 1 OR b.v = 2)\n"
        "  AND a.w IN (SELECT z FROM Z WHERE z.q = 1 OR z.q = 2)\n"
    )
    assert [line for line, _ in run(or_in_predicates, sql)] == [2, 5, 6]
    messages = [m for _, m in run(or_in_predicates, sql)]
    assert messages[0] == "JOIN koşulunda OR kullanılmış: b.x = a.x OR b.y = a.y"
    assert messages[1].startswith("WHERE koşulunda farklı alanlar OR ile bağlanmış: @p IS NULL")


# ------------------------------------------------------------------ DWH-PERF-07
def test_scalar_udf_in_query() -> None:
    sql = (
        "DECLARE @x INT = dbo.fnScalar(1)\n"
        "SET @x = dbo.fnScalar(2)\n"
        "SELECT @x = dbo.fnScalar(3)\n"
        "IF dbo.fnScalar(@x) = 1 PRINT 1\n"
        "SELECT a.Id, dbo.fnScalar(a.Id) FROM A a WHERE EDW.dbo.fnScalar(a.Id) = 1\n"
        "UPDATE t SET c = dbo.fnScalar(t.c) FROM T t\n"
        "SELECT * FROM dbo.fnTable(1)\n"
        "SET @x = (SELECT MAX(dbo.fnScalar(b.Id)) FROM B b)\n"
    )
    assert [line for line, _ in run(scalar_udf_in_query, sql)] == [5, 5, 6, 8]
    assert run(scalar_udf_in_query, sql)[0][1] == "Sorgu içinde scalar fonksiyon çağrısı: EDW.dbo.fnScalar"


# ------------------------------------------------------------------ DWH-SQL-06
def test_window_order_by_type() -> None:
    sql = (
        "SELECT ROW_NUMBER() OVER (PARTITION BY a.BranchId ORDER BY a.AccountNk DESC) r1,\n"
        "       RANK() OVER (ORDER BY (SELECT NULL)) r2,\n"
        "       DENSE_RANK() OVER (ORDER BY CAST(a.AccountNk AS INT)) r3,\n"
        "       ROW_NUMBER() OVER (ORDER BY a.OpenDate, 1) r4,\n"
        "       ROW_NUMBER() OVER (ORDER BY t.Unknown) r5,\n"
        "       SUM(a.BranchId) OVER (ORDER BY a.AccountNk) s\n"
        "FROM EDW.CON.Account a JOIN #t t ON 1 = 1\n"
    )
    assert run(window_order_by_type, sql) == [
        (1, "a.AccountNk (varchar(50)) metin tipinde"),
        (2, "Sıralama sabit/belirsiz: (SELECT NULL)"),
        (4, "Sıralama sabit/belirsiz: 1"),
    ]


# ------------------------------------------------------------------ DWH-DATE-01
def test_variable_types() -> None:
    sql = (
        "CREATE PROCEDURE TRX.ins_X @DataDate DATE, @ReportPeriod INT = NULL\nAS\nBEGIN\n"
        "DECLARE @DataDateDT DATETIME = @DataDate, @Name VARCHAR(10) = 'a,b', @n INT\n"
        "DECLARE @t TABLE (a INT)\n"
    )
    assert variable_types(SqlDoc(sql)) == {
        "@datadate": "DATE", "@reportperiod": "INT", "@datadatedt": "DATETIME",
        "@name": "VARCHAR(10)", "@n": "INT",
    }
    assert type_family("datetime2(3)") == "datetime" and type_family("date") == "date"
    assert type_family("geography") is None


def test_date_variable_type_mismatch() -> None:
    sql = (
        "CREATE PROCEDURE TRX.ins_X @DataDate DATE, @Period INT\nAS\nBEGIN\n"
        "DECLARE @DataDateDT DATETIME = @DataDate, @Count INT = 0\n"
        "SELECT 1 FROM EDW.CON.Account a\n"
        "WHERE @DataDate BETWEEN a.EdwValidFrom AND a.EdwValidUntil\n"
        "  AND @DataDateDT BETWEEN a.EdwValidFrom AND a.EdwValidUntil\n"
        "  AND a.OpenDate = @DataDate\n"
        "  AND a.OpenDate <= @Period\n"
        "  AND a.BranchId = @Count\n"
        "  AND CAST(a.EdwValidFrom AS DATE) = @DataDate\n"
        "END\n"
    )
    assert run(date_variable_type_mismatch, sql) == [
        (6, "SCD filtresi için DATETIME değişken kullanın: @DataDate (DATE) ↔ a.EdwValidFrom "
            "(datetime). Örn. DECLARE @DataDateDT DATETIME = @DataDate"),
        (9, "@Period (INT) ↔ a.OpenDate (date)"),
    ]


def test_isnull_with_variable_first_is_accepted() -> None:
    sql = (
        "SELECT 1 FROM EDW.CON.Account a\n"
        "WHERE a.BranchId = ISNULL(@BranchId, a.BranchId)\n"
        "  AND a.OpenDate = COALESCE(@d, a.OpenDate)\n"
        "  AND ISNULL(a.BranchId, @BranchId) = 5\n"
    )
    # Only the column-first ISNULL is reported.
    assert run(non_sargable_predicates, sql) == [(4, "Filtre kolonunda fonksiyon: ISNULL(a.BranchId, @BranchId)")]


def test_functions_on_calendar_columns_are_accepted() -> None:
    sql = (
        "SELECT 1 FROM EDW.CON.Account a\n"
        "JOIN EDW.COR.Calendar C ON C.CalendarDate = EOMONTH(C.CalendarDate)\n"
        "WHERE YEAR(C.CalendarDate) = 2026\n"
        "  AND YEAR(a.OpenDate) = 2026\n"
    )
    # Only the Account column is reported; the Calendar table's own columns are exempt.
    assert run(non_sargable_predicates, sql) == [(4, "Filtre kolonunda fonksiyon: YEAR(a.OpenDate)")]
    # Same when the calendar is referenced without the database part.
    two_part = sql.replace("EDW.COR.Calendar", "COR.Calendar")
    assert run(non_sargable_predicates, two_part, empty_metadata()) == [
        (4, "Filtre kolonunda fonksiyon: YEAR(a.OpenDate)")
    ]


def test_non_sargable_isnull_is_accepted_only_in_scd_merge_procedures() -> None:
    sql = (
        "UPDATE TGT SET EdwValidUntil = GETDATE()\n"
        "FROM EDW.CON.Account TGT\n"
        "JOIN EDW.CHN.Branch SRC ON SRC.BranchId = TGT.BranchId\n"
        "WHERE ISNULL(SRC.BranchNk, '') <> ISNULL(TGT.AccountNk, '')\n"
        "  AND COALESCE(SRC.BranchName, '') <> ''\n"
        "  AND YEAR(TGT.OpenDate) = 2024\n"
    )
    merge = ObjectRef("EDW", "scd", "mrgCONAccount", "PROCEDURE")
    # In scd.mrg* only ISNULL/COALESCE are accepted; other functions are still reported.
    assert run(non_sargable_predicates, sql, obj=merge) == [
        (6, "Filtre kolonunda fonksiyon: YEAR(TGT.OpenDate)"),
    ]
    # The same code in any other procedure is reported in full.
    assert [line for line, _ in run(non_sargable_predicates, sql)] == [4, 4, 5, 6]


def test_non_sargable_staging_exception_but_key_table_conversion_is_flagged() -> None:
    meta = metadata(
        entry("EDWSTG", "BOAAI", "Src", columns=[col("PointOfServiceId")]),
        entry("EDWSKEY", "CHN", "ChannelDetailKey", columns=[col("ChannelDetailId"),
                                                            varchar("ChannelDetailNk")]),
    )
    sql = (
        "SELECT 1 FROM EDWSTG.BOAAI.Src STG WITH (NOLOCK)\n"
        "INNER JOIN EDWSKEY.CHN.ChannelDetailKey CDK WITH (NOLOCK)\n"
        "  ON CDK.ChannelDetailNk = CAST(STG.PointOfServiceId AS VARCHAR(50))\n"
        "INNER JOIN EDWSKEY.CHN.ChannelDetailKey K2 WITH (NOLOCK)\n"
        "  ON CAST(K2.ChannelDetailNk AS INT) = STG.PointOfServiceId\n"
    )
    assert run(non_sargable_predicates, sql, meta) == [
        (5, "Join kolonunda dönüşüm: CAST(K2.ChannelDetailNk AS INT)"),
    ]
    # Without catalog metadata the three-part name still identifies the staging database.
    assert run(non_sargable_predicates, sql, empty_metadata()) == [
        (5, "Join kolonunda dönüşüm: CAST(K2.ChannelDetailNk AS INT)"),
    ]


# ------------------------------------------------------------------ DWH-PF-01
VIEW = ObjectRef("EDWDM", "CUS", "vCustomer", "VIEW")
LKP = entry("EDWUTIL", "DTG", "LKPCustomerParty", columns=[col("CustomerPartyId")])
DM_SOURCE = entry("EDWDM", "CUS", "CustomerInfo", columns=[col("CustomerPartyId"), col("PersonnelFlag")])
EDW_SOURCE = entry("EDW", "PTY", "Customer", columns=[col("CustomerPartyId")])
SIBLING = entry("EDWDM", "CUS", "vCustomerPersonnelExcluded", "V", [col("CustomerPartyId")])


def pf(refs: list, own_cols: list, siblings: list | None = None) -> list[tuple]:  # type: ignore[type-arg]
    own = entry("EDWDM", "CUS", "vCustomer", "V", own_cols)
    meta = metadata(*refs, own=own, related=[SIBLING] if siblings is None else siblings)
    sql = "CREATE VIEW CUS.vCustomer AS SELECT 1 a\nFROM X\nJOIN EDWUTIL.DTG.LKPCustomerParty l ON 1=1"
    return run(personnel_flag_view_source, sql, meta, VIEW)


def test_personnel_flag_view_source() -> None:
    with_flag = [col("CustomerPartyId"), col("PersonnelFlag")]
    assert related_objects("personnel_flag_view_source", VIEW) == [
        ("EDWDM", "CUS", "vCustomerPersonnelExcluded"), ("EDWDM", "CUS", "vCustomerPersonnelMasked"),
    ]
    assert pf([EDW_SOURCE], [col("CustomerPartyId")], siblings=[]) == []  # no Personnel* sibling
    assert pf([EDW_SOURCE, LKP], with_flag) == []  # EDW source + LKP: standard
    assert pf([DM_SOURCE], with_flag) == []  # EDWDM source, no LKP: standard
    assert pf([EDW_SOURCE, LKP], [col("CustomerPartyId")]) == [
        (None, "Asıl view PersonnelFlag kolonunu sunmuyor")
    ]
    assert pf([DM_SOURCE, LKP], with_flag) == [
        (3, "EDWDM kaynağı (EDWDM.CUS.CustomerInfo) PersonnelFlag içeriyor; EDWUTIL.DTG LKP "
            "tabloları kullanılmamalı")
    ]
    assert pf([EDW_SOURCE], with_flag) == [
        (None, "View doğrudan EDW'den okuyor; PersonnelFlag EDWUTIL.DTG LKP tablolarıyla hesaplanmalı")
    ]
    assert run(personnel_flag_view_source, "x", empty_metadata(), VIEW) == []


# ------------------------------------------------------------------ SCD definition
def test_scd_definition() -> None:
    assert is_scd_table("EDW", True, True)
    assert not is_scd_table("EDW", True, False)  # no scd.mrg procedure
    assert is_scd_table("erpedw", True, True)
    assert is_scd_table("EDWDM", True, False)
    assert not is_scd_table("EDWDM", False, False)
    assert not is_scd_table("EDWSKEY", True, True)  # key map tables
    assert not is_scd_table("EDWLRY", True, False)


def test_non_sargable_ignores_dateparts_and_outer_columns() -> None:
    meta = metadata(entry("EDW", "X", "Cal", columns=[col("Month"), col("Year"), col("D", "date", 3, 10, 0)]),
                    entry("EDW", "COR", "FXRate", columns=[col("TranDate", "date", 3, 10, 0)]),
                    entry("EDW", "X", "E", columns=[col("SystemDate", "datetime", 8, 23, 3)]))
    sql = (
        "SELECT 1 FROM EDW.X.Cal x WHERE x.Month IN (MONTH(DATEADD(month, -2, @d)))\n"
        "SELECT (SELECT fr.TranDate FROM EDW.COR.FXRate fr WHERE fr.TranDate = "
        "CONVERT(DATE, e.SystemDate)) FROM EDW.X.E e\n"
    )
    assert run(non_sargable_predicates, sql, meta) == []


def test_nested_or_is_one_finding() -> None:
    sql = "SELECT 1 FROM A a WHERE a.x = 0 OR (a.y = 1 OR a.z = 2)"
    assert len(run(or_in_predicates, sql)) == 1
