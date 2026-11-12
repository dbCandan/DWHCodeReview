from fastapi.testclient import TestClient

from app.seed import SEED_RULES

RULE = {
    "code": "TST001",
    "name": "Test kuralı",
    "description": "Açıklama",
    "recommendation": "Öneri",
    "severity": "high",
    "kind": "regex",
    "pattern": r"\bFOO\b",
    "match_mode": "match",
    "target": "definition",
    "ignore_case": True,
    "ignore_comments": True,
    "llm_prompt": None,
    "object_types": ["PROCEDURE"],
    "enabled": True,
    "group_ids": [],
}

CONN = {
    "name": "Yerel",
    "server": "localhost",
    "port": 1433,
    "username": "sa",
    "password": "secret",
    "encrypt": True,
    "trust_server_certificate": True,
}


def test_health_and_seed(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "version": "1.0.0", "commit": ""}
    rules = client.get("/api/rules").json()
    codes = [r["code"] for r in rules]
    assert codes == sorted(codes)
    assert codes == sorted(d["code"] for d in SEED_RULES) and len(codes) == 32
    by_code = {r["code"]: r for r in rules}
    assert all(r["enabled"] for r in rules)
    assert sum(r["severity"] == "critical" for r in rules) == 8
    assert sum(r["severity"] == "high" for r in rules) == 23
    assert by_code["DWH-CAL-01"]["severity"] == "low" and by_code["DWH-ID-01"]["kind"] == "builtin"
    assert all(r["exception_count"] == 0 for r in rules)
    assert by_code["DWH-JOIN-01"]["builtin_check"] == "left_then_inner_join"
    assert by_code["DWH-PERF-04"]["ignore_comments"] is False
    assert by_code["DWH-NOLOCK-01"]["kind"] == "builtin"
    assert by_code["DWH-NOLOCK-01"]["builtin_check"] == "nolock_physical_tables"
    assert by_code["DWH-DM-02"]["databases"] == ["EDWDM"]
    assert by_code["DWH-SCD-01"]["metadata_precondition"] == "references_scd_table"
    assert by_code["DWH-PART-01"]["requires_metadata"] is True
    assert by_code["DWH-PART-01"]["precondition"].startswith(r"\$PARTITION")
    groups = client.get("/api/rule-groups").json()
    main = [g for g in groups if g["name"].startswith("DWH ")]
    assert sorted((g["name"], g["color"], len(g["rule_ids"])) for g in main) == [
        ("DWH Kodlama ve Performans", "#D97706", 24),
        ("DWH Standartları", "#DC2626", 8),
    ]
    sizes = {g["name"]: len(g["rule_ids"]) for g in groups}
    assert len(groups) == 11
    assert sizes["Hızlı Tarama (LLM'siz)"] == 25 and sizes["LLM Kuralları"] == 7
    assert sizes["Hızlı Tarama (LLM'siz)"] + sizes["LLM Kuralları"] == 32
    llm = client.get("/api/settings/llm").json()
    assert llm == {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "model": "",
        "has_api_key": False,
        "temperature": 0.0,
        "timeout_seconds": 120,
        "chunk_lines": 250,
    }


def test_rule_crud(legacy_client: TestClient) -> None:
    client = legacy_client
    group = client.post(
        "/api/rule-groups", json={"name": "G1", "description": "", "color": "#112233", "rule_ids": []}
    ).json()
    created = client.post("/api/rules", json={**RULE, "group_ids": [group["id"]]})
    assert created.status_code == 201
    rule = created.json()
    assert rule["group_ids"] == [group["id"]]
    assert rule["created_at"].endswith("Z")

    assert client.post("/api/rules", json=RULE).status_code == 409
    bad = client.post("/api/rules", json={**RULE, "code": "TST002", "pattern": "(x"})
    assert bad.status_code == 422 and "düzenli ifade" in bad.json()["detail"]
    bad_code = client.post("/api/rules", json={**RULE, "code": "lower"})
    assert bad_code.status_code == 422 and isinstance(bad_code.json()["detail"], str)
    bad_type = client.post("/api/rules", json={**RULE, "code": "TST003", "severity": "huge"})
    assert bad_type.status_code == 422 and "severity" in bad_type.json()["detail"]
    llm_missing = client.post("/api/rules", json={**RULE, "code": "TST004", "kind": "llm"})
    assert llm_missing.status_code == 422

    updated = client.put(f"/api/rules/{rule['id']}", json={**RULE, "name": "Yeni ad", "group_ids": []})
    assert updated.status_code == 200 and updated.json()["name"] == "Yeni ad"
    assert updated.json()["group_ids"] == []

    filtered = client.get("/api/rules", params={"q": "yeni ad"}).json()
    assert [r["code"] for r in filtered] == ["TST001"]
    assert all(r["kind"] == "llm" for r in client.get("/api/rules", params={"kind": "llm"}).json())
    perf = client.get("/api/rule-groups").json()
    perf_id = next(g["id"] for g in perf if g["name"] == "Performans")
    in_group = client.get("/api/rules", params={"group_id": perf_id}).json()
    assert "DWH001" in [r["code"] for r in in_group]

    dup = client.post(f"/api/rules/{rule['id']}/duplicate")
    assert dup.status_code == 200 and dup.json()["code"] == "TST001_COPY"
    dup2 = client.post(f"/api/rules/{rule['id']}/duplicate").json()
    assert dup2["code"] == "TST001_COPY2"

    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    missing = client.get(f"/api/rules/{rule['id']}")
    assert missing.status_code == 404 and missing.json() == {"detail": "Kural bulunamadı."}


def test_rule_test_endpoint(client: TestClient) -> None:
    body = {"rule": RULE, "sql": "-- FOO\nSELECT FOO FROM t", "object_type": "PROCEDURE"}
    result = client.post("/api/rules/test", json=body).json()
    assert result == {
        "findings": [{"line": 2, "snippet": "SELECT FOO FROM t", "message": "Açıklama"}],
        "error": None,
    }
    invalid = client.post("/api/rules/test", json={**body, "rule": {**RULE, "pattern": "[x"}}).json()
    assert invalid["findings"] == [] and invalid["error"]
    llm = client.post(
        "/api/rules/test", json={**body, "rule": {**RULE, "kind": "llm", "llm_prompt": "x"}}
    ).json()
    assert llm["error"] and "LLM" in llm["error"]


def test_group_crud(client: TestClient) -> None:
    rules = client.get("/api/rules").json()
    ids = [rules[0]["id"], rules[1]["id"]]
    created = client.post(
        "/api/rule-groups", json={"name": "Benim", "description": "d", "color": "#abcdef", "rule_ids": ids}
    )
    assert created.status_code == 201
    group = created.json()
    assert group["rule_ids"] == sorted(ids) and group["color"] == "#ABCDEF"
    dup = client.post("/api/rule-groups", json={"name": "Benim", "description": "", "color": "#000000", "rule_ids": []})
    assert dup.status_code == 409
    bad = client.post("/api/rule-groups", json={"name": "X", "description": "", "color": "red", "rule_ids": []})
    assert bad.status_code == 422
    updated = client.put(
        f"/api/rule-groups/{group['id']}",
        json={"name": "Benim2", "description": "", "color": "#000000", "rule_ids": [ids[0]]},
    ).json()
    assert updated["rule_ids"] == [ids[0]] and updated["name"] == "Benim2"
    assert client.delete(f"/api/rule-groups/{group['id']}").status_code == 204
    assert client.get(f"/api/rules/{ids[0]}").status_code == 200  # rules survive


def test_connection_crud_never_returns_password(client: TestClient) -> None:
    created = client.post("/api/connections", json=CONN)
    assert created.status_code == 201
    conn = created.json()
    assert conn["has_password"] is True
    assert "password" not in conn and "secret" not in created.text
    assert client.post("/api/connections", json={**CONN, "name": "Yeni", "password": ""}).status_code == 422
    assert client.post("/api/connections", json={**CONN, "name": "Kötü", "server": "a;b"}).status_code == 422

    updated = client.put(f"/api/connections/{conn['id']}", json={**CONN, "password": None, "port": 1444})
    assert updated.status_code == 200 and updated.json()["port"] == 1444
    assert updated.json()["has_password"] is True
    listing = client.get("/api/connections")
    assert "secret" not in listing.text and len(listing.json()) == 1

    # Test with stored password (id given, password empty).
    ok = client.post("/api/connections/test", json={**CONN, "password": "", "id": conn["id"]}).json()
    assert ok["ok"] is True and ok["database_count"] == 2
    bad = client.post("/api/connections/test", json={**CONN, "password": "wrong"})
    assert bad.status_code == 200 and bad.json()["ok"] is False and bad.json()["message"]

    assert client.get(f"/api/connections/{conn['id']}/databases").json() == ["DWH", "Stage"]
    schemas = client.get(f"/api/connections/{conn['id']}/schemas", params={"databases": "DWH"}).json()
    assert schemas == [{"database": "DWH", "schema": "dbo", "object_count": 2}]
    objects = client.post(
        f"/api/connections/{conn['id']}/objects",
        json={"databases": ["DWH"], "types": ["VIEW"], "modified_from": "2024-01-01", "search": "s"},
    ).json()
    assert objects["total"] == 2 and objects["items"][0]["schema"] == "dbo"
    assert objects["items"][0]["create_date"].endswith("Z")
    assert client.post(f"/api/connections/{conn['id']}/objects", json={"databases": []}).status_code == 422

    assert client.delete(f"/api/connections/{conn['id']}").status_code == 204
    assert client.get(f"/api/connections/{conn['id']}/databases").status_code == 404


def test_llm_settings_keep_api_key(client: TestClient) -> None:
    body = {
        "enabled": True,
        "base_url": "http://localhost:11434/v1",
        "model": "qwen",
        "api_key": "sk-1",
        "temperature": 0,
        "timeout_seconds": 60,
    }
    saved = client.put("/api/settings/llm", json=body)
    assert saved.status_code == 200 and saved.json()["has_api_key"] is True
    assert "sk-1" not in saved.text
    again = client.put("/api/settings/llm", json={**body, "api_key": ""}).json()
    assert again["has_api_key"] is True
    assert client.put("/api/settings/llm", json={**body, "base_url": "ftp://x"}).status_code == 422


def test_unknown_route_detail_is_turkish(client: TestClient) -> None:
    response = client.get("/api/yok")
    assert response.status_code == 404 and response.json() == {"detail": "Kaynak bulunamadı."}
