"""Catalog metadata of the objects a SQL object references (read-only).

`MetadataCollector` asks SQL Server, for one analysed object, which objects it references
(`sys.dm_sql_referenced_entities` plus names parsed from the comment-masked text), resolves
each to its `sys.objects` type and, for user tables and views, reads columns; for user tables
also the SCD flag (EdwValidFrom + EdwValidUntil columns) and the partitioning. One collector
lives for one analysis run, so objects referenced by many procedures are read once.

Every catalog query runs through `EXEC [db].sys.sp_executesql` so the connection's current
database never changes; all user values are `?` parameters, the only identifier placed in SQL
text is the bracket-quoted database name (checked against `sys.databases` first).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("dwhcr.metadata")

MAX_TABLE_COLUMNS = 80
MAX_VIEW_COLUMNS = 1000
MAX_CANDIDATES = 80
LLM_BLOCK_LIMIT = 6000

Key = tuple[str, str, str]  # (database, schema, name), lower-cased

TYPE_LABELS = {
    "U": "TABLO",
    "V": "VIEW",
    "P": "PROSEDÜR",
    "FN": "SKALER FONKSİYON",
    "IF": "INLINE FONKSİYON",
    "TF": "TABLO FONKSİYONU",
    "SN": "SYNONYM",
    "S": "SİSTEM TABLOSU",
    "IT": "İÇ TABLO",
}

SYSTEM_DATABASES = frozenset({"master", "tempdb", "model", "msdb"})


# ------------------------------------------------------------------ value types
def format_column_type(
    type_name: str, max_length: int | None, precision: int | None, scale: int | None
) -> str:
    """`varchar(50)`, `nvarchar(max)`, `decimal(18,2)`, `datetime2(3)`, `int`..."""
    t = (type_name or "").strip().lower()
    length = max_length if max_length is not None else 0
    if t in ("varchar", "varbinary", "char", "binary"):
        return f"{type_name}(max)" if length < 0 else f"{type_name}({length})"
    if t in ("nvarchar", "nchar"):
        return f"{type_name}(max)" if length < 0 else f"{type_name}({length // 2})"
    if t in ("decimal", "numeric"):
        return f"{type_name}({precision},{scale})"
    if t in ("datetime2", "time", "datetimeoffset") and scale is not None and scale != 7:
        return f"{type_name}({scale})"
    return type_name


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type_name: str
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None

    @property
    def type_label(self) -> str:
        return format_column_type(self.type_name, self.max_length, self.precision, self.scale)

    @property
    def type_key(self) -> tuple[str, int | None, int | None, int | None]:
        return (self.type_name.lower(), self.max_length, self.precision, self.scale)


@dataclass(frozen=True, slots=True)
class PartitionInfo:
    column: str | None
    column_type: str | None
    function: str
    parameter_type: str | None
    boundary: str  # "LEFT" | "RIGHT"
    scheme: str


@dataclass(slots=True)
class CatalogEntry:
    database: str
    schema: str
    name: str
    type: str  # sys.objects.type, e.g. "U", "V", "P"
    columns: list[ColumnInfo] = field(default_factory=list)
    column_count: int = 0
    is_scd: bool = False
    partition: PartitionInfo | None = None

    @property
    def label(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"

    @property
    def key(self) -> Key:
        return make_key(self.database, self.schema, self.name)


def make_key(database: str, schema: str, name: str) -> Key:
    return (database.lower(), schema.lower(), name.lower())


@dataclass(slots=True)
class ObjectMetadata:
    """Catalog facts about one analysed object; `available` is False when nothing was read."""

    available: bool = False
    entries: dict[Key, CatalogEntry] = field(default_factory=dict)
    referenced: list[Key] = field(default_factory=list)
    aliases: dict[Key, Key] = field(default_factory=dict)  # written name -> entry key
    self_entry: CatalogEntry | None = None
    # "<X>" (lower-cased) for every table in EDWSKEY/EDW/ERPEDW that has both <X>Id and <X>Nk
    surrogate_key_bases: frozenset[str] = frozenset()
    notes: list[str] = field(default_factory=list)

    def add(self, entry: CatalogEntry, referenced: bool = True) -> None:
        self.entries[entry.key] = entry
        if referenced and entry.key not in self.referenced:
            self.referenced.append(entry.key)

    def lookup(self, database: str, schema: str | None, name: str) -> CatalogEntry | None:
        """The entry for a written name; a missing schema means the default (dbo)."""
        for candidate in (
            make_key(database, schema or "", name),
            make_key(database, schema or "dbo", name),
        ):
            key = self.aliases.get(candidate, candidate)
            if key in self.entries:
                return self.entries[key]
        return None

    def resolve(self, parts: Sequence[str], default_database: str) -> CatalogEntry | None:
        target = split_name(parts, default_database)
        return self.lookup(*target) if target else None

    def referenced_entries(self) -> list[CatalogEntry]:
        return [self.entries[key] for key in self.referenced if key in self.entries]

    @property
    def references_scd_table(self) -> bool:
        return any(e.type == "U" and e.is_scd for e in self.referenced_entries())

    @property
    def references_partitioned_table(self) -> bool:
        return any(e.type == "U" and e.partition is not None for e in self.referenced_entries())


# ------------------------------------------------------------------ SCD definition
# A user table is SCD only when (RULES_SPEC_v13 section 0):
# - EDW / ERPEDW: it has EdwValidFrom + EdwValidUntil AND `[db].scd.mrg<Schema><Table>` exists;
# - EDWDM: it has EdwValidFrom + EdwValidUntil;
# - any other database (EDWSKEY key maps, EDWLRY landing, EDWSTG...): never.
SCD_MRG_DATABASES = frozenset({"edw", "erpedw"})
SCD_COLUMN_DATABASES = frozenset({"edwdm"})


def has_validity_columns(column_names: Iterable[str]) -> bool:
    return {"edwvalidfrom", "edwvaliduntil"} <= {c.lower() for c in column_names}


def is_scd_table(database: str, has_columns: bool, has_mrg_procedure: bool) -> bool:
    db = database.lower()
    if not has_columns:
        return False
    if db in SCD_MRG_DATABASES:
        return has_mrg_procedure
    return db in SCD_COLUMN_DATABASES


def empty_metadata(note: str | None = None) -> ObjectMetadata:
    return ObjectMetadata(available=False, notes=[note] if note else [])


def metadata_precondition_met(name: str | None, metadata: ObjectMetadata) -> bool:
    if not name:
        return True
    if name == "references_scd_table":
        return metadata.references_scd_table
    if name == "references_partitioned_table":
        return metadata.references_partitioned_table
    return False


# ------------------------------------------------------------------ SQL name parsing
_IDENT_START = re.compile(r"\[|\"|[A-Za-z_@#$À-￿]")
_BARE = re.compile(r"[A-Za-z_@#$À-￿][\w@#$]*")


def _read_ident(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text):
        return None
    ch = text[pos]
    if ch in "[\"":
        close = "]" if ch == "[" else '"'
        j = pos + 1
        buf: list[str] = []
        while j < len(text):
            if text[j] == close:
                if j + 1 < len(text) and text[j + 1] == close:
                    buf.append(close)
                    j += 2
                    continue
                return "".join(buf), j + 1
            if text[j] in "\r\n" and close == '"':
                return None
            buf.append(text[j])
            j += 1
        return None
    match = _BARE.match(text, pos)
    if match is None:
        return None
    return match.group(0), match.end()


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def parse_name_at(text: str, pos: int) -> tuple[list[str], int] | None:
    """A 1-4 part (optionally bracketed) name starting at `pos` -> (parts, end offset).

    `db..table` gives an empty schema part. Whitespace around the dots is allowed.
    """
    first = _read_ident(text, pos)
    if first is None:
        return None
    parts = [first[0]]
    end = first[1]
    while len(parts) < 4:
        probe = _skip_ws(text, end)
        if probe >= len(text) or text[probe] != ".":
            break
        nxt = _skip_ws(text, probe + 1)
        if nxt < len(text) and text[nxt] == "." and len(parts) < 3:
            parts.append("")  # db..name
            end = nxt
            continue
        ident = _read_ident(text, nxt)
        if ident is None:
            break  # "t.*" or a trailing dot: the name ends before the dot
        parts.append(ident[0])
        end = ident[1]
    return parts, end


def split_name(parts: Sequence[str], default_database: str) -> tuple[str, str | None, str] | None:
    """(database, schema or None, name) for 1-3 part names; 4-part (linked server) -> None."""
    cleaned = [p.strip() for p in parts]
    if not cleaned or not cleaned[-1] or len(cleaned) > 3:
        return None
    if len(cleaned) == 1:
        return default_database, None, cleaned[0]
    if len(cleaned) == 2:
        return default_database, cleaned[0] or None, cleaned[1]
    return cleaned[0] or default_database, cleaned[1] or None, cleaned[2]


def parse_name_text(value: str) -> list[str] | None:
    """Parts of a whole string such as `EDW.TRX.[Fact]`; None if it is not just a name."""
    stripped = value.strip()
    parsed = parse_name_at(stripped, 0)
    if parsed is None or parsed[1] != len(stripped):
        return None
    return parsed[0]


_CTE_RE = re.compile(
    r"(?:\bWITH|,)\s*(\[[^\]]+\]|[A-Za-z_]\w*)\s*(?:\([^()]*\))?\s*AS\s*\(", re.IGNORECASE
)


def cte_names(masked: str) -> set[str]:
    names: set[str] = set()
    for match in _CTE_RE.finditer(masked):
        name = match.group(1).strip("[]").lower()
        if name not in ("nolock", "readuncommitted"):
            names.add(name)
    return names


_REFERENCE_KEYWORDS = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|TRUNCATE\s+TABLE|MERGE(?:\s+INTO)?|USING|"
    r"EXEC(?:UTE)?(?:\s+@\w+\s*=)?)\s+",
    re.IGNORECASE,
)
_TABLE_PARAMS = re.compile(
    r"@(?:EdwTableName|StgTableName|TableName)\s*=\s*N?'([^']*)'", re.IGNORECASE
)
_NOT_NAMES = frozenset({"select", "set", "values", "default", "table", "statistics", "into"})
_NAME_PART = r"(?:\[(?:[^\]]|\]\])+\]|[A-Za-z_][\w$#@]*)"
_FUNCTION_CALL = re.compile(
    rf"(?<![\w.\]@#$])({_NAME_PART}\s*\.\s*{_NAME_PART}(?:\s*\.\s*{_NAME_PART})?)\s*\("
)


def text_references(sql: str, masked: str) -> list[list[str]]:
    """Object names referenced in the code text (comments and strings excluded).

    Names after FROM/JOIN/UPDATE/INTO/TRUNCATE TABLE/MERGE/USING/EXEC plus the string values
    of `@EdwTableName=`, `@StgTableName=` and `@TableName=` arguments. #temp tables, @table
    variables and CTE names are skipped. Unresolvable names (aliases...) are dropped later.
    """
    ctes = cte_names(masked)
    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []

    def add(parts: list[str]) -> None:
        if not parts or not parts[-1] or parts[0][:1] in ("#", "@"):
            return
        if len(parts) == 1 and (parts[0].lower() in ctes or parts[0].lower() in _NOT_NAMES):
            return
        key = tuple(p.lower() for p in parts)
        if key not in seen and len(result) < MAX_CANDIDATES:
            seen.add(key)
            result.append(parts)

    for match in _REFERENCE_KEYWORDS.finditer(masked):
        parsed = parse_name_at(masked, match.end())
        if parsed is not None:
            add(parsed[0])
    for match in _TABLE_PARAMS.finditer(sql):
        if masked[match.start()] != "@":  # inside a comment
            continue
        parts = parse_name_text(match.group(1))
        if parts:
            add(parts)
    for match in _FUNCTION_CALL.finditer(masked):  # schema-qualified (scalar) function calls
        parts = parse_name_text(match.group(1))
        if parts and len(parts) >= 2:
            add(parts)
    return result


# ------------------------------------------------------------------ LLM block
def _entry_line(entry: CatalogEntry, column_cap: int) -> str:
    flags = [TYPE_LABELS.get(entry.type, entry.type)]
    if entry.is_scd:
        flags.append("SCD")
    if entry.partition is not None:
        flags.append("PARTITION")
    line = f"- {entry.label} [{', '.join(flags)}]"
    if entry.columns:
        shown = entry.columns[:column_cap]
        cols = ", ".join(f"{c.name} {c.type_label}" for c in shown)
        hidden = max(entry.column_count, len(entry.columns)) - len(shown)
        if hidden > 0:
            cols = f"{cols}, … (+{hidden} kolon)" if cols else f"{hidden} kolon"
        line += f" kolonlar: {cols}"
    if entry.partition is not None:
        p = entry.partition
        column = f"{p.column} {p.column_type}" if p.column else "?"
        parameter = p.parameter_type or "?"
        line += (
            f"\n  partition: kolon {column}, fonksiyon {p.function}({parameter}), "
            f"RANGE {p.boundary}, şema {p.scheme}"
        )
    return line


def format_for_llm(metadata: ObjectMetadata, limit: int = LLM_BLOCK_LIMIT) -> str:
    """Compact Turkish "KATALOG METADATASI" block, shortened to `limit` characters."""
    header = "KATALOG METADATASI (SQL Server kataloğundan, referans verilen nesneler):"
    if not metadata.available:
        reason = "; ".join(metadata.notes) or "katalog bilgisi yok"
        return (
            f"KATALOG METADATASI: alınamadı ({reason}). Metadata gerektiren maddelerde "
            "tahmin yürütme; yalnız metinden kesin olanları raporla."
        )
    entries = metadata.referenced_entries()
    for cap in (MAX_TABLE_COLUMNS, 40, 20, 10, 5, 0):
        lines = [header]
        lines += [_entry_line(e, cap) for e in entries] or ["- (referans verilen nesne bulunamadı)"]
        if metadata.self_entry is not None and metadata.self_entry.columns:
            own = _entry_line(metadata.self_entry, cap).removeprefix("- ")
            lines.append(f"Bu nesne: {own}")
        if metadata.notes:
            lines.append("Not: " + "; ".join(metadata.notes))
        text = "\n".join(lines)
        if len(text) <= limit:
            return text
    return text[: limit - 1] + "…"


# ------------------------------------------------------------------ collector
class Cursor(Protocol):
    def execute(self, sql: str, *params: Any) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...


DATABASES_SQL = "SELECT name FROM sys.databases WHERE state = 0 AND HAS_DBACCESS(name) = 1"

REFERENCED_SQL = (
    "SELECT DISTINCT referenced_server_name, referenced_database_name, "
    "referenced_schema_name, referenced_entity_name "
    "FROM sys.dm_sql_referenced_entities(@p0, N'OBJECT')"
)

RESOLVE_SQL = (
    "SELECT o.object_id, RTRIM(o.type), s.name, o.name, sn.base_object_name "
    "FROM sys.objects o INNER JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "LEFT JOIN sys.synonyms sn ON sn.object_id = o.object_id "
    "WHERE o.object_id = OBJECT_ID(@p0)"
)

MRG_PROCEDURE_SQL = "SELECT OBJECT_ID(@p0, N'P')"

COLUMNS_SQL = (
    "SELECT c.name, t.name, c.max_length, c.precision, c.scale "
    "FROM sys.columns c INNER JOIN sys.types t ON t.user_type_id = c.user_type_id "
    "WHERE c.object_id = @p0 ORDER BY c.column_id"
)

# Key/LKP tables carrying both <X>Id and <X>Nk -> "<X>" (DWH-ID-01 surrogate key detection).
SURROGATE_KEY_DATABASES = ("EDWSKEY", "EDW", "ERPEDW")
SURROGATE_BASES_SQL = (
    "SELECT DISTINCT LEFT(c.name, LEN(c.name) - 2) FROM sys.columns c "
    "INNER JOIN sys.tables t ON t.object_id = c.object_id "
    "WHERE c.name LIKE N'%Id' AND LEN(c.name) > 2 AND EXISTS (SELECT 1 FROM sys.columns n "
    "WHERE n.object_id = c.object_id AND n.name = LEFT(c.name, LEN(c.name) - 2) + N'Nk')"
)

PARTITION_SQL = (
    "SELECT TOP 1 c.name, ct.name, c.max_length, c.precision, c.scale, pf.name, pt.name, "
    "pp.max_length, pp.precision, pp.scale, pf.boundary_value_on_right, ps.name "
    "FROM sys.indexes i "
    "INNER JOIN sys.partition_schemes ps ON ps.data_space_id = i.data_space_id "
    "INNER JOIN sys.partition_functions pf ON pf.function_id = ps.function_id "
    "LEFT JOIN sys.partition_parameters pp ON pp.function_id = pf.function_id "
    "AND pp.parameter_id = 1 "
    "LEFT JOIN sys.types pt ON pt.user_type_id = pp.user_type_id "
    "LEFT JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id "
    "AND ic.partition_ordinal = 1 "
    "LEFT JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
    "LEFT JOIN sys.types ct ON ct.user_type_id = c.user_type_id "
    "WHERE i.object_id = @p0 AND i.index_id IN (0, 1) ORDER BY i.index_id"
)


def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def _in_database(database: str, sql: str, param_types: Sequence[str]) -> str:
    """`EXEC [db].sys.sp_executesql` wrapper; the values are bound as `?` parameters."""
    declared = ", ".join(f"@p{i} {t}" for i, t in enumerate(param_types))
    args = ", ".join(f"@p{i} = ?" for i in range(len(param_types)))
    body = sql.replace("'", "''")
    return f"EXEC {quote_ident(database)}.sys.sp_executesql N'{body}', N'{declared}', {args}"


def _short_error(error: Exception) -> str:
    text = str(getattr(error, "args", [None, ""])[-1] if getattr(error, "args", None) else error)
    text = re.sub(r"(\[[^\]]*\])+", "", text).strip()
    text = re.sub(r"\s*\(\d+\)\s*\(SQL\w+\)\s*$", "", text)
    return (text[:150] + "…") if len(text) > 150 else (text or type(error).__name__)


class MetadataCollector:
    """Reads catalog metadata over one cursor; caches resolved objects for its lifetime."""

    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor
        self._databases: dict[str, str] | None = None
        self._resolved: dict[Key, CatalogEntry | None] = {}
        self._surrogate_bases: frozenset[str] | None = None

    # -------------------------------------------------------------- public
    def describe(
        self,
        database: str,
        schema: str,
        name: str,
        object_type: str,
        sql: str,
        masked: str,
        extra: Iterable[tuple[str, str, str]] = (),
    ) -> ObjectMetadata:
        metadata = ObjectMetadata(available=True)
        try:
            databases = self._database_map()
        except Exception as error:  # noqa: BLE001 - metadata must never fail a check
            logger.info("metadata unavailable for %s.%s.%s: %s", database, schema, name, error)
            return empty_metadata(f"Katalog metadatası alınamadı: {_short_error(error)}")
        home = databases.get(database.lower(), database)
        metadata.surrogate_key_bases = self._surrogate_key_bases(databases)
        candidates: list[tuple[str, str | None, str]] = []
        try:
            candidates.extend(self._referenced_entities(home, schema, name))
        except Exception as error:  # noqa: BLE001 - fails for some objects (temp tables...)
            logger.debug("dm_sql_referenced_entities failed for %s.%s: %s", schema, name, error)
            metadata.notes.append(
                "sys.dm_sql_referenced_entities çalışmadı; referanslar metinden ayrıştırıldı"
            )
        for parts in text_references(sql, masked):
            target = split_name(parts, home)
            if target is not None:
                candidates.append(target)

        own_key = make_key(home, schema, name)
        failures = 0
        for ref_db, ref_schema, ref_name in candidates:
            try:
                entry = self._resolve(databases, ref_db, ref_schema, ref_name, metadata)
            except Exception as error:  # noqa: BLE001
                failures += 1
                logger.debug("resolve %s.%s.%s failed: %s", ref_db, ref_schema, ref_name, error)
                continue
            if entry is not None and entry.key != own_key:
                metadata.add(entry)
        for ref_db, ref_schema, ref_name in extra:
            try:
                entry = self._resolve(databases, ref_db, ref_schema, ref_name, metadata)
            except Exception:  # noqa: BLE001
                failures += 1
                continue
            if entry is not None:
                metadata.add(entry, referenced=False)
        if object_type == "VIEW":
            try:
                metadata.self_entry = self._resolve(databases, home, schema, name, metadata)
            except Exception:  # noqa: BLE001
                failures += 1
        if failures:
            metadata.notes.append(f"{failures} nesnenin katalog bilgisi okunamadı")
        return metadata

    # -------------------------------------------------------------- internals
    def _surrogate_key_bases(self, databases: dict[str, str]) -> frozenset[str]:
        """Computed once per collector (analysis run): one query per key/EDW database."""
        if self._surrogate_bases is None:
            bases: set[str] = set()
            for name in SURROGATE_KEY_DATABASES:
                real = databases.get(name.lower())
                if real is None:
                    continue
                body = SURROGATE_BASES_SQL.replace("'", "''")
                try:
                    self._cursor.execute(f"EXEC {quote_ident(real)}.sys.sp_executesql N'{body}'")
                    bases.update(str(row[0]).lower() for row in self._cursor.fetchall() if row[0])
                except Exception as error:  # noqa: BLE001 - optional information
                    logger.info("surrogate key list of %s failed: %s", real, error)
            self._surrogate_bases = frozenset(bases)
        return self._surrogate_bases

    def _query(self, database: str, sql: str, *params: tuple[str, Any]) -> list[Any]:
        statement = _in_database(database, sql, [t for t, _ in params])
        self._cursor.execute(statement, *[value for _, value in params])
        return list(self._cursor.fetchall())

    def _database_map(self) -> dict[str, str]:
        if self._databases is None:
            self._cursor.execute(DATABASES_SQL)
            self._databases = {
                str(row[0]).lower(): str(row[0])
                for row in self._cursor.fetchall()
                if str(row[0]).lower() not in SYSTEM_DATABASES
            }
        return self._databases

    def _referenced_entities(
        self, database: str, schema: str, name: str
    ) -> list[tuple[str, str | None, str]]:
        rows = self._query(
            database, REFERENCED_SQL, ("nvarchar(600)", f"{quote_ident(schema)}.{quote_ident(name)}")
        )
        result: list[tuple[str, str | None, str]] = []
        for server, ref_db, ref_schema, ref_name in rows:
            if server or not ref_name:
                continue
            result.append((str(ref_db or database), str(ref_schema) if ref_schema else None,
                           str(ref_name)))
        return result

    def _resolve(
        self,
        databases: dict[str, str],
        database: str,
        schema: str | None,
        name: str,
        metadata: ObjectMetadata,
        depth: int = 0,
    ) -> CatalogEntry | None:
        real_db = databases.get(database.lower())
        if real_db is None or name.startswith(("#", "@")):
            return None
        written = make_key(real_db, schema or "", name)
        if written in self._resolved:
            entry = self._resolved[written]
        else:
            entry = self._load(databases, real_db, schema, name, metadata, depth)
            self._resolved[written] = entry
        if entry is not None:
            if written != entry.key:
                metadata.aliases[written] = entry.key
            metadata.entries.setdefault(entry.key, entry)
        return entry

    def _load(
        self,
        databases: dict[str, str],
        database: str,
        schema: str | None,
        name: str,
        metadata: ObjectMetadata,
        depth: int,
    ) -> CatalogEntry | None:
        written = f"{quote_ident(schema)}.{quote_ident(name)}" if schema else quote_ident(name)
        rows = self._query(database, RESOLVE_SQL, ("nvarchar(600)", written))
        if not rows:
            return None
        object_id, type_code, real_schema, real_name, base_object = rows[0]
        type_code = str(type_code).strip().upper()
        if type_code == "SN" and base_object and depth == 0:
            parts = parse_name_text(str(base_object))
            target = split_name(parts, database) if parts else None
            if target is not None:
                return self._resolve(databases, *target, metadata, depth=1)
        entry = CatalogEntry(database, str(real_schema), str(real_name), type_code)
        if type_code in ("U", "V"):
            columns = [
                ColumnInfo(str(r[0]), str(r[1]), _int(r[2]), _int(r[3]), _int(r[4]))
                for r in self._query(database, COLUMNS_SQL, ("int", int(object_id)))
            ]
            names = {c.name.lower() for c in columns}
            entry.column_count = len(columns)
            if type_code == "U":
                entry.is_scd = self._is_scd(database, entry.schema, entry.name, names)
            cap = MAX_TABLE_COLUMNS if type_code == "U" else MAX_VIEW_COLUMNS
            entry.columns = columns[:cap]
        if type_code == "U":
            rows = self._query(database, PARTITION_SQL, ("int", int(object_id)))
            if rows:
                r = rows[0]
                entry.partition = PartitionInfo(
                    column=str(r[0]) if r[0] is not None else None,
                    column_type=(
                        format_column_type(str(r[1]), _int(r[2]), _int(r[3]), _int(r[4]))
                        if r[1] is not None
                        else None
                    ),
                    function=str(r[5]),
                    parameter_type=(
                        format_column_type(str(r[6]), _int(r[7]), _int(r[8]), _int(r[9]))
                        if r[6] is not None
                        else None
                    ),
                    boundary="RIGHT" if r[10] else "LEFT",
                    scheme=str(r[11]),
                )
        return entry

    def _is_scd(self, database: str, schema: str, name: str, column_names: set[str]) -> bool:
        if not has_validity_columns(column_names):
            return False
        mrg_procedure = False
        if database.lower() in SCD_MRG_DATABASES:
            rows = self._query(
                database, MRG_PROCEDURE_SQL, ("nvarchar(600)", f"[scd].[mrg{schema}{name}]")
            )
            mrg_procedure = bool(rows and rows[0][0] is not None)
        return is_scd_table(database, True, mrg_procedure)


def _int(value: Any) -> int | None:
    return int(value) if value is not None else None
