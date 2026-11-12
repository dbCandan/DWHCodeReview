"""v1.5: LLM chunking of large objects, retries, settings, migration 4 -> 5."""

import json
import re
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import llm
from app.services.llm import LlmConfig, LlmError, context_lines, plan_chunks, review
from app.services.rule_engine import RuleError, RuleSpec, run_rule
from tests.conftest import FakeCatalog, wait_for

CONFIG = LlmConfig(base_url="http://llm.local/v1", model="m1", chunk_lines=250)
RULE = RuleSpec(code="T-LLM", name="Test", kind="llm", llm_prompt="Kural metni", description="Açıklama")


def big_sql(lines: int = 600) -> str:
    out = ["CREATE PROCEDURE TRX.ins_Big @DataDate DATE,", "    @Period INT", "AS", "BEGIN",
           "DECLARE @a INT = 1;", "DECLARE @b DATETIME = GETDATE();"]
    while len(out) < lines:
        n = len(out) + 1
        out.append(f"SELECT {n} AS x FROM t;" if n % 10 == 0 else f"    -- satır {n}")
    out[-1] = "END"
    return "\n".join(out)


@pytest.fixture(autouse=True)
def _no_wait() -> None:
    previous = llm.RETRY_DELAYS
    llm.RETRY_DELAYS = (0.0, 0.0)
    yield
    llm.RETRY_DELAYS = previous
    llm.http_transport = None


def reply(violations: list[dict]) -> httpx.Response:
    content = json.dumps({"violations": violations})
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def user_prompt(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][1]["content"]


def prompt_lines(prompt: str) -> list[int]:
    sql_part = prompt.split('örn. "L001| "):', 1)[1]
    return [int(n) for n in re.findall(r"^L(\d+)\|", sql_part, re.MULTILINE)]


# ------------------------------------------------------------------ chunk planning
def test_plan_chunks_boundaries_and_overlap() -> None:
    lines = big_sql().splitlines()
    chunks = plan_chunks(lines, 250)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(lines)
    for (_, end), (start, _) in zip(chunks, chunks[1:], strict=False):
        assert end - start == 15  # overlap
    for _, end in chunks[:-1]:
        assert lines[end - 1].endswith(";")  # cut after a statement boundary
    assert all(end - start <= 250 for start, end in chunks)


def test_plan_chunks_hard_cut_and_char_cap() -> None:
    lines = [f"x{i}" for i in range(500)]  # no boundary at all
    assert plan_chunks(lines, 200) == [(0, 200), (185, 385), (370, 500)]
    wide = ["a" * 999] * 100  # 100 lines, 100 000 chars -> about 20 lines per chunk
    chunks = plan_chunks(wide, 250)
    assert len(chunks) > 4 and all(end - start <= 20 for start, end in chunks)
    assert plan_chunks(["SELECT 1"] * 10, 250) == [(0, 10)]


def test_context_lines_header_and_declares() -> None:
    sql = big_sql()
    assert context_lines(sql) == [0, 1, 2, 4, 5]


# ------------------------------------------------------------------ chunked review
def test_chunked_review_numbering_context_and_dedupe() -> None:
    sql = big_sql()
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = user_prompt(request)
        prompts.append(prompt)
        numbers = prompt_lines(prompt)
        found = [{"line": 240, "snippet": "SELECT 240 AS x FROM t;", "reason": "çift"}] if 240 in numbers else []
        found.append({"line": numbers[-1], "snippet": "", "reason": f"son {numbers[-1]}"})
        return reply(found)

    llm.http_transport = httpx.MockTransport(handler)
    found = review(CONFIG, RULE, sql, "TRX.ins_Big", "KATALOG METADATASI: x")
    chunks = plan_chunks(sql.splitlines(), 250)
    assert len(prompts) == len(chunks) == 3
    for index, (prompt, (start, end)) in enumerate(zip(prompts, chunks, strict=True), 1):
        assert prompt_lines(prompt) == list(range(start + 1, end + 1))  # original numbering
        assert f"Bu, nesnenin {index}/3. parçasıdır (satır {start + 1}–{end})." in prompt
        assert "KATALOG METADATASI: x" in prompt and "Kural metni" in prompt
    second = prompts[1]
    context = second.split("BAĞLAM (nesne başlığı ve DECLARE satırları):\n", 1)[1].split("\n\n", 1)[0]
    assert context.splitlines() == [
        "L001| CREATE PROCEDURE TRX.ins_Big @DataDate DATE,", "L002|     @Period INT", "L003| AS",
        "L005| DECLARE @a INT = 1;", "L006| DECLARE @b DATETIME = GETDATE();",
    ]
    # line 240 lies in the overlap of chunks 1 and 2: reported once
    assert [f.line for f in found].count(240) == 1
    assert len(found) == 1 + 3


def test_small_object_single_call_unchanged_prompt() -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(user_prompt(request))
        return reply([])

    llm.http_transport = httpx.MockTransport(handler)
    review(CONFIG, RULE, "SELECT 1\nSELECT 2", "dbo.x")
    assert len(prompts) == 1
    assert "BAĞLAM" not in prompts[0] and "parçasıdır" not in prompts[0]
    assert "NESNE: dbo.x\n\nSQL (her satırın" in prompts[0]
    assert "L001| SELECT 1\nL002| SELECT 2" in prompts[0]


def test_chunks_failing_precondition_are_skipped() -> None:
    sql = big_sql().replace("SELECT 400 AS x FROM t;", "MERGE INTO t USING s ON 1=1;")
    calls: list[list[int]] = []
    llm.http_transport = httpx.MockTransport(
        lambda request: (calls.append(prompt_lines(user_prompt(request))), reply([]))[1]
    )
    rule = RuleSpec(code="T", name="T", kind="llm", llm_prompt="p", precondition=r"\bMERGE\b")
    review(CONFIG, rule, sql, "x")
    assert len(calls) == 1 and 400 in calls[0]


def test_retry_on_read_error_then_success() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ReadError("bağlantı koptu", request=request)
        return reply([{"line": 1, "snippet": "SELECT 1", "reason": "r"}])

    llm.http_transport = httpx.MockTransport(handler)
    found = review(CONFIG, RULE, "SELECT 1", "dbo.x")
    assert len(attempts) == 3 and [f.message for f in found] == ["r"]

    attempts.clear()
    llm.http_transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.RemoteProtocolError("kapandı", request=request))
    )
    with pytest.raises(LlmError, match="RemoteProtocolError"):
        review(CONFIG, RULE, "SELECT 1", "dbo.x")


def test_one_chunk_failing_keeps_other_findings() -> None:
    sql = big_sql()

    def handler(request: httpx.Request) -> httpx.Response:
        numbers = prompt_lines(user_prompt(request))
        if numbers[0] > 1 and numbers[-1] < 600:  # the middle chunk
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return reply([{"line": numbers[0], "snippet": "", "reason": f"ilk {numbers[0]}"}])

    llm.http_transport = httpx.MockTransport(handler)
    with pytest.raises(RuleError) as caught:
        run_rule(RULE, sql, "TRX.ins_Big", CONFIG)
    assert "parça 2/3" in str(caught.value) and "boom" in str(caught.value)
    assert len(caught.value.findings) == 2


def test_runner_stores_partial_findings(client: TestClient, fake_catalog: FakeCatalog) -> None:
    fake_catalog.definitions[("DWH", "TRX", "ins_Big")] = big_sql()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "m1"}]})
        numbers = prompt_lines(user_prompt(request))
        if numbers[0] > 1 and numbers[-1] < 600:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return reply([{"line": numbers[0], "snippet": "", "reason": "ihlal"}])

    llm.http_transport = httpx.MockTransport(handler)
    client.put("/api/settings/llm", json={"enabled": True, "base_url": "http://llm.local/v1", "model": "m1",
                                          "api_key": None, "temperature": 0, "timeout_seconds": 30,
                                          "chunk_lines": 250})
    rule = client.post("/api/rules", json={"code": "T-LLM", "name": "T", "kind": "llm", "llm_prompt": "p",
                                           "severity": "high"}).json()
    conn = client.post("/api/connections", json={"name": "c", "server": "localhost", "port": 1433,
                                                 "username": "sa", "password": "secret"}).json()["id"]
    summary = client.post("/api/analyses", json={
        "connection_id": conn, "rule_ids": [rule["id"]],
        "objects": [{"database": "DWH", "schema": "TRX", "name": "ins_Big", "type": "PROCEDURE"}],
    }).json()
    detail = wait_for(client, summary["id"])
    obj = detail["objects"][0]
    assert detail["status"] == "completed" and detail["finding_count"] == 2
    assert obj["status"] == "error" and "parça 2/3" in obj["error"]


# ------------------------------------------------------------------ settings API
def test_chunk_lines_setting(client: TestClient) -> None:
    body = {"enabled": False, "base_url": "http://llm.local/v1", "model": "m", "api_key": None,
            "temperature": 0, "timeout_seconds": 60}
    assert client.get("/api/settings/llm").json()["chunk_lines"] == 250
    bad = client.put("/api/settings/llm", json={**body, "chunk_lines": 10})
    assert bad.status_code == 422 and "50 ile 2000" in bad.json()["detail"]
    assert client.put("/api/settings/llm", json={**body, "chunk_lines": 400}).json()["chunk_lines"] == 400
    assert client.put("/api/settings/llm", json=body).json()["chunk_lines"] == 250  # default


# ------------------------------------------------------------------ migration 4 -> 5
def test_migration_v4_to_v5(tmp_path: Path) -> None:
    from app.seed import _TEXTS

    with TestClient(create_app(tmp_path)):
        pass
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:
        db.execute("UPDATE rules SET llm_prompt = ?, enabled = 0, name = 'Benim' WHERE code = 'DWH-DM-01'",
                   (_TEXTS["DWH-DM-01"]["llm_prompt"],))
        db.execute("ALTER TABLE llm_settings DROP COLUMN chunk_lines")
        db.execute("UPDATE app_meta SET value = '4' WHERE key = 'ruleset_version'")
        db.commit()
    finally:
        db.close()
    with TestClient(create_app(tmp_path)) as client:
        rule = next(r for r in client.get("/api/rules").json() if r["code"] == "DWH-DM-01")
        assert "MaskedIdentityId" in rule["llm_prompt"] and "LKPIdentityNumber" in rule["llm_prompt"]
        assert rule["enabled"] is False and rule["name"] == "Benim"
        assert client.get("/api/settings/llm").json()["chunk_lines"] == 250
