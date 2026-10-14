"""Database and object lists for choosing what to review (sql-review 003 Requirement 1-2).

The SQL Server port lists and filters (Decision 6 of 003, Requirement 7 of 002); this service
adds the type filter and the pages, and maps port failures to the error envelope: 503 when no
connection is configured or the server fails, 504 on a timeout, 403 for a system database.
"""

from collections.abc import Awaitable
from datetime import date

from fastapi import status

from app.core.errors import ApplicationError
from app.domain.sql_server import (
    DATABASE_NOT_ALLOWED_CODE,
    DATABASE_NOT_ALLOWED_MESSAGE,
    NOT_CONFIGURED_CODE,
    NOT_CONFIGURED_MESSAGE,
    CatalogObject,
    DatabaseNotAllowed,
    SqlCatalogPort,
    SqlServerError,
    SqlServerErrorClass,
    SqlServerNotConfigured,
)
from app.schemas.reviews.contracts import (
    CatalogObjectItem,
    CatalogObjectPage,
    DatabasePage,
)

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


def _not_allowed() -> ApplicationError:
    return ApplicationError(
        status.HTTP_403_FORBIDDEN, DATABASE_NOT_ALLOWED_CODE, DATABASE_NOT_ALLOWED_MESSAGE
    )


async def _catalog_call[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except SqlServerNotConfigured:
        raise ApplicationError(
            status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED_CODE, NOT_CONFIGURED_MESSAGE
        ) from None
    except DatabaseNotAllowed:
        raise _not_allowed() from None
    except SqlServerError as error:
        code = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if error.error_class is SqlServerErrorClass.TIMEOUT
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise ApplicationError(code, error.error_class.value, error.message) from None


class ReviewCatalogService:
    def __init__(self, catalog: SqlCatalogPort) -> None:
        self.catalog = catalog

    async def databases(self, *, page: int, page_size: int) -> DatabasePage:
        names = await _catalog_call(self.catalog.list_databases())
        start = (page - 1) * page_size
        return DatabasePage(
            items=names[start : start + page_size], page=page, page_size=page_size, total=len(names)
        )

    async def matching_objects(
        self, database: str, *, query: str | None, from_date: date | None
    ) -> list[CatalogObject]:
        """Every object of the filter at once, for a scheduled run (sql-review 008 Decision 4).

        The same checks and error codes as the paged list; the type filter is the caller's.
        """

        if not self.catalog.is_allowed(database):
            raise _not_allowed()
        return await _catalog_call(
            self.catalog.list_objects(database, query=query or None, from_date=from_date)
        )

    async def objects(
        self,
        database: str,
        *,
        query: str | None,
        type_code: str | None,
        from_date: date | None,
        page: int,
        page_size: int,
    ) -> CatalogObjectPage:
        if not self.catalog.is_allowed(database):
            raise _not_allowed()
        rows = await _catalog_call(
            self.catalog.list_objects(database, query=query or None, from_date=from_date)
        )
        if type_code:
            rows = [row for row in rows if row.type_code == type_code]
        start = (page - 1) * page_size
        return CatalogObjectPage(
            items=[
                CatalogObjectItem(
                    schema=row.schema,
                    name=row.name,
                    type=row.type,
                    type_code=row.type_code,
                    created_at=row.created_at,
                    last_modified=row.last_modified,
                )
                for row in rows[start : start + page_size]
            ],
            page=page,
            page_size=page_size,
            total=len(rows),
        )
