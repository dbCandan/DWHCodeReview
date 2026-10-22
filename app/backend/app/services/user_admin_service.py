"""Super-admin user list, role assignment and activation (application-foundation 001 Req. 5).

Every change re-reads the acting super admin from the database (Requirement 12), writes the
append-only history row in the same transaction and ends the target's refresh sessions.
"""

import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.logging import log_event
from app.core.request_context import RequestContext
from app.domain.models.refresh_session import RefreshSessionEndReason
from app.domain.models.role import SUPER_ADMIN_ROLE, application_role_of
from app.domain.models.tenant import Tenant
from app.domain.models.user import User
from app.domain.models.user_change import UserChange, UserChangeField
from app.infrastructure.repositories.refresh_session_repository import (
    RefreshSessionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.schemas.admin.users import UserPage, UserSummary
from app.schemas.auth.response import AccountTypeValue, ApplicationRoleValue
from app.services.request_scope import acting_user, active_tenant

logger = logging.getLogger("app.admin")

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def _forbidden() -> ApplicationError:
    return ApplicationError(status.HTTP_403_FORBIDDEN, "forbidden", "Bu işlem için yetkiniz yok.")


def _user_not_found() -> ApplicationError:
    return ApplicationError(status.HTTP_404_NOT_FOUND, "user_not_found", "Kullanıcı bulunamadı.")


def _super_admin_protected() -> ApplicationError:
    return ApplicationError(
        status.HTTP_409_CONFLICT,
        "super_admin_protected",
        "Süper yönetici hesabının rolü ve durumu bu ekrandan değiştirilemez.",
    )


def _own_account() -> ApplicationError:
    return ApplicationError(
        status.HTTP_409_CONFLICT,
        "own_account",
        "Kendi hesabınızın durumunu değiştiremezsiniz.",
    )


class UserAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = RefreshSessionRepository(session)

    async def list_users(
        self, context: RequestContext, *, page: int, size: int, query: str | None
    ) -> UserPage:
        tenant = await active_tenant(self.users, context)
        rows, total = await self.users.list_users(
            tenant_id=tenant.tenant_id,
            query=query.strip() if query and query.strip() else None,
            offset=(page - 1) * size,
            limit=size,
        )
        return UserPage(
            items=[_summary(row.user, row.roles) for row in rows],
            page=page,
            size=size,
            total=total,
        )

    async def set_active(
        self, context: RequestContext, target_public_id: UUID, active: bool
    ) -> bool:
        tenant = await active_tenant(self.users, context)
        actor = await self._acting_super_admin(context)
        target = await self._target(target_public_id, tenant)
        if target.user_id == actor.user_id:
            raise _own_account()
        if SUPER_ADMIN_ROLE in await self.users.role_codes(target):
            raise _super_admin_protected()
        if target.is_active == active:
            return active
        now = datetime.now(UTC)
        old = target.is_active
        target.is_active = active
        target.updated_by = actor.user_id
        await self._record_change(
            tenant,
            actor,
            target,
            UserChangeField.ACTIVE,
            old=str(old).lower(),
            new=str(active).lower(),
            now=now,
        )
        log_event(
            logger,
            "admin.user.active_changed",
            actor_public_id=actor.public_id,
            target_public_id=target.public_id,
            old_value=old,
            new_value=active,
        )
        return active

    async def _record_change(
        self,
        tenant: Tenant,
        actor: User,
        target: User,
        field: UserChangeField,
        *,
        old: str | None,
        new: str,
        now: datetime,
    ) -> None:
        await self.users.add_change(
            UserChange(
                tenant_id=tenant.tenant_id,
                actor_user_id=actor.user_id,
                target_user_id=target.user_id,
                changed_field=field.value,
                old_value=old,
                new_value=new,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
        )
        # rules/58: a changed authorization level ends every refresh session of the user.
        await self.sessions.end_user_sessions(
            target.user_id,
            reason=RefreshSessionEndReason.AUTHORIZATION_CHANGED.value,
            now=now,
        )

    async def _acting_super_admin(self, context: RequestContext) -> User:
        actor = await acting_user(self.users, context)
        if SUPER_ADMIN_ROLE not in await self.users.role_codes(actor):
            raise _forbidden()
        return actor

    async def _target(self, public_id: UUID, tenant: Tenant) -> User:
        target = await self.users.get_in_tenant_for_update(public_id, tenant.tenant_id)
        if target is None:
            raise _user_not_found()
        return target


def _summary(user: User, roles: tuple[str, ...]) -> UserSummary:
    return UserSummary(
        public_id=UUID(user.public_id),
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        account_type=cast(AccountTypeValue, user.account_type),
        role=cast(ApplicationRoleValue | None, application_role_of(roles)),
        is_super_admin=SUPER_ADMIN_ROLE in roles,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )
