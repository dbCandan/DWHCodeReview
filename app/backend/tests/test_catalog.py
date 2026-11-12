from datetime import date, datetime

import pytest

from app.services.catalog import (
    CatalogError,
    ConnectionConfig,
    ObjectQuery,
    build_connection_string,
    build_object_sql,
    classify_error,
    pick_driver,
    schemas_for_database,
)


class FakePyodbcError(Exception):
    pass


def config(**kwargs) -> ConnectionConfig:  # type: ignore[no-untyped-def]
    values = {"server": "sqlhost", "port": 1433, "username": "sa", "password": "p;w}d="}
    values.update(kwargs)
    return ConnectionConfig(**values)


def test_connection_string_braces_values() -> None:
    text = build_connection_string(config(), "ODBC Driver 18 for SQL Server")
    assert "Driver={ODBC Driver 18 for SQL Server}" in text
    assert "Server=sqlhost,1433" in text
    assert "PWD={p;w}}d=}" in text
    assert "UID={sa}" in text and "Encrypt=yes" in text and "TrustServerCertificate=yes" in text


def test_named_instance_and_invalid_server() -> None:
    text = build_connection_string(config(server="host\\SQL2022"), "D")
    assert "Server=host\\SQL2022;" in text
    assert "Server=host\\SQL2022,1500" in build_connection_string(config(server="host\\SQL2022", port=1500), "D")
    with pytest.raises(CatalogError):
        build_connection_string(config(server="host;Database=x"), "D")
    with pytest.raises(CatalogError):
        build_connection_string(config(password=""), "D")


def test_pick_driver() -> None:
    assert pick_driver(["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"]) == (
        "ODBC Driver 18 for SQL Server"
    )
    assert pick_driver(["ODBC Driver 17 for SQL Server"]) == "ODBC Driver 17 for SQL Server"
    with pytest.raises(CatalogError):
        pick_driver(["SQL Server"])


def test_schema_filter() -> None:
    dbs = ["DWH", "Stage"]
    assert schemas_for_database("DWH", [], dbs) is None
    assert schemas_for_database("DWH", ["DWH.dbo", "etl"], dbs) == ["dbo", "etl"]
    assert schemas_for_database("Stage", ["DWH.dbo", "etl"], dbs) == ["etl"]
    assert schemas_for_database("Stage", ["DWH.dbo"], dbs) == []


def test_object_sql_all_filters() -> None:
    query = ObjectQuery(
        databases=["DWH"],
        types=["PROCEDURE", "VIEW"],
        created_from=date(2024, 1, 1),
        created_to=date(2024, 1, 31),
        modified_to=date(2024, 6, 30),
        search="Load_%",
    )
    sql, params = build_object_sql(query, ["dbo"])
    assert sql.count("?") == len(params)
    assert "o.type IN (?, ?)" in sql and "s.name IN (?)" in sql
    assert "o.create_date >= ?" in sql and "o.create_date < ?" in sql and "o.modify_date < ?" in sql
    assert "o.modify_date >= ?" not in sql
    assert params[:3] == ["P", "V", "dbo"]
    assert params[3] == datetime(2024, 1, 1)
    assert params[4] == datetime(2024, 2, 1)  # inclusive end date
    assert params[5] == datetime(2024, 7, 1)
    assert params[6] == "%load\\_\\%%"


def test_object_sql_defaults_to_all_types() -> None:
    sql, params = build_object_sql(ObjectQuery(databases=["DWH"]), None)
    assert params == ["P", "V", "FN", "IF", "TF"]
    assert "s.name IN" not in sql and "LIKE" not in sql


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("28000", "[28000] [Microsoft]Login failed for user 'sa'. (18456)"), "girişi reddedildi"),
        (("08001", "[08001] TCP Provider: No such host is known."), "ulaşılamadı"),
        (("08001", "[08001] SSL Provider: The certificate chain was issued by an authority"), "TLS"),
        (("HYT00", "[HYT00] Query timeout expired"), "zaman aşımı"),
        (("42000", "[42000] [Microsoft][SQL Server]Incorrect syntax near 'x'. (102) (SQLExecDirectW)"),
         "Incorrect syntax"),
    ],
)
def test_classify_error(args: tuple[str, str], expected: str) -> None:
    assert expected in str(classify_error(FakePyodbcError(*args)))


# ------------------------------------------------------------------ client aliases / address
def test_resolve_address_expands_tcp_alias():
    from app.services.catalog import resolve_address

    aliases = {"sqldocker": "DBMSSOCN,localhost,14333"}
    assert resolve_address("SQLDOCKER", 1433, aliases) == "localhost,14333"
    assert resolve_address("sqldocker", 5555, aliases) == "localhost,14333"


def test_resolve_address_alias_without_port_and_named_instance():
    from app.services.catalog import resolve_address

    aliases = {"a": "DBMSSOCN,dbhost", "b": r"DBMSSOCN,dbhost\INST", "c": r"DBNMPNTW,\\h\pipe\sql\query"}
    assert resolve_address("a", 1433, aliases) == "dbhost,1433"
    assert resolve_address("b", 1433, aliases) == r"dbhost\INST"
    assert resolve_address("c", 1433, aliases) == "c"


def test_resolve_address_plain_values():
    from app.services.catalog import CatalogError, resolve_address

    assert resolve_address("sqlhost", 1433, {}) == "sqlhost,1433"
    assert resolve_address(r"sqlhost\INST", 1433, {}) == r"sqlhost\INST"
    assert resolve_address(r"sqlhost\INST", 1500, {}) == r"sqlhost\INST,1500"
    assert resolve_address("sqlhost,14333", 1433, {}) == "sqlhost,14333"
    with pytest.raises(CatalogError):
        resolve_address("sqlhost,abc", 1433, {})
