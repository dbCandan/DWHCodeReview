"""Persistence of review runs, their objects, rule results, findings and false-positive marks.

sql-review/PRDs/003-object-review Requirement 16, 004-script-review Requirement 9 and
005-review-history-export Requirement 1-6. Every read is scoped to one tenant. A run is created
with its selection rows; results and the reviewed SQL text are written only when the run
completes, in the caller's single transaction. Deletion is physical: the foreign keys cascade to
objects, results and findings, and empty the run link of LLM call summaries.

A run has no object limit, so no read loads a whole run at once unless the caller asks for it
chunk by chunk: results are read by object position range and joined to their run, never through
a list of identifiers, which a single PostgreSQL statement limits to 32,767 parameters.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.domain.models.mixins import new_public_id
from app.domain.models.review import (
    ReviewFinding,
    ReviewRuleResult,
    ReviewRun,
    ReviewRunObject,
    ReviewRunRule,
    ReviewRunRuleGroup,
    ReviewRunStatus,
)
from app.domain.models.rule_set import RuleSetVersion
from app.domain.models.user import User
from app.domain.review import ObjectOutcome
from app.domain.rule_set import RuleGroup

# Objects whose outcomes are written, flushed and released together when a run completes.
_STORE_CHUNK_OBJECTS = 100
# pg_try_advisory_xact_lock key of the history retention job: one running copy deletes at a time.
RETENTION_LOCK_KEY = 0x6477_6863_7276_6801  # "dwhcrvh" + 1


@dataclass(frozen=True, slots=True)
class NewRunObject:
    database: str | None
    schema: str
    name: str
    type_code: str
    object_type: str


@dataclass(frozen=True, slots=True)
class RunRow:
    run: ReviewRun
    owner_public_id: str
    owner_display_name: str
    rule_version: int
    finding_count: int


@dataclass(frozen=True, slots=True)
class StoredResult:
    """The public identifiers given to one object's rule results and findings."""

    rule_result_ids: list[str]
    finding_ids: list[str]


@dataclass(frozen=True, slots=True)
class RunResults:
    objects: list[ReviewRunObject]
    rule_results: dict[int, list[ReviewRuleResult]]
    findings: dict[int, list[ReviewFinding]]


@dataclass(frozen=True, slots=True)
class RunObjectName:
    database: str | None
    schema: str
    name: str
    type_code: str


@dataclass(frozen=True, slots=True)
class RunHeading:
    """What the title of a run needs: its databases in selection order and its first objects."""

    databases: list[str]
    first_objects: list[RunObjectName]


# Objects named in the subtitle of a run.
HEADING_OBJECTS = 4


def _finding_count() -> Select[tuple[int]]:
    return (
        select(func.count(ReviewFinding.review_finding_id))
        .join(
            ReviewRuleResult,
            ReviewRuleResult.review_rule_result_id == ReviewFinding.review_rule_result_id,
        )
        .join(
            ReviewRunObject,
            ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
        )
        .where(
            ReviewRunObject.review_run_id == ReviewRun.review_run_id,
            ReviewFinding.is_deleted.is_(False),
        )
    )


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(
        self,
        *,
        tenant_id: int,
        owner_user_id: int,
        kind: str,
        label: str | None,
        rule_set_version_id: int,
        started_at: datetime,
        objects: Sequence[NewRunObject],
        selected_groups: Sequence[tuple[int, RuleGroup]] = (),
        selected_rule_codes: Sequence[str] = (),
        scheduled_review_id: int | None = None,
    ) -> ReviewRun:
        """Insert the running run, its objects and its rule selection (empty = every rule).

        ``selected_groups`` pairs each selected group with its position in the pinned version;
        ``selected_rule_codes`` are the single rules in version order
        (sql-review/PRDs/007-rule-group-selection Requirement 5).
        """

        run = ReviewRun(
            public_id=new_public_id(),
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            kind=kind,
            label=label,
            rule_set_version_id=rule_set_version_id,
            object_count=len(objects),
            status=ReviewRunStatus.RUNNING.value,
            started_at=started_at,
            scheduled_review_id=scheduled_review_id,
            created_by=owner_user_id,
            updated_by=owner_user_id,
        )
        self.session.add(run)
        await self.session.flush()
        self.session.add_all(
            ReviewRunObject(
                review_run_id=run.review_run_id,
                position=position,
                database_name=item.database,
                schema_name=item.schema,
                object_name=item.name,
                type_code=item.type_code,
                object_type=item.object_type,
                created_by=owner_user_id,
                updated_by=owner_user_id,
            )
            for position, item in enumerate(objects)
        )
        self.session.add_all(
            ReviewRunRuleGroup(
                review_run_id=run.review_run_id,
                rule_group_public_id=group.public_id,
                name=group.name,
                position=position,
                created_by=owner_user_id,
                updated_by=owner_user_id,
            )
            for position, group in selected_groups
        )
        self.session.add_all(
            ReviewRunRule(
                review_run_id=run.review_run_id,
                rule_code=code,
                position=position,
                created_by=owner_user_id,
                updated_by=owner_user_id,
            )
            for position, code in enumerate(selected_rule_codes)
        )
        await self.session.flush()
        return run

    async def complete_run(
        self,
        run_id: int,
        *,
        owner_user_id: int,
        finished_at: datetime,
        outcomes: Sequence[ObjectOutcome],
        collect_identifiers: bool = True,
        rule_group_names: Mapping[str, Sequence[str]] | None = None,
    ) -> list[StoredResult] | None:
        """Write every outcome and mark the run completed; None when it no longer runs.

        The outcomes are written chunk by chunk in the caller's transaction and each chunk leaves
        the session again, so a run of thousands of objects never holds all its rows as ORM
        objects. Without ``collect_identifiers`` the returned list is empty.
        """

        run = await self.session.scalar(
            select(ReviewRun).where(ReviewRun.review_run_id == run_id).with_for_update()
        )
        if run is None or run.status != ReviewRunStatus.RUNNING.value:
            return None
        stored: list[StoredResult] = []
        for start in range(0, len(outcomes), _STORE_CHUNK_OBJECTS):
            chunk = outcomes[start : start + _STORE_CHUNK_OBJECTS]
            identifiers = await self._store_outcomes(
                run_id, owner_user_id, chunk, rule_group_names or {}
            )
            if collect_identifiers:
                stored.extend(identifiers)
        run.status = ReviewRunStatus.COMPLETED.value
        run.finished_at = finished_at
        run.updated_by = owner_user_id
        await self.session.flush()
        return stored

    async def _store_outcomes(
        self,
        run_id: int,
        owner_user_id: int,
        outcomes: Sequence[ObjectOutcome],
        rule_group_names: Mapping[str, Sequence[str]],
    ) -> list[StoredResult]:
        objects = {
            item.position: item
            for item in await self.session.scalars(
                select(ReviewRunObject).where(
                    ReviewRunObject.review_run_id == run_id,
                    ReviewRunObject.position.in_([outcome.position for outcome in outcomes]),
                )
            )
        }
        stored: list[StoredResult] = []
        pending: list[tuple[ReviewRuleResult, list[ReviewFinding]]] = []
        for outcome in outcomes:
            row = objects[outcome.position]
            row.source_sql = outcome.source_sql
            row.error_code = outcome.error_code
            row.error_message = outcome.error_message
            row.parse_warning = outcome.warning
            row.updated_by = owner_user_id
            result_ids: list[str] = []
            finding_ids: list[str] = []
            for position, check in enumerate(outcome.checks):
                result = ReviewRuleResult(
                    public_id=new_public_id(),
                    review_run_object_id=row.review_run_object_id,
                    position=position,
                    rule_code=check.rule_code,
                    priority_group=check.tier.value,
                    rule_group_names=list(rule_group_names.get(check.rule_code, ())),
                    status=check.status.value,
                    severity=None if check.severity is None else check.severity.value,
                    decision_basis=check.decision_basis or None,
                    explanation=check.description or None,
                    line_reference=check.line_reference or None,
                    code_snippet=check.code_snippet or None,
                    created_by=owner_user_id,
                    updated_by=owner_user_id,
                )
                findings = [
                    ReviewFinding(
                        public_id=new_public_id(),
                        position=index,
                        rule_code=finding.rule_code,
                        severity=finding.severity.value,
                        description=finding.description,
                        line_reference=finding.line_reference or None,
                        code_snippet=finding.code_snippet or None,
                        created_by=owner_user_id,
                        updated_by=owner_user_id,
                    )
                    for index, finding in enumerate(
                        item for item in outcome.findings if item.rule_code == check.rule_code
                    )
                ]
                pending.append((result, findings))
                result_ids.append(result.public_id)
                finding_ids.extend(finding.public_id for finding in findings)
            stored.append(StoredResult(result_ids, finding_ids))
        self.session.add_all(result for result, _ in pending)
        await self.session.flush()
        for result, findings in pending:
            for finding in findings:
                finding.review_rule_result_id = result.review_rule_result_id
            self.session.add_all(findings)
        await self.session.flush()
        for row in objects.values():
            self.session.expunge(row)
        for result, findings in pending:
            self.session.expunge(result)
            for finding in findings:
                self.session.expunge(finding)
        return stored

    async def finish_run(
        self,
        run_id: int,
        *,
        status: ReviewRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """End a running run without results; False when it had already ended."""

        result = await self.session.execute(
            update(ReviewRun)
            .where(
                ReviewRun.review_run_id == run_id,
                ReviewRun.status == ReviewRunStatus.RUNNING.value,
            )
            .values(
                status=status.value,
                finished_at=finished_at,
                error_code=error_code,
                error_message=error_message,
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def interrupt_running_runs(
        self, *, finished_at: datetime, error_code: str, error_message: str
    ) -> int:
        result = await self.session.execute(
            update(ReviewRun)
            .where(ReviewRun.status == ReviewRunStatus.RUNNING.value)
            .values(
                status=ReviewRunStatus.INTERRUPTED.value,
                finished_at=finished_at,
                error_code=error_code,
                error_message=error_message,
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def _runs(self, tenant_id: int) -> Select[tuple[ReviewRun, str, str, int, int]]:
        return (
            select(
                ReviewRun,
                User.public_id,
                User.display_name,
                RuleSetVersion.number,
                _finding_count().scalar_subquery(),
            )
            .join(User, User.user_id == ReviewRun.owner_user_id)
            .join(
                RuleSetVersion,
                RuleSetVersion.rule_set_version_id == ReviewRun.rule_set_version_id,
            )
            .where(ReviewRun.tenant_id == tenant_id, ReviewRun.is_deleted.is_(False))
        )

    async def list_runs(
        self, tenant_id: int, *, owner_user_id: int | None, offset: int, limit: int
    ) -> tuple[list[RunRow], int]:
        conditions = [ReviewRun.tenant_id == tenant_id, ReviewRun.is_deleted.is_(False)]
        query = self._runs(tenant_id)
        if owner_user_id is not None:
            conditions.append(ReviewRun.owner_user_id == owner_user_id)
            query = query.where(ReviewRun.owner_user_id == owner_user_id)
        total = await self.session.scalar(
            select(func.count(ReviewRun.review_run_id)).where(*conditions)
        )
        rows = await self.session.execute(
            query.order_by(ReviewRun.started_at.desc(), ReviewRun.review_run_id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [RunRow(*row) for row in rows.all()], int(total or 0)

    async def selected_groups_of_run(self, run_id: int) -> list[RuleGroup]:
        """The named groups a run was started with, in version order (rule-group-selection)."""

        rows = await self.session.scalars(
            select(ReviewRunRuleGroup)
            .where(
                ReviewRunRuleGroup.review_run_id == run_id,
                ReviewRunRuleGroup.is_deleted.is_(False),
            )
            .order_by(ReviewRunRuleGroup.position)
        )
        return [RuleGroup(row.rule_group_public_id, row.name) for row in rows]

    async def selected_rule_codes_of_run(self, run_id: int) -> list[str]:
        """The single rules a run was started with, in version order (rule-group-selection)."""

        rows = await self.session.scalars(
            select(ReviewRunRule.rule_code)
            .where(ReviewRunRule.review_run_id == run_id, ReviewRunRule.is_deleted.is_(False))
            .order_by(ReviewRunRule.position)
        )
        return list(rows)

    async def get_run(self, tenant_id: int, public_id: str) -> RunRow | None:
        row = (
            await self.session.execute(
                self._runs(tenant_id).where(ReviewRun.public_id == public_id)
            )
        ).first()
        return None if row is None else RunRow(*row)

    async def headings_of_runs(self, run_ids: Sequence[int]) -> dict[int, RunHeading]:
        """Titles of the listed runs without reading a row per object or any SQL text."""

        headings = {run_id: RunHeading([], []) for run_id in run_ids}
        if not run_ids:
            return headings
        first_position = func.min(ReviewRunObject.position)
        for run_id, database in await self.session.execute(
            select(ReviewRunObject.review_run_id, ReviewRunObject.database_name)
            .where(
                ReviewRunObject.review_run_id.in_(run_ids),
                ReviewRunObject.is_deleted.is_(False),
            )
            .group_by(ReviewRunObject.review_run_id, ReviewRunObject.database_name)
            .order_by(ReviewRunObject.review_run_id, first_position)
        ):
            headings[run_id].databases.append(database or "")
        for run_id, database, schema, name, type_code in await self.session.execute(
            select(
                ReviewRunObject.review_run_id,
                ReviewRunObject.database_name,
                ReviewRunObject.schema_name,
                ReviewRunObject.object_name,
                ReviewRunObject.type_code,
            )
            .where(
                ReviewRunObject.review_run_id.in_(run_ids),
                ReviewRunObject.position < HEADING_OBJECTS,
                ReviewRunObject.is_deleted.is_(False),
            )
            .order_by(ReviewRunObject.review_run_id, ReviewRunObject.position)
        ):
            headings[run_id].first_objects.append(RunObjectName(database, schema, name, type_code))
        return headings

    async def results_of_run(
        self, run_id: int, *, offset: int, limit: int, with_sql: bool = False
    ) -> RunResults:
        """The objects at positions ``offset`` to ``offset + limit - 1`` with their results.

        The reviewed SQL text is read only for ``with_sql`` (the SQL export).
        """

        in_range = (
            ReviewRunObject.review_run_id == run_id,
            ReviewRunObject.position >= offset,
            ReviewRunObject.position < offset + limit,
            ReviewRunObject.is_deleted.is_(False),
        )
        query = select(ReviewRunObject).where(*in_range).order_by(ReviewRunObject.position)
        if not with_sql:
            query = query.options(defer(ReviewRunObject.source_sql, raiseload=True))
        objects = list(await self.session.scalars(query))
        rule_results: dict[int, list[ReviewRuleResult]] = {
            item.review_run_object_id: [] for item in objects
        }
        findings: dict[int, list[ReviewFinding]] = {}
        if not objects:
            return RunResults(objects, rule_results, findings)
        for result in await self.session.scalars(
            select(ReviewRuleResult)
            .join(
                ReviewRunObject,
                ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
            )
            .where(*in_range, ReviewRuleResult.is_deleted.is_(False))
            .order_by(ReviewRuleResult.review_run_object_id, ReviewRuleResult.position)
        ):
            rule_results[result.review_run_object_id].append(result)
            findings[result.review_rule_result_id] = []
        for finding in await self.session.scalars(
            select(ReviewFinding)
            .join(
                ReviewRuleResult,
                ReviewRuleResult.review_rule_result_id == ReviewFinding.review_rule_result_id,
            )
            .join(
                ReviewRunObject,
                ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
            )
            .where(
                *in_range,
                ReviewRuleResult.is_deleted.is_(False),
                ReviewFinding.is_deleted.is_(False),
            )
            .order_by(ReviewFinding.review_rule_result_id, ReviewFinding.position)
        ):
            findings[finding.review_rule_result_id].append(finding)
        return RunResults(objects, rule_results, findings)

    def release(self, results: RunResults) -> None:
        """Let the rows of one read chunk leave the session before the next chunk is read."""

        for item in results.objects:
            self.session.expunge(item)
        for rule_results in results.rule_results.values():
            for result in rule_results:
                self.session.expunge(result)
        for run_findings in results.findings.values():
            for finding in run_findings:
                self.session.expunge(finding)

    async def rule_result_of_run(
        self, run_id: int, public_id: str
    ) -> tuple[ReviewRuleResult, int] | None:
        """The rule result with its finding count, locked for a false-positive change."""

        result = await self.session.scalar(
            select(ReviewRuleResult)
            .join(
                ReviewRunObject,
                ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
            )
            .where(
                ReviewRunObject.review_run_id == run_id,
                ReviewRuleResult.public_id == public_id,
                ReviewRuleResult.is_deleted.is_(False),
            )
            .with_for_update(of=ReviewRuleResult)
        )
        if result is None:
            return None
        count = await self.session.scalar(
            select(func.count(ReviewFinding.review_finding_id)).where(
                ReviewFinding.review_rule_result_id == result.review_rule_result_id,
                ReviewFinding.is_deleted.is_(False),
            )
        )
        return result, int(count or 0)

    async def finding_of_run(self, run_id: int, public_id: str) -> ReviewFinding | None:
        finding: ReviewFinding | None = await self.session.scalar(
            select(ReviewFinding)
            .join(
                ReviewRuleResult,
                ReviewRuleResult.review_rule_result_id == ReviewFinding.review_rule_result_id,
            )
            .join(
                ReviewRunObject,
                ReviewRunObject.review_run_object_id == ReviewRuleResult.review_run_object_id,
            )
            .where(
                ReviewRunObject.review_run_id == run_id,
                ReviewFinding.public_id == public_id,
                ReviewFinding.is_deleted.is_(False),
            )
            .with_for_update(of=ReviewFinding)
        )
        return finding

    async def lock_run(self, run_id: int) -> ReviewRun | None:
        run: ReviewRun | None = await self.session.scalar(
            select(ReviewRun).where(ReviewRun.review_run_id == run_id).with_for_update()
        )
        return run

    async def delete_run(self, run_id: int) -> None:
        await self.session.execute(delete(ReviewRun).where(ReviewRun.review_run_id == run_id))

    async def delete_finished_runs_of_owner(self, tenant_id: int, owner_user_id: int) -> int:
        result = await self.session.execute(
            delete(ReviewRun).where(
                ReviewRun.tenant_id == tenant_id,
                ReviewRun.owner_user_id == owner_user_id,
                ReviewRun.status != ReviewRunStatus.RUNNING.value,
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def try_retention_lock(self) -> bool:
        """Transaction-scoped advisory lock; False when another copy is already deleting."""

        return bool(
            await self.session.scalar(select(func.pg_try_advisory_xact_lock(RETENTION_LOCK_KEY)))
        )

    async def delete_finished_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(ReviewRun).where(
                ReviewRun.finished_at.is_not(None), ReviewRun.finished_at < cutoff
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
