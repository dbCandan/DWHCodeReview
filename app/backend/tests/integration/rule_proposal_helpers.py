"""HTTP helpers of the rule proposal and publish request tests (sql-review 009-rule-proposals)."""

from typing import Any
from uuid import uuid4

from tests.integration.conftest import AuthHarness, RoleSession, RoleSessions


def rule_item(code: str, text_value: str) -> dict[str, Any]:
    return {"id": code, "text": text_value, "summary": "", "requires_metadata": False}


class Proposals:
    """HTTP helpers of one test; leaves the shared draft ungrouped when it ends."""

    def __init__(self, auth: AuthHarness, sessions: RoleSessions) -> None:
        self.auth = auth
        self.sessions = sessions

    async def call(
        self, method: str, path: str, session: RoleSession, body: Any = None, **params: Any
    ) -> Any:
        return await self.auth.client.request(
            method,
            f"{self.auth.prefix}{path}",
            json=body,
            params=params or None,
            headers=session.headers,
        )

    async def workspace(self) -> dict[str, Any]:
        manager = await self.sessions.rule_manager()
        response = await self.call("GET", "/rule-set", manager)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def publish_fresh(self, groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Publish three fresh rules (two critical, one normal) as the latest version."""

        manager = await self.sessions.rule_manager()
        admin = await self.sessions.super_admin()
        current = await self.workspace()
        number = int(current["next_rule_id"].removeprefix("Kural"))
        codes = [f"Kural{number + offset:02d}" for offset in range(3)]
        group_ids = [group["id"] for group in groups or []]
        saved = await self.call(
            "PUT",
            "/rule-set/draft",
            manager,
            {
                "base_revision": current["revision"],
                "critical": [
                    {**rule_item(codes[0], "Kritik bir"), "rule_group_ids": group_ids[:1]},
                    rule_item(codes[1], "Kritik iki"),
                ],
                "normal": [rule_item(codes[2], "Normal üç")],
                "groups": groups or [],
            },
        )
        assert saved.status_code == 200, saved.text
        published = await self.call(
            "POST", "/rule-set/versions", admin, {"base_revision": saved.json()["revision"]}
        )
        assert published.status_code == 201, published.text
        version: dict[str, Any] = published.json()
        return version

    async def ungroup(self) -> None:
        manager = await self.sessions.rule_manager()
        current = await self.workspace()
        restored = await self.call(
            "PUT",
            "/rule-set/draft",
            manager,
            {
                "base_revision": current["revision"],
                **{
                    priority: [{**rule, "rule_group_ids": []} for rule in current[priority]]
                    for priority in ("critical", "normal")
                },
                "groups": [],
            },
        )
        assert restored.status_code == 200, restored.text

    async def proposer(self) -> RoleSession:
        """A reviewer the super admin gave the proposal permission."""

        reviewer = await self.sessions.reviewer()
        admin = await self.sessions.super_admin()
        granted = await self.call("PUT", f"/rule-proposers/{reviewer.public_id}", admin)
        assert granted.status_code == 204, granted.text
        return reviewer

    async def propose_rule(self, session: RoleSession, **changes: Any) -> Any:
        body = {
            "kind": "rule",
            "summary": "Geçici tablolar silinmelidir.",
            "text": f"Geçici tablolar işlem sonunda DROP edilmelidir. {uuid4().hex}",
            "priority": "normal",
            "requires_metadata": False,
            "rule_group_ids": [],
            **changes,
        }
        return await self.call("POST", "/rule-proposals", session, body)

    async def propose_group(self, session: RoleSession, name: str, codes: list[str]) -> Any:
        return await self.call(
            "POST",
            "/rule-proposals",
            session,
            {"kind": "group", "group_name": name, "rule_codes": codes},
        )
