import pytest

from app.services.builtin_checks import (
    ObjectRef,
    derived_view_consistency,
    main_view_of,
    nolock_physical_tables,
    related_objects,
)
from app.services.metadata import ObjectMetadata, empty_metadata
from app.services.rule_engine import mask_sql
from tests.helpers import col, entry, metadata, varchar

PROC = ObjectRef("EDW", "TRX", "ins_Test", "PROCEDURE")

META = metadata(
    entry("EDW", "CON", "Account"),
    entry("EDW", "dbo", "Branch"),
    entry("EDW", "CON", "vAccount", "V"),
    entry("EDWSTG", "BOAAI", "ATM_ATMDeposit"),
    entry("EDW", "TRX", "Target"),
    entry("EDW", "CON", "fnRows", "IF"),
)


def nolock(sql: str, meta: ObjectMetadata = META) -> list[tuple[int | None, str]]:
    return [(f.line, f.message) for f in nolock_physical_tables(sql, mask_sql(sql), PROC, meta)]


def test_physical_table_without_hint_is_flagged() -> None:
    sql = "SELECT a.x\nFROM EDW.CON.Account a\nJOIN CON.Account b ON a.Id = b.Id"
    assert nolock(sql) == [
        (2, "EDW.CON.Account fiziksel tablo; WITH (NOLOCK) eksik"),
        (3, "EDW.CON.Account fiziksel tablo; WITH (NOLOCK) eksik"),
    ]
    finding = nolock_physical_tables(sql, mask_sql(sql), PROC, META)[0]
    assert finding.snippet == "FROM EDW.CON.Account a"


def test_accepted_hint_spellings() -> None:
    sql = (
        "SELECT 1 FROM EDW.CON.Account WITH(NOLOCK)\n"
        "SELECT 1 FROM EDW.CON.Account a (NOLOCK)\n"
        "SELECT 1 FROM EDW.CON.Account (nolock) a\n"
        "SELECT 1 FROM EDW.CON.Account AS a WITH (NOLOCK, INDEX(1))\n"
        "SELECT 1 FROM EDW.CON.Account a WITH (READUNCOMMITTED)\n"
        "SELECT 1 FROM [EDW].[CON].[Account] [a] WITH (NOLOCK)\n"
    )
    assert nolock(sql) == []
    assert nolock("SELECT 1 FROM EDW.CON.Account a WITH (INDEX(1))") == [
        (1, "EDW.CON.Account fiziksel tablo; WITH (NOLOCK) eksik")
    ]


def test_three_part_bracketed_and_default_schema_names() -> None:
    sql = (
        "SELECT 1 FROM [EDWSTG].[BOAAI].[ATM_ATMDeposit] s\n"
        "SELECT 1 FROM EDW..Branch\n"
        "SELECT 1 FROM Branch b\n"
        "SELECT 1 FROM EDWSTG . BOAAI . ATM_ATMDeposit\n"
    )
    assert [line for line, _ in nolock(sql)] == [1, 2, 3, 4]
    assert nolock(sql)[0][1].startswith("EDWSTG.BOAAI.ATM_ATMDeposit")


def test_comma_separated_from_list() -> None:
    sql = "SELECT 1 FROM EDW.CON.Account a WITH (NOLOCK), EDW.dbo.Branch b, #t t WHERE a.x = b.x"
    assert nolock(sql) == [(1, "EDW.dbo.Branch fiziksel tablo; WITH (NOLOCK) eksik")]


def test_views_functions_temp_variables_ctes_and_unknown_not_flagged() -> None:
    sql = (
        "WITH Account AS (SELECT 1 x), Second AS (SELECT 2 y)\n"
        "SELECT * FROM Account\n"
        "JOIN Second s ON 1 = 1\n"
        "SELECT * FROM EDW.CON.vAccount v\n"
        "SELECT * FROM #tmp t JOIN ##g g ON 1 = 1\n"
        "SELECT * FROM @t\n"
        "SELECT * FROM EDW.CON.fnRows(1) f\n"
        "SELECT * FROM EDW.CON.Unknown u\n"
        "SELECT * FROM (SELECT 1 a FROM EDW.CON.Account WITH (NOLOCK)) d\n"
        "-- SELECT * FROM EDW.CON.Account\n"
        "PRINT 'FROM EDW.CON.Account'\n"
    )
    assert nolock(sql) == []


def test_update_and_delete_targets_not_flagged() -> None:
    sql = (
        "UPDATE t SET t.x = 1\n"
        "FROM EDW.TRX.Target t\n"
        "JOIN EDW.CON.Account a ON a.Id = t.Id;\n"
        "DELETE FROM EDW.TRX.Target WHERE x = 1;\n"
        "DELETE d FROM EDW.TRX.Target d INNER JOIN EDW.dbo.Branch b WITH (NOLOCK) ON b.x = d.x;\n"
        "UPDATE EDW.TRX.Target SET x = 2 FROM EDW.TRX.Target JOIN EDW.CON.Account a2 WITH (NOLOCK) ON 1=1\n"
        "SELECT * FROM EDW.TRX.Target t\n"
    )
    found = nolock(sql)
    assert found == [
        (3, "EDW.CON.Account fiziksel tablo; WITH (NOLOCK) eksik"),
        (7, "EDW.TRX.Target fiziksel tablo; WITH (NOLOCK) eksik"),
    ]


def test_update_target_scope_ends_with_statement() -> None:
    sql = (
        "UPDATE a SET x = CASE WHEN y = 1 THEN 2 ELSE 3 END FROM EDW.CON.Account a\n"
        "SELECT * FROM EDW.CON.Account a\n"
    )
    assert nolock(sql) == [(2, "EDW.CON.Account fiziksel tablo; WITH (NOLOCK) eksik")]


def test_no_metadata_reports_nothing() -> None:
    sql = "SELECT 1 FROM EDW.CON.Account"
    assert nolock(sql, empty_metadata()) == []
    assert nolock(sql, ObjectMetadata(available=True)) == []


# ------------------------------------------------------------------ derived views
VIEW = ObjectRef("EDWDM", "CUS", "vCustomerInfoMasked", "VIEW")
MAIN_COLS = [
    col("CustomerId"), varchar("CustomerName"), varchar("TaxNo", 11), col("PersonnelFlag"),
    col("BranchId"),
]
GOOD_SQL = (
    "CREATE VIEW CUS.vCustomerInfoMasked AS\n"
    "SELECT T1.CustomerId,\n"
    "       CAST(NULL AS varchar(50)) AS [CustomerName],\n"
    "       T1.TaxNo,\n"
    "       T1.BranchId\n"
    "FROM [EDWDM].[CUS].[vCustomerInfo] T1 WITH(NOLOCK)\n"
)
DERIVED_OK = [col("CustomerId"), varchar("CustomerName"), varchar("TaxNo", 11), col("BranchId")]


def derived(sql: str, own_cols: list, obj: ObjectRef = VIEW, main_cols: list | None = None,
            with_main: bool = True) -> list[tuple[int | None, str]]:
    main = entry("EDWDM", obj.schema, main_view_of(obj)[2], "V", main_cols or MAIN_COLS)
    own = entry(obj.database, obj.schema, obj.name, "V", own_cols)
    meta = metadata(own=own, related=[main] if with_main else [])
    return [(f.line, f.message) for f in derived_view_consistency(sql, mask_sql(sql), obj, meta)]


def test_consistent_derived_view() -> None:
    assert derived(GOOD_SQL, DERIVED_OK) == []
    assert related_objects("derived_view_consistency", VIEW) == [("EDWDM", "CUS", "vCustomerInfo")]
    assert main_view_of(ObjectRef("EDWDM", "CUS", "vXPersonnelMasked")) == ("EDWDM", "CUS", "vX")


def test_main_view_missing() -> None:
    assert derived(GOOD_SQL, DERIVED_OK, with_main=False) == [
        (None, "Asıl view bulunamadı: CUS.vCustomerInfo")
    ]


def test_missing_extra_and_order() -> None:
    own = [varchar("TaxNo", 11), col("CustomerId"), varchar("CustomerName"), col("Extra1")]
    messages = [m for _, m in derived(GOOD_SQL, own)]
    assert "Asıl view'da olup türevde eksik kolonlar: BranchId" in messages
    assert "Türevde olup asıl view'da olmayan kolonlar: Extra1" in messages
    assert "Kolon sırası asıl view ile farklı: CustomerId, CustomerName, TaxNo" in messages


def test_case_only_difference_is_one_finding() -> None:
    own = [col("customerId"), varchar("CustomerName"), varchar("TaxNo", 11), col("BranchId")]
    sql = GOOD_SQL.replace("T1.CustomerId", "T1.customerId")
    assert derived(sql, own) == [
        (2, "Kolon adı yalnızca büyük/küçük harf farkıyla farklı: asıl 'CustomerId', türev 'customerId'")
    ]


def test_null_masked_type_change_is_ignored_but_real_type_difference_is_reported() -> None:
    # Team standard: NULL masking in derived views may change the type; only real differences count.
    sql = GOOD_SQL.replace("CAST(NULL AS varchar(50)) AS [CustomerName]", "NULL AS [CustomerName]")
    own = [col("CustomerId"), col("CustomerName"), varchar("TaxNo", 20), col("BranchId")]
    found = derived(sql, own)
    assert found == [(4, "Kolon tipi farklı: TaxNo türevde varchar(20), asıl view'da varchar(11).")]


@pytest.mark.parametrize(
    "expression",
    [
        "NULL AS [CustomerName]",
        "NULL [CustomerName]",
        "null as CustomerName",
        "CAST(NULL AS int) AS [CustomerName]",
        "CAST(NULL AS varchar(10)) CustomerName",
        "CONVERT(int, NULL) AS [CustomerName]",
    ],
)
def test_all_null_mask_forms_are_ignored(expression: str) -> None:
    sql = GOOD_SQL.replace("CAST(NULL AS varchar(50)) AS [CustomerName]", expression)
    own = [col("CustomerId"), col("CustomerName"), varchar("TaxNo", 11), col("BranchId")]
    assert derived(sql, own) == []


def test_personnel_flag_in_derived_and_missing_filter() -> None:
    obj = ObjectRef("EDWDM", "CUS", "vCustomerInfoPersonnelExcluded", "VIEW")
    sql = GOOD_SQL.replace("vCustomerInfoMasked", obj.name).replace(
        "T1.BranchId\n", "T1.BranchId,\n       T1.PersonnelFlag\n"
    )
    own = DERIVED_OK + [col("PersonnelFlag")]
    messages = [m for _, m in derived(sql, own, obj)]
    assert any("PersonnelFlag kolonunu sunmamalı" in m for m in messages)
    assert any("PersonnelFlag = 0 filtresi yok" in m for m in messages)
    assert len(messages) == 2
    fixed = GOOD_SQL.replace("vCustomerInfoMasked", obj.name) + "WHERE T1.PersonnelFlag = 0\n"
    assert derived(fixed, DERIVED_OK, obj) == []


def test_not_reading_main_view() -> None:
    sql = GOOD_SQL.replace("[EDWDM].[CUS].[vCustomerInfo]", "EDW.CUS.Customer")
    assert derived(sql, DERIVED_OK) == [
        (None, "Türev view asıl view'dan okumuyor: EDWDM.CUS.vCustomerInfo referansı yok.")
    ]
    # Other spellings of the main view count; a longer name does not.
    for spelling in ("EDWDM.CUS.vCustomerInfo", "[CUS].[vCustomerInfo]", "cus.vcustomerinfo"):
        assert derived(GOOD_SQL.replace("[EDWDM].[CUS].[vCustomerInfo]", spelling), DERIVED_OK) == []
    longer = GOOD_SQL.replace("[EDWDM].[CUS].[vCustomerInfo]", "CUS.vCustomerInfoOld")
    assert len(derived(longer, DERIVED_OK)) == 1


def test_text_checks_without_metadata() -> None:
    obj = ObjectRef("EDWDM", "CUS", "vCustomerInfoPersonnelMasked", "VIEW")
    sql = "CREATE VIEW CUS.vCustomerInfoPersonnelMasked AS SELECT 1 a FROM EDW.CUS.X"
    found = derived_view_consistency(sql, mask_sql(sql), obj, empty_metadata())
    # without the main view's columns the PersonnelFlag = 0 filter is not required (v4)
    assert [f.message for f in found] == [
        "Türev view asıl view'dan okumuyor: EDWDM.CUS.vCustomerInfo referansı yok."
    ]
    assert derived_view_consistency(sql, mask_sql(sql), ObjectRef("EDWDM", "CUS", "vMain"),
                                    empty_metadata()) == []
