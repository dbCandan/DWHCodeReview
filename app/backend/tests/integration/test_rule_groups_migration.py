"""Revision 202610050001: named rule groups, memberships and a run's rule selection.

sql-review/PRDs/007-rule-group-selection "Veri ve geçiş" and Decision 4, against the migrated
database: the step goes down and up again, and it refuses to go down while a stored run or rule
result carries group information, so group data is never dropped silently.
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
from tests.integration.test_scheduled_reviews_migration import (
    clear_scheduled_review_data,
)

pytestmark = pytest.mark.integration

_BEFORE_GROUPS = "202610020001"
_GROUP_TABLES = (
    "rule_set_draft_group",
    "rule_set_version_group",
    "rule_set_draft_rule_group",
    "rule_set_version_rule_group",
    "review_run_rule_group",
    "review_run_rule",
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
            names=list(_GROUP_TABLES),
        )
    )
    return {str(row[0]) for row in rows}


def _stored_run_with_group() -> int:
    marker = uuid4().hex
    rows = asyncio.run(
        _run(
            "WITH owner AS (INSERT INTO app_user (home_tenant_id, public_id, username, email, "
            "display_name, account_type, directory_object_guid) SELECT tenant_id, :user_id, "
            ":name, :name, 'Test Person', 'directory', :guid FROM tenant WHERE code = 'platform' "
            "RETURNING user_id, home_tenant_id), version AS (INSERT INTO rule_set_version "
            "(public_id, tenant_id, number, published_at, source, content_sha256) SELECT "
            ":version_id, home_tenant_id, 910001, now(), 'ice-aktarim', repeat('b', 64) FROM owner "
            "RETURNING rule_set_version_id, tenant_id) INSERT INTO review_run (public_id, "
            "tenant_id, owner_user_id, kind, rule_set_version_id, object_count, started_at) "
            "SELECT :run_id, version.tenant_id, owner.user_id, 'object', "
            "version.rule_set_version_id, 1, now() FROM owner, version RETURNING review_run_id",
            user_id=str(uuid4()),
            name=f"{marker}@corp.example.test",
            guid=uuid4(),
            version_id=str(uuid4()),
            run_id=str(uuid4()),
        )
    )
    run_id = int(rows[0][0])
    asyncio.run(
        _run(
            "INSERT INTO review_run_rule_group (review_run_id, rule_group_public_id, name, "
            "position) VALUES (:run, 'grp-a', 'Performans', 0)",
            run=run_id,
        )
    )
    return run_id


def _remove_run(run_id: int) -> None:
    asyncio.run(
        _run(
            "WITH gone AS (DELETE FROM review_run WHERE review_run_id = :run "
            "RETURNING rule_set_version_id) DELETE FROM rule_set_version WHERE "
            "rule_set_version_id IN (SELECT rule_set_version_id FROM gone)",
            run=run_id,
        )
    )


def clear_rule_group_data() -> None:
    """Remove every stored group row on the disposable test database.

    Other integration tests publish grouped versions and start grouped runs; a migration test
    that walks below 202610050001 clears them first, since the downgrade refuses stored group
    data by design (Decision 4).
    """

    for statement in (
        (
            "UPDATE review_rule_result SET rule_group_names = '[]'::jsonb "
            "WHERE rule_group_names <> '[]'::jsonb"
        ),
        "DELETE FROM review_run_rule_group",
        "DELETE FROM review_run_rule",
        "DELETE FROM rule_set_version_rule_group",
        "DELETE FROM rule_set_version_group",
        "DELETE FROM rule_set_draft_rule_group",
        "DELETE FROM rule_set_draft_group",
    ):
        asyncio.run(_run(statement))


def test_the_rule_group_migration_goes_down_and_up_again(
    migrated_database: None,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    run_id: int | None = None
    try:
        assert _tables() == set(_GROUP_TABLES)
        # The later proposal revision is walked down first; its own data must not stop it.
        clear_rule_proposal_data()
        run_id = _stored_run_with_group()

        # Decision 4: a stored group selection must not be dropped silently.
        with pytest.raises(RuntimeError, match="rule group"):
            command.downgrade(config, _BEFORE_GROUPS)
        assert _tables() == set(_GROUP_TABLES)

        _remove_run(run_id)
        run_id = None
        clear_scheduled_review_data()
        clear_rule_group_data()
        command.downgrade(config, _BEFORE_GROUPS)
        assert _tables() == set()
    finally:
        command.upgrade(config, "head")
        if run_id is not None:
            _remove_run(run_id)
    assert _tables() == set(_GROUP_TABLES)
    command.check(config)
