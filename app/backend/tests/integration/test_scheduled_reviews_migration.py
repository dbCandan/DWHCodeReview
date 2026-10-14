"""Revision 202610050002: scheduled review definitions, their runs, recipients and the setting.

sql-review/PRDs/008-scheduled-review-email "Veri ve geçiş" against the migrated database: the step
goes down and up again, and it refuses to go down while a definition or a scheduled run is
stored, so recipient addresses and run history are never dropped silently.
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.integration.test_rule_proposals_migration import clear_rule_proposal_data

pytestmark = pytest.mark.integration

_BEFORE_SCHEDULES = "202610050001"
_SCHEDULE_TABLES = (
    "scheduled_review",
    "scheduled_review_run",
    "review_run_recipient",
    "scheduled_review_setting",
)


async def _run(statement: str, **params: Any) -> list[Any]:
    probe = create_async_engine(get_settings().database_url)
    try:
        async with probe.begin() as connection:
            result = await connection.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await probe.dispose()


def _tables() -> set[str]:
    rows = asyncio.run(
        _run(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = ANY(:names)",
            names=list(_SCHEDULE_TABLES),
        )
    )
    return {str(row[0]) for row in rows}


def clear_scheduled_review_data() -> None:
    """Remove every stored scheduled review row on the disposable test database.

    Other integration tests create definitions and scheduled runs; a migration test that walks
    below 202610050002 clears them first, since the downgrade refuses stored data by design.
    """

    for statement in (
        "DELETE FROM review_run_recipient",
        "DELETE FROM review_run WHERE kind = 'scheduled'",
        "DELETE FROM scheduled_review_run",
        "DELETE FROM scheduled_review",
        "DELETE FROM scheduled_review_setting",
    ):
        asyncio.run(_run(statement))


def _stored_definition() -> None:
    marker = uuid4().hex
    asyncio.run(
        _run(
            "WITH owner AS (INSERT INTO app_user (home_tenant_id, public_id, username, email, "
            "display_name, account_type, directory_object_guid) SELECT tenant_id, :user_id, "
            ":name, :name, 'Test Person', 'directory', :guid FROM tenant WHERE code = 'platform' "
            "RETURNING user_id, home_tenant_id) INSERT INTO scheduled_review (public_id, "
            "tenant_id, owner_user_id, name, selection_mode, selection, frequency, run_hour, "
            "run_minute, timezone, recipients) SELECT :definition, home_tenant_id, user_id, "
            "'Gece taraması', 'filter', CAST(:selection AS jsonb), 'daily', 7, 30, "
            "'Europe/Istanbul', CAST(:recipients AS jsonb) FROM owner",
            user_id=str(uuid4()),
            name=f"{marker}@corp.example.test",
            guid=uuid4(),
            definition=str(uuid4()),
            selection='{"database": "DWH"}',
            recipients='["a@kurum.example"]',
        )
    )


def test_the_scheduled_review_migration_goes_down_and_up_again(
    migrated_database: None,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        assert _tables() == set(_SCHEDULE_TABLES)
        # The later proposal revision is walked down first; its own data must not stop it.
        clear_rule_proposal_data()
        _stored_definition()

        # A stored definition carries recipient addresses; they are not dropped silently.
        with pytest.raises(RuntimeError, match="scheduled review data is stored"):
            command.downgrade(config, _BEFORE_SCHEDULES)
        assert _tables() == set(_SCHEDULE_TABLES)

        clear_scheduled_review_data()
        command.downgrade(config, _BEFORE_SCHEDULES)
        assert _tables() == set()
    finally:
        command.upgrade(config, "head")
    assert _tables() == set(_SCHEDULE_TABLES)
    command.check(config)
