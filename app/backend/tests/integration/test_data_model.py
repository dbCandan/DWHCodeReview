"""Migrated-schema contract of the wave-one data model against real PostgreSQL.

Specs: application-foundation/PRDs/001-directory-login "Veri ve geçiş" and the data sections of
sql-review/PRDs/001-rule-management, 002-sql-server-connection, 003-object-review,
004-script-review, 005-review-history-export, 006-llm-connection, 007-rule-group-selection and
008-scheduled-review-email; rules 41 (mandatory block),
42 (references) and 43 (comments) are checked on the migrated database, not on source text.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.session import engine

pytestmark = pytest.mark.integration

WAVE_ONE_TABLES = {
    "app_user_change",
    "auth_refresh_session",
    "llm_call_summary",
    "review_finding",
    "review_rule_result",
    "review_run",
    "review_run_object",
    "rule_set_draft",
    "rule_set_draft_rule",
    "rule_set_version",
    "rule_set_version_rule",
}
# sql-review 002-sql-server-connection "Veri ve geçiş": the connection the super admin saves.
SQL_CONNECTION_TABLES = {"sql_connection_setting"}
# sql-review 007-rule-group-selection "Veri ve geçiş": named groups, the rules' memberships and
# a run's group and rule selection.
RULE_GROUP_TABLES = {
    "rule_set_draft_group",
    "rule_set_version_group",
    "rule_set_draft_rule_group",
    "rule_set_version_rule_group",
    "review_run_rule_group",
    "review_run_rule",
}
# sql-review 008-scheduled-review-email "Veri ve geçiş": definitions, their runs, run
# recipients and the per-tenant setting.
SCHEDULED_REVIEW_TABLES = {
    "scheduled_review",
    "scheduled_review_run",
    "review_run_recipient",
    "scheduled_review_setting",
}
# sql-review 009-rule-proposals "Veri ve geçiş": proposals, publish requests and the permission.
RULE_PROPOSAL_TABLES = {"rule_proposal", "rule_publish_request", "rule_proposer"}
CHECKED_TABLES = (
    WAVE_ONE_TABLES
    | SQL_CONNECTION_TABLES
    | RULE_GROUP_TABLES
    | SCHEDULED_REVIEW_TABLES
    | RULE_PROPOSAL_TABLES
)
ALL_DOMAIN_TABLES = CHECKED_TABLES | {
    "app_permission",
    "app_role",
    "app_role_permission",
    "app_user",
    "app_user_role",
    "tenant",
}
MANDATORY_COLUMNS = {
    "props": "jsonb",
    "created_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone",
    "created_by": "bigint",
    "updated_by": "bigint",
    "is_deleted": "boolean",
    "deleted_at": "timestamp with time zone",
    "deleted_by": "bigint",
}
PUBLIC_ID_TABLES = {
    "llm_call_summary",
    "review_finding",
    "review_rule_result",
    "review_run",
    "rule_proposal",
    "rule_publish_request",
    "rule_set_draft_group",
    "rule_set_version",
    "scheduled_review",
    "scheduled_review_run",
}
# Columns whose meaning is a closed value set, a cross-table reference or a lifecycle contract:
# rule 43 requires a database comment on each.
COMMENTED_COLUMNS = {
    ("app_user", "account_type"),
    ("app_user", "directory_object_guid"),
    ("app_user", "home_tenant_id"),
    ("app_user_change", "changed_field"),
    ("app_user_change", "actor_user_id"),
    ("app_user_change", "target_user_id"),
    ("auth_refresh_session", "revoke_reason"),
    ("auth_refresh_session", "token_sha256"),
    ("auth_refresh_session", "user_id"),
    ("llm_call_summary", "outcome"),
    ("llm_call_summary", "chat_api"),
    ("llm_call_summary", "part_index"),
    ("llm_call_summary", "review_run_id"),
    ("review_finding", "severity"),
    ("review_finding", "review_rule_result_id"),
    ("review_rule_result", "status"),
    ("review_rule_result", "severity"),
    ("review_run", "kind"),
    ("review_run", "status"),
    ("review_run", "rule_set_version_id"),
    ("review_run", "owner_user_id"),
    ("review_run_object", "source_sql"),
    ("review_run_object", "type_code"),
    ("rule_set_draft", "revision"),
    ("rule_set_draft", "next_rule_number"),
    ("rule_set_draft_rule", "priority_group"),
    ("rule_set_version", "source"),
    ("rule_set_version", "number"),
    ("rule_set_version_rule", "priority_group"),
    ("review_rule_result", "rule_group_names"),
    ("rule_proposal", "kind"),
    ("rule_proposal", "status"),
    ("rule_proposal", "proposer_user_id"),
    ("rule_proposal", "decided_by_user_id"),
    ("rule_proposal", "rule_group_ids"),
    ("rule_proposal", "rule_codes"),
    ("rule_publish_request", "status"),
    ("rule_publish_request", "requester_user_id"),
    ("rule_publish_request", "draft_revision"),
    ("rule_proposer", "user_id"),
    ("rule_proposer", "granted_by_user_id"),
    ("rule_set_draft_rule", "summary"),
    ("rule_set_version_rule", "summary"),
    ("review_run_rule", "review_run_id"),
    ("review_run_rule", "rule_code"),
    ("review_run_rule_group", "review_run_id"),
    ("review_run_rule_group", "rule_group_public_id"),
    ("rule_set_draft_group", "rule_set_draft_id"),
    ("rule_set_draft_group", "position"),
    ("rule_set_draft_rule_group", "rule_set_draft_id"),
    ("rule_set_draft_rule_group", "rule_set_draft_group_id"),
    ("rule_set_version_group", "rule_set_version_id"),
    ("rule_set_version_group", "rule_group_public_id"),
    ("rule_set_version_rule_group", "rule_set_version_id"),
    ("rule_set_version_rule_group", "rule_group_public_id"),
    ("sql_connection_setting", "tenant_id"),
    ("sql_connection_setting", "password_ciphertext"),
    ("sql_connection_setting", "trust_server_certificate"),
    ("review_run", "scheduled_review_id"),
    ("review_run_recipient", "review_run_id"),
    ("review_run_recipient", "email"),
    ("scheduled_review", "tenant_id"),
    ("scheduled_review", "owner_user_id"),
    ("scheduled_review", "selection_mode"),
    ("scheduled_review", "selection"),
    ("scheduled_review", "rule_group_ids"),
    ("scheduled_review", "frequency"),
    ("scheduled_review", "timezone"),
    ("scheduled_review", "recipients"),
    ("scheduled_review", "status"),
    ("scheduled_review_run", "scheduled_review_id"),
    ("scheduled_review_run", "review_run_id"),
    ("scheduled_review_run", "trigger"),
    ("scheduled_review_run", "triggered_by_user_id"),
    ("scheduled_review_run", "state"),
    ("scheduled_review_run", "skip_reason"),
    ("scheduled_review_run", "email_status"),
    ("scheduled_review_setting", "tenant_id"),
    ("scheduled_review_setting", "max_concurrent_runs"),
}


async def _scalar(connection: AsyncConnection, sql: str, **params: Any) -> Any:
    return (await connection.execute(text(sql), params)).scalar_one()


async def test_every_domain_table_is_commented_and_carries_the_mandatory_block(
    migrated_database: None,
) -> None:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT c.relname, obj_description(c.oid, 'pg_class') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                    "AND c.relname <> 'alembic_version'"
                )
            )
        ).all()
        tables = {name: comment for name, comment in rows}
        assert set(tables) == ALL_DOMAIN_TABLES
        for table in CHECKED_TABLES:
            assert tables[table], f"{table} has no table comment"
            columns = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = :table"
                        ),
                        {"table": table},
                    )
                ).all()
            )
            for column, data_type in MANDATORY_COLUMNS.items():
                assert columns.get(column) == data_type, f"{table}.{column}"
            assert ("public_id" in columns) == (table in PUBLIC_ID_TABLES), table
            partial = await _scalar(
                connection,
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = :table AND indexdef LIKE '%WHERE (is_deleted = false)%'",
                table=table,
            )
            assert partial >= 1, f"{table} has no active-row partial index"
            naive = await _scalar(
                connection,
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = :table AND data_type = 'timestamp without time zone'",
                table=table,
            )
            assert naive == 0, f"{table} stores a naive timestamp"


async def test_closed_value_and_reference_columns_are_commented(migrated_database: None) -> None:
    async with engine.connect() as connection:
        for table, column in sorted(COMMENTED_COLUMNS):
            comment = await _scalar(
                connection,
                "SELECT col_description(c.oid, a.attnum) FROM pg_class c "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE c.relname = :table AND a.attname = :column",
                table=table,
                column=column,
            )
            assert comment, f"{table}.{column} has no comment"


async def test_migration_seeds_the_platform_tenant_and_both_roles(migrated_database: None) -> None:
    async with engine.connect() as connection:
        assert await _scalar(connection, "SELECT count(*) FROM tenant WHERE code = 'platform'") == 1
        grants = (
            await connection.execute(
                text(
                    "SELECT r.code FROM app_role_permission rp "
                    "JOIN app_role r USING (role_id) JOIN app_permission p USING (permission_id) "
                    "WHERE p.code = 'platform:access' AND r.code <> 'super_admin' ORDER BY 1"
                )
            )
        ).scalars()
        assert list(grants) == ["inceleyici", "kural-yoneticisi"]


async def _tenant_id(connection: AsyncConnection) -> int:
    return int(await _scalar(connection, "SELECT tenant_id FROM tenant WHERE code = 'platform'"))


async def _insert_directory_user(connection: AsyncConnection, tenant_id: int) -> int:
    marker = uuid4().hex
    return int(
        await _scalar(
            connection,
            "INSERT INTO app_user (home_tenant_id, public_id, username, email, display_name, "
            "account_type, directory_object_guid) VALUES (:tenant, :public_id, :username, "
            ":email, 'Test Person', 'directory', :guid) RETURNING user_id",
            tenant=tenant_id,
            public_id=str(uuid4()),
            username=f"{marker}@corp.example.test",
            email=f"{marker}@corp.example.test",
            guid=uuid4(),
        )
    )


@pytest.mark.parametrize(
    ("account_type", "password_hash", "with_guid"),
    (
        ("directory", "hash-value", True),
        ("directory", None, False),
        ("local", None, False),
        ("local", "hash-value", True),
        ("service", "hash-value", False),
    ),
)
async def test_credential_columns_must_match_the_account_type(
    migrated_database: None, account_type: str, password_hash: str | None, with_guid: bool
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        marker = uuid4().hex
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO app_user (home_tenant_id, public_id, username, email, "
                    "display_name, account_type, password_hash, directory_object_guid) "
                    "VALUES (:tenant, :public_id, :name, :email, 'X', :type, :hash, :guid)"
                ),
                {
                    "tenant": tenant_id,
                    "public_id": str(uuid4()),
                    "name": marker,
                    "email": f"{marker}@example.test",
                    "type": account_type,
                    "hash": password_hash,
                    "guid": uuid4() if with_guid else None,
                },
            )
        await connection.rollback()


async def _insert_version(connection: AsyncConnection, tenant_id: int, number: int) -> int:
    return int(
        await _scalar(
            connection,
            "INSERT INTO rule_set_version (public_id, tenant_id, number, published_at, source, "
            "content_sha256) VALUES (:public_id, :tenant, :number, now(), 'ice-aktarim', "
            ":digest) RETURNING rule_set_version_id",
            public_id=str(uuid4()),
            tenant=tenant_id,
            number=number,
            digest="0" * 64,
        )
    )


async def test_version_number_is_unique_inside_the_tenant(migrated_database: None) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        number = 1_000_000 + int(uuid4().int % 1_000_000)
        await _insert_version(connection, tenant_id, number)
        with pytest.raises(IntegrityError):
            await _insert_version(connection, tenant_id, number)
        await connection.rollback()


@pytest.mark.parametrize("code", ("Kural00", "Kural1", "Rule01", "kural01", "Kural01x"))
async def test_rule_codes_outside_the_kural_format_are_rejected(
    migrated_database: None, code: str
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        version_id = await _insert_version(
            connection, tenant_id, 2_000_000 + int(uuid4().int % 1_000_000)
        )
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO rule_set_version_rule (rule_set_version_id, rule_code, "
                    "priority_group, position, rule_text) VALUES (:version, :code, 'critical', "
                    "0, 'text')"
                ),
                {"version": version_id, "code": code},
            )
        await connection.rollback()


async def test_rule_set_version_publisher_matches_its_source(migrated_database: None) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO rule_set_version (public_id, tenant_id, number, published_at, "
                    "source, content_sha256) VALUES (:public_id, :tenant, :number, now(), "
                    "'arayuz', :digest)"
                ),
                {
                    "public_id": str(uuid4()),
                    "tenant": tenant_id,
                    "number": 3_000_000 + int(uuid4().int % 1_000_000),
                    "digest": "a" * 64,
                },
            )
        await connection.rollback()


async def test_deleting_a_run_removes_its_rows_and_keeps_llm_summaries_unlinked(
    migrated_database: None,
) -> None:
    async with engine.begin() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version = await _insert_version(
            connection, tenant_id, 4_000_000 + int(uuid4().int % 1_000_000)
        )
        run = int(
            await _scalar(
                connection,
                "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, label, "
                "rule_set_version_id, object_count, status, started_at, finished_at) VALUES "
                "(:public_id, :tenant, :owner, 'script', 'Etiket', :version, 1, 'completed', "
                ":started, :finished) RETURNING review_run_id",
                public_id=str(uuid4()),
                tenant=tenant_id,
                owner=owner,
                version=version,
                started=datetime(2026, 9, 1, tzinfo=UTC),
                finished=datetime(2026, 9, 1, 0, 1, tzinfo=UTC),
            )
        )
        run_object = int(
            await _scalar(
                connection,
                "INSERT INTO review_run_object (review_run_id, position, schema_name, "
                "object_name, type_code, object_type, source_sql) VALUES (:run, 0, 'sql', "
                "'Etiket', 'SCRIPT', 'SCRIPT', 'SELECT 1') RETURNING review_run_object_id",
                run=run,
            )
        )
        result = int(
            await _scalar(
                connection,
                "INSERT INTO review_rule_result (public_id, review_run_object_id, position, "
                "rule_code, priority_group, status, severity) VALUES (:public_id, :object, 0, "
                "'Kural01', 'critical', 'FAIL', 'HIGH') RETURNING review_rule_result_id",
                public_id=str(uuid4()),
                object=run_object,
            )
        )
        await connection.execute(
            text(
                "INSERT INTO review_finding (public_id, review_rule_result_id, position, "
                "rule_code, severity, description) VALUES (:public_id, :result, 0, 'Kural01', "
                "'HIGH', 'Etiket: neden')"
            ),
            {"public_id": str(uuid4()), "result": result},
        )
        summary_public_id = str(uuid4())
        await connection.execute(
            text(
                "INSERT INTO llm_call_summary (public_id, tenant_id, review_run_id, started_at, "
                "object_label, rule_code, attempt, chat_api, model, endpoint_host, streamed, "
                "outcome, duration_ms) VALUES (:public_id, :tenant, :run, now(), "
                "'Etiket (SCRIPT)', 'Kural01', 1, 'openai', 'model', 'llm.example.test', true, "
                "'ok', 10)"
            ),
            {"public_id": summary_public_id, "tenant": tenant_id, "run": run},
        )

        await connection.execute(
            text("DELETE FROM review_run WHERE review_run_id = :run"), {"run": run}
        )

        for table in ("review_run_object", "review_rule_result", "review_finding"):
            remaining = await _scalar(
                connection,
                f"SELECT count(*) FROM {table} WHERE "
                + {
                    "review_run_object": "review_run_id = :key",
                    "review_rule_result": "review_run_object_id = :object",
                    "review_finding": "review_rule_result_id = :result",
                }[table],
                key=run,
                object=run_object,
                result=result,
            )
            assert remaining == 0, table
        link = (
            await connection.execute(
                text("SELECT review_run_id FROM llm_call_summary WHERE public_id = :public_id"),
                {"public_id": summary_public_id},
            )
        ).one()
        assert link.review_run_id is None


async def test_a_run_cannot_point_at_a_missing_rule_version(migrated_database: None) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, "
                    "rule_set_version_id, object_count, started_at) VALUES (:public_id, "
                    ":tenant, :owner, 'object', -1, 1, now())"
                ),
                {"public_id": str(uuid4()), "tenant": tenant_id, "owner": owner},
            )
        await connection.rollback()


@pytest.mark.parametrize(
    ("status", "severity", "accepted"),
    [
        ("FAIL", "HIGH", True),
        ("PASS", None, True),
        ("UNKNOWN", None, True),
        ("PASS", "LOW", False),
        ("FAIL", None, False),
    ],
)
async def test_only_a_fail_verdict_has_a_severity(
    migrated_database: None, status: str, severity: str | None, accepted: bool
) -> None:
    """sql-review 003 Requirement 13: severity is set exactly for FAIL (revision 202609260003)."""

    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version = await _insert_version(
            connection, tenant_id, 5_000_000 + int(uuid4().int % 1_000_000)
        )
        run = int(
            await _scalar(
                connection,
                "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, "
                "rule_set_version_id, object_count, status, started_at) VALUES (:p, :t, :o, "
                "'object', :v, 1, 'running', now()) RETURNING review_run_id",
                p=str(uuid4()),
                t=tenant_id,
                o=owner,
                v=version,
            )
        )
        run_object = int(
            await _scalar(
                connection,
                "INSERT INTO review_run_object (review_run_id, position, schema_name, "
                "object_name, type_code, object_type) VALUES (:run, 0, 'dbo', 'p', 'P', "
                "'PROCEDURE') RETURNING review_run_object_id",
                run=run,
            )
        )
        insert = text(
            "INSERT INTO review_rule_result (public_id, review_run_object_id, position, "
            "rule_code, priority_group, status, severity, line_reference) VALUES (:p, :o, 0, "
            "'Kural01', 'critical', :status, :severity, :line)"
        )
        values = {
            "p": str(uuid4()),
            "o": run_object,
            "status": status,
            "severity": severity,
            "line": "Satır " + ", ".join(str(n) for n in range(1, 120)),
        }
        if accepted:
            await connection.execute(insert, values)
        else:
            with pytest.raises(IntegrityError):
                await connection.execute(insert, values)
        await connection.rollback()


async def test_a_saved_sql_connection_is_one_row_per_tenant(
    migrated_database: None,
) -> None:
    # sql-review 002-sql-server-connection Requirement 10, Decision 5 and 6.
    insert = (
        "INSERT INTO sql_connection_setting (tenant_id, server, port, user_name) "
        "VALUES (:tenant, 'sql.corp.example.test', :port, 'okuyucu')"
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            tenant_id = await _tenant_id(connection)
            await connection.execute(text("DELETE FROM sql_connection_setting"))
            for values in (
                {"tenant": tenant_id, "port": 0},
                {"tenant": tenant_id, "port": 65536},
                {"tenant": 0, "port": 1433},
            ):
                savepoint = await connection.begin_nested()
                with pytest.raises(IntegrityError):
                    await connection.execute(text(insert), values)
                await savepoint.rollback()
            first = {"tenant": tenant_id, "port": 1433}
            await connection.execute(text(insert), first)
            # No list of databases is stored, and the certificate is verified unless chosen.
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'sql_connection_setting'"
                        )
                    )
                ).scalars()
            )
            assert "allowed_databases" not in columns
            assert (
                await _scalar(
                    connection, "SELECT trust_server_certificate FROM sql_connection_setting"
                )
            ) is False
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(text(insert), first)
            await savepoint.rollback()
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text("DELETE FROM tenant WHERE tenant_id = :tenant"), {"tenant": tenant_id}
                )
            await savepoint.rollback()
        finally:
            await transaction.rollback()


async def _insert_version(connection: AsyncConnection, tenant_id: int, number: int) -> int:
    return int(
        await _scalar(
            connection,
            "INSERT INTO rule_set_version (public_id, tenant_id, number, published_at, source, "
            "content_sha256) VALUES (:public_id, :tenant, :number, now(), 'ice-aktarim', "
            "repeat('a', 64)) RETURNING rule_set_version_id",
            public_id=str(uuid4()),
            tenant=tenant_id,
            number=number,
        )
    )


async def test_a_version_membership_points_only_at_a_rule_and_group_of_its_version(
    migrated_database: None,
) -> None:
    """rule-group-selection Decision 1: a rule may join several groups, inside the same version."""

    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        version_id = await _insert_version(connection, tenant_id, 900_001)
        other_id = await _insert_version(connection, tenant_id, 900_002)
        for version in (version_id, other_id):
            await connection.execute(
                text(
                    "INSERT INTO rule_set_version_rule (rule_set_version_id, rule_code, "
                    "priority_group, position, rule_text) VALUES (:version, 'Kural01', "
                    "'critical', 0, 'metin')"
                ),
                {"version": version},
            )
        for position, group in enumerate(("grp-a", "grp-b")):
            await connection.execute(
                text(
                    "INSERT INTO rule_set_version_group (rule_set_version_id, "
                    "rule_group_public_id, name, description, position) VALUES (:version, "
                    ":group, :name, '', :position)"
                ),
                {"version": version_id, "group": group, "name": group, "position": position},
            )
        membership = (
            "INSERT INTO rule_set_version_rule_group (rule_set_version_id, rule_code, "
            "rule_group_public_id) VALUES (:version, 'Kural01', :group)"
        )
        for group in ("grp-a", "grp-b"):
            await connection.execute(text(membership), {"version": version_id, "group": group})
        with pytest.raises(IntegrityError):
            await connection.execute(text(membership), {"version": other_id, "group": "grp-a"})
        await connection.rollback()


async def test_a_draft_membership_points_only_at_a_group_of_its_own_draft(
    migrated_database: None,
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        other_tenant = int(
            await _scalar(
                connection,
                "INSERT INTO tenant (public_id, code, name) VALUES (:public_id, :code, 'Diğer') "
                "RETURNING tenant_id",
                public_id=str(uuid4()),
                code=f"t{uuid4().hex[:12]}",
            )
        )
        drafts = []
        for tenant in (tenant_id, other_tenant):
            drafts.append(
                int(
                    await _scalar(
                        connection,
                        "INSERT INTO rule_set_draft (tenant_id) VALUES (:tenant) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET revision = rule_set_draft.revision "
                        "RETURNING rule_set_draft_id",
                        tenant=tenant,
                    )
                )
            )
        # The platform draft is shared by the tests: a code no other test uses.
        code = f"Kural{uuid4().int % 900_000 + 100_000}"
        await connection.execute(
            text(
                "INSERT INTO rule_set_draft_rule (rule_set_draft_id, rule_code, priority_group, "
                "position, rule_text) VALUES (:draft, :code, 'critical', 0, 'metin')"
            ),
            {"draft": drafts[0], "code": code},
        )
        foreign_group = int(
            await _scalar(
                connection,
                "INSERT INTO rule_set_draft_group (public_id, rule_set_draft_id, name, "
                "description, position) VALUES (:public_id, :draft, 'Güvenlik', '', 0) "
                "RETURNING rule_set_draft_group_id",
                public_id=str(uuid4()),
                draft=drafts[1],
            )
        )
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO rule_set_draft_rule_group (rule_set_draft_id, rule_code, "
                    "rule_set_draft_group_id) VALUES (:draft, :code, :group)"
                ),
                {"draft": drafts[0], "code": code, "group": foreign_group},
            )
        await connection.rollback()


async def test_deleting_a_run_removes_its_selected_groups_and_rules(
    migrated_database: None,
) -> None:
    async with engine.begin() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version_id = await _insert_version(connection, tenant_id, 900_003)
        run_id = int(
            await _scalar(
                connection,
                "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, "
                "rule_set_version_id, object_count, started_at) VALUES (:public_id, :tenant, "
                ":owner, 'object', :version, 1, now()) RETURNING review_run_id",
                public_id=str(uuid4()),
                tenant=tenant_id,
                owner=owner,
                version=version_id,
            )
        )
        await connection.execute(
            text(
                "INSERT INTO review_run_rule_group (review_run_id, rule_group_public_id, name, "
                "position) VALUES (:run, 'grp-a', 'Performans', 0)"
            ),
            {"run": run_id},
        )
        await connection.execute(
            text(
                "INSERT INTO review_run_rule (review_run_id, rule_code, position) "
                "VALUES (:run, 'Kural07', 0)"
            ),
            {"run": run_id},
        )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO review_run_rule (review_run_id, rule_code, position) "
                        "VALUES (:run, 'Kural00', 1)"
                    ),
                    {"run": run_id},
                )
        await connection.execute(
            text("DELETE FROM review_run WHERE review_run_id = :run"), {"run": run_id}
        )
        remaining = await _scalar(
            connection,
            "SELECT (SELECT count(*) FROM review_run_rule_group WHERE review_run_id = :run) "
            "+ (SELECT count(*) FROM review_run_rule WHERE review_run_id = :run)",
            run=run_id,
        )
        assert remaining == 0
        await connection.execute(
            text("DELETE FROM rule_set_version WHERE rule_set_version_id = :v"),
            {"v": version_id},
        )


# --- sql-review 008-scheduled-review-email ----------------------------------------------------

_DEFINITION = (
    "INSERT INTO scheduled_review (public_id, tenant_id, owner_user_id, name, selection_mode, "
    "selection, frequency, weekday, day_of_month, run_hour, run_minute, timezone, recipients) "
    "VALUES (:public_id, :tenant, :owner, :name, 'filter', CAST(:selection AS jsonb), "
    ":frequency, :weekday, :day, 7, 30, 'Europe/Istanbul', CAST(:recipients AS jsonb)) "
    "RETURNING scheduled_review_id"
)


async def _insert_definition(
    connection: AsyncConnection,
    tenant_id: int,
    owner: int,
    *,
    name: str = "Gece taraması",
    frequency: str = "daily",
    weekday: int | None = None,
    day: int | None = None,
) -> int:
    return int(
        await _scalar(
            connection,
            _DEFINITION,
            public_id=str(uuid4()),
            tenant=tenant_id,
            owner=owner,
            name=name,
            selection='{"database": "DWH"}',
            frequency=frequency,
            weekday=weekday,
            day=day,
            recipients='["a@kurum.example"]',
        )
    )


async def _insert_scheduled_run(
    connection: AsyncConnection, tenant_id: int, owner: int, version_id: int, definition: int
) -> int:
    return int(
        await _scalar(
            connection,
            "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, "
            "rule_set_version_id, object_count, started_at, scheduled_review_id) VALUES "
            "(:public_id, :tenant, :owner, 'scheduled', :version, 3, now(), :definition) "
            "RETURNING review_run_id",
            public_id=str(uuid4()),
            tenant=tenant_id,
            owner=owner,
            version=version_id,
            definition=definition,
        )
    )


@pytest.mark.parametrize(
    ("frequency", "weekday", "day"),
    (
        ("weekly", None, None),
        ("daily", 2, None),
        ("monthly", None, None),
        ("monthly", None, 29),
        ("weekly", 7, None),
        ("hourly", None, None),
    ),
)
async def test_a_definition_period_must_be_one_of_the_closed_forms(
    migrated_database: None, frequency: str, weekday: int | None, day: int | None
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        with pytest.raises(IntegrityError):
            await _insert_definition(
                connection, tenant_id, owner, frequency=frequency, weekday=weekday, day=day
            )
        await connection.rollback()


async def test_a_definition_name_is_unique_per_owner_regardless_of_case(
    migrated_database: None,
) -> None:
    # The index folds ASCII letters; the service also folds Turkish dotted/dotless I before it
    # writes (schedule_name_duplicate), which a C-collated lower() cannot do.
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        other = await _insert_directory_user(connection, tenant_id)
        await _insert_definition(connection, tenant_id, owner, name="Gece kontrol")
        await _insert_definition(connection, tenant_id, other, name="Gece kontrol")
        with pytest.raises(IntegrityError):
            await _insert_definition(connection, tenant_id, owner, name="GECE KONTROL")
        await connection.rollback()


async def test_only_a_scheduled_run_points_at_a_definition_and_may_hold_many_objects(
    migrated_database: None,
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version_id = await _insert_version(connection, tenant_id, 900_101)
        definition = await _insert_definition(connection, tenant_id, owner)
        assert await _insert_scheduled_run(connection, tenant_id, owner, version_id, definition)
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO review_run (public_id, tenant_id, owner_user_id, kind, "
                    "rule_set_version_id, object_count, started_at, scheduled_review_id) VALUES "
                    "(:public_id, :tenant, :owner, 'object', :version, 1, now(), :definition)"
                ),
                {
                    "public_id": str(uuid4()),
                    "tenant": tenant_id,
                    "owner": owner,
                    "version": version_id,
                    "definition": definition,
                },
            )
        await connection.rollback()


async def test_deleting_a_definition_removes_its_history_and_keeps_its_runs_unlinked(
    migrated_database: None,
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version_id = await _insert_version(connection, tenant_id, 900_102)
        definition = await _insert_definition(connection, tenant_id, owner)
        run_id = await _insert_scheduled_run(connection, tenant_id, owner, version_id, definition)
        await connection.execute(
            text(
                "INSERT INTO scheduled_review_run (public_id, scheduled_review_id, tenant_id, "
                "review_run_id, due_at, trigger, state) VALUES (:public_id, :definition, "
                ":tenant, :run, now(), 'scheduled', 'running')"
            ),
            {
                "public_id": str(uuid4()),
                "definition": definition,
                "tenant": tenant_id,
                "run": run_id,
            },
        )
        await connection.execute(
            text("DELETE FROM scheduled_review WHERE scheduled_review_id = :d"), {"d": definition}
        )
        history = await _scalar(
            connection,
            "SELECT count(*) FROM scheduled_review_run WHERE scheduled_review_id = :d",
            d=definition,
        )
        link = await _scalar(
            connection,
            "SELECT scheduled_review_id FROM review_run WHERE review_run_id = :run",
            run=run_id,
        )
        assert (history, link) == (0, None)
        await connection.rollback()


async def test_run_recipients_are_lower_case_and_deleted_with_the_run(
    migrated_database: None,
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        owner = await _insert_directory_user(connection, tenant_id)
        version_id = await _insert_version(connection, tenant_id, 900_103)
        definition = await _insert_definition(connection, tenant_id, owner)
        run_id = await _insert_scheduled_run(connection, tenant_id, owner, version_id, definition)
        insert = text(
            "INSERT INTO review_run_recipient (review_run_id, email) VALUES (:run, :email)"
        )
        await connection.execute(insert, {"run": run_id, "email": "ayse@kurum.example"})
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(insert, {"run": run_id, "email": "Ali@Kurum.Example"})
        await connection.execute(
            text("DELETE FROM review_run WHERE review_run_id = :run"), {"run": run_id}
        )
        remaining = await _scalar(
            connection,
            "SELECT count(*) FROM review_run_recipient WHERE review_run_id = :run",
            run=run_id,
        )
        assert remaining == 0
        await connection.rollback()


@pytest.mark.parametrize("limit", (0, 11))
async def test_the_concurrency_setting_stays_between_1_and_10(
    migrated_database: None, limit: int
) -> None:
    async with engine.connect() as connection:
        tenant_id = await _tenant_id(connection)
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO scheduled_review_setting (tenant_id, max_concurrent_runs) "
                    "VALUES (:tenant, :limit)"
                ),
                {"tenant": tenant_id, "limit": limit},
            )
        await connection.rollback()
