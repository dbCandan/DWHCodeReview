"""Tenant-scoped persistence of the rule-set draft and its immutable published versions."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.rule_set import (
    RulePriorityGroup,
    RuleSetDraft,
    RuleSetDraftGroup,
    RuleSetDraftRule,
    RuleSetDraftRuleGroup,
    RuleSetVersion,
    RuleSetVersionGroup,
    RuleSetVersionRule,
    RuleSetVersionRuleGroup,
)
from app.domain.models.user import User
from app.domain.rule_set import Rule, RuleGroup, RuleGroups


@dataclass(frozen=True, slots=True)
class VersionRow:
    """A published version with its rule counts and the publisher's display name."""

    version: RuleSetVersion
    critical_count: int
    normal_count: int
    published_by_name: str | None


@dataclass(frozen=True, slots=True)
class DraftGroupChanges:
    """Public identifiers of groups a draft save created and removed, for the audit log."""

    created: tuple[str, ...]
    deleted: tuple[str, ...]


def _groups(
    rows: Sequence[RuleSetDraftRule | RuleSetVersionRule],
    definitions: tuple[RuleGroup, ...],
    memberships: Mapping[str, Sequence[str]],
) -> RuleGroups:
    """Rules in their priority groups; ``memberships`` maps a rule code to its group ids."""

    ordered = sorted(rows, key=lambda row: row.position)
    order = {group.public_id: position for position, group in enumerate(definitions)}

    def group_ids(code: str) -> tuple[str, ...]:
        known = (group_id for group_id in memberships.get(code, ()) if group_id in order)
        return tuple(sorted(known, key=order.__getitem__))

    def rules(priority: RulePriorityGroup) -> tuple[Rule, ...]:
        return tuple(
            Rule(
                row.rule_code,
                row.rule_text,
                row.requires_metadata,
                group_ids(row.rule_code),
                row.summary,
            )
            for row in ordered
            if row.priority_group == priority.value
        )

    return RuleGroups(
        critical=rules(RulePriorityGroup.CRITICAL),
        normal=rules(RulePriorityGroup.NORMAL),
        rule_groups=definitions,
    )


class RuleSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_draft(self, tenant_id: int) -> RuleSetDraft | None:
        statement = select(RuleSetDraft).where(
            RuleSetDraft.tenant_id == tenant_id, RuleSetDraft.is_deleted.is_(False)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def lock_draft(self, tenant_id: int, *, actor_user_id: int) -> RuleSetDraft:
        """Return the tenant draft locked for this transaction, creating it on first use."""

        await self.session.execute(
            insert(RuleSetDraft)
            .values(tenant_id=tenant_id, created_by=actor_user_id, updated_by=actor_user_id)
            .on_conflict_do_nothing(index_elements=[RuleSetDraft.tenant_id])
        )
        draft = await self.session.scalar(
            select(RuleSetDraft)
            .where(RuleSetDraft.tenant_id == tenant_id, RuleSetDraft.is_deleted.is_(False))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if draft is None:  # pragma: no cover - the insert above guarantees the row
            raise RuntimeError("rule-set draft is missing after creation")
        return draft

    async def _draft_group_rows(self, draft: RuleSetDraft) -> list[RuleSetDraftGroup]:
        rows = await self.session.scalars(
            select(RuleSetDraftGroup)
            .where(
                RuleSetDraftGroup.rule_set_draft_id == draft.rule_set_draft_id,
                RuleSetDraftGroup.is_deleted.is_(False),
            )
            .order_by(RuleSetDraftGroup.position)
        )
        return list(rows)

    async def draft_rules(self, draft: RuleSetDraft) -> RuleGroups:
        groups = await self._draft_group_rows(draft)
        public_ids = {group.rule_set_draft_group_id: group.public_id for group in groups}
        rows = await self.session.scalars(
            select(RuleSetDraftRule).where(
                RuleSetDraftRule.rule_set_draft_id == draft.rule_set_draft_id,
                RuleSetDraftRule.is_deleted.is_(False),
            )
        )
        links = await self.session.execute(
            select(
                RuleSetDraftRuleGroup.rule_code, RuleSetDraftRuleGroup.rule_set_draft_group_id
            ).where(
                RuleSetDraftRuleGroup.rule_set_draft_id == draft.rule_set_draft_id,
                RuleSetDraftRuleGroup.is_deleted.is_(False),
            )
        )
        memberships: defaultdict[str, list[str]] = defaultdict(list)
        for code, group_key in links.all():
            if group_key in public_ids:
                memberships[code].append(public_ids[group_key])
        return _groups(
            list(rows),
            tuple(RuleGroup(g.public_id, g.name, g.description) for g in groups),
            memberships,
        )

    async def group_ids_taken_elsewhere(self, draft: RuleSetDraft, ids: frozenset[str]) -> bool:
        """True when a submitted group identifier already belongs to another tenant's draft."""

        if not ids:
            return False
        taken = await self.session.scalar(
            select(RuleSetDraftGroup.rule_set_draft_group_id)
            .where(
                RuleSetDraftGroup.public_id.in_(ids),
                RuleSetDraftGroup.rule_set_draft_id != draft.rule_set_draft_id,
            )
            .limit(1)
        )
        return taken is not None

    async def used_codes(self, tenant_id: int) -> frozenset[str]:
        """Every code ever stored for the tenant: live and removed draft rules and versions."""

        draft_codes = (
            select(RuleSetDraftRule.rule_code)
            .join(RuleSetDraft)
            .where(RuleSetDraft.tenant_id == tenant_id)
        )
        version_codes = (
            select(RuleSetVersionRule.rule_code)
            .join(RuleSetVersion)
            .where(RuleSetVersion.tenant_id == tenant_id)
        )
        return frozenset(await self.session.scalars(union(draft_codes, version_codes)))

    async def _replace_draft_groups(
        self,
        draft: RuleSetDraft,
        rules: RuleGroups,
        *,
        actor_user_id: int,
        now: datetime,
    ) -> tuple[dict[str, int], DraftGroupChanges]:
        """Store the named groups; groups left out are soft-deleted (rule-group-selection)."""

        existing = {
            row.public_id: row
            for row in await self.session.scalars(
                select(RuleSetDraftGroup).where(
                    RuleSetDraftGroup.rule_set_draft_id == draft.rule_set_draft_id
                )
            )
        }
        active_before = {key for key, row in existing.items() if not row.is_deleted}
        kept = {group.public_id for group in rules.rule_groups}
        for public_id, row in existing.items():
            if public_id not in kept and not row.is_deleted:
                row.is_deleted = True
                row.deleted_at = now
                row.deleted_by = actor_user_id
                row.updated_by = actor_user_id
        for position, group in enumerate(rules.rule_groups):
            stored = existing.get(group.public_id)
            if stored is None:
                stored = RuleSetDraftGroup(
                    public_id=group.public_id,
                    rule_set_draft_id=draft.rule_set_draft_id,
                    name=group.name,
                    description=group.description,
                    position=position,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
                self.session.add(stored)
                existing[group.public_id] = stored
                continue
            stored.name = group.name
            stored.description = group.description
            stored.position = position
            stored.is_deleted = False
            stored.deleted_at = None
            stored.deleted_by = None
            stored.updated_by = actor_user_id
        await self.session.flush()
        changes = DraftGroupChanges(
            created=tuple(
                g.public_id for g in rules.rule_groups if g.public_id not in active_before
            ),
            deleted=tuple(sorted(active_before - kept)),
        )
        return {key: row.rule_set_draft_group_id for key, row in existing.items()}, changes

    async def replace_draft_rules(
        self,
        draft: RuleSetDraft,
        rules: RuleGroups,
        *,
        actor_user_id: int,
        now: datetime,
    ) -> DraftGroupChanges:
        """Store the draft; rules left out are soft-deleted so their codes stay used."""

        group_keys, changes = await self._replace_draft_groups(
            draft, rules, actor_user_id=actor_user_id, now=now
        )
        existing = {
            row.rule_code: row
            for row in await self.session.scalars(
                select(RuleSetDraftRule).where(
                    RuleSetDraftRule.rule_set_draft_id == draft.rule_set_draft_id
                )
            )
        }
        kept = rules.codes
        for code, row in existing.items():
            if code not in kept and not row.is_deleted:
                row.is_deleted = True
                row.deleted_at = now
                row.deleted_by = actor_user_id
                row.updated_by = actor_user_id
        for group, members in rules.grouped():
            for position, rule in enumerate(members):
                stored = existing.get(rule.code)
                if stored is None:
                    self.session.add(
                        RuleSetDraftRule(
                            rule_set_draft_id=draft.rule_set_draft_id,
                            rule_code=rule.code,
                            priority_group=group.value,
                            position=position,
                            rule_text=rule.text,
                            summary=rule.summary,
                            requires_metadata=rule.requires_metadata,
                            created_by=actor_user_id,
                            updated_by=actor_user_id,
                        )
                    )
                    continue
                stored.priority_group = group.value
                stored.position = position
                stored.rule_text = rule.text
                stored.summary = rule.summary
                stored.requires_metadata = rule.requires_metadata
                stored.updated_by = actor_user_id
        await self.session.flush()
        await self._replace_draft_memberships(
            draft,
            {
                (rule.code, group_keys[group_id])
                for _, members in rules.grouped()
                for rule in members
                for group_id in rule.rule_group_ids
            },
            actor_user_id=actor_user_id,
            now=now,
        )
        return changes

    async def _replace_draft_memberships(
        self,
        draft: RuleSetDraft,
        wanted: set[tuple[str, int]],
        *,
        actor_user_id: int,
        now: datetime,
    ) -> None:
        """Soft-delete memberships left out, revive the ones added back and insert new ones."""

        existing = {
            (row.rule_code, row.rule_set_draft_group_id): row
            for row in await self.session.scalars(
                select(RuleSetDraftRuleGroup).where(
                    RuleSetDraftRuleGroup.rule_set_draft_id == draft.rule_set_draft_id
                )
            )
        }
        for key, row in existing.items():
            if key not in wanted and not row.is_deleted:
                row.is_deleted = True
                row.deleted_at = now
                row.deleted_by = actor_user_id
                row.updated_by = actor_user_id
            elif key in wanted and row.is_deleted:
                row.is_deleted = False
                row.deleted_at = None
                row.deleted_by = None
                row.updated_by = actor_user_id
        for code, group_key in sorted(wanted - existing.keys()):
            self.session.add(
                RuleSetDraftRuleGroup(
                    rule_set_draft_id=draft.rule_set_draft_id,
                    rule_code=code,
                    rule_set_draft_group_id=group_key,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
            )
        await self.session.flush()

    async def latest_version(self, tenant_id: int) -> RuleSetVersion | None:
        statement = (
            select(RuleSetVersion)
            .where(RuleSetVersion.tenant_id == tenant_id, RuleSetVersion.is_deleted.is_(False))
            .order_by(RuleSetVersion.number.desc())
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def version_by_number(self, tenant_id: int, number: int) -> RuleSetVersion | None:
        statement = select(RuleSetVersion).where(
            RuleSetVersion.tenant_id == tenant_id,
            RuleSetVersion.number == number,
            RuleSetVersion.is_deleted.is_(False),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def version_rules(self, version: RuleSetVersion) -> RuleGroups:
        groups = await self.session.scalars(
            select(RuleSetVersionGroup)
            .where(
                RuleSetVersionGroup.rule_set_version_id == version.rule_set_version_id,
                RuleSetVersionGroup.is_deleted.is_(False),
            )
            .order_by(RuleSetVersionGroup.position)
        )
        rows = await self.session.scalars(
            select(RuleSetVersionRule).where(
                RuleSetVersionRule.rule_set_version_id == version.rule_set_version_id,
                RuleSetVersionRule.is_deleted.is_(False),
            )
        )
        links = await self.session.execute(
            select(
                RuleSetVersionRuleGroup.rule_code, RuleSetVersionRuleGroup.rule_group_public_id
            ).where(
                RuleSetVersionRuleGroup.rule_set_version_id == version.rule_set_version_id,
                RuleSetVersionRuleGroup.is_deleted.is_(False),
            )
        )
        memberships: defaultdict[str, list[str]] = defaultdict(list)
        for code, group_id in links.all():
            memberships[code].append(group_id)
        return _groups(
            list(rows),
            tuple(RuleGroup(g.rule_group_public_id, g.name, g.description) for g in groups),
            memberships,
        )

    async def version_row(self, version: RuleSetVersion) -> VersionRow:
        rows, _ = await self._version_rows(
            version.tenant_id, number=version.number, offset=0, limit=1
        )
        return rows[0]

    async def list_versions(
        self, tenant_id: int, *, offset: int, limit: int
    ) -> tuple[list[VersionRow], int]:
        return await self._version_rows(tenant_id, number=None, offset=offset, limit=limit)

    async def _version_rows(
        self, tenant_id: int, *, number: int | None, offset: int, limit: int
    ) -> tuple[list[VersionRow], int]:
        counts = (
            select(
                RuleSetVersionRule.rule_set_version_id,
                func.count()
                .filter(RuleSetVersionRule.priority_group == RulePriorityGroup.CRITICAL.value)
                .label("critical_count"),
                func.count()
                .filter(RuleSetVersionRule.priority_group == RulePriorityGroup.NORMAL.value)
                .label("normal_count"),
            )
            .where(RuleSetVersionRule.is_deleted.is_(False))
            .group_by(RuleSetVersionRule.rule_set_version_id)
            .subquery()
        )
        filters = [RuleSetVersion.tenant_id == tenant_id, RuleSetVersion.is_deleted.is_(False)]
        if number is not None:
            filters.append(RuleSetVersion.number == number)
        total = await self.session.scalar(
            select(func.count()).select_from(RuleSetVersion).where(*filters)
        )
        result = await self.session.execute(
            select(
                RuleSetVersion,
                func.coalesce(counts.c.critical_count, 0),
                func.coalesce(counts.c.normal_count, 0),
                User.display_name,
            )
            .outerjoin(counts, counts.c.rule_set_version_id == RuleSetVersion.rule_set_version_id)
            .outerjoin(User, User.user_id == RuleSetVersion.published_by_user_id)
            .where(*filters)
            .order_by(RuleSetVersion.number.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [
            VersionRow(version, int(critical), int(normal), name)
            for version, critical, normal, name in result.all()
        ]
        return rows, int(total or 0)

    async def add_version(
        self,
        *,
        tenant_id: int,
        number: int,
        rules: RuleGroups,
        digest: str,
        source: str,
        published_at: datetime,
        publisher_user_id: int | None,
    ) -> RuleSetVersion:
        version = RuleSetVersion(
            tenant_id=tenant_id,
            number=number,
            published_at=published_at,
            published_by_user_id=publisher_user_id,
            source=source,
            content_sha256=digest,
            created_by=publisher_user_id,
            updated_by=publisher_user_id,
        )
        self.session.add(version)
        await self.session.flush()
        for position, rule_group in enumerate(rules.rule_groups):
            self.session.add(
                RuleSetVersionGroup(
                    rule_set_version_id=version.rule_set_version_id,
                    rule_group_public_id=rule_group.public_id,
                    name=rule_group.name,
                    description=rule_group.description,
                    position=position,
                    created_by=publisher_user_id,
                    updated_by=publisher_user_id,
                )
            )
        await self.session.flush()
        for group, members in rules.grouped():
            for position, rule in enumerate(members):
                self.session.add(
                    RuleSetVersionRule(
                        rule_set_version_id=version.rule_set_version_id,
                        rule_code=rule.code,
                        priority_group=group.value,
                        position=position,
                        rule_text=rule.text,
                        summary=rule.summary,
                        requires_metadata=rule.requires_metadata,
                        created_by=publisher_user_id,
                        updated_by=publisher_user_id,
                    )
                )
        await self.session.flush()
        for _, members in rules.grouped():
            for rule in members:
                for group_id in rule.rule_group_ids:
                    self.session.add(
                        RuleSetVersionRuleGroup(
                            rule_set_version_id=version.rule_set_version_id,
                            rule_code=rule.code,
                            rule_group_public_id=group_id,
                            created_by=publisher_user_id,
                            updated_by=publisher_user_id,
                        )
                    )
        await self.session.flush()
        return version
