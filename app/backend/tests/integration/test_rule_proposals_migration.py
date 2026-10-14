"""Revision 202610140001: rule proposals, publish requests, the permission and rule summaries.

sql-review/PRDs/009-rule-proposals "Veri ve geçiş", against the migrated database: the step goes
down and up again, and it refuses to go down while a proposal, a publish request, a permission or
a given summary is stored, so that data is never dropped silently.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

pytestmark = pytest.mark.integration

_BEFORE_PROPOSALS = "202610050002"
_PROPOSAL_TABLES = ("rule_proposal", "rule_publish_request", "rule_proposer")


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
            names=list(_PROPOSAL_TABLES),
        )
    )
    return {str(row[0]) for row in rows}


def clear_rule_proposal_data() -> None:
    """Remove every proposal row and given summary on the disposable test database.

    Other integration tests send proposals and save summaries; a migration test that walks below
    202610140001 clears them first, since the downgrade refuses stored data by design.
    """

    for statement in (
        "DELETE FROM rule_proposal",
        "DELETE FROM rule_publish_request",
        "DELETE FROM rule_proposer",
        "UPDATE rule_set_draft_rule SET summary = '' WHERE summary <> ''",
        "UPDATE rule_set_version_rule SET summary = '' WHERE summary <> ''",
    ):
        asyncio.run(_run(statement))


def _stored_permission() -> None:
    asyncio.run(
        _run(
            "INSERT INTO rule_proposer (tenant_id, user_id, granted_by_user_id) "
            "SELECT home_tenant_id, user_id, user_id FROM app_user ORDER BY user_id LIMIT 1 "
            "ON CONFLICT (tenant_id, user_id) DO UPDATE SET is_deleted = false"
        )
    )


def test_the_rule_proposal_migration_goes_down_and_up_again(
    migrated_database: None,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        assert _tables() == set(_PROPOSAL_TABLES)
        _stored_permission()

        with pytest.raises(RuntimeError, match="rule proposal data is stored"):
            command.downgrade(config, _BEFORE_PROPOSALS)
        assert _tables() == set(_PROPOSAL_TABLES)

        clear_rule_proposal_data()
        command.downgrade(config, _BEFORE_PROPOSALS)
        assert _tables() == set()
    finally:
        command.upgrade(config, "head")
    assert _tables() == set(_PROPOSAL_TABLES)
    command.check(config)
