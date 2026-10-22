"""Authentication responses containing public identifiers only."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AccountTypeValue = Literal["local", "directory"]
ApplicationRoleValue = Literal["inceleyici"]


class AuthenticatedUser(BaseModel):
    public_id: UUID
    username: str
    display_name: str
    tenant_id: UUID
    account_type: AccountTypeValue
    # The single application role; empty for the super admin, who holds no application role.
    role: ApplicationRoleValue | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    is_super_admin: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds.")
    user: AuthenticatedUser
