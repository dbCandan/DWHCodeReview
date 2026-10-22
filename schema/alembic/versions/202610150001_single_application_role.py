"""Retire the rule manager role: every user holds the single application role.

Data-only. Each active 'kural-yoneticisi' assignment becomes an 'inceleyici' assignment in the
same tenant (a soft-deleted one is revived), the old assignment and the 'kural-yoneticisi' role
are soft-deleted (rules/41). Rule management, connections and LLM call summaries are the super
admin's from now on. Downgrade revives the role definition only: which users held it is not
recoverable from the retired rows' meaning, so they stay 'inceleyici' and a super admin assigns
the role again if the previous version is restored.

Spec: application-foundation/PRDs/001-directory-login 1.3.0 (Decision 14).

Revision ID: 202610150001
Revises: 202610140001
Create Date: 2026-10-15 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610150001"
down_revision: str | None = "202610140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO app_user_role (user_id, role_id, tenant_id) "
            "SELECT held.user_id, reviewer.role_id, held.tenant_id "
            "FROM app_user_role AS held "
            "JOIN app_role AS manager ON manager.role_id = held.role_id "
            "CROSS JOIN app_role AS reviewer "
            "WHERE manager.code = 'kural-yoneticisi' AND reviewer.code = 'inceleyici' "
            "AND held.is_deleted = false "
            "ON CONFLICT (user_id, role_id, tenant_id) DO UPDATE "
            "SET is_deleted = false, deleted_at = NULL, deleted_by = NULL, updated_at = now()"
        )
    )
    op.execute(
        sa.text(
            "UPDATE app_user_role SET is_deleted = true, deleted_at = now(), updated_at = now() "
            "WHERE is_deleted = false AND role_id IN "
            "(SELECT role_id FROM app_role WHERE code = 'kural-yoneticisi')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE app_role SET is_deleted = true, deleted_at = now(), updated_at = now() "
            "WHERE code = 'kural-yoneticisi' AND is_deleted = false"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE app_role SET is_deleted = false, deleted_at = NULL, deleted_by = NULL, "
            "updated_at = now() WHERE code = 'kural-yoneticisi'"
        )
    )
