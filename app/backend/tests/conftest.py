"""Shared fixtures: a fresh SQLite data dir per test and a fake SQL Server catalog."""

import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

# Never touch the real data directory, even at import time of app.main.
os.environ.setdefault("DWHCR_DATA_DIR", tempfile.mkdtemp(prefix="dwhcr-import-"))

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import get_database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import build_rule  # noqa: E402
from app.services import llm  # noqa: E402
from app.services.catalog import (  # noqa: E402
    CatalogError,
    CatalogObject,
    ConnectionConfig,
    ObjectQuery,
    ProbeResult,
    get_catalog,
)
from app.services.metadata import ObjectMetadata  # noqa: E402
from tests.legacy_rules import SEED_GROUPS as LEGACY_GROUPS  # noqa: E402
from tests.legacy_rules import SEED_RULES as LEGACY_RULES  # noqa: E402

PROC_SQL = """CREATE PROCEDURE dbo.usp_LoadSales
AS
BEGIN
    -- SELECT * FROM dbo.Comment
    SELECT * FROM dbo.Sales WITH (NOLOCK);
    SELECT @@IDENTITY;
END
"""

VIEW_SQL = """CREATE VIEW dbo.vSales
AS
SELECT s.Id, s.Amount FROM dbo.Sales s
"""

PROC2_SQL = """CREATE PROCEDURE dbo.sp_Bad
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        SELECT 1;
    END TRY
    BEGIN CATCH
        THROW;
    END CATCH
END
"""


class FakeReader:
    def __init__(self, catalog: "FakeCatalog") -> None:
        self.catalog = catalog

    def fetch(self, database: str, schema: str, name: str) -> str | None:
        if self.catalog.delay:
            time.sleep(self.catalog.delay)
        key = (database, schema, name)
        if key in self.catalog.fail:
            raise CatalogError("Simüle edilmiş hata.")
        return self.catalog.definitions.get(key)

    def describe(self, database, schema, name, object_type, sql, masked, extra=()):  # type: ignore[no-untyped-def]
        self.catalog.describe_calls.append((database, schema, name, tuple(extra)))
        return self.catalog.metadata.get((database, schema, name), ObjectMetadata(available=True))


class FakeCatalog:
    def __init__(self) -> None:
        self.definitions: dict[tuple[str, str, str], str] = {
            ("DWH", "dbo", "usp_LoadSales"): PROC_SQL,
            ("DWH", "dbo", "vSales"): VIEW_SQL,
            ("DWH", "dbo", "sp_Bad"): PROC2_SQL,
        }
        self.objects = [
            CatalogObject("DWH", "dbo", "usp_LoadSales", "PROCEDURE", datetime(2024, 1, 1), datetime(2024, 6, 1)),
            CatalogObject("DWH", "dbo", "vSales", "VIEW", datetime(2024, 2, 1), datetime(2024, 2, 1)),
        ]
        self.fail: set[tuple[str, str, str]] = set()
        self.delay = 0.0
        self.queries: list[ObjectQuery] = []
        self.metadata: dict[tuple[str, str, str], ObjectMetadata] = {}
        self.describe_calls: list[tuple[str, str, str, tuple]] = []

    def probe(self, config: ConnectionConfig) -> ProbeResult:
        if config.password != "secret":
            raise CatalogError("SQL Server girişi reddedildi. Kullanıcı adı ve parolayı kontrol edin.")
        return ProbeResult("Microsoft SQL Server 2022", 2)

    def list_databases(self, config: ConnectionConfig) -> list[str]:
        return ["DWH", "Stage"]

    def list_schemas(self, config, databases):  # type: ignore[no-untyped-def]
        return [(db, "dbo", 2) for db in databases]

    def list_objects(self, config: ConnectionConfig, query: ObjectQuery) -> list[CatalogObject]:
        self.queries.append(query)
        return [o for o in self.objects if o.database in query.databases]

    @contextmanager
    def open_reader(self, config: ConnectionConfig) -> Iterator[FakeReader]:
        yield FakeReader(self)


@pytest.fixture
def fake_catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest.fixture
def client(tmp_path: Path, fake_catalog: FakeCatalog) -> Iterator[TestClient]:
    app = create_app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: fake_catalog
    llm.http_transport = None
    with TestClient(app) as test_client:
        yield test_client
    llm.http_transport = None


def install_legacy_rules() -> None:
    """Add the v1.0 rule set (21 rules, 4 groups) next to the seeded DWH standards."""
    with get_database().session_factory() as session:
        rules = {data["code"]: build_rule(data) for data in LEGACY_RULES}
        session.add_all(rules.values())
        for group in LEGACY_GROUPS:
            session.add(
                models.RuleGroup(
                    name=group["name"],
                    description=group["description"],
                    color=group["color"],
                    rules=[rules[code] for code in group["rules"]],
                )
            )
        session.commit()


@pytest.fixture
def legacy_client(client: TestClient) -> TestClient:
    install_legacy_rules()
    return client


def wait_for(client: TestClient, analysis_id: int, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/analyses/{analysis_id}").json()
        if data["status"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")
