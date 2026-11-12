"""v1.4 (RULES_SPEC_v14.md): rule fixes, new builtins, rule exceptions, migration 3 -> 4."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.builtin_checks import ObjectRef, derived_view_consistency
from app.services.exceptions import ExceptionMatcher
from app.services.metadata import ObjectMetadata
from app.services.perf_checks import personnel_flag_view_source, tablock_physical_insert
from app.services.rule_engine import mask_sql
from app.services.v4_checks import calendar_date_predicate, id_literal_filter
from tests.conftest import FakeCatalog, wait_for
from tests.helpers import col, entry, metadata, varchar

PROC = ObjectRef("EDWDM", "TRX", "ins_X", "PROCEDURE")
DATE = col("TranDate", "date", 3, 10, 0)
DATETIME = col("SystemDate", "datetime", 8, 23, 3)


def run(check, sql: str, meta: ObjectMetadata, obj: ObjectRef = PROC) -> list[tuple]:  # type: ignore[no-untyped-def]
    return [(f.line, f.message) for f in check(sql, mask_sql(sql), obj, meta)]


# ------------------------------------------------------------------ 1) DWH-INS-01
def test_ins01_skips_values_and_edwutil() -> None:
    meta = metadata(
        entry("EDWUTIL", "OPR", "DMExecutionStepTimeControl", columns=[col("Step")]),
        entry("EDWDM", "TRX", "Target", columns=[col("A")]),
    )
    sql = (
        "INSERT INTO [EDWUTIL].[OPR].[DMExecutionStepTimeControl](SpName, Step) VALUES ('x', 1)\n"
        "INSERT INTO EDWUTIL.OPR.DMExecutionStepTimeControl (Step) SELECT 1\n"
        "INSERT INTO TRX.Target (A) VALUES (1)\n"
        "INSERT INTO TRX.Target VALUES (1)\n"
        "INSERT INTO TRX.Target WITH (HOLDLOCK) (A) VALUES (1)\n"
        "INSERT INTO TRX.Target (A) SELECT 1\n"
        "INSERT INTO TRX.Target (A) EXEC dbo.p\n"
    )
    assert [line for line, _ in run(tablock_physical_insert, sql, meta)] == [6, 7]


# ------------------------------------------------------------------ 2) DWH-DM-02
def test_dm02_personnel_filter_only_when_main_view_has_flag() -> None:
    obj = ObjectRef("EDWDM", "CMP", "vPermPersonnelExcluded", "VIEW")
    sql = "CREATE VIEW CMP.vPermPersonnelExcluded AS SELECT T1.A FROM [EDWDM].[CMP].[vPerm] T1 WITH(NOLOCK)"

    def derived(main_cols: list) -> list[str]:  # type: ignore[type-arg]
        meta = metadata(own=entry("EDWDM", "CMP", obj.name, "V", [col("A")]),
                        related=[entry("EDWDM", "CMP", "vPerm", "V", main_cols)])
        return [f.message for f in derived_view_consistency(sql, mask_sql(sql), obj, meta)]

    assert derived([col("A")]) == []  # aggregated main view without PersonnelFlag
    assert derived([col("A"), col("PersonnelFlag")]) == [
        "Personnel türevinde PersonnelFlag = 0 filtresi yok (WHERE T1.PersonnelFlag = 0 uygulanmalı)."
    ]


# ------------------------------------------------------------------ 3) DWH-PF-01
VIEW = ObjectRef("EDWDM", "CUS", "vCustomer", "VIEW")
SIBLING = entry("EDWDM", "CUS", "vCustomerPersonnelMasked", "V", [col("A")])
DM_SOURCE = entry("EDWDM", "CUS", "CustomerInfo", columns=[col("CustomerPartyId"), col("PersonnelFlag")])
IDENTITY_LKP = entry("EDWUTIL", "DTG", "LKPIdentityNumber", columns=[col("IdentityOrTAXNk")])
PARTY_LKP = entry("EDWUTIL", "DTG", "LKPCustomerParty", columns=[col("CustomerPartyId")])
EDW_SOURCE = entry("EDW", "PTY", "Customer", columns=[col("CustomerPartyId")])


def pf(refs: list, own_cols: list) -> list[str]:  # type: ignore[type-arg]
    own = entry("EDWDM", "CUS", "vCustomer", "V", own_cols)
    meta = metadata(*refs, own=own, related=[SIBLING])
    sql = "CREATE VIEW CUS.vCustomer AS SELECT 1 a FROM X JOIN EDWUTIL.DTG.LKPCustomerParty l ON 1=1"
    return [f.message for f in personnel_flag_view_source(sql, mask_sql(sql), VIEW, meta)]


def test_pf01_requires_identity_column() -> None:
    assert pf([EDW_SOURCE], [col("Period"), col("Amount")]) == []  # no CustomerPartyId/PersonPartyId
    assert pf([EDW_SOURCE], [col("personpartyid")]) == [
        "Asıl view PersonnelFlag kolonunu sunmuyor",
        "View doğrudan EDW'den okuyor; PersonnelFlag EDWUTIL.DTG LKP tablolarıyla hesaplanmalı",
    ]


def test_pf01_identity_number_lkp_allowed_next_to_dm_source() -> None:
    with_flag = [col("CustomerPartyId"), col("PersonnelFlag")]
    assert pf([DM_SOURCE, IDENTITY_LKP], with_flag) == []
    assert len(pf([DM_SOURCE, IDENTITY_LKP, PARTY_LKP], with_flag)) == 1
    assert pf([EDW_SOURCE, IDENTITY_LKP], with_flag) == []  # still a valid LKP for rule 3


# ------------------------------------------------------------------ 4/7a) DWH-ID-01
ID_META = metadata(
    entry("EDWDM", "TRX", "Fact", columns=[col("SourceId"), col("FECId"), varchar("FECNk"),
                                           col("LedgerId"), varchar("LedgerNk"), col("FirmId"),
                                           varchar("FirmNk"), col("BranchId"), col("index_id")]),
    entry("EDWDM", "CUS", "vCustomer", "V", columns=[col("CustomerClassId"), varchar("CustomerClassNk")]),
)
ID_META.surrogate_key_bases = frozenset({"branch", "fec"})


def test_id_literal_filter() -> None:
    sql = (
        "SELECT 1 FROM TRX.Fact A\n"
        "JOIN CUS.vCustomer v ON v.CustomerClassId IN ('1','3')\n"
        "JOIN #t t ON t.FECId = 5\n"
        "WHERE A.SourceId NOT IN ('2','6')\n"
        "  AND A.FECId = 5\n"
        "  AND A.LedgerId <> 0\n"
        "  AND A.FirmId NOT IN (-98,-99)\n"
        "  AND A.FirmId = -1\n"
        "  AND A.index_id IN (0,1)\n"
        "  AND A.BranchId = 12\n"
        "  AND 7 = A.FECId\n"
        "  AND A.FECId = @Fec\n"
    )
    assert run(id_literal_filter, sql, ID_META) == [
        (5, "A.FECId veri ambarı vekil anahtarı; sabit değer filtresi FECNk üzerinden yapılmalı (değer: 5)"),
        (6, "A.LedgerId veri ambarı vekil anahtarı; sabit değer filtresi LedgerNk üzerinden yapılmalı (değer: 0)"),
        (10, "A.BranchId veri ambarı vekil anahtarı; ilgili LKP/anahtar tablosuna BranchId üzerinden join "
             "kurup BranchNk ile filtreleyin (değer: 12)"),
        (11, "A.FECId veri ambarı vekil anahtarı; sabit değer filtresi FECNk üzerinden yapılmalı (değer: 7)"),
    ]
    assert run(id_literal_filter, sql, ObjectMetadata()) == []


# ------------------------------------------------------------------ 5) DWH-CAL-01
CAL_META = metadata(entry("EDWDM", "TRX", "T", columns=[DATE, DATETIME, col("Amount")]),
                    entry("EDWSTG", "S", "Stg", columns=[DATE]))


def test_calendar_date_predicate() -> None:
    sql = (
        "DECLARE @Period INT = CAST(CONVERT(VARCHAR(6),@ReportDate,112) AS INT);\n"
        "SELECT CONVERT(VARCHAR(6), t.TranDate, 112) AS Period FROM TRX.T t\n"
        "WHERE CONVERT(DATE, t.SystemDate) = @DataDate\n"
        "SELECT 1 FROM TRX.T a JOIN EDW.COR.Calendar c ON CAST(a.TranDate AS DATE) = c.CalendarDate\n"
        "SELECT 1 FROM TRX.T t WHERE t.TranDate >= @d AND t.TranDate < DATEADD(DAY,1,@d)\n"
        "SELECT 1 FROM TRX.T t WHERE YEAR(t.TranDate) * 100 + MONTH(t.TranDate) = @Period\n"
        "SELECT 1 FROM TRX.T t WHERE CAST(t.Amount AS INT) = 5\n"
        "SELECT 1 FROM EDWSTG.S.Stg s WHERE CONVERT(DATE, s.TranDate) = @d\n"
        "SELECT 1 FROM #tmp x WHERE CONVERT(VARCHAR(8), x.Anything, 112) = @p\n"
        "SELECT 1 FROM #tmp x WHERE UPPER(x.Anything) = @p\n"
    )
    found = run(calendar_date_predicate, sql, CAL_META)
    assert [line for line, _ in found] == [3, 4, 6, 9]
    assert found[0][1] == (
        "Öneri: CONVERT(DATE, t.SystemDate) yerine EDW.COR.Calendar ile aralık join'i "
        "(X >= C.CalendarDate AND X < DATEADD(DAY,1,C.CalendarDate))"
    )
    assert found[2][1].startswith("Öneri: YEAR(t.TranDate) * 100 + MONTH(t.TranDate) yerine")


def test_calendar_date_predicate_ignores_calendar_columns() -> None:
    calendar = entry("EDW", "COR", "Calendar", columns=[col("CalendarDate", "date", 3, 10, 0)])
    meta = metadata(entry("EDWDM", "TRX", "T", columns=[DATE, DATETIME, col("Amount")]), calendar)
    sql = (
        "SELECT 1 FROM TRX.T t JOIN EDW.COR.Calendar c ON c.CalendarDate = EOMONTH(c.CalendarDate)\n"
        "WHERE CONVERT(DATE, c.CalendarDate) = @d AND CONVERT(DATE, t.SystemDate) = @d\n"
    )
    assert [line for line, _ in run(calendar_date_predicate, sql, meta)] == [2]


# ------------------------------------------------------------------ 6) rule exceptions
def test_exception_matcher() -> None:
    row = type("R", (), {"database": "edwdm", "schema": None, "object_name": " ",
                         "snippet_pattern": r"MAX_GRANT_PERCENT"})()
    matcher = ExceptionMatcher.from_row(row)  # type: ignore[arg-type]
    assert matcher.matches("EDWDM", "TRX", "p", "OPTION (MIN_GRANT_PERCENT = 5, max_grant_percent = 20)", "m")
    assert not matcher.matches("EDW", "TRX", "p", "OPTION (MAX_GRANT_PERCENT = 20)", "m")
    assert not matcher.matches("EDWDM", "TRX", "p", "OPTION (MAXDOP 1)", "m")


def rule_id(client: TestClient, code: str) -> int:
    return next(r["id"] for r in client.get("/api/rules").json() if r["code"] == code)


def test_exception_api(client: TestClient) -> None:
    hint = rule_id(client, "DWH-HINT-01")
    url = f"/api/rules/{hint}/exceptions"
    empty = client.post(url, json={"reason": "x", "database": " "})
    assert empty.status_code == 422 and "pasifleştirin" in empty.json()["detail"]
    assert client.post(url, json={"database": "EDWDM", "reason": " "}).status_code == 422
    assert client.post(url, json={"database": "EDWDM", "reason": "x" * 501}).status_code == 422
    bad = client.post(url, json={"snippet_pattern": "(x", "reason": "r"})
    assert bad.status_code == 422 and "snippet_pattern" in bad.json()["detail"]
    assert client.post("/api/rules/99999/exceptions", json={"database": "X", "reason": "r"}).status_code == 404

    created = client.post(url, json={"database": "EDWDM", "schema": "TRX", "object_name": "p",
                                     "snippet_pattern": "GRANT_PERCENT", "reason": "Bilinçli"})
    assert created.status_code == 201
    body = created.json()
    assert body["rule_code"] == "DWH-HINT-01" and body["schema"] == "TRX" and body["created_at"].endswith("Z")
    assert client.get(f"/api/rules/{hint}").json()["exception_count"] == 1
    assert [e["id"] for e in client.get("/api/rule-exceptions", params={"rule_id": hint}).json()] == [body["id"]]
    assert client.get("/api/rule-exceptions", params={"rule_id": hint + 1}).json() == []
    assert client.delete(f"/api/rule-exceptions/{body['id']}").status_code == 204
    assert client.delete(f"/api/rule-exceptions/{body['id']}").status_code == 404
    assert client.get(f"/api/rules/{hint}").json()["exception_count"] == 0


def test_exceptions_suppress_findings_in_analysis(client: TestClient, fake_catalog: FakeCatalog) -> None:
    sql = (
        "CREATE PROCEDURE dbo.p AS\n"
        "SELECT 1 FROM t OPTION (MIN_GRANT_PERCENT = 5, MAX_GRANT_PERCENT = 20)\n"
        "SELECT 1 FROM t OPTION (MAXDOP 1)\n"
    )
    fake_catalog.definitions[("DWH", "dbo", "p")] = sql
    fake_catalog.definitions[("DWH", "dbo", "q")] = sql
    hint = rule_id(client, "DWH-HINT-01")
    client.post(f"/api/rules/{hint}/exceptions",
                json={"object_name": "P", "snippet_pattern": "GRANT_PERCENT", "reason": "Bilinçli"})
    conn = client.post("/api/connections", json={"name": "c", "server": "localhost", "port": 1433,
                                                 "username": "sa", "password": "secret"}).json()["id"]
    objects = [{"database": "DWH", "schema": "dbo", "name": n, "type": "PROCEDURE"} for n in ("p", "q")]
    summary = client.post("/api/analyses", json={"connection_id": conn, "objects": objects,
                                                 "rule_ids": [hint]}).json()
    assert summary["suppressed_count"] == 0
    detail = wait_for(client, summary["id"])
    assert detail["finding_count"] == 3 and detail["suppressed_count"] == 1
    by_name = {o["name"]: o for o in detail["objects"]}
    assert (by_name["p"]["finding_count"], by_name["p"]["suppressed_count"]) == (1, 1)
    assert (by_name["q"]["finding_count"], by_name["q"]["suppressed_count"]) == (2, 0)
    html = client.get(f"/api/analyses/{summary['id']}/report.html").text
    assert "İstisna nedeniyle gizlenen bulgu: 1" in html
    # The rule test endpoint ignores exceptions.
    rule = client.get(f"/api/rules/{hint}").json()
    tested = client.post("/api/rules/test", json={"rule": rule, "sql": sql, "object_name": "dbo.p"}).json()
    assert len(tested["findings"]) == 2
    # Deleting the rule deletes its exceptions.
    assert client.delete(f"/api/rules/{hint}").status_code == 204
    assert client.get("/api/rule-exceptions").json() == []


# ------------------------------------------------------------------ migration 3 -> 4
def test_migration_v3_to_v4(tmp_path: Path) -> None:
    from app.seed import _TEXTS_V3

    with TestClient(create_app(tmp_path)):
        pass
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:  # back to a v3 database: v3 definitions, no v1.4 columns/table, a user edit
        for code in ("DWH-ID-01", "DWH-CAL-01"):
            old = _TEXTS_V3[code]
            db.execute("UPDATE rules SET kind='regex', builtin_check=NULL, pattern=?, severity='high', "
                       "name=?, description=? WHERE code=?", (old["pattern"], old["name"], old["description"], code))
        db.execute("UPDATE rules SET pattern = ? WHERE code = 'DWH-PERF-02'", (_TEXTS_V3["DWH-PERF-02"]["pattern"],))
        db.execute("UPDATE rules SET enabled = 0, recommendation = 'Benim önerim' WHERE code = 'DWH-ID-01'")
        db.execute("DROP TABLE rule_exceptions")
        for table in ("analyses", "analysis_objects"):
            db.execute(f"ALTER TABLE {table} DROP COLUMN suppressed_count")
        db.execute("UPDATE app_meta SET value = '3' WHERE key = 'ruleset_version'")
        db.commit()
    finally:
        db.close()

    with TestClient(create_app(tmp_path)) as client:
        rules = {r["code"]: r for r in client.get("/api/rules").json()}
        assert len(rules) == 32
        id01, cal01 = rules["DWH-ID-01"], rules["DWH-CAL-01"]
        assert (id01["kind"], id01["builtin_check"], id01["pattern"]) == ("builtin", "id_literal_filter", None)
        assert id01["enabled"] is False and id01["recommendation"] == "Benim önerim"  # user edits kept
        assert "Vekil anahtar tespiti katalogdan yapılır." in id01["description"]
        assert (cal01["severity"], cal01["builtin_check"]) == ("low", "calendar_date_predicate")
        assert "FORMAT" in rules["DWH-PERF-02"]["pattern"]
        assert "EDWUTIL log/kontrol" in rules["DWH-INS-01"]["description"]
        assert "LKPIdentityNumber kimlik maskeleme" in rules["DWH-PF-01"]["description"]
        assert client.get("/api/rule-exceptions").json() == []
        assert client.get("/api/analyses").json() == []
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(analysis_objects)")}
        assert "suppressed_count" in cols
        assert db.execute("SELECT value FROM app_meta").fetchone() == ("7",)
    finally:
        db.close()
