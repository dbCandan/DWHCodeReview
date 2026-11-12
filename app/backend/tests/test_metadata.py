from typing import Any

import pytest

from app.services.metadata import (
    MetadataCollector,
    PartitionInfo,
    empty_metadata,
    format_column_type,
    format_for_llm,
    metadata_precondition_met,
    parse_name_at,
    quote_ident,
    text_references,
)
from app.services.rule_engine import mask_sql
from tests.helpers import col, entry, metadata, varchar


def test_parse_names() -> None:
    assert parse_name_at("[EDW].[CON].[Acc]]x] a", 0) == (["EDW", "CON", "Acc]x"], 20)
    assert parse_name_at("EDW..T x", 0)[0] == ["EDW", "", "T"]
    assert parse_name_at("s . t WITH", 0)[0] == ["s", "t"]
    assert parse_name_at("t.* FROM", 0)[0] == ["t"]
    assert parse_name_at("(SELECT", 0) is None


def test_text_references() -> None:
    sql = (
        "WITH C AS (SELECT 1 x)\n"
        "INSERT INTO EDW.TRX.Target SELECT * FROM C JOIN [EDWSTG].[BOAAI].[Src] s ON 1=1\n"
        "JOIN #tmp t ON 1=1 JOIN @v v ON 1=1\n"
        "UPDATE a SET x = 1 FROM dbo.T a\n"
        "TRUNCATE TABLE EDW.TRX.Target\n"
        "EXEC @rc = EDWUTIL.OPR.spTruncateWithPartitions_withDate @EdwTableName='EDW.TRX.Target',"
        " @StgTableName = N'EDWSTG.BOAAI.Src2'\n"
        "-- FROM EDW.Comment.Only\n"
        "-- @TableName='EDW.Comment.Too'\n"
    )
    found = text_references(sql, mask_sql(sql))
    assert found == [
        ["EDW", "TRX", "Target"],
        ["EDWSTG", "BOAAI", "Src"],
        ["a"],
        ["dbo", "T"],
        ["EDWUTIL", "OPR", "spTruncateWithPartitions_withDate"],
        ["EDWSTG", "BOAAI", "Src2"],
    ]


def test_column_type_format() -> None:
    assert format_column_type("varchar", 50, 0, 0) == "varchar(50)"
    assert format_column_type("nvarchar", -1, 0, 0) == "nvarchar(max)"
    assert format_column_type("nchar", 20, 0, 0) == "nchar(10)"
    assert format_column_type("decimal", 9, 18, 2) == "decimal(18,2)"
    assert format_column_type("datetime2", 8, 27, 7) == "datetime2"
    assert format_column_type("datetime2", 7, 23, 3) == "datetime2(3)"


def test_llm_block_and_preconditions() -> None:
    partition = PartitionInfo("TranDate", "date", "fn_date_X", "datetime", "RIGHT", "ps_date_X")
    scd = entry("EDW", "CON", "Account", columns=[col("AccountId"), varchar("AccountNk"),
                                                  col("EdwValidFrom", "datetime", 8, 23, 3),
                                                  col("EdwValidUntil", "datetime", 8, 23, 3)])
    fact = entry("EDW", "TRX", "Fact", columns=[col("TranDate", "date", 3, 10, 0)],
                 partition=partition)
    meta = metadata(scd, fact, entry("EDWUTIL", "OPR", "spX", "P"))
    text = format_for_llm(meta)
    assert text.startswith("KATALOG METADATASI")
    assert "- EDW.CON.Account [TABLO, SCD] kolonlar: AccountId int, AccountNk varchar(50)" in text
    assert "partition: kolon TranDate date, fonksiyon fn_date_X(datetime), RANGE RIGHT" in text
    assert "- EDWUTIL.OPR.spX [PROSEDÜR]" in text
    assert metadata_precondition_met("references_scd_table", meta)
    assert metadata_precondition_met("references_partitioned_table", meta)
    assert not metadata_precondition_met("references_scd_table", metadata(fact))
    assert not metadata_precondition_met("references_partitioned_table", empty_metadata())
    assert metadata_precondition_met(None, empty_metadata())
    assert "alınamadı" in format_for_llm(empty_metadata("bağlantı yok"))


def test_llm_block_is_shortened() -> None:
    wide = [entry("EDW", "S", f"T{i}", columns=[col(f"Column{j:03d}") for j in range(80)])
            for i in range(6)]
    text = format_for_llm(metadata(*wide))
    assert len(text) <= 6000 and "- EDW.S.T5 [TABLO]" in text and "(+" in text


class FakeCursor:
    """Answers the collector's catalog queries from dictionaries."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[int, str, str, str, str | None]] = {
            ("EDW", "[TRX].[ins_X]"): (1, "P", "TRX", "ins_X", None),
            ("EDW", "[CON].[Account]"): (10, "U", "CON", "Account", None),
            ("EDWSTG", "[BOAAI].[Src]"): (20, "U", "BOAAI", "Src", None),
            ("EDW", "[dbo].[SynAcc]"): (30, "SN", "dbo", "SynAcc", "[EDW].[CON].[Account]"),
            ("EDW", "[CON].[vAccount]"): (40, "V", "CON", "vAccount", None),
        }
        self.columns = {
            ("EDW", 10): [("AccountId", "int", 4, 10, 0), ("EdwValidFrom", "datetime", 8, 23, 3),
                          ("EdwValidUntil", "datetime", 8, 23, 3)],
            ("EDWSTG", 20): [("TranDate", "date", 3, 10, 0)],
            ("EDW", 40): [("AccountId", "int", 4, 10, 0)],
        }
        self.partitions = {
            ("EDWSTG", 20): [("TranDate", "date", 3, 10, 0, "fn_date", "datetime", 8, 23, 3, 1,
                              "ps_date")],
        }
        self.mrg_procedures = {"EDW": {"[scd].[mrgCONAccount]"}}
        self.surrogates = {"EDW": ("Account",), "EDWSKEY": ("ChannelDetail",)}
        self.dm_fails = False
        self.statements: list[str] = []
        self._rows: list[Any] = []

    def execute(self, sql: str, *params: Any) -> None:
        if sql.startswith("EXEC [") and params:
            # sp_executesql call: the statement, its declaration and the values are all bound.
            assert sql.endswith("?") and "'" not in sql, sql
            body, params = params[0], params[2:]
            sql = f"{sql} -- {body}"
        self.statements.append(sql)
        if sql.startswith("SELECT name FROM sys.databases"):
            self._rows = [("EDW",), ("EDWSTG",), ("master",)]
            return
        database = sql.split("]", 1)[0].removeprefix("EXEC [")
        if "LEFT(c.name" in sql:
            self._rows = [(b,) for b in self.surrogates.get(database, ())]
            return
        if "dm_sql_referenced_entities" in sql:
            if self.dm_fails:
                raise RuntimeError("[42000] Invalid object name '#tmp'. (208)")
            self._rows = [(None, None, "CON", "Account"), (None, "EDWSTG", "BOAAI", "Src"),
                          ("LINKED", "X", "Y", "Z")]
        elif "OBJECT_ID(@p0, N'P')" in sql:
            self._rows = [(99,)] if params[0] in self.mrg_procedures.get(database, ()) else [(None,)]
        elif "OBJECT_ID(@p0)" in sql:
            row = self.objects.get((database, params[0]))
            self._rows = [row] if row else []
        elif "partition_ordinal" in sql:
            self._rows = self.partitions.get((database, params[0]), [])
        elif "sys.columns" in sql:
            self._rows = self.columns.get((database, params[0]), [])
        else:
            raise AssertionError(sql)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)


def test_collector_reads_references_columns_partition_and_caches() -> None:
    cursor = FakeCursor()
    collector = MetadataCollector(cursor)
    sql = "CREATE PROCEDURE TRX.ins_X AS SELECT * FROM dbo.SynAcc s JOIN CON.vAccount v ON 1=1"
    meta = collector.describe("edw", "TRX", "ins_X", "PROCEDURE", sql, mask_sql(sql))
    assert meta.available
    labels = [e.label for e in meta.referenced_entries()]
    assert labels == ["EDW.CON.Account", "EDWSTG.BOAAI.Src", "EDW.CON.vAccount"]
    account = meta.lookup("EDW", "dbo", "SynAcc")  # synonym resolves to its base table
    assert account is not None and account.label == "EDW.CON.Account" and account.is_scd
    src = meta.lookup("EDWSTG", "BOAAI", "Src")
    assert src.partition == PartitionInfo("TranDate", "date", "fn_date", "datetime", "RIGHT",
                                          "ps_date")
    assert meta.lookup("EDW", "CON", "vAccount").columns[0].name == "AccountId"
    assert meta.references_scd_table and meta.references_partitioned_table
    assert all(s.startswith("EXEC [") or "sys.databases" in s for s in cursor.statements)

    count = len(cursor.statements)
    again = collector.describe("EDW", "TRX", "ins_X", "PROCEDURE", sql, mask_sql(sql))
    assert [e.label for e in again.referenced_entries()] == labels
    assert len(cursor.statements) == count + 1  # only the dependency query runs again


def test_collector_falls_back_to_text_and_view_self() -> None:
    cursor = FakeCursor()
    cursor.dm_fails = True
    cursor.objects[("EDW", "[CON].[vSelf]")] = (50, "V", "CON", "vSelf", None)
    cursor.columns[("EDW", 50)] = [("A", "int", 4, 10, 0), ("B", "varchar", 10, 0, 0)]
    sql = "CREATE VIEW CON.vSelf AS SELECT 1 A FROM [EDWSTG].[BOAAI].[Src] JOIN Unknown.T ON 1=1"
    meta = MetadataCollector(cursor).describe(
        "EDW", "CON", "vSelf", "VIEW", sql, mask_sql(sql), extra=[("EDW", "CON", "vAccount")]
    )
    assert [e.label for e in meta.referenced_entries()] == ["EDWSTG.BOAAI.Src"]
    assert meta.self_entry is not None and [c.name for c in meta.self_entry.columns] == ["A", "B"]
    assert meta.lookup("EDW", "CON", "vAccount") is not None  # extra object, not referenced
    assert any("dm_sql_referenced_entities" in note for note in meta.notes)


def test_collector_connection_failure_gives_empty_metadata() -> None:
    class Broken:
        def execute(self, *args: Any) -> None:
            raise RuntimeError("connection lost")

    meta = MetadataCollector(Broken()).describe("EDW", "a", "b", "VIEW", "", "")  # type: ignore[arg-type]
    assert not meta.available and "alınamadı" in meta.notes[0]


def test_collector_scd_definition() -> None:
    cursor = FakeCursor()
    validity = [("Id", "int", 4, 10, 0), ("EdwValidFrom", "datetime", 8, 23, 3),
                ("EdwValidUntil", "datetime", 8, 23, 3)]
    cursor.objects[("EDW", "[CON].[NoMrg]")] = (60, "U", "CON", "NoMrg", None)
    cursor.objects[("EDWSKEY", "[CHN].[ChannelDetailKey]")] = (70, "U", "CHN", "ChannelDetailKey", None)
    cursor.objects[("EDWDM", "[CUS].[Scd]")] = (80, "U", "CUS", "Scd", None)
    for key in (("EDW", 60), ("EDWSKEY", 70), ("EDWDM", 80)):
        cursor.columns[key] = validity
    original = cursor.execute

    def execute(sql: str, *params: Any) -> None:
        if sql.startswith("SELECT name FROM sys.databases"):
            cursor._rows = [("EDW",), ("EDWSKEY",), ("EDWDM",), ("EDWSTG",)]
            return
        if params and "dm_sql_referenced_entities" in str(params[0]):
            cursor._rows = []
            return
        original(sql, *params)

    cursor.execute = execute  # type: ignore[method-assign]
    sql = ("SELECT 1 FROM EDW.CON.Account a JOIN EDW.CON.NoMrg n ON 1=1 "
           "JOIN EDWSKEY.CHN.ChannelDetailKey k ON 1=1 JOIN EDWDM.CUS.Scd s ON 1=1")
    meta = MetadataCollector(cursor).describe("EDW", "TRX", "ins_X", "PROCEDURE", sql, mask_sql(sql))
    flags = {e.label: e.is_scd for e in meta.referenced_entries()}
    assert flags == {"EDW.CON.Account": True, "EDW.CON.NoMrg": False,
                     "EDWSKEY.CHN.ChannelDetailKey": False, "EDWDM.CUS.Scd": True}
    # The mrg procedure is only asked for in EDW/ERPEDW.
    assert sum("N'P'" in s for s in cursor.statements) == 2


def test_quote_ident_escapes_and_rejects_invalid_names() -> None:
    assert quote_ident("EDW") == "[EDW]"
    assert quote_ident("a]b; DROP TABLE x--") == "[a]]b; DROP TABLE x--]"
    for bad in ("", "x" * 129, "a\x00b", "a\nb"):
        with pytest.raises(ValueError):
            quote_ident(bad)


def test_collector_surrogate_key_bases_cached() -> None:
    cursor = FakeCursor()
    collector = MetadataCollector(cursor)
    sql = "SELECT 1"
    first = collector.describe("EDW", "TRX", "ins_X", "PROCEDURE", sql, sql)
    second = collector.describe("EDW", "TRX", "ins_X", "PROCEDURE", sql, sql)
    assert first.surrogate_key_bases == second.surrogate_key_bases == frozenset({"account"})
    assert sum("LEFT(c.name" in s for s in cursor.statements) == 1  # EDWSKEY not accessible here
