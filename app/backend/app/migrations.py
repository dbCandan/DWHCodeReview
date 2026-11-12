"""Startup migrations for an existing SQLite database.

`create_all` creates missing tables but never alters existing ones, so columns added after
v1.0 are appended here with `ALTER TABLE ... ADD COLUMN` (SQLite keeps existing rows; the
DEFAULT fills them). The rule set version lives in `app_meta` and is upgraded step by step
(see `upgrade_ruleset`); connections, LLM settings and analysis history are always kept.
"""

import logging

import re

from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from app import models
from app.seed import (
    RULESET_VERSION,
    apply_ruleset,
    apply_ruleset_v3,
    apply_ruleset_v4,
    apply_ruleset_v5,
    apply_ruleset_v6,
    apply_ruleset_v7,
)

logger = logging.getLogger("dwhcr.migrations")

RULESET_KEY = "ruleset_version"

# Column -> SQLite column definition; shared by `rules` and its snapshot `analysis_rules`.
RULE_ENGINE_COLUMNS: dict[str, str] = {
    "builtin_check": "VARCHAR(64)",
    "precondition": "TEXT",
    "metadata_precondition": "VARCHAR(64)",
    "requires_metadata": "BOOLEAN NOT NULL DEFAULT 0",
    "databases": "JSON NOT NULL DEFAULT '[]'",
    "name_pattern": "TEXT",
}

RULE_SAMPLE_COLUMNS: dict[str, str] = {
    "sample_sql": "TEXT",
    "sample_object_name": "VARCHAR(300)",
    "sample_object_type": "VARCHAR(32)",
    "sample_database": "VARCHAR(128)",
}

ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "rules": {**RULE_ENGINE_COLUMNS, **RULE_SAMPLE_COLUMNS},
    "analysis_rules": RULE_ENGINE_COLUMNS,
    # v1.4: findings hidden by rule exceptions
    "analyses": {
        "suppressed_count": "INTEGER NOT NULL DEFAULT 0",
        # v1.7: scheduled analyses
        "schedule_id": "INTEGER",
        "schedule_run_id": "INTEGER",
        "schedule_name": "VARCHAR(200)",
    },
    "analysis_objects": {"suppressed_count": "INTEGER NOT NULL DEFAULT 0"},
    # v1.5: LLM chunking of large objects
    "llm_settings": {"chunk_lines": "INTEGER NOT NULL DEFAULT 250"},
}


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_DDL = re.compile(r"^[A-Z]+(?:\(\d+\))?(?: NOT NULL)?(?: DEFAULT (?:-?\d+|'[^']*'))?$")


def _add_column_ddl(preparer: object, table: str, column: str, ddl: str) -> str:
    """ALTER TABLE for one ADDED_COLUMNS entry; names and types come only from that constant."""
    if not (_IDENT.match(table) and _IDENT.match(column) and _DDL.match(ddl)):
        raise ValueError(f"geçersiz şema tanımı: {table}.{column} {ddl}")
    quote = preparer.quote  # type: ignore[attr-defined]
    return f"ALTER TABLE {quote(table)} ADD COLUMN {quote(column)} {ddl}"


def upgrade_schema(engine: Engine) -> list[str]:
    """Add missing columns; returns "table.column" for each column added."""
    added: list[str] = []
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        preparer = connection.dialect.identifier_preparer
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:  # table missing: create_all makes it with every column
                continue
            existing = {str(c["name"]) for c in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column not in existing:
                    statement = _add_column_ddl(preparer, table, column, ddl)
                    # Identifiers and types are validated constants from ADDED_COLUMNS, not input.
                    connection.exec_driver_sql(statement)  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query, python.lang.security.audit.formatted-sql-query.formatted-sql-query
                    added.append(f"{table}.{column}")
    if added:
        logger.info("eklenen kolonlar: %s", ", ".join(added))
    return added


def ruleset_version(session: Session) -> int:
    row = session.get(models.AppMeta, RULESET_KEY)
    try:
        return int(row.value) if row is not None else 0
    except ValueError:
        return 0


def upgrade_ruleset(session: Session) -> bool:
    """Bring the rule set up to RULESET_VERSION step by step; True if anything changed.

    < 2: every rule and group is replaced by the v2 standards set.
    < 3: the v3 rules (missing codes only) and their group are added, DWH-NOLOCK-02 and
         DWH-SCD-01 are updated; other rules are not touched.
    < 4: only the fields listed in `seed.V4_UPDATES` of five rules are updated.
    < 5: only DWH-DM-01's llm_prompt is updated (`seed.V5_UPDATES`).
    < 6: live-tester samples (`rule_samples.SAMPLES`) for rules whose sample_sql is empty.
    < 7: topic groups (`seed.TOPIC_GROUPS`) that do not exist yet, with their memberships.
    """
    version = ruleset_version(session)
    if version >= RULESET_VERSION:
        return False
    if version < 2:
        apply_ruleset(session)
    if version < 3:
        apply_ruleset_v3(session)
    if version < 4:
        apply_ruleset_v4(session)
    if version < 5:
        apply_ruleset_v5(session)
    if version < 6:
        apply_ruleset_v6(session)
    if version < 7:
        apply_ruleset_v7(session)
    row = session.get(models.AppMeta, RULESET_KEY)
    if row is None:
        session.add(models.AppMeta(key=RULESET_KEY, value=str(RULESET_VERSION)))
    else:
        row.value = str(RULESET_VERSION)
    session.commit()
    count = len(list(session.scalars(select(models.Rule.id))))
    logger.info("kural seti sürüm %s yüklendi (%s kural)", RULESET_VERSION, count)
    return True
