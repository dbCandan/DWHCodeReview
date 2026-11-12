"""The seeded DWH standards: regexes, preconditions and applicability."""

import pytest

from app.seed import SEED_RULES
from app.services.rule_engine import (
    RuleSpec,
    applies_to_object,
    compile_optional,
    precondition_met,
    run_regex,
)

SEED = {data["code"]: data for data in SEED_RULES}


def spec(code: str) -> RuleSpec:
    data = SEED[code]
    return RuleSpec(
        code=code,
        name=data["name"],
        kind=data["kind"],
        description=data["description"],
        pattern=data.get("pattern"),
        ignore_case=data["ignore_case"],
        ignore_comments=data["ignore_comments"],
        llm_prompt=data.get("llm_prompt"),
        object_types=tuple(data["object_types"]),
        builtin_check=data.get("builtin_check"),
        precondition=data.get("precondition"),
        metadata_precondition=data.get("metadata_precondition"),
        requires_metadata=data["requires_metadata"],
        databases=tuple(data["databases"]),
        name_pattern=data.get("name_pattern"),
    )


def test_seed_shape() -> None:
    assert list(SEED)[:8] == [
        "DWH-PART-01", "DWH-SCD-01", "DWH-SCD-02", "DWH-DM-01", "DWH-DM-02", "DWH-NK-01",
        "DWH-NOLOCK-01", "DWH-NOLOCK-02",
    ]
    assert len(SEED) == 32
    for code, data in SEED.items():
        assert data["severity"] in ("critical", "high", "low") and data["name"] and data["description"]
        assert data["recommendation"], code
        if data["kind"] == "llm":
            assert data["llm_prompt"] and "İHLAL" in data["llm_prompt"], code
        for field, flags in (("pattern", 0), ("precondition", 0), ("name_pattern", 0)):
            compile_optional(data.get(field), flags, field)
    assert "EdwStatus = 0" in SEED["DWH-SCD-01"]["llm_prompt"]


@pytest.mark.parametrize(
    "sql",
    [
        "WHERE EdwStatus = 1",
        "AND t.EdwStatus=1",
        "AND b.[EdwStatus] = '1'",
        "ON a.Id=b.Id AND b.EdwStatus IN (1)",
        "WHERE EdwStatus = 0",
        "AND x.EdwStatus <> 0",
        "AND EdwStatus != 1",
        "AND EdwStatus IN (0,1)",
        "AND EdwStatus NOT IN (0)",
    ],
)
def test_scd02_positive(sql: str) -> None:
    assert len(run_regex(spec("DWH-SCD-02"), f"SELECT a FROM t\n{sql}\n")) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "AND EdwStatus = 10",
        "AND EdwStatus = 2",
        "SET EdwStatus = 0",
        "EdwValidUntil = x, EdwStatus = 0,",
        "EdwStatus,",
        "INSERT (a, EdwStatus)",
        "SELECT PTR.EdwStatus",
        "CASE WHEN EdwStatus = 1 THEN",
        "-- WHERE EdwStatus = 1",
    ],
)
def test_scd02_negative(sql: str) -> None:
    assert run_regex(spec("DWH-SCD-02"), f"SELECT a FROM t\n{sql}\n") == []


@pytest.mark.parametrize(
    "sql",
    [
        "FROM #tmp WITH (NOLOCK)",
        "JOIN #x x (NOLOCK)",
        "FROM #nakit AS n WITH(NOLOCK)",
        "FROM ##g WITH (NOLOCK)",
    ],
)
def test_nolock02_positive(sql: str) -> None:
    assert len(run_regex(spec("DWH-NOLOCK-02"), sql)) == 1


@pytest.mark.parametrize(
    "sql",
    ["FROM #tmp t", "FROM EDW.CON.Account A WITH (NOLOCK)", "INSERT INTO #t", "FROM #t t JOIN x ON 1=1"],
)
def test_nolock02_negative(sql: str) -> None:
    assert run_regex(spec("DWH-NOLOCK-02"), sql) == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t ORDER BY a.CustomerNk",
        "SELECT MAX(t.AccountNk) FROM t",
        "SELECT a FROM t WHERE x.BranchNk > 100",
        "SELECT a FROM t WHERE x.BranchNk BETWEEN 1 AND 5",
        "SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b.ContractNk DESC) FROM t",
    ],
)
def test_nk01_precondition_matches(sql: str) -> None:
    assert precondition_met(spec("DWH-NK-01"), sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a.CustomerNk FROM t a JOIN u b ON a.CustomerNk = b.CustomerNk",
        "SELECT a FROM t GROUP BY a.CustomerNk",
        "-- ORDER BY a.CustomerNk\nSELECT 1",
    ],
)
def test_nk01_precondition_does_not_match(sql: str) -> None:
    assert not precondition_met(spec("DWH-NK-01"), sql)


def test_part01_precondition() -> None:
    rule = spec("DWH-PART-01")
    assert precondition_met(rule, "EXEC EDWUTIL.OPR.spTruncateWithPartitions_withDate @x = 1")
    assert precondition_met(rule, "TRUNCATE TABLE T WITH (PARTITIONS(@p))")
    assert not precondition_met(rule, "TRUNCATE TABLE T; INSERT INTO T SELECT 1")
    # Comments are masked because ignore_comments is true.
    assert not precondition_met(rule, "-- DELETE FROM T\nSELECT 1")


def test_dm_rules_applicability() -> None:
    dm01, dm02 = spec("DWH-DM-01"), spec("DWH-DM-02")
    assert applies_to_object(dm01, "EDWDM", "CUS", "vCustomerInfo", "VIEW")
    assert applies_to_object(dm01, "edwdm", "CUS", "vCustomerInfo", "VIEW")
    assert not applies_to_object(dm01, "EDW", "CUS", "vCustomerInfo", "VIEW")
    assert not applies_to_object(dm01, "EDWDM", "CUS", "vCustomerInfoMasked", "VIEW")
    assert not applies_to_object(dm01, "EDWDM", "CUS", "CustomerInfo", "VIEW")
    assert not applies_to_object(dm01, "EDWDM", "CUS", "vCustomerInfo", "PROCEDURE")
    assert applies_to_object(dm02, "EDWDM", "CUS", "vCustomerInfoMasked", "VIEW")
    assert applies_to_object(dm02, "EDWDM", "CUS", "vCustomerInfoPersonnelExcluded", "VIEW")
    assert not applies_to_object(dm02, "EDWDM", "CUS", "vCustomerInfo", "VIEW")
    nolock = spec("DWH-NOLOCK-01")
    assert applies_to_object(nolock, "ANY", "x", "y", "FUNCTION_INLINE")
    assert nolock.needs_metadata and not spec("DWH-SCD-02").needs_metadata
