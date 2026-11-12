"""Per-rule live-tester samples: seed, API, duplicate, migration and the samples themselves."""

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rule_samples import SAMPLES
from app.seed import SEED_RULES
from app.services.rule_engine import TEXT_ONLY_BUILTINS


def test_every_seeded_rule_has_a_sample() -> None:
    assert set(SAMPLES) == {r["code"] for r in SEED_RULES}
    for code, sample in SAMPLES.items():
        assert sample["sql"].strip() and sample["object_name"] and sample["object_type"], code
        assert re.search(r"--\s*(HATA|ÖNERİ)", sample["sql"]), code  # CAL-01 is a suggestion


def test_seed_and_api_expose_samples(client: TestClient) -> None:
    rules = {r["code"]: r for r in client.get("/api/rules").json()}
    nolock = rules["DWH-NOLOCK-02"]
    assert nolock["sample_sql"] == SAMPLES["DWH-NOLOCK-02"]["sql"]
    assert nolock["sample_object_type"] == SAMPLES["DWH-NOLOCK-02"]["object_type"]
    assert nolock["sample_database"] == SAMPLES["DWH-NOLOCK-02"]["database"]

    # Update without sample fields keeps the sample (older clients); explicit null clears it.
    body = {k: v for k, v in nolock.items() if not k.startswith("sample_")}
    kept = client.put(f"/api/rules/{nolock['id']}", json=body).json()
    assert kept["sample_sql"] == nolock["sample_sql"]
    changed = client.put(f"/api/rules/{nolock['id']}", json={**nolock, "sample_sql": "SELECT 1",
                                                             "sample_object_type": "VIEW"}).json()
    assert changed["sample_sql"] == "SELECT 1" and changed["sample_object_type"] == "VIEW"
    bad = client.put(f"/api/rules/{nolock['id']}", json={**nolock, "sample_object_type": "TABLE"})
    assert bad.status_code == 422
    copy = client.post(f"/api/rules/{nolock['id']}/duplicate").json()
    assert copy["sample_sql"] == "SELECT 1" and copy["sample_object_name"] == nolock["sample_object_name"]
    cleared = client.put(f"/api/rules/{nolock['id']}", json={**nolock, "sample_sql": None}).json()
    assert cleared["sample_sql"] is None


@pytest.mark.parametrize("code", sorted(SAMPLES))
def test_text_rules_hit_exactly_the_hata_lines(client: TestClient, code: str) -> None:
    rule = next(r for r in client.get("/api/rules").json() if r["code"] == code)
    if rule["kind"] == "llm" or (rule["kind"] == "builtin" and rule["builtin_check"] not in TEXT_ONLY_BUILTINS):
        pytest.skip("needs an LLM or catalog metadata")
    sample = SAMPLES[code]
    result = client.post("/api/rules/test", json={
        "rule": rule, "sql": sample["sql"], "object_name": sample["object_name"],
        "object_type": sample["object_type"], "database": sample["database"],
    }).json()
    lines = sample["sql"].splitlines()
    # a violation is on the line after a "-- HATA" comment (or on the same line)
    hata = {n for n, text in enumerate(lines, 1) if re.search(r"--\s*(HATA|ÖNERİ)", text)}
    expected_near = hata | {n + 1 for n in hata}
    found = {f["line"] for f in result["findings"]}
    assert result["findings"], code
    assert found <= expected_near | {None}, (code, found, hata)


def test_migration_fills_only_empty_samples(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)):
        pass
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:
        db.execute("UPDATE rules SET sample_sql = NULL, sample_object_name = NULL")
        db.execute("UPDATE rules SET sample_sql = 'SELECT benim' WHERE code = 'DWH-SQL-04'")
        db.execute("INSERT INTO rules (code, name, description, recommendation, severity, kind, pattern,"
                   " match_mode, target, ignore_case, ignore_comments, object_types, enabled,"
                   " requires_metadata, databases, created_at, updated_at) SELECT 'DWH-CAL-01_COPY', name,"
                   " description, recommendation, severity, kind, pattern, match_mode, target, ignore_case,"
                   " ignore_comments, object_types, enabled, requires_metadata, databases, created_at,"
                   " updated_at FROM rules WHERE code = 'DWH-CAL-01'")
        db.execute("UPDATE app_meta SET value = '5' WHERE key = 'ruleset_version'")
        db.commit()
    finally:
        db.close()
    with TestClient(create_app(tmp_path)) as client:
        rules = {r["code"]: r for r in client.get("/api/rules").json()}
        assert rules["DWH-SQL-04"]["sample_sql"] == "SELECT benim"  # user sample kept
        assert rules["DWH-HINT-01"]["sample_sql"] == SAMPLES["DWH-HINT-01"]["sql"]
        assert rules["DWH-HINT-01"]["sample_object_name"] == SAMPLES["DWH-HINT-01"]["object_name"]
        assert rules["DWH-CAL-01_COPY"]["sample_sql"] is None  # user copy left alone
