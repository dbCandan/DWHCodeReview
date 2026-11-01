"""Schema-aware readiness of the runtime database connection.

The process is ready only when its runtime role authenticates and the database schema has reached
the Alembic head shipped in this image. On a first installation the migration Job creates the
runtime role and the schema while the backend already runs; until both exist the probe reports
"not ready" instead of letting requests fail.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.logging import log_event

logger = logging.getLogger("app.readiness")

ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"
NOT_READY_LOG_INTERVAL_SECONDS = 60.0
_CAUSE_DEPTH = 5

SchemaPosition = Literal["current", "behind", "ahead"]


@dataclass(frozen=True, slots=True)
class PackagedSchema:
    """The Alembic heads and every revision this image ships."""

    heads: frozenset[str]
    revisions: frozenset[str]


@lru_cache(maxsize=1)
def packaged_schema() -> PackagedSchema:
    """Read the shipped migration scripts once; without a head the image is unusable."""

    if not ALEMBIC_CONFIG.is_file():
        raise RuntimeError("the image ships no alembic.ini beside the backend package")
    scripts = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    heads = frozenset(scripts.get_heads())
    if not heads:
        raise RuntimeError("the image ships no Alembic migration head")
    revisions = frozenset(script.revision for script in scripts.walk_revisions())
    return PackagedSchema(heads=heads, revisions=revisions)


def schema_position(recorded: frozenset[str], packaged: PackagedSchema) -> SchemaPosition:
    """Place the revisions recorded in the database relative to the image's heads."""

    if recorded == packaged.heads:
        return "current"
    if recorded and not recorded <= packaged.revisions:
        # A newer release already migrated the schema. Migrations are expand-only and a rollback
        # never downgrades the schema, so this image still runs on it.
        return "ahead"
    return "behind"


async def recorded_revisions(connection: AsyncConnection) -> frozenset[str]:
    """Return the revisions in ``alembic_version``; no table means no migration has run yet."""

    exists = await connection.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL"))
    if not exists:
        return frozenset()
    result = await connection.execute(text("SELECT version_num FROM alembic_version"))
    # A textual query carries no column types, so the scalars stay untyped until str() reads them.
    versions: Iterable[object] = result.scalars()
    return frozenset(str(revision) for revision in versions)


def _error_type(error: BaseException) -> str:
    """Name the driver-level cause; exception messages may carry connection details."""

    cause = error
    for _ in range(_CAUSE_DEPTH):
        if cause.__cause__ is None:
            break
        cause = cause.__cause__
    return type(cause).__name__


class DatabaseReadiness:
    """Answer readiness probes: the schema is confirmed once, the connection on every probe."""

    def __init__(
        self,
        engine: AsyncEngine,
        packaged: Callable[[], PackagedSchema] = packaged_schema,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._engine = engine
        self._packaged = packaged
        self._clock = clock
        self._schema_confirmed = False
        self._last_reported: dict[tuple[str, str], float] = {}

    async def is_ready(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                if self._schema_confirmed:
                    await connection.execute(text("SELECT 1"))
                    return True
                recorded = await recorded_revisions(connection)
        except Exception as error:  # noqa: BLE001 - a rejected login or lost server is "not ready"
            self._report_not_ready("database_unavailable", _error_type(error))
            return False
        position = schema_position(recorded, self._packaged())
        if position == "behind":
            self._report_not_ready("schema_behind", "")
            return False
        self._schema_confirmed = True
        log_event(logger, "readiness.schema_confirmed", schema_position=position)
        return True

    def _report_not_ready(self, reason: str, error_type: str) -> None:
        """Log at most one event per reason and error type in each interval."""

        key = (reason, error_type)
        now = self._clock()
        last = self._last_reported.get(key)
        if last is not None and now - last < NOT_READY_LOG_INTERVAL_SECONDS:
            return
        self._last_reported[key] = now
        if error_type:
            log_event(logger, "readiness.not_ready", reason=reason, error_type=error_type)
        else:
            log_event(logger, "readiness.not_ready", reason=reason)
