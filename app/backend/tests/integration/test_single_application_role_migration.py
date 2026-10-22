"""Revision 202610150001: the rule manager role retires (directory-login 1.3.0 Decision 14).

Against the migrated database: going down revives the role definition; a user who held it then
holds the single application role after going up again, the old assignment and the role are
soft-deleted, and a user who already held both keeps exactly one active assignment.
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

pytestmark = pytest.mark.integration

_ACTIVE_ROLES = (
    "SELECT r.code FROM app_user_role ur JOIN app_role r ON r.role_id = ur.role_id "
    "WHERE ur.user_id = :user AND ur.is_deleted = false ORDER BY r.code"
)


async def _run(statement: str, **params: Any) -> list[Any]:
    probe = create_async_engine(get_settings().database_url)
    try:
        async with probe.begin() as connection:
            result = await connection.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await probe.dispose()


def _user() -> int:
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


def _assign(user: int, code: str) -> None:
    asyncio.run(
        _run(
            "INSERT INTO app_user_role (user_id, role_id, tenant_id) SELECT :user, r.role_id, "
            "t.tenant_id FROM app_role r, tenant t WHERE r.code = :code AND t.code = 'platform'",
            user=user,
            code=code,
        )
    )


def _roles(user: int) -> list[str]:
    return [str(row[0]) for row in asyncio.run(_run(_ACTIVE_ROLES, user=user))]


def _role_retired() -> bool:
    rows = asyncio.run(_run("SELECT is_deleted FROM app_role WHERE code = 'kural-yoneticisi'"))
    return bool(rows[0][0])


def test_rule_managers_become_users_and_the_role_retires(
    migrated_database: None,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    manager, both = _user(), _user()
    try:
        assert _role_retired()
        command.downgrade(config, "202610140001")
        assert not _role_retired()
        _assign(manager, "kural-yoneticisi")
        _assign(both, "kural-yoneticisi")
        _assign(both, "inceleyici")
        assert _roles(manager) == ["kural-yoneticisi"]
    finally:
        command.upgrade(config, "head")
    assert _role_retired()
    assert _roles(manager) == ["inceleyici"]
    assert _roles(both) == ["inceleyici"]
    command.check(config)
