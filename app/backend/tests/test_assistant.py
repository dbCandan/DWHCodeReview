"""Rule assistant (v1.6) with a mocked LLM and the fake catalog; kind groups."""

import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import get_database
from app.main import create_app
from app.services import llm
from tests.conftest import FakeCatalog

LLM = {"enabled": True, "base_url": "http://llm.local/v1", "model": "m1", "api_key": None,
       "temperature": 0, "timeout_seconds": 30}
REQUEST = {
    "description": "Prosedürlerde TRUNCATE TABLE ile EDWSTG dışındaki tabloların boşaltılması yasak.",
    "positive_examples": [{"sql": "CREATE PROCEDURE dbo.p AS\nTRUNCATE TABLE EDW.TRX.Fact;",
                           "object_type": "PROCEDURE", "object_name": "dbo.p", "database": "EDW"}],
    "negative_examples": [{"sql": "CREATE PROCEDURE dbo.q AS\nTRUNCATE TABLE EDWSTG.BOA.Stg;"}],
}
RULE = {"code": "DWH-TRUNC-01", "name": "Hedef tablo TRUNCATE", "description": "Açıklama",
        "recommendation": "Öneri", "severity": "high", "kind": "regex",
        "pattern": r"\bTRUNCATE\s+TABLE\s+(?!EDWSTG\.)", "match_mode": "match", "target": "definition",
        "ignore_case": True, "ignore_comments": True, "llm_prompt": None, "object_types": ["PROCEDURE"],
        "enabled": True, "group_ids": [], "change_summary": "Yeni kural."}


def llm_reply(payload: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def install(answers: dict[str, list[object]], seen: list[str] | None = None) -> None:
    """answers[stage] = queue of replies for 'GÖREV: <stage>' prompts."""

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        stage = next((s for s in ("EŞLEŞTİRME", "TASLAK", "DÜZELTME") if f"GÖREV: {s}" in user), None)
        if stage is None:  # an LLM-kind rule reviewing an example
            hit = "EDW.TRX.Fact" in user
            return llm_reply({"violations": [{"line": 2, "snippet": "TRUNCATE", "reason": "r"}] if hit else []})
        if seen is not None:
            seen.append(stage)
        queue = answers[stage]
        return llm_reply(queue.pop(0) if len(queue) > 1 else queue[0])

    llm.http_transport = httpx.MockTransport(handler)


@pytest.fixture
def assistant(client: TestClient) -> TestClient:
    client.put("/api/settings/llm", json=LLM)
    return client


def wait(client: TestClient, session_id: int, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/rule-assistant/sessions/{session_id}").json()
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError("assistant session did not finish")


def start(client: TestClient, body: dict | None = None) -> dict:
    response = client.post("/api/rule-assistant/sessions", json=body or REQUEST)
    assert response.status_code == 201, response.json()
    return response.json()


def group_id(client: TestClient, name: str) -> int:
    return next(g["id"] for g in client.get("/api/rule-groups").json() if g["name"] == name)


def test_new_regex_rule_flow_and_save(assistant: TestClient, fake_catalog: FakeCatalog) -> None:
    seen: list[str] = []
    install({"EŞLEŞTİRME": [{"decision": "new", "target_rule_code": None, "rationale": "Yeni denetim",
                             "builtin_needed": False, "builtin_note": None}],
             "TASLAK": [RULE]}, seen)
    fake_catalog.definitions[("DWH", "dbo", "usp_LoadSales")] = "CREATE PROCEDURE x AS TRUNCATE TABLE dbo.Sales"
    conn = assistant.post("/api/connections", json={"name": "c", "server": "localhost", "port": 1433,
                                                    "username": "sa", "password": "secret"}).json()["id"]
    created = start(assistant, {**REQUEST, "noise": {"connection_id": conn, "databases": ["DWH"],
                                                     "sample_size": 10}})
    assert created["status"] == "running" and created["stage"] == "matching"
    done = wait(assistant, created["id"])
    assert done["status"] == "ready" and done["stage"] == "done", done
    assert seen == ["EŞLEŞTİRME", "TASLAK"]
    assert done["decision"] == "new" and done["rationale"] == "Yeni denetim"
    assert done["change_summary"] == "Yeni kural."
    proposal = done["proposal"]
    quick = group_id(assistant, "Hızlı Tarama (LLM'siz)")
    assert proposal["code"] == "DWH-TRUNC-01" and quick in proposal["group_ids"]
    validation = done["validation"]
    assert validation == {"iterations": 1, "passed": True, "cases": validation["cases"]}
    assert [(c["kind"], c["passed"], len(c["findings"])) for c in validation["cases"]] == [
        ("positive", True, 1), ("negative", True, 0)]
    noise = done["noise"]
    assert noise["status"] == "done" and noise["sampled"] == 1  # only one PROCEDURE in the fake catalog
    assert noise["findings"] == 1 and noise["examples"][0]["object_label"] == "DWH.dbo.usp_LoadSales"
    assert [line["stage"] for line in done["log"]][0] == "matching"
    assert not any(a for a in assistant.get("/api/analyses").json())  # no Analysis record

    saved = assistant.post(f"/api/rule-assistant/sessions/{done['id']}/save",
                           json={"proposal": {**proposal, "name": "Düzenlenmiş ad"}})
    assert saved.status_code == 200, saved.json()
    rule = saved.json()["rule"]
    assert rule["code"] == "DWH-TRUNC-01" and rule["name"] == "Düzenlenmiş ad"
    assert quick in rule["group_ids"]
    assert rule["sample_sql"] == REQUEST["positive_examples"][0]["sql"]
    assert rule["sample_object_type"] == "PROCEDURE"
    assert saved.json()["session"]["status"] == "saved"
    again = assistant.post(f"/api/rule-assistant/sessions/{done['id']}/save", json={"proposal": proposal})
    assert again.status_code == 409


def test_refine_until_examples_pass(assistant: TestClient) -> None:
    seen: list[str] = []
    wrong = {**RULE, "pattern": r"\bTRUNCATE\b"}  # also hits the negative example
    install({"EŞLEŞTİRME": [{"decision": "new"}], "TASLAK": [wrong], "DÜZELTME": [RULE]}, seen)
    done = wait(assistant, start(assistant)["id"])
    assert seen == ["EŞLEŞTİRME", "TASLAK", "DÜZELTME"]
    assert done["validation"]["iterations"] == 2 and done["validation"]["passed"] is True
    assert any(line["stage"] == "refining" for line in done["log"])


def test_refining_gives_up_after_three_rounds(assistant: TestClient) -> None:
    wrong = {**RULE, "pattern": r"\bTRUNCATE\b"}
    install({"EŞLEŞTİRME": [{"decision": "new"}], "TASLAK": [wrong], "DÜZELTME": [wrong]})
    done = wait(assistant, start(assistant)["id"])
    assert done["status"] == "ready" and done["validation"] == {
        "iterations": 3, "passed": False, "cases": done["validation"]["cases"]}


def test_extend_existing_rule(assistant: TestClient) -> None:
    target = next(r for r in assistant.get("/api/rules").json() if r["code"] == "DWH-SQL-04")
    extended = {**{k: v for k, v in target.items() if k not in ("id", "created_at", "updated_at")},
                "pattern": r"\bCOUNT(?:_BIG)?\s*\(\s*(?:\*|DISTINCT\s+\*)\s*\)|\bSELECT\s+COUNT\(\*\)",
                "change_summary": "COUNT_BIG desteği"}
    install({"EŞLEŞTİRME": [{"decision": "extend", "target_rule_code": "DWH-SQL-04",
                             "rationale": "Aynı denetim"}],
             "TASLAK": [{**extended, "code": "BASKA-KOD"}]})
    request = {"description": "COUNT(*) ve COUNT_BIG(*) kullanımları raporlanmalı.",
               "positive_examples": [{"sql": "SELECT COUNT_BIG(*) FROM t"}],
               "negative_examples": [{"sql": "SELECT COUNT(1) FROM t"}]}
    done = wait(assistant, start(assistant, request)["id"])
    assert done["decision"] == "extend" and done["target_rule_code"] == "DWH-SQL-04"
    assert done["original"]["code"] == "DWH-SQL-04" and done["proposal"]["code"] == "DWH-SQL-04"
    assert done["change_summary"] == "COUNT_BIG desteği"
    positive = done["validation"]["cases"][0]
    assert positive["passed"] is True and positive["old_passed"] is True  # old pattern had COUNT_BIG too
    saved = assistant.post(f"/api/rule-assistant/sessions/{done['id']}/save",
                           json={"proposal": done["proposal"]}).json()
    assert saved["rule"]["id"] == target["id"] and "DISTINCT" in saved["rule"]["pattern"]
    assert len(assistant.get("/api/rules").json()) == 32


def test_schema_error_is_sent_back_once(assistant: TestClient) -> None:
    seen: list[str] = []
    install({"EŞLEŞTİRME": [{"decision": "new"}],
             "TASLAK": [{**RULE, "severity": "huge"}, RULE]}, seen)
    done = wait(assistant, start(assistant)["id"])
    assert done["status"] == "ready" and seen == ["EŞLEŞTİRME", "TASLAK", "TASLAK"]


def test_unknown_builtin_becomes_llm(assistant: TestClient) -> None:
    llm_group = group_id(assistant, "LLM Kuralları")
    proposal = {**RULE, "kind": "builtin", "builtin_check": "yeni_kontrol", "pattern": None,
                "llm_prompt": None}
    install({"EŞLEŞTİRME": [{"decision": "new", "builtin_needed": True, "builtin_note": "Akış analizi"}],
             "TASLAK": [proposal]})
    done = wait(assistant, start(assistant)["id"])
    assert done["builtin_needed"] is True and done["builtin_note"] == "Akış analizi"
    assert done["proposal"]["kind"] == "llm" and done["proposal"]["llm_prompt"] == "Açıklama"
    assert llm_group in done["proposal"]["group_ids"]


def test_revalidate_without_llm_drafting(assistant: TestClient) -> None:
    seen: list[str] = []
    install({"EŞLEŞTİRME": [{"decision": "new"}], "TASLAK": [RULE]}, seen)
    done = wait(assistant, start(assistant)["id"])
    seen.clear()
    edited = {**done["proposal"], "pattern": r"\bTRUNCATE\b"}
    response = assistant.post(f"/api/rule-assistant/sessions/{done['id']}/revalidate",
                              json={"proposal": edited, "run_noise": False})
    assert response.json()["status"] == "running"
    again = wait(assistant, done["id"])
    assert seen == [] and again["status"] == "ready"
    assert again["proposal"]["pattern"] == r"\bTRUNCATE\b" and again["validation"]["passed"] is False


def test_request_validation_and_llm_required(client: TestClient) -> None:
    assert client.post("/api/rule-assistant/sessions", json=REQUEST).json()["detail"] == (
        "Kural asistanı için LLM ayarlarının etkin olması gerekir.")
    client.put("/api/settings/llm", json=LLM)
    short = client.post("/api/rule-assistant/sessions", json={**REQUEST, "description": "kısa"})
    assert short.status_code == 422
    none = client.post("/api/rule-assistant/sessions", json={**REQUEST, "positive_examples": []})
    assert none.status_code == 422
    noise = client.post("/api/rule-assistant/sessions",
                        json={**REQUEST, "noise": {"connection_id": 1, "databases": ["X"], "sample_size": 5}})
    assert noise.status_code == 422
    install({"EŞLEŞTİRME": [{"decision": "new"}], "TASLAK": [RULE]})
    builtin = start(client, {**REQUEST, "preferred_kind": "builtin"})
    assert builtin["request"]["preferred_kind"] is None
    wait(client, builtin["id"])
    listing = client.get("/api/rule-assistant/sessions").json()
    assert [s["id"] for s in listing] == [builtin["id"]] and len(listing[0]["log"]) <= 5
    assert client.get("/api/rule-assistant/sessions/999").status_code == 404


def test_cancel_running_session(assistant: TestClient) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.3)
        return llm_reply({"decision": "new"})

    llm.http_transport = httpx.MockTransport(slow)
    created = start(assistant)
    cancelled = assistant.post(f"/api/rule-assistant/sessions/{created['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    time.sleep(0.5)
    assert assistant.get(f"/api/rule-assistant/sessions/{created['id']}").json()["status"] == "cancelled"
    assert assistant.post(f"/api/rule-assistant/sessions/{created['id']}/cancel").status_code == 200


def test_running_sessions_fail_on_restart(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)):
        with get_database().session_factory() as session:
            session.add(models.RuleAssistantSession(status="running", stage="drafting",
                                                    request=REQUEST, log=[]))
            session.commit()
    with TestClient(create_app(tmp_path)) as client:
        row = client.get("/api/rule-assistant/sessions").json()[0]
        assert row["status"] == "failed" and row["error"] == "Uygulama yeniden başlatıldı"


def test_editor_kind_change_moves_kind_groups(client: TestClient) -> None:
    quick, llm_group = group_id(client, "Hızlı Tarama (LLM'siz)"), group_id(client, "LLM Kuralları")
    rule = next(r for r in client.get("/api/rules").json() if r["code"] == "DWH-SQL-04")
    assert quick in rule["group_ids"]
    changed = client.put(f"/api/rules/{rule['id']}", json={**rule, "kind": "llm", "llm_prompt": "p"}).json()
    assert llm_group in changed["group_ids"] and quick not in changed["group_ids"]
    back = client.put(f"/api/rules/{rule['id']}", json={**changed, "kind": "regex"}).json()
    assert quick in back["group_ids"] and llm_group not in back["group_ids"]


def test_discard_ready_proposal(assistant: TestClient) -> None:
    install({"EŞLEŞTİRME": [{"decision": "new"}], "TASLAK": [RULE]})
    created = start(assistant)
    assert wait(assistant, created["id"])["status"] == "ready"
    rules_before = len(assistant.get("/api/rules").json())
    discarded = assistant.post(f"/api/rule-assistant/sessions/{created['id']}/cancel")
    assert discarded.status_code == 200 and discarded.json()["status"] == "cancelled"
    assert len(assistant.get("/api/rules").json()) == rules_before
    body = {"proposal": wait(assistant, created["id"])["proposal"]}
    assert assistant.post(f"/api/rule-assistant/sessions/{created['id']}/save", json=body).status_code == 409
