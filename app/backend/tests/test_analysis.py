import json
import ssl

import httpx
import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import get_database
from app.services import llm
from app.services.analysis_runner import RESTART_MESSAGE, recover_interrupted
from tests.conftest import FakeCatalog, install_legacy_rules, wait_for

CONN = {
    "name": "Yerel",
    "server": "localhost",
    "port": 1433,
    "username": "sa",
    "password": "secret",
    "encrypt": True,
    "trust_server_certificate": True,
}

OBJECTS = [
    {"database": "DWH", "schema": "dbo", "name": "usp_LoadSales", "type": "PROCEDURE",
     "create_date": "2024-01-01T00:00:00Z", "modify_date": "2024-06-01T00:00:00Z"},
    {"database": "DWH", "schema": "dbo", "name": "vSales", "type": "VIEW"},
    {"database": "DWH", "schema": "dbo", "name": "sp_Bad", "type": "PROCEDURE"},
    {"database": "DWH", "schema": "dbo", "name": "usp_Encrypted", "type": "PROCEDURE"},
]


@pytest.fixture(autouse=True)
def _legacy_rules(client: TestClient) -> None:
    install_legacy_rules()


def rule_ids(client: TestClient, *codes: str) -> list[int]:
    by_code = {r["code"]: r["id"] for r in client.get("/api/rules").json()}
    return [by_code[code] for code in codes]


def setup_connection(client: TestClient) -> int:
    return client.post("/api/connections", json=CONN).json()["id"]


def test_analysis_end_to_end(client: TestClient) -> None:
    conn_id = setup_connection(client)
    ids = rule_ids(client, "DWH001", "DWH004", "DWH007", "DWH014")
    response = client.post(
        "/api/analyses",
        json={
            "connection_id": conn_id,
            "objects": OBJECTS,
            "rule_ids": ids[:2],
            "group_ids": [],
            "filters": {"databases": ["DWH"], "types": []},
        },
    )
    # Union with an extra rule list sent the second time below; first check the simple case.
    assert response.status_code == 201
    first = response.json()
    assert first["name"] == f"Analiz #{first['id']}"
    assert first["status"] in ("queued", "running", "completed")
    assert set(first["severity_counts"]) == {"critical", "high", "medium", "low", "info"}
    wait_for(client, first["id"])

    response = client.post(
        "/api/analyses",
        json={"name": "Gece kontrolü", "connection_id": conn_id, "objects": OBJECTS, "rule_ids": ids},
    )
    summary = response.json()
    # PROC: DWH001, DWH004, DWH007 (x3 procs) + VIEW: DWH001, DWH014
    assert summary["total_checks"] == 3 * 3 + 2
    assert summary["object_count"] == 4 and summary["rule_count"] == 4

    detail = wait_for(client, summary["id"])
    assert detail["status"] == "completed"
    assert detail["completed_checks"] == detail["total_checks"] == 11
    assert detail["finding_count"] == 3
    assert detail["severity_counts"]["medium"] == 2 and detail["severity_counts"]["low"] == 1
    assert detail["duration_ms"] is not None and detail["finished_at"].endswith("Z")
    assert {r["code"] for r in detail["rules"]} == {"DWH001", "DWH004", "DWH007", "DWH014"}

    objects = {o["name"]: o for o in detail["objects"]}
    assert objects["usp_LoadSales"]["status"] == "done"
    assert objects["usp_LoadSales"]["finding_count"] == 2
    assert objects["usp_LoadSales"]["line_count"] == 7
    assert objects["usp_LoadSales"]["create_date"] == "2024-01-01T00:00:00Z"
    assert objects["vSales"]["finding_count"] == 0
    assert objects["sp_Bad"]["finding_count"] == 1
    assert objects["usp_Encrypted"]["status"] == "error"
    assert "okunamadı" in objects["usp_Encrypted"]["error"]

    findings = client.get(f"/api/analyses/{summary['id']}/findings").json()
    assert [f["rule_code"] for f in findings] == ["DWH007", "DWH001", "DWH004"]
    select_star = next(f for f in findings if f["rule_code"] == "DWH001")
    assert select_star["line"] == 5
    assert select_star["snippet"] == "SELECT * FROM dbo.Sales WITH (NOLOCK);"
    assert select_star["object_label"] == "DWH.dbo.usp_LoadSales"
    assert select_star["recommendation"]
    only_low = client.get(f"/api/analyses/{summary['id']}/findings", params={"severity": "low"}).json()
    assert [f["rule_code"] for f in only_low] == ["DWH004"]
    searched = client.get(f"/api/analyses/{summary['id']}/findings", params={"q": "nolock"}).json()
    assert len(searched) == 1

    source = client.get(
        f"/api/analyses/{summary['id']}/objects/{objects['usp_LoadSales']['id']}/source"
    ).json()
    assert source["definition"].startswith("CREATE PROCEDURE dbo.usp_LoadSales")
    assert len(source["findings"]) == 2

    # Rule edits do not change history.
    rule = client.get(f"/api/rules/{ids[0]}").json()
    client.put(f"/api/rules/{ids[0]}", json={**rule, "name": "Değişti"})
    again = client.get(f"/api/analyses/{summary['id']}").json()
    assert next(r for r in again["rules"] if r["code"] == "DWH001")["name"] == "SELECT * kullanımı"

    html = client.get(f"/api/analyses/{summary['id']}/report.html")
    assert html.status_code == 200
    assert html.headers["content-disposition"] == f'attachment; filename="analiz-{summary["id"]}.html"'
    assert "Gece kontrolü" in html.text and "Önem Dağılımı" in html.text
    assert "SELECT * FROM dbo.Sales WITH (NOLOCK);" in html.text

    csv_response = client.get(f"/api/analyses/{summary['id']}/report.csv")
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    text = csv_response.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Veritabanı;Şema;Nesne")
    assert len(text.strip().splitlines()) == 4

    listing = client.get("/api/analyses").json()
    assert [a["id"] for a in listing] == [summary["id"], first["id"]]
    assert client.get("/api/analyses", params={"status": "failed"}).json() == []

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["analysis_count"] == 2 and dashboard["connection_count"] == 1
    assert dashboard["total_findings"] == sum(dashboard["severity_counts"].values())
    assert dashboard["top_rules"][0]["code"] in {"DWH001", "DWH004"}
    assert len(dashboard["recent_analyses"]) == 2

    assert client.post(f"/api/analyses/{summary['id']}/cancel").status_code == 409
    assert client.delete(f"/api/analyses/{summary['id']}").status_code == 204
    assert client.get(f"/api/analyses/{summary['id']}").status_code == 404


def test_group_union_and_disabled_rules(client: TestClient) -> None:
    conn_id = setup_connection(client)
    groups = {g["name"]: g for g in client.get("/api/rule-groups").json()}
    security = groups["Güvenlik"]
    extra = rule_ids(client, "DWH005", "DWH006")  # DWH005 is already in Güvenlik
    response = client.post(
        "/api/analyses",
        json={"connection_id": conn_id, "objects": OBJECTS[:1], "rule_ids": extra, "group_ids": [security["id"]]},
    ).json()
    assert response["rule_count"] == len(set(security["rule_ids"]) | set(extra))
    wait_for(client, response["id"])

    rule = client.get(f"/api/rules/{extra[1]}").json()
    client.put(f"/api/rules/{extra[1]}", json={**rule, "enabled": False})
    bad = client.post(
        "/api/analyses", json={"connection_id": conn_id, "objects": OBJECTS[:1], "rule_ids": [extra[1]]}
    )
    assert bad.status_code == 400 and bad.json()["detail"] == "En az bir etkin kural seçilmelidir."


def test_validation_errors(client: TestClient) -> None:
    conn_id = setup_connection(client)
    ids = rule_ids(client, "DWH001")
    assert client.post(
        "/api/analyses", json={"connection_id": 999, "objects": OBJECTS, "rule_ids": ids}
    ).status_code == 400
    empty = client.post("/api/analyses", json={"connection_id": conn_id, "objects": [], "rule_ids": ids})
    assert empty.status_code == 400 and empty.json()["detail"] == "En az bir nesne seçilmelidir."


def test_llm_not_configured_returns_400(client: TestClient) -> None:
    conn_id = setup_connection(client)
    response = client.post(
        "/api/analyses",
        json={"connection_id": conn_id, "objects": OBJECTS, "rule_ids": rule_ids(client, "DWH001", "LLM002")},
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Seçili kurallar arasında LLM kuralı var ancak LLM ayarları etkin değil."
    }


def test_llm_rule_with_mock_transport(client: TestClient) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "nomic-embed"}]})
        body = json.loads(request.content)
        captured.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        content = (
            "<think>düşünüyorum {not json}</think>\n```json\n"
            '{"violations": [{"line": 5, "snippet": "SELECT * FROM dbo.Sales WITH (NOLOCK);", '
            '"reason": "Join koşulu yok."}, {"line": "L006", "snippet": "", "reason": "İkinci"}]}\n```'
        )
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    llm.http_transport = httpx.MockTransport(handler)
    client.put(
        "/api/settings/llm",
        json={"enabled": True, "base_url": "http://llm.local/v1/", "model": "m1", "api_key": "sk-test",
              "temperature": 0, "timeout_seconds": 30},
    )
    conn_id = setup_connection(client)
    summary = client.post(
        "/api/analyses",
        json={"connection_id": conn_id, "objects": OBJECTS[:1], "rule_ids": rule_ids(client, "LLM002")},
    ).json()
    detail = wait_for(client, summary["id"])
    assert detail["status"] == "completed" and detail["completed_checks"] == 1
    findings = client.get(f"/api/analyses/{summary['id']}/findings").json()
    assert [(f["line"], f["message"], f["kind"]) for f in findings] == [
        (5, "Join koşulu yok.", "llm"),
        (6, "İkinci", "llm"),
    ]
    assert findings[1]["snippet"] == "SELECT @@IDENTITY;"
    assert captured[0]["url"] == "http://llm.local/v1/chat/completions"
    assert captured[0]["auth"] == "Bearer sk-test"
    assert captured[0]["body"]["model"] == "m1"
    user_message = captured[0]["body"]["messages"][1]["content"]
    assert "L005|     SELECT * FROM dbo.Sales" in user_message and "LLM002" in user_message

    # Same engine through the rule test endpoint.
    rule = client.get(f"/api/rules/{rule_ids(client, 'LLM002')[0]}").json()
    tested = client.post("/api/rules/test", json={"rule": rule, "sql": "a\nb\nc\nd\ne\nf"}).json()
    assert tested["error"] is None and [f["line"] for f in tested["findings"]] == [5, 6]

    # Connection test.
    result = client.post(
        "/api/settings/llm/test",
        json={"enabled": True, "base_url": "http://llm.local/v1", "model": "m1", "api_key": "",
              "temperature": 0, "timeout_seconds": 30},
    ).json()
    assert result["ok"] is True and result["latency_ms"] is not None
    assert captured[-1]["auth"] == "Bearer sk-test"

    # Unknown model: the test names the models the server really offers.
    wrong = client.post(
        "/api/settings/llm/test",
        json={"enabled": True, "base_url": "http://llm.local/v1", "model": "yok", "api_key": "",
              "temperature": 0, "timeout_seconds": 30},
    ).json()
    assert wrong["ok"] is False and "m1" in wrong["message"] and "nomic" not in wrong["message"]

    # Model list endpoint (embeddings excluded).
    models = client.post(
        "/api/settings/llm/models",
        json={"enabled": True, "base_url": "http://llm.local/v1", "model": "", "api_key": "",
              "temperature": 0, "timeout_seconds": 30},
    ).json()
    assert models == {"models": ["m1"], "error": None}


def test_llm_unreachable_docker_host_hint(client: TestClient) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    llm.http_transport = httpx.MockTransport(refuse)
    result = client.post(
        "/api/settings/llm/test",
        json={"enabled": True, "base_url": "http://host.docker.internal:1234/v1", "model": "m1",
              "api_key": "", "temperature": 0, "timeout_seconds": 30},
    ).json()
    assert result["ok"] is False and "127.0.0.1" in result["message"]


def test_llm_untrusted_certificate_is_named(client: TestClient) -> None:
    def untrusted(request: httpx.Request) -> httpx.Response:
        cause = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer")
        raise httpx.ConnectError(str(cause), request=request) from cause

    llm.http_transport = httpx.MockTransport(untrusted)
    body = {"enabled": True, "base_url": "https://runai.example.internal/v1", "model": "m1",
            "api_key": "", "temperature": 0, "timeout_seconds": 30}
    result = client.post("/api/settings/llm/test", json=body).json()
    assert result["ok"] is False and "sertifika" in result["message"]
    models = client.post("/api/settings/llm/models", json=body).json()
    assert "sertifika" in models["error"]


def test_llm_failure_marks_object_error_but_completes(client: TestClient) -> None:
    llm.http_transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": {"message": "boom"}}))
    client.put(
        "/api/settings/llm",
        json={"enabled": True, "base_url": "http://llm.local/v1", "model": "m1", "api_key": None,
              "temperature": 0, "timeout_seconds": 30},
    )
    conn_id = setup_connection(client)
    summary = client.post(
        "/api/analyses",
        json={"connection_id": conn_id, "objects": OBJECTS[:1], "rule_ids": rule_ids(client, "LLM001", "DWH001")},
    ).json()
    detail = wait_for(client, summary["id"])
    assert detail["status"] == "completed" and detail["completed_checks"] == 2
    obj = detail["objects"][0]
    assert obj["status"] == "error" and "LLM001" in obj["error"] and "boom" in obj["error"]
    assert detail["finding_count"] == 1  # DWH001 still ran


def test_cancel_running_analysis(client: TestClient, fake_catalog: FakeCatalog) -> None:
    fake_catalog.delay = 0.3
    conn_id = setup_connection(client)
    objects = [{"database": "DWH", "schema": "dbo", "name": f"p{i}", "type": "PROCEDURE"} for i in range(20)]
    summary = client.post(
        "/api/analyses", json={"connection_id": conn_id, "objects": objects, "rule_ids": rule_ids(client, "DWH001")}
    ).json()
    cancelled = client.post(f"/api/analyses/{summary['id']}/cancel")
    assert cancelled.status_code == 200
    detail = wait_for(client, summary["id"])
    assert detail["status"] == "cancelled"
    assert detail["completed_checks"] < detail["total_checks"]


def test_recover_interrupted(client: TestClient) -> None:
    with get_database().session_factory() as session:
        session.add(models.Analysis(name="x", status="running"))
        session.commit()
        assert recover_interrupted(session) == 1
        analysis = session.query(models.Analysis).one()
        assert analysis.status == "failed" and analysis.error == RESTART_MESSAGE
