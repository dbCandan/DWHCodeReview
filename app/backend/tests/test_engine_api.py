"""v1.1 rule engine through the API: validation, applicability, preconditions, builtins."""

import json

import httpx
from fastapi.testclient import TestClient

from app import models
from app.db import get_database
from app.services import llm
from app.services.metadata import PartitionInfo
from tests.conftest import FakeCatalog, wait_for
from tests.helpers import col, entry, metadata

CONN = {"name": "Yerel", "server": "localhost", "port": 1433, "username": "sa",
        "password": "secret", "encrypt": True, "trust_server_certificate": True}

BASE = {"code": "T-001", "name": "Test", "description": "Açıklama", "recommendation": "",
        "severity": "high", "kind": "regex", "pattern": r"\bSELECT\b", "match_mode": "match",
        "target": "definition", "ignore_case": True, "ignore_comments": True, "llm_prompt": None,
        "object_types": [], "enabled": True, "group_ids": []}

SCD_PROC = """CREATE PROCEDURE TRX.ins_Scd
AS
SELECT a.AccountId FROM EDW.CON.Account a WITH (NOLOCK)
JOIN EDW.TRX.Fact f ON f.AccountId = a.AccountId
"""


def by_code(client: TestClient) -> dict[str, dict]:
    return {r["code"]: r for r in client.get("/api/rules").json()}


def test_rule_validation(client: TestClient) -> None:
    cases = [
        ({"kind": "builtin"}, "builtin_check"),
        ({"kind": "builtin", "builtin_check": "yok"}, "Bilinmeyen yerleşik kontrol"),
        ({"metadata_precondition": "yok"}, "metadata_precondition"),
        ({"precondition": "(x"}, "precondition"),
        ({"name_pattern": "[x"}, "name_pattern"),
        ({"kind": "llm", "llm_prompt": " "}, "llm_prompt"),
        ({"pattern": None}, "pattern"),
    ]
    for change, text in cases:
        response = client.post("/api/rules", json={**BASE, **change})
        assert response.status_code == 422, change
        assert text in response.json()["detail"], response.json()

    created = client.post(
        "/api/rules",
        json={**BASE, "kind": "builtin", "pattern": None,
              "builtin_check": "nolock_physical_tables", "precondition": "  ",
              "metadata_precondition": "references_partitioned_table", "requires_metadata": True,
              "databases": [" EDW ", "edw", "EDWDM", ""], "name_pattern": r"^TRX\."},
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["builtin_check"] == "nolock_physical_tables" and rule["precondition"] is None
    assert rule["databases"] == ["EDW", "EDWDM"] and rule["name_pattern"] == r"^TRX\."
    assert rule["metadata_precondition"] == "references_partitioned_table"
    assert rule["requires_metadata"] is True
    copy = client.post(f"/api/rules/{rule['id']}/duplicate").json()
    assert {k: copy[k] for k in ("builtin_check", "databases", "name_pattern", "kind")} == {
        k: rule[k] for k in ("builtin_check", "databases", "name_pattern", "kind")
    }
    # Switching kind clears builtin_check.
    updated = client.put(f"/api/rules/{rule['id']}", json={**rule, "kind": "regex",
                                                           "pattern": "x"}).json()
    assert updated["builtin_check"] is None


def test_rule_test_endpoint_v11(client: TestClient) -> None:
    rules = by_code(client)
    note = "Bu kural katalog metadatası gerektirir; tam sonuç için analiz çalıştırın."
    nolock = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-NOLOCK-01"], "sql": "SELECT 1 FROM EDW.CON.Account a"},
    ).json()
    assert nolock == {"findings": [], "error": note}

    derived = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-DM-02"], "sql": "CREATE VIEW CUS.vXPersonnelMasked AS SELECT 1 a",
              "object_name": "CUS.vXPersonnelMasked", "object_type": "VIEW", "database": "EDWDM"},
    ).json()
    assert derived["error"] == note and len(derived["findings"]) == 1

    other_db = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-DM-02"], "sql": "x", "database": "EDW"},
    ).json()
    assert other_db["findings"] == [] and "databases" in other_db["error"]
    wrong_name = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-DM-02"], "sql": "x", "object_name": "CUS.vX"},
    ).json()
    assert "name_pattern" in wrong_name["error"]

    regex = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-SCD-02"], "sql": "SELECT 1 FROM t\nWHERE EdwStatus = 1"},
    ).json()
    assert regex["error"] is None and [f["line"] for f in regex["findings"]] == [2]

    skipped = client.post(
        "/api/rules/test",
        json={"rule": {**BASE, "precondition": "MERGE"}, "sql": "SELECT 1"},
    ).json()
    assert skipped["findings"] == [] and "Ön koşul" in skipped["error"]


def setup(client: TestClient, fake_catalog: FakeCatalog) -> int:
    fake_catalog.definitions[("EDW", "TRX", "ins_Scd")] = SCD_PROC
    return client.post("/api/connections", json=CONN).json()["id"]


def test_applicability_affects_total_checks(client: TestClient, fake_catalog: FakeCatalog) -> None:
    conn_id = setup(client, fake_catalog)
    ids = []
    for code, extra in (
        ("A-ALL", {}),
        ("A-DB", {"databases": ["edw"]}),
        ("A-OTHERDB", {"databases": ["EDWDM"]}),
        ("A-NAME", {"name_pattern": r"^TRX\.ins_"}),
        ("A-VIEW", {"object_types": ["VIEW"]}),
    ):
        ids.append(client.post("/api/rules", json={**BASE, "code": code, **extra}).json()["id"])
    objects = [
        {"database": "EDW", "schema": "TRX", "name": "ins_Scd", "type": "PROCEDURE"},
        {"database": "DWH", "schema": "dbo", "name": "vSales", "type": "VIEW"},
    ]
    summary = client.post(
        "/api/analyses", json={"connection_id": conn_id, "objects": objects, "rule_ids": ids}
    ).json()
    # ins_Scd: ALL, DB, NAME; vSales: ALL, VIEW
    assert summary["total_checks"] == 5
    detail = wait_for(client, summary["id"])
    assert detail["status"] == "completed" and detail["completed_checks"] == 5
    findings = client.get(f"/api/analyses/{summary['id']}/findings").json()
    assert sorted((f["object_label"], f["rule_code"]) for f in findings) == [
        ("DWH.dbo.vSales", "A-ALL"), ("DWH.dbo.vSales", "A-VIEW"),
        ("EDW.TRX.ins_Scd", "A-ALL"), ("EDW.TRX.ins_Scd", "A-DB"), ("EDW.TRX.ins_Scd", "A-NAME"),
    ]
    with get_database().session_factory() as session:
        snapshot = session.query(models.AnalysisRule).filter_by(code="A-DB").one()
        assert snapshot.databases == ["edw"]


def enable_llm(client: TestClient, calls: list[dict]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        content = '{"violations": [{"line": 4, "snippet": "JOIN EDW.TRX.Fact f", "reason": "Filtre yok."}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    llm.http_transport = httpx.MockTransport(handler)
    client.put("/api/settings/llm", json={"enabled": True, "base_url": "http://llm.local/v1",
                                          "model": "m1", "api_key": None, "temperature": 0,
                                          "timeout_seconds": 30})


def run(client: TestClient, conn_id: int, codes: list[str]) -> dict:
    rules = by_code(client)
    summary = client.post(
        "/api/analyses",
        json={"connection_id": conn_id,
              "objects": [{"database": "EDW", "schema": "TRX", "name": "ins_Scd",
                           "type": "PROCEDURE"}],
              "rule_ids": [rules[c]["id"] for c in codes]},
    ).json()
    return wait_for(client, summary["id"])


def test_metadata_precondition_skips_llm(client: TestClient, fake_catalog: FakeCatalog) -> None:
    conn_id = setup(client, fake_catalog)
    calls: list[dict] = []
    enable_llm(client, calls)

    # Fact is not an SCD table: the check completes without an LLM call.
    fake_catalog.metadata[("EDW", "TRX", "ins_Scd")] = metadata(
        entry("EDW", "CON", "Account", columns=[col("AccountId")]),
        entry("EDW", "TRX", "Fact", columns=[col("AccountId")]),
    )
    detail = run(client, conn_id, ["DWH-SCD-01"])
    assert detail["status"] == "completed" and detail["completed_checks"] == 1
    assert detail["finding_count"] == 0 and calls == []

    # NK-01 text precondition fails: no metadata is even collected.
    fake_catalog.describe_calls.clear()
    detail = run(client, conn_id, ["DWH-NK-01"])
    assert detail["completed_checks"] == 1 and calls == [] and fake_catalog.describe_calls == []

    # With an SCD table the LLM is called once, with the metadata block in the prompt.
    fake_catalog.metadata[("EDW", "TRX", "ins_Scd")] = metadata(
        entry("EDW", "CON", "Account", columns=[col("AccountId"), col("EdwValidFrom", "datetime"),
                                                 col("EdwValidUntil", "datetime")]),
        entry("EDW", "TRX", "Fact", columns=[col("AccountId")],
              partition=PartitionInfo("D", "date", "fn_d", "date", "RIGHT", "ps_d")),
    )
    fake_catalog.describe_calls.clear()
    detail = run(client, conn_id, ["DWH-SCD-01", "DWH-NOLOCK-01"])
    assert len(calls) == 1 and detail["finding_count"] == 2
    assert len(fake_catalog.describe_calls) == 1  # one catalog read per object
    prompt = calls[0]["messages"][1]["content"]
    assert "KATALOG METADATASI" in prompt and "EDW.CON.Account [TABLO, SCD]" in prompt
    assert prompt.index("KATALOG METADATASI") < prompt.index("L001|")
    findings = client.get(f"/api/analyses/{detail['id']}/findings").json()
    assert sorted((f["rule_code"], f["kind"], f["line"]) for f in findings) == [
        ("DWH-NOLOCK-01", "builtin", 4), ("DWH-SCD-01", "llm", 4),
    ]
    nolock = next(f for f in findings if f["kind"] == "builtin")
    assert nolock["message"] == "EDW.TRX.Fact fiziksel tablo; WITH (NOLOCK) eksik"
    report = client.get(f"/api/analyses/{detail['id']}/report.html").text
    assert "Yerleşik" in report


def test_metadata_failure_does_not_fail_check(client: TestClient, fake_catalog: FakeCatalog) -> None:
    conn_id = setup(client, fake_catalog)

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("katalog kapalı")

    from tests.conftest import FakeReader

    original = FakeReader.describe
    FakeReader.describe = broken  # type: ignore[method-assign]
    try:
        detail = run(client, conn_id, ["DWH-NOLOCK-01", "DWH-SCD-02"])
    finally:
        FakeReader.describe = original  # type: ignore[method-assign]
    assert detail["status"] == "completed" and detail["completed_checks"] == 2
    obj = detail["objects"][0]
    assert obj["status"] == "done" and "Katalog metadatası alınamadı" in obj["error"]


def test_v3_builtin_checks_accepted(client: TestClient) -> None:
    from app import schemas

    for index, check in enumerate(schemas.BUILTIN_CHECKS):
        body = {**BASE, "code": f"B-{index:02d}", "kind": "builtin", "pattern": None,
                "builtin_check": check}
        assert client.post("/api/rules", json=body).status_code == 201, check
    rules = by_code(client)
    tested = client.post(
        "/api/rules/test",
        json={"rule": rules["DWH-SQL-02"], "sql": "SELECT (SELECT MAX(1) FROM t) x FROM u"},
    ).json()
    assert tested["error"] is None and len(tested["findings"]) == 1
