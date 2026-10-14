"""Revision 202610020001: a review run has no object limit (sql-review 003 Decision 3).

Against the migrated database: the check keeps only "at least one object", the step goes down
and up again, and it refuses to go down while a run with more than 50 objects is stored.
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.integration.test_rule_groups_migration import clear_rule_group_data
from tests.integration.test_rule_proposals_migration import clear_rule_proposal_data
from tests.integration.test_scheduled_reviews_migration import (
    clear_scheduled_review_data,
)

pytestmark = pytest.mark.integration

_CHECKS = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = 'review_run'::regclass AND conname LIKE 'ck_review_run_object_count%'"
)
_INSERT_RUN = (
    "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, rule_set_version_id, "
    "object_count, started_at) SELECT :public_id, t.tenant_id, :owner, 'object', "
    "(SELECT min(rule_set_version_id) FROM rule_set_version), :count, now() "
    "FROM tenant t WHERE t.code = 'platform'"
)


async def _run(statement: str, **params: Any) -> list[Any]:
    probe = create_async_engine(get_settings().database_url)
    try:
        async with probe.begin() as connection:
            result = await connection.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await probe.dispose()


def _checks() -> dict[str, str]:
    return {str(name): str(definition) for name, definition in asyncio.run(_run(_CHECKS))}


def _owner() -> int:
    marker = uuid4().hex
    rows = asyncio.run(
        _run(
            "INSERT INTO app_user (home_tenant_id, public_id, username, email, display_name, "
            "account_type, directory_object_guid) SELECT tenant_id, :public_id, :name, :name, "
            "'Test Person', 'directory', :guid FROM tenant WHERE code = 'platform' "
            "RETURNING user_id",
            public_id=str(uuid4()),
            name=f"{marker}@corp.example.test",
            guid=uuid4(),
        )
    )
    return int(rows[0][0])


def _insert_run(owner: int, count: int) -> str:
    public_id = str(uuid4())
    asyncio.run(_run(_INSERT_RUN, public_id=public_id, owner=owner, count=count))
    return public_id


def test_the_object_limit_migration_goes_down_and_up_again(migrated_database: None) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    owner = _owner()
    created: list[str] = []
    try:
        # The step below 202610050001 refuses stored rule group data (rule-group-selection
        # Decision 4); this test walks through it, so it starts without any.
        clear_rule_proposal_data()
        clear_scheduled_review_data()
        clear_rule_group_data()
        asyncio.run(_run("DELETE FROM review_run WHERE object_count > 50"))
        assert _checks() == {"ck_review_run_object_count_positive": "CHECK ((object_count >= 1))"}
        created.append(_insert_run(owner, 5_000))
        with pytest.raises(IntegrityError):
            _insert_run(owner, 0)

        # A stored run with more than 50 objects cannot satisfy the previous check.
        with pytest.raises(RuntimeError, match="more than 50 objects"):
            command.downgrade(config, "202610010002")
        assert "ck_review_run_object_count_positive" in _checks()

        asyncio.run(_run("DELETE FROM review_run WHERE public_id = :id", id=created.pop()))
        command.downgrade(config, "202610010002")
        assert _checks() == {
            "ck_review_run_object_count_range": (
                "CHECK (((object_count >= 1) AND (object_count <= 50)))"
            )
        }
        created.append(_insert_run(owner, 50))
        with pytest.raises(IntegrityError):
            _insert_run(owner, 51)
    finally:
        command.upgrade(config, "head")
        for public_id in created:
            asyncio.run(_run("DELETE FROM review_run WHERE public_id = :id", id=public_id))
    assert _checks() == {"ck_review_run_object_count_positive": "CHECK ((object_count >= 1))"}
    command.check(config)
