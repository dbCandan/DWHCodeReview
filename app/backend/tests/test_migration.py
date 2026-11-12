"""Startup migration of a v1.0 database (old columns, old rule set)."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

OLD_SCHEMA = """
CREATE TABLE rules (
    id INTEGER NOT NULL, code VARCHAR(32) NOT NULL, name VARCHAR(200) NOT NULL,
    description TEXT NOT NULL, recommendation TEXT NOT NULL, severity VARCHAR(16) NOT NULL,
    kind VARCHAR(16) NOT NULL, pattern TEXT, match_mode VARCHAR(16) NOT NULL,
    target VARCHAR(16) NOT NULL, ignore_case BOOLEAN NOT NULL, ignore_comments BOOLEAN NOT NULL,
    llm_prompt TEXT, object_types JSON NOT NULL, enabled BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE (code));
CREATE TABLE rule_groups (
    id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, description TEXT NOT NULL,
    color VARCHAR(7) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
    PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE connections (
    id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, server VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL, username VARCHAR(128) NOT NULL, password_enc TEXT,
    encrypt BOOLEAN NOT NULL, trust_server_certificate BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE llm_settings (
    id INTEGER NOT NULL, enabled BOOLEAN NOT NULL, base_url VARCHAR(500) NOT NULL,
    model VARCHAR(200) NOT NULL, api_key_enc TEXT, temperature FLOAT NOT NULL,
    timeout_seconds INTEGER NOT NULL, PRIMARY KEY (id));
CREATE TABLE rule_group_members (
    rule_id INTEGER NOT NULL, group_id INTEGER NOT NULL, PRIMARY KEY (rule_id, group_id),
    FOREIGN KEY(rule_id) REFERENCES rules (id) ON DELETE CASCADE,
    FOREIGN KEY(group_id) REFERENCES rule_groups (id) ON DELETE CASCADE);
CREATE TABLE analyses (
    id INTEGER NOT NULL, name VARCHAR(200) NOT NULL, connection_id INTEGER,
    connection_name VARCHAR(100) NOT NULL, status VARCHAR(16) NOT NULL,
    object_count INTEGER NOT NULL, rule_count INTEGER NOT NULL, total_checks INTEGER NOT NULL,
    completed_checks INTEGER NOT NULL, error TEXT, filters JSON NOT NULL,
    cancel_requested BOOLEAN NOT NULL, created_at DATETIME NOT NULL, started_at DATETIME,
    finished_at DATETIME, PRIMARY KEY (id),
    FOREIGN KEY(connection_id) REFERENCES connections (id) ON DELETE SET NULL);
CREATE TABLE analysis_rules (
    id INTEGER NOT NULL, analysis_id INTEGER NOT NULL, rule_id INTEGER, code VARCHAR(32) NOT NULL,
    name VARCHAR(200) NOT NULL, description TEXT NOT NULL, recommendation TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL, kind VARCHAR(16) NOT NULL, pattern TEXT,
    match_mode VARCHAR(16) NOT NULL, target VARCHAR(16) NOT NULL, ignore_case BOOLEAN NOT NULL,
    ignore_comments BOOLEAN NOT NULL, llm_prompt TEXT, object_types JSON NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE);
CREATE TABLE analysis_objects (
    id INTEGER NOT NULL, analysis_id INTEGER NOT NULL, "database" VARCHAR(128) NOT NULL,
    schema VARCHAR(128) NOT NULL, name VARCHAR(128) NOT NULL, type VARCHAR(32) NOT NULL,
    create_date DATETIME, modify_date DATETIME, status VARCHAR(16) NOT NULL, error TEXT,
    finding_count INTEGER NOT NULL, line_count INTEGER NOT NULL, definition TEXT,
    PRIMARY KEY (id), FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE);
CREATE TABLE findings (
    id INTEGER NOT NULL, analysis_id INTEGER NOT NULL, object_id INTEGER NOT NULL,
    object_label VARCHAR(400) NOT NULL, rule_code VARCHAR(32) NOT NULL,
    rule_name VARCHAR(200) NOT NULL, severity VARCHAR(16) NOT NULL, kind VARCHAR(16) NOT NULL,
    line INTEGER, snippet TEXT NOT NULL, message TEXT NOT NULL, recommendation TEXT NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE,
    FOREIGN KEY(object_id) REFERENCES analysis_objects (id) ON DELETE CASCADE);
"""

NOW = "2026-10-01 10:00:00"


def build_old_database(data_dir: Path) -> None:
    db = sqlite3.connect(data_dir / "dwhcr.db")
    db.executescript(OLD_SCHEMA)
    for rule_id, code in ((1, "DWH001"), (2, "DWH002"), (3, "LLM001")):
        db.execute(
            "INSERT INTO rules VALUES (?, ?, ?, '', '', 'medium', 'regex', 'x', 'match', "
            "'definition', 1, 1, NULL, '[]', 1, ?, ?)",
            (rule_id, code, f"Eski {code}", NOW, NOW),
        )
    db.execute("INSERT INTO rule_groups VALUES (1, 'Performans', '', '#2563EB', ?, ?)", (NOW, NOW))
    db.execute("INSERT INTO rule_groups VALUES (2, 'Güvenlik', '', '#DC2626', ?, ?)", (NOW, NOW))
    db.executemany("INSERT INTO rule_group_members VALUES (?, ?)", [(1, 1), (2, 1), (3, 2)])
    db.execute(
        "INSERT INTO connections VALUES (1, 'SQLDOCKER', 'sqlhost', 1433, 'sa', NULL, 1, 1, ?, ?)",
        (NOW, NOW),
    )
    db.execute(
        "INSERT INTO llm_settings VALUES (1, 1, 'http://llm.local/v1', 'qwen', NULL, 0.0, 60)"
    )
    db.execute(
        "INSERT INTO analyses VALUES (1, 'Eski analiz', 1, 'SQLDOCKER', 'completed', 1, 2, 2, 2, "
        "NULL, '{}', 0, ?, ?, ?)",
        (NOW, NOW, NOW),
    )
    db.execute(
        "INSERT INTO analysis_rules VALUES (1, 1, 1, 'DWH001', 'Eski DWH001', '', '', 'medium', "
        "'regex', 'x', 'match', 'definition', 1, 1, NULL, '[]')"
    )
    db.execute(
        "INSERT INTO analysis_objects VALUES (1, 1, 'DWH', 'dbo', 'p', 'PROCEDURE', NULL, NULL, "
        "'done', NULL, 1, 3, 'CREATE PROC p AS SELECT x')"
    )
    db.execute(
        "INSERT INTO findings VALUES (1, 1, 1, 'DWH.dbo.p', 'DWH001', 'Eski DWH001', 'medium', "
        "'regex', 1, 'SELECT x', 'm', 'r')"
    )
    db.commit()
    db.close()


def columns(path: Path, table: str) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


def test_migrates_old_database(tmp_path: Path) -> None:
    build_old_database(tmp_path)
    new_columns = {"builtin_check", "precondition", "metadata_precondition", "requires_metadata",
                   "databases", "name_pattern"}

    with TestClient(create_app(tmp_path)) as client:
        assert new_columns <= columns(tmp_path / "dwhcr.db", "rules")
        assert new_columns <= columns(tmp_path / "dwhcr.db", "analysis_rules")

        rules = client.get("/api/rules").json()
        assert len(rules) == 32 and all(r["code"].startswith("DWH-") for r in rules)
        groups = {g["name"]: g for g in client.get("/api/rule-groups").json()}
        assert {"DWH Kodlama ve Performans", "DWH Standartları", "LLM Kuralları"} <= set(groups)
        assert len(groups) == 11
        critical = {r["id"] for r in rules if r["severity"] == "critical"}
        assert set(groups["DWH Standartları"]["rule_ids"]) == critical and len(critical) == 8
        assert len(groups["DWH Kodlama ve Performans"]["rule_ids"]) == 24

        # History, connection and LLM settings survive.
        detail = client.get("/api/analyses/1").json()
        assert detail["name"] == "Eski analiz" and detail["status"] == "completed"
        assert detail["rules"] == [
            {"id": None, "code": "DWH001", "name": "Eski DWH001", "severity": "medium",
             "kind": "regex"}
        ]
        findings = client.get("/api/analyses/1/findings").json()
        assert [f["rule_code"] for f in findings] == ["DWH001"]
        assert client.get("/api/analyses/1/report.html").status_code == 200
        assert [c["name"] for c in client.get("/api/connections").json()] == ["SQLDOCKER"]
        assert client.get("/api/settings/llm").json()["model"] == "qwen"

        # A rule added after the migration is kept across restarts.
        rule = {**rules[0], "code": "MY-RULE", "group_ids": []}
        assert client.post("/api/rules", json=rule).status_code == 201

    with TestClient(create_app(tmp_path)) as client:
        codes = {r["code"] for r in client.get("/api/rules").json()}
        assert len(codes) == 33 and "MY-RULE" in codes


def test_fresh_install_gets_the_ruleset(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        rules = {r["code"]: r for r in client.get("/api/rules").json()}
        assert len(rules) == 32
        assert rules["DWH-NOLOCK-02"]["name"] == "Temp tablo okumasında NOLOCK/TABLOCK kullanılmış"
        assert "YALNIZ 'SCD' işaretli" in rules["DWH-SCD-01"]["llm_prompt"]
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:
        assert db.execute("SELECT value FROM app_meta WHERE key = 'ruleset_version'").fetchone() == (
            "7",
        )
    finally:
        db.close()


def test_migrates_v2_to_v3_keeping_user_changes(tmp_path: Path) -> None:
    """A v2 database (8 rules, user rule, user edit) gets the v3 additions only."""
    from app.seed import _TEXTS, GROUP_V3, V3_RULES

    with TestClient(create_app(tmp_path)):
        pass
    db = sqlite3.connect(tmp_path / "dwhcr.db")
    try:  # turn the fresh v3 install back into a v2 database
        v3_codes = [r["code"] for r in V3_RULES]
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"DELETE FROM rules WHERE code IN ({','.join('?' * len(v3_codes))})", v3_codes)
        db.execute("DELETE FROM rule_groups WHERE name = ?", (GROUP_V3["name"],))
        old = _TEXTS["DWH-NOLOCK-02"]
        db.execute("UPDATE rules SET name = ?, pattern = ? WHERE code = 'DWH-NOLOCK-02'",
                   (old["name"], old["pattern"]))
        db.execute("UPDATE rules SET llm_prompt = ? WHERE code = 'DWH-SCD-01'",
                   (_TEXTS["DWH-SCD-01"]["llm_prompt"],))
        db.execute("UPDATE rules SET enabled = 0, name = 'Benim adım' WHERE code = 'DWH-DM-01'")
        db.execute(
            "INSERT INTO rules (code, name, description, recommendation, severity, kind, pattern,"
            " match_mode, target, ignore_case, ignore_comments, object_types, enabled,"
            " requires_metadata, databases, created_at, updated_at) VALUES ('MY-RULE', 'Benim',"
            " '', '', 'low', 'regex', 'x', 'match', 'definition', 1, 1, '[]', 1, 0, '[]', ?, ?)",
            (NOW, NOW),
        )
        db.execute("UPDATE app_meta SET value = '2' WHERE key = 'ruleset_version'")
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM rules").fetchone() == (9,)
    finally:
        db.close()

    with TestClient(create_app(tmp_path)) as client:
        rules = {r["code"]: r for r in client.get("/api/rules").json()}
        assert len(rules) == 33 and "MY-RULE" in rules
        assert rules["DWH-DM-01"]["enabled"] is False and rules["DWH-DM-01"]["name"] == "Benim adım"
        nolock = rules["DWH-NOLOCK-02"]
        assert nolock["name"] == "Temp tablo okumasında NOLOCK/TABLOCK kullanılmış"
        assert "TABLOCKX?" in nolock["pattern"] and nolock["severity"] == "critical"
        assert "YALNIZ 'SCD' işaretli" in rules["DWH-SCD-01"]["llm_prompt"]
        groups = {g["name"]: g for g in client.get("/api/rule-groups").json()}
        assert len(groups["DWH Standartları"]["rule_ids"]) == 8
        new_group = groups["DWH Kodlama ve Performans"]
        assert sorted(new_group["rule_ids"]) == sorted(rules[c]["id"] for c in v3_codes)
        assert rules["MY-RULE"]["group_ids"] == []

    with TestClient(create_app(tmp_path)) as client:  # idempotent on restart
        assert len(client.get("/api/rules").json()) == 33
