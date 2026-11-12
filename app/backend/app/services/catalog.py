"""SQL Server catalog access over pyodbc (read-only).

All calls are blocking; routers run them in the thread pool. Every user value travels as a
`?` parameter; the only identifier placed in SQL text is the database name of `USE`, which
is bracket-quoted with `]` doubled.
"""

import re
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from app.config import SQL_LOGIN_TIMEOUT_SECONDS, SQL_QUERY_TIMEOUT_SECONDS
from app.services.metadata import MetadataCollector, ObjectMetadata, quote_ident

SYSTEM_DATABASES = frozenset({"master", "tempdb", "model", "msdb"})

TYPE_CODES: dict[str, str] = {
    "P": "PROCEDURE",
    "V": "VIEW",
    "FN": "FUNCTION_SCALAR",
    "IF": "FUNCTION_INLINE",
    "TF": "FUNCTION_TABLE",
}
CODE_BY_TYPE = {value: key for key, value in TYPE_CODES.items()}

PREFERRED_DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
_SERVER_RE = re.compile(r"^[A-Za-z0-9._\-]+(\\[A-Za-z0-9_$\-]+)?$|^\[[0-9A-Fa-f:.]+\]$")


# ------------------------------------------------------------------ value types
@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    server: str
    port: int
    username: str
    password: str | None = field(default=None, repr=False)
    encrypt: bool = True
    trust_server_certificate: bool = True


@dataclass(frozen=True, slots=True)
class ObjectQuery:
    databases: Sequence[str]
    schemas: Sequence[str] = ()
    types: Sequence[str] = ()
    created_from: date | None = None
    created_to: date | None = None
    modified_from: date | None = None
    modified_to: date | None = None
    search: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogObject:
    database: str
    schema: str
    name: str
    type: str
    create_date: datetime | None  # UTC
    modify_date: datetime | None  # UTC


@dataclass(frozen=True, slots=True)
class ProbeResult:
    server_version: str
    database_count: int


class CatalogError(Exception):
    """Classified SQL Server failure with a short Turkish message."""


class DefinitionReader(Protocol):
    """Reads definitions during one analysis run.

    Readers may also offer `describe(database, schema, name, object_type, sql, masked, extra)`
    returning `metadata.ObjectMetadata`; the runner treats a reader without it as having no
    catalog metadata.
    """

    def fetch(self, database: str, schema: str, name: str) -> str | None: ...


class Catalog(Protocol):
    def probe(self, config: ConnectionConfig) -> ProbeResult: ...

    def list_databases(self, config: ConnectionConfig) -> list[str]: ...

    def list_schemas(
        self, config: ConnectionConfig, databases: Sequence[str]
    ) -> list[tuple[str, str, int]]: ...

    def list_objects(self, config: ConnectionConfig, query: ObjectQuery) -> list[CatalogObject]: ...

    def open_reader(self, config: ConnectionConfig) -> Any:
        """Context manager yielding a `DefinitionReader`."""
        ...


# ------------------------------------------------------------------ helpers
def is_system_database(name: str) -> bool:
    return name.strip().casefold() in SYSTEM_DATABASES


def validate_server(server: str) -> str:
    value = server.strip()
    if not value or _SERVER_RE.fullmatch(value) is None:
        raise CatalogError("Sunucu adı geçersiz. Örnek: sqlhost, sqlhost\\INSTANCE, 10.0.0.5")
    return value


def _has_control(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def braced(value: str) -> str:
    """ODBC brace quoting: `;`, `=` and braces inside the value cannot add keywords."""
    return "{" + value.replace("}", "}}") + "}"


def pick_driver(available: Sequence[str]) -> str:
    for driver in PREFERRED_DRIVERS:
        if driver in available:
            return driver
    raise CatalogError(
        "SQL Server ODBC sürücüsü bulunamadı. 'ODBC Driver 18 for SQL Server' kurun."
    )


_ALIAS_KEYS = (
    r"SOFTWARE\Microsoft\MSSQLServer\Client\ConnectTo",
    r"SOFTWARE\WOW6432Node\Microsoft\MSSQLServer\Client\ConnectTo",
)


def read_client_aliases() -> dict[str, str]:
    """SQL Server client aliases (cliconfg / SQL Server Configuration Manager) on Windows.

    Keys are lower-cased alias names, values the raw registry string such as
    ``DBMSSOCN,localhost,14333``. Empty on other platforms or when nothing is configured.
    """
    try:
        import winreg
    except ImportError:  # not Windows
        return {}
    aliases: dict[str, str] = {}
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for path in _ALIAS_KEYS:
            try:
                with winreg.OpenKey(hive, path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        if isinstance(value, str):
                            aliases.setdefault(name.strip().casefold(), value)
            except OSError:
                continue
    return aliases


def resolve_address(server: str, port: int, aliases: dict[str, str] | None = None) -> str:
    """The ODBC ``Server=`` value for a server name, port and optional client alias.

    - ``host,1435`` typed into the server field wins over the port field.
    - A TCP client alias (``DBMSSOCN,host[,port]``) is expanded, because an explicit port after
      the alias name would make the driver skip the alias lookup.
    - A named instance on the default port is resolved through SQL Browser.
    """
    value = server.strip()
    if "," in value:
        host, _, typed_port = value.partition(",")
        host = validate_server(host)
        if not typed_port.strip().isdigit():
            raise CatalogError("Sunucu adındaki port geçersiz. Örnek: sqlhost,1433")
        return f"{host},{int(typed_port)}"
    host = validate_server(value)
    alias = (read_client_aliases() if aliases is None else aliases).get(host.casefold())
    if alias:
        protocol, _, rest = alias.partition(",")
        if protocol.strip().upper() == "DBMSSOCN" and rest.strip():
            target_host, _, target_port = rest.partition(",")
            target_host = target_host.strip()
            if target_port.strip().isdigit():
                return f"{target_host},{int(target_port)}"
            return target_host if "\\" in target_host else f"{target_host},1433"
        return host  # named pipes etc.: let the driver resolve the alias itself
    if "\\" in host and port == 1433:
        return host
    return f"{host},{port}"


def build_connection_string(
    config: ConnectionConfig, driver: str, database: str = "master"
) -> str:
    address = resolve_address(config.server, config.port)
    user = config.username.strip()
    if not user or _has_control(user):
        raise CatalogError("Kullanıcı adı geçersiz.")
    if not config.password:
        raise CatalogError("Parola girilmemiş.")
    if _has_control(database):
        raise CatalogError("Veritabanı adı geçersiz.")
    parts = [
        f"Driver={{{driver}}}",
        f"Server={address}",
        f"Database={braced(database)}",
        f"UID={braced(user)}",
        f"PWD={braced(config.password)}",
        f"Encrypt={'yes' if config.encrypt else 'no'}",
        f"TrustServerCertificate={'yes' if config.trust_server_certificate else 'no'}",
        "APP=DWH Code Review",
    ]
    return ";".join(parts) + ";"


_STATE_IN_TEXT = re.compile(r"\[([0-9A-Z]{5})\]")
_NATIVE_IN_TEXT = re.compile(r"\((\d{3,5})\)")
_TLS_MARKERS = ("ssl provider", "certificate", "ssl routines", "tls", "sertifika")


def classify_error(error: Exception) -> CatalogError:
    """Map a pyodbc error to a short Turkish message."""
    args = getattr(error, "args", ())
    sqlstate = args[0] if args and isinstance(args[0], str) else ""
    detail = str(args[1]) if len(args) > 1 else str(error)
    states = set(_STATE_IN_TEXT.findall(detail)) | ({sqlstate} if sqlstate else set())
    natives = set(_NATIVE_IN_TEXT.findall(detail))
    lowered = detail.lower()

    if states & {"08001", "08S01"} and any(marker in lowered for marker in _TLS_MARKERS):
        return CatalogError(
            "SQL Server ile güvenli (TLS) bağlantı kurulamadı. "
            "'Sunucu sertifikasına güven' seçeneğini açmayı deneyin."
        )
    if "28000" in states or "18456" in natives:
        return CatalogError("SQL Server girişi reddedildi. Kullanıcı adı ve parolayı kontrol edin.")
    if "4060" in natives:
        return CatalogError("Veritabanı açılamadı veya bu kullanıcının erişimi yok.")
    if "IM002" in states:
        return CatalogError("SQL Server ODBC sürücüsü bulunamadı.")
    if states & {"08001", "08S01"}:
        return CatalogError(
            "SQL Server'a ulaşılamadı. Sunucu adı, port ve ağ erişimini kontrol edin."
        )
    if states & {"HYT00", "HYT01"}:
        return CatalogError("SQL Server zamanında yanıt vermedi (zaman aşımı).")
    if "916" in natives or "911" in natives:
        return CatalogError("Veritabanına erişim izni yok.")
    text = re.sub(r"(\[[^\]]*\])+", "", detail).strip()
    text = re.sub(r"\s*\(\d+\)\s*\(SQL\w+\)\s*$", "", text)
    short = (text[:200] + "…") if len(text) > 200 else text
    if not short:
        return CatalogError("SQL Server sorgusu başarısız oldu.")
    return CatalogError(f"SQL Server sorgusu başarısız oldu: {short}")


def object_type_codes(types: Sequence[str]) -> list[str]:
    selected = [CODE_BY_TYPE[t] for t in types if t in CODE_BY_TYPE]
    return selected or list(TYPE_CODES)


def schemas_for_database(
    database: str, schemas: Sequence[str], all_dbs: Sequence[str]
) -> list[str] | None:
    """Schema names that apply to `database`.

    Entries are "db.schema" (only that database) or "schema" (every database). Returns None
    when no schema filter is given; an empty list means "nothing in this database".
    """
    cleaned = [s.strip() for s in schemas if s and s.strip()]
    if not cleaned:
        return None
    result: list[str] = []
    for entry in cleaned:
        owner = next((db for db in all_dbs if entry.startswith(db + ".")), None)
        if owner is None:
            result.append(entry)
        elif owner == database:
            result.append(entry[len(owner) + 1 :])
    return result


def _like_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")
    )


def build_object_sql(
    query: ObjectQuery, schemas: list[str] | None
) -> tuple[str, list[Any]]:
    """Object list SQL for the current database plus its parameters."""
    codes = object_type_codes(query.types)
    params: list[Any] = list(codes)
    sql = [
        "SELECT s.name, o.name, RTRIM(o.type),",
        " DATEADD(minute, DATEDIFF(minute, GETDATE(), GETUTCDATE()), o.create_date),",
        " DATEADD(minute, DATEDIFF(minute, GETDATE(), GETUTCDATE()), o.modify_date)",
        "FROM sys.objects o INNER JOIN sys.schemas s ON s.schema_id = o.schema_id",
        f"WHERE o.is_ms_shipped = 0 AND o.type IN ({', '.join('?' * len(codes))})",
    ]
    if schemas is not None:
        sql.append(f"AND s.name IN ({', '.join('?' * len(schemas))})")
        params.extend(schemas)
    for column, start, end in (
        ("o.create_date", query.created_from, query.created_to),
        ("o.modify_date", query.modified_from, query.modified_to),
    ):
        if start is not None:
            sql.append(f"AND {column} >= ?")
            params.append(datetime.combine(start, datetime.min.time()))
        if end is not None:  # inclusive: before the next day
            sql.append(f"AND {column} < ?")
            params.append(datetime.combine(end + timedelta(days=1), datetime.min.time()))
    search = (query.search or "").strip()
    if search:
        sql.append("AND LOWER(o.name) LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(search.lower())}%")
    sql.append("ORDER BY s.name, o.name")
    return "\n".join(sql), params


LIST_DATABASES_SQL = (
    "SELECT name FROM sys.databases WHERE state = 0 AND HAS_DBACCESS(name) = 1 "
    "AND name NOT IN ('master', 'tempdb', 'model', 'msdb') ORDER BY name"
)

LIST_SCHEMAS_SQL = (
    "SELECT s.name, COUNT(*) FROM sys.objects o "
    "INNER JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "WHERE o.is_ms_shipped = 0 AND o.type IN ('P', 'V', 'FN', 'IF', 'TF') "
    "GROUP BY s.name ORDER BY s.name"
)

DEFINITION_SQL = "SELECT OBJECT_DEFINITION(OBJECT_ID(?))"


# ------------------------------------------------------------------ pyodbc implementation
class PyodbcCatalog:
    """`Catalog` over pyodbc."""

    def _connect(self, config: ConnectionConfig) -> Any:
        try:
            import pyodbc
        except ImportError:  # pragma: no cover - pyodbc is a hard dependency
            raise CatalogError("pyodbc kurulu değil.") from None
        driver = pick_driver(pyodbc.drivers())
        conn_str = build_connection_string(config, driver)
        try:
            connection = pyodbc.connect(
                conn_str, timeout=SQL_LOGIN_TIMEOUT_SECONDS, autocommit=True
            )
        except pyodbc.Error as error:
            classified = classify_error(error)
            # A closed port or unknown host surfaces only as login timeout HYT00.
            if "zaman aşımı" in str(classified):
                raise CatalogError(
                    "SQL Server'a ulaşılamadı (bağlantı zaman aşımı). "
                    "Sunucu adı, port ve ağ erişimini kontrol edin."
                ) from None
            raise classified from None
        connection.timeout = SQL_QUERY_TIMEOUT_SECONDS
        return connection

    @staticmethod
    def _use(cursor: Any, database: str) -> None:
        if is_system_database(database):
            raise CatalogError("Sistem veritabanları incelenemez.")
        try:
            target = quote_ident(database)
        except ValueError as error:
            raise CatalogError(str(error)) from None
        # A database name cannot be a bound parameter; quote_ident escapes it and rejects invalid names.
        cursor.execute("USE " + target)  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query, python.lang.security.audit.formatted-sql-query.formatted-sql-query

    def _run(self, config: ConnectionConfig, work: Any) -> Any:
        import pyodbc

        try:
            with closing(self._connect(config)) as connection:
                return work(connection.cursor())
        except pyodbc.Error as error:
            raise classify_error(error) from None

    def probe(self, config: ConnectionConfig) -> ProbeResult:
        def work(cursor: Any) -> ProbeResult:
            cursor.execute("SELECT @@VERSION")
            version = str(cursor.fetchone()[0] or "").splitlines()[0].strip()
            cursor.execute(LIST_DATABASES_SQL)
            count = len(cursor.fetchall())
            return ProbeResult(version, count)

        return self._run(config, work)

    def list_databases(self, config: ConnectionConfig) -> list[str]:
        def work(cursor: Any) -> list[str]:
            cursor.execute(LIST_DATABASES_SQL)
            return [str(row[0]) for row in cursor.fetchall() if not is_system_database(row[0])]

        return self._run(config, work)

    def list_schemas(
        self, config: ConnectionConfig, databases: Sequence[str]
    ) -> list[tuple[str, str, int]]:
        def work(cursor: Any) -> list[tuple[str, str, int]]:
            result: list[tuple[str, str, int]] = []
            for database in databases:
                self._use(cursor, database)
                cursor.execute(LIST_SCHEMAS_SQL)
                result.extend((database, str(r[0]), int(r[1])) for r in cursor.fetchall())
            return result

        return self._run(config, work)

    def list_objects(self, config: ConnectionConfig, query: ObjectQuery) -> list[CatalogObject]:
        def work(cursor: Any) -> list[CatalogObject]:
            result: list[CatalogObject] = []
            for database in query.databases:
                schemas = schemas_for_database(database, query.schemas, query.databases)
                if schemas is not None and not schemas:
                    continue
                self._use(cursor, database)
                sql, params = build_object_sql(query, schemas)
                cursor.execute(sql, *params)
                for row in cursor.fetchall():
                    result.append(
                        CatalogObject(
                            database=database,
                            schema=str(row[0]),
                            name=str(row[1]),
                            type=TYPE_CODES.get(str(row[2]).strip(), str(row[2]).strip()),
                            create_date=row[3],
                            modify_date=row[4],
                        )
                    )
            return result

        return self._run(config, work)

    @contextmanager
    def open_reader(self, config: ConnectionConfig) -> Iterator[DefinitionReader]:
        connection = self._connect(config)
        try:
            yield _PyodbcReader(connection.cursor(), self._use)
        finally:
            connection.close()


class _PyodbcReader:
    def __init__(self, cursor: Any, use: Any) -> None:
        self._cursor = cursor
        self._use = use
        self._current: str | None = None
        self._collector = MetadataCollector(cursor)

    def describe(
        self,
        database: str,
        schema: str,
        name: str,
        object_type: str,
        sql: str,
        masked: str,
        extra: Sequence[tuple[str, str, str]] = (),
    ) -> ObjectMetadata:
        """Catalog metadata of the object (cached per reader, i.e. per analysis run)."""
        return self._collector.describe(database, schema, name, object_type, sql, masked, extra)

    def fetch(self, database: str, schema: str, name: str) -> str | None:
        import pyodbc

        try:
            if self._current != database:
                self._use(self._cursor, database)
                self._current = database
            self._cursor.execute(DEFINITION_SQL, f"{quote_ident(schema)}.{quote_ident(name)}")
            row = self._cursor.fetchone()
        except pyodbc.Error as error:
            raise classify_error(error) from None
        if not row or row[0] is None:
            return None
        return str(row[0])


_catalog: Catalog = PyodbcCatalog()


def get_catalog() -> Catalog:
    """FastAPI dependency; tests override it with a fake catalog."""
    return _catalog
