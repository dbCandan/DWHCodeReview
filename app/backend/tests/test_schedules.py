"""Scheduled analyses (v1.7): timing, incremental selection, comparison, API."""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import get_database, utcnow
from app.services.catalog import CatalogObject
from app.services.scheduler import (
    _multiset_diff,
    changed_objects,
    next_run_after,
    next_runs,
    schedule_text,
)
from tests.conftest import FakeCatalog

TZ = timezone(timedelta(hours=3))  # Europe/Istanbul without DST


def utc(*args: int) -> datetime:
    return datetime(*args)


# ------------------------------------------------------------------ timing
def test_daily_and_weekly() -> None:
    daily = {"kind": "daily", "time": "02:00"}
    # 2026-11-12 22:00 UTC = 13 Nov 01:00 local -> 13 Nov 02:00 local = 12 Nov 23:00 UTC
    assert next_run_after(daily, utc(2026, 11, 12, 22, 0), TZ) == utc(2026, 11, 12, 23, 0)
    assert next_run_after(daily, utc(2026, 11, 12, 23, 0), TZ) == utc(2026, 11, 13, 23, 0)
    weekly = {"kind": "weekly", "time": "06:30", "weekdays": [1, 3, 5]}
    # Thu 12 Nov 2026 10:00 local -> Fri 13 Nov 06:30 local
    assert next_run_after(weekly, utc(2026, 11, 12, 7, 0), TZ) == utc(2026, 11, 13, 3, 30)
    assert next_runs(weekly, utc(2026, 11, 12, 7, 0), 3, TZ) == [
        utc(2026, 11, 13, 3, 30), utc(2026, 11, 16, 3, 30), utc(2026, 11, 18, 3, 30)]


def test_monthly_day_overflow() -> None:
    spec = {"kind": "monthly", "time": "03:00", "month_day": 31}
    runs = next_runs(spec, utc(2027, 1, 31, 1, 0), 4, TZ)  # 31 Jan 04:00 local: Jan run passed
    assert [r.date() for r in runs] == [
        datetime(2027, 2, 28).date(), datetime(2027, 3, 31).date(),
        datetime(2027, 4, 30).date(), datetime(2027, 5, 31).date()]
    assert runs[0] == utc(2027, 2, 28, 0, 0)
    leap = next_run_after({**spec, "month_day": 30}, utc(2028, 2, 1), TZ)
    assert leap == utc(2028, 2, 29, 0, 0)


def test_interval_anchored_at_time() -> None:
    spec = {"kind": "interval", "time": "00:00", "interval_hours": 6}
    # local 13:10 -> next 18:00 local
    assert next_run_after(spec, utc(2026, 11, 12, 10, 10), TZ) == utc(2026, 11, 12, 15, 0)
    # local 00:30 -> 06:00 local
    assert next_run_after(spec, utc(2026, 11, 11, 21, 30), TZ) == utc(2026, 11, 12, 3, 0)


def test_schedule_text() -> None:
    assert schedule_text({"kind": "daily", "time": "02:00"}) == "Her gün 02:00"
    assert schedule_text({"kind": "weekly", "time": "06:30", "weekdays": [5, 1, 3]}) == "Pzt, Çar, Cum 06:30"
    assert schedule_text({"kind": "monthly", "time": "03:00", "month_day": 1}) == "Her ayın 1'i 03:00"
    assert schedule_text({"kind": "interval", "time": "00:00", "interval_hours": 6}) == "Her 6 saatte bir"


# ------------------------------------------------------------------ selection / diff units
def test_changed_objects_with_overlap() -> None:
    mark = utc(2026, 11, 10, 12, 0)
    objects = [
        CatalogObject("D", "s", "old", "VIEW", utc(2026, 1, 1), utc(2026, 1, 1)),
        CatalogObject("D", "s", "edited", "VIEW", utc(2026, 1, 1), mark - timedelta(minutes=3)),
        CatalogObject("D", "s", "created", "VIEW", mark + timedelta(hours=1), None),
        CatalogObject("D", "s", "edge", "VIEW", utc(2026, 1, 1), mark - timedelta(minutes=6)),
    ]
    assert [o.name for o in changed_objects(objects, mark)] == ["edited", "created"]
    assert len(changed_objects(objects, None)) == 4


def finding(code: str, snippet: str, line: int, fid: int) -> SimpleNamespace:
    return SimpleNamespace(rule_code=code, snippet=snippet, line=line, id=fid)


def test_multiset_diff_ignores_lines_and_counts_duplicates() -> None:
    previous = [finding("A", "SELECT  *  FROM t", 3, 1), finding("A", "select * from t", 9, 2),
                finding("B", "x", 1, 3)]
    current = [finding("A", "SELECT * FROM t", 40, 10), finding("C", "y", 2, 11)]
    new, resolved, unchanged = _multiset_diff(current, previous, {"A", "B", "C"})  # type: ignore[arg-type]
    assert [f.id for f in new] == [11] and unchanged == 1
    # one of the two identical previous findings and the B finding are resolved
    assert len(resolved) == 2 and {f.rule_code for f in resolved} == {"A", "B"}
    # a rule the baseline did not run: its findings are new even if the snippet matches
    new, resolved, unchanged = _multiset_diff([finding("C", "x", 1, 20)], [], {"A"})  # type: ignore[arg-type]
    assert [f.id for f in new] == [20] and resolved == [] and unchanged == 0


# ------------------------------------------------------------------ API
CONN = {"name": "c", "server": "localhost", "port": 1433, "username": "sa", "password": "secret"}
STAR = {"code": "T-STAR", "name": "Yıldız", "kind": "regex", "pattern": r"SELECT\s+\*",
        "severity": "medium", "object_types": []}


def schedule_body(conn_id: int, rule_id: int, **extra: object) -> dict:
    return {"name": "Gece taraması", "description": "", "enabled": True, "connection_id": conn_id,
            "scope": {"databases": ["DWH"], "queries": [{"schemas": ["dbo"], "types": ["PROCEDURE"]}]},
            "rule_selection": {"mode": "rules", "group_ids": [], "rule_ids": [rule_id]},
            "schedule": {"kind": "daily", "time": "02:00", "weekdays": [], "month_day": 1, "interval_hours": 24},
            "incremental": True, "first_run_full": True, **extra}


@pytest.fixture
def setup(client: TestClient) -> tuple[TestClient, int, int]:
    conn_id = client.post("/api/connections", json=CONN).json()["id"]
    rule_id = client.post("/api/rules", json=STAR).json()["id"]
    return client, conn_id, rule_id


def wait_run(client: TestClient, schedule_id: int, run_id: int, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = next(r for r in client.get(f"/api/scheduled-analyses/{schedule_id}/runs").json()
                   if r["id"] == run_id)
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_crud_and_validation(setup: tuple[TestClient, int, int]) -> None:
    client, conn_id, rule_id = setup
    body = schedule_body(conn_id, rule_id)
    created = client.post("/api/scheduled-analyses", json=body)
    assert created.status_code == 201, created.json()
    item = created.json()
    assert item["schedule_text"] == "Her gün 02:00" and item["next_run_at"].endswith("Z")
    assert item["connection_name"] == "c" and item["last_run"] is None and item["watermark_at"] is None
    assert client.post("/api/scheduled-analyses", json=body).status_code == 409
    cases = [
        ({"name": " "}, "Ad zorunludur"),
        ({"scope": {"databases": [], "queries": []}}, "veritabanı"),
        ({"schedule": {**body["schedule"], "time": "25:00"}}, "HH:MM"),
        ({"schedule": {**body["schedule"], "kind": "weekly", "weekdays": []}}, "gün"),
        ({"schedule": {**body["schedule"], "kind": "interval", "interval_hours": 0}}, "1 ile 168"),
        ({"rule_selection": {"mode": "groups", "group_ids": [], "rule_ids": []}}, "grubu"),
        ({"rule_selection": {"mode": "rules", "group_ids": [], "rule_ids": []}}, "kural"),
    ]
    for change, text in cases:
        bad = client.post("/api/scheduled-analyses", json={**body, "name": "X", **change})
        assert bad.status_code == 422 and text in bad.json()["detail"], (change, bad.json())

    updated = client.put(f"/api/scheduled-analyses/{item['id']}", json={
        **body, "schedule": {**body["schedule"], "kind": "weekly", "weekdays": [1, 3], "time": "06:30"}}).json()
    assert updated["schedule_text"] == "Pzt, Çar 06:30" and updated["next_run_at"] != item["next_run_at"]
    assert [s["id"] for s in client.get("/api/scheduled-analyses").json()] == [item["id"]]
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["upcoming_schedules"][0]["name"] == "Gece taraması"
    assert client.delete(f"/api/connections/{conn_id}").status_code == 409

    preview = client.post("/api/scheduled-analyses/preview", json=body).json()
    # the fake catalog ignores the type filter: the procedure and the view
    assert preview["object_count"] == 2 and preview["rule_count"] == 1 and preview["changed_count"] is None
    assert preview["estimated_checks"] == 2 and preview["estimated_llm_checks"] == 0
    assert len(preview["next_runs"]) == 3

    assert client.delete(f"/api/scheduled-analyses/{item['id']}").status_code == 204
    assert client.get(f"/api/scheduled-analyses/{item['id']}").status_code == 404


def test_runs_incremental_and_diff(setup: tuple[TestClient, int, int], fake_catalog: FakeCatalog) -> None:
    client, conn_id, rule_id = setup
    schedule = client.post("/api/scheduled-analyses", json=schedule_body(conn_id, rule_id)).json()
    sid = schedule["id"]

    first = client.post(f"/api/scheduled-analyses/{sid}/run")
    assert first.status_code == 202 and first.json()["trigger"] == "manual"
    run1 = wait_run(client, sid, first.json()["id"])
    assert run1["status"] == "completed" and run1["object_count"] == 2
    assert run1["changed_object_count"] == 2 and run1["finding_count"] == 1
    assert (run1["new_count"], run1["resolved_count"], run1["unchanged_count"]) == (1, 0, 0)
    analysis = client.get(f"/api/analyses/{run1['analysis_id']}").json()
    assert analysis["schedule_id"] == sid and analysis["schedule_name"] == "Gece taraması"
    assert analysis["name"].startswith("Gece taraması · ")
    assert analysis["filters"]["schedule"] == "Gece taraması" and analysis["filters"]["incremental"] is True
    html = client.get(f"/api/analyses/{run1['analysis_id']}/report.html").text
    assert "Zamanlanmış analiz" in html and "Artımlı tarama" in html
    after1 = client.get(f"/api/scheduled-analyses/{sid}").json()
    assert after1["watermark_at"] is not None and after1["last_run"]["id"] == run1["id"]

    # nothing changed since the watermark -> skipped, no analysis, watermark advances
    second = client.post(f"/api/scheduled-analyses/{sid}/run").json()
    assert second["status"] == "skipped" and second["analysis_id"] is None
    assert second["reason"] == "Son çalıştırmadan beri değişen veya yeni nesne yok"
    assert client.get(f"/api/scheduled-analyses/{sid}").json()["watermark_at"] >= after1["watermark_at"]
    assert len(client.get("/api/analyses").json()) == 1

    # the procedure changes: one finding resolved, one new (line numbers differ, ignored)
    old = fake_catalog.objects[0]
    fake_catalog.objects[0] = CatalogObject(old.database, old.schema, old.name, old.type,
                                            old.create_date, utcnow() + timedelta(minutes=1))
    fake_catalog.definitions[("DWH", "dbo", "usp_LoadSales")] = (
        "CREATE PROCEDURE dbo.usp_LoadSales\nAS\n\n\nSELECT * FROM dbo.Orders;\n"
        "SELECT   *   FROM dbo.Sales WITH (NOLOCK);\n"
    )
    third = client.post(f"/api/scheduled-analyses/{sid}/run").json()
    run3 = wait_run(client, sid, third["id"])
    assert run3["status"] == "completed" and run3["finding_count"] == 2
    assert run3["changed_object_count"] == 1
    assert (run3["new_count"], run3["resolved_count"], run3["unchanged_count"]) == (1, 0, 1)
    diff = client.get(f"/api/scheduled-runs/{run3['id']}/diff").json()
    assert diff["compared_objects"] == 1
    assert [f["snippet"] for f in diff["new"]] == ["SELECT * FROM dbo.Orders;"]

    fake_catalog.objects[0] = CatalogObject(old.database, old.schema, old.name, old.type,
                                            old.create_date, utcnow() + timedelta(minutes=2))
    fake_catalog.definitions[("DWH", "dbo", "usp_LoadSales")] = "CREATE PROCEDURE dbo.usp_LoadSales AS SELECT 1"
    run4 = wait_run(client, sid, client.post(f"/api/scheduled-analyses/{sid}/run").json()["id"])
    assert (run4["new_count"], run4["resolved_count"], run4["finding_count"]) == (0, 2, 0)
    resolved = client.get(f"/api/scheduled-runs/{run4['id']}/diff").json()["resolved"]
    assert {f["snippet"] for f in resolved} == {
        "SELECT * FROM dbo.Orders;", "SELECT   *   FROM dbo.Sales WITH (NOLOCK);"}
    runs = client.get(f"/api/scheduled-analyses/{sid}/runs").json()
    assert [r["id"] for r in runs] == sorted((r["id"] for r in runs), reverse=True)

    # deleting the schedule keeps its analyses
    assert client.delete(f"/api/scheduled-analyses/{sid}").status_code == 204
    kept = client.get(f"/api/analyses/{run1['analysis_id']}").json()
    assert kept["schedule_id"] is None and kept["schedule_name"] == "Gece taraması"


def test_skip_running_and_failures(setup: tuple[TestClient, int, int]) -> None:
    client, conn_id, rule_id = setup
    sid = client.post("/api/scheduled-analyses", json=schedule_body(conn_id, rule_id)).json()["id"]
    with get_database().session_factory() as session:
        session.add(models.Analysis(name="eski", status="running", schedule_id=sid))
        session.commit()
    skipped = client.post(f"/api/scheduled-analyses/{sid}/run").json()
    assert skipped["status"] == "skipped" and skipped["reason"] == "Önceki çalıştırma devam ediyor"

    rule = client.get(f"/api/rules/{rule_id}").json()
    client.put(f"/api/rules/{rule_id}", json={**rule, "enabled": False})
    other = client.post("/api/scheduled-analyses", json=schedule_body(conn_id, rule_id, name="İkinci")).json()
    failed = client.post(f"/api/scheduled-analyses/{other['id']}/run").json()
    assert failed["status"] == "failed" and failed["reason"] == "Çalıştırılacak etkin kural yok"

    llm_rule = next(r for r in client.get("/api/rules").json() if r["code"] == "DWH-SQL-05")
    third = client.post("/api/scheduled-analyses", json=schedule_body(
        conn_id, llm_rule["id"], name="Üçüncü")).json()
    result = client.post(f"/api/scheduled-analyses/{third['id']}/run").json()
    assert result["status"] == "failed" and "LLM" in result["reason"]


def test_tick_runs_due_schedules_once(setup: tuple[TestClient, int, int]) -> None:
    client, conn_id, rule_id = setup
    sid = client.post("/api/scheduled-analyses", json=schedule_body(conn_id, rule_id)).json()["id"]
    scheduler = client.app.state.scheduler  # type: ignore[attr-defined]
    now = utcnow()
    with get_database().session_factory() as session:
        row = session.get(models.ScheduledAnalysis, sid)
        row.next_run_at = now - timedelta(days=3)  # several missed periods
        session.commit()
    started = scheduler.tick(now)
    assert len(started) == 1
    run = wait_run(client, sid, started[0])
    assert run["trigger"] == "catch_up" and run["status"] == "completed"
    after = client.get(f"/api/scheduled-analyses/{sid}").json()
    assert after["next_run_at"] > now.isoformat()
    assert scheduler.tick(now) == []  # next run is in the future now
    with get_database().session_factory() as session:
        row = session.get(models.ScheduledAnalysis, sid)
        row.next_run_at = now - timedelta(seconds=10)
        row.enabled = True
        session.commit()
    on_time = scheduler.tick(now)
    assert len(on_time) == 1
    latest = client.get(f"/api/scheduled-analyses/{sid}/runs").json()[0]
    assert latest["trigger"] == "schedule"
    assert latest["status"] == "skipped"  # nothing changed since the catch-up run
