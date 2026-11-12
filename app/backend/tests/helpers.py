"""Builders for fake catalog metadata."""

from app.services.metadata import CatalogEntry, ColumnInfo, ObjectMetadata, PartitionInfo


def col(name: str, type_name: str = "int", max_length: int | None = 4,
        precision: int | None = 10, scale: int | None = 0) -> ColumnInfo:
    return ColumnInfo(name, type_name, max_length, precision, scale)


def varchar(name: str, length: int = 50) -> ColumnInfo:
    return ColumnInfo(name, "varchar", length, 0, 0)


def entry(database: str, schema: str, name: str, type_code: str = "U",
          columns: list[ColumnInfo] | None = None,
          partition: PartitionInfo | None = None) -> CatalogEntry:
    cols = list(columns or [])
    names = {c.name.lower() for c in cols}
    return CatalogEntry(
        database, schema, name, type_code, cols, len(cols),
        is_scd=type_code == "U" and {"edwvalidfrom", "edwvaliduntil"} <= names,
        partition=partition,
    )


def metadata(*entries: CatalogEntry, own: CatalogEntry | None = None,
             related: list[CatalogEntry] | None = None) -> ObjectMetadata:
    result = ObjectMetadata(available=True)
    for item in entries:
        result.add(item)
    for item in related or []:
        result.add(item, referenced=False)
    result.self_entry = own
    return result
