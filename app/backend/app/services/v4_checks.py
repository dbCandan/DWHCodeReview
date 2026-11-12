"""Builtin checks added in v1.4 (RULES_SPEC_v14.md): DWH-ID-01 and DWH-CAL-01.

Both are pure functions `(sql, masked, obj, metadata) -> list[EngineFinding]` over
`app.services.sql_parse`; unresolvable columns or sources are never reported.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.services.builtin_checks import ObjectRef
from app.services.metadata import ColumnInfo, ObjectMetadata
from app.services.perf_checks import _finding, _is_staging, _predicate_ranges, _short
from app.services.rule_engine import EngineFinding
from app.services.sql_parse import (
    COMPARISON_OPS,
    DATE_TYPES,
    FromBlock,
    FromItem,
    SqlDoc,
    atoms,
    base_type,
    column_expr,
    comparison,
    parse_predicate,
    type_family,
)


def _doc(sql: str, obj: ObjectRef, metadata: ObjectMetadata) -> SqlDoc:
    return SqlDoc(sql, metadata if metadata.available else None, obj.database)


# ------------------------------------------------------------------ literals
def _literal(doc: SqlDoc, i: int, j: int) -> str | None:
    """Text of a number / negative number / string literal filling tokens [i, j)."""
    tokens = doc.tokens
    while i < j and tokens[i].is_punct("(") and doc.close_of(i) == j - 1 and not doc.is_subquery(i):
        i, j = i + 1, j - 1
    if j - i == 1 and tokens[i].kind in ("num", "str"):
        return tokens[i].text
    if j - i == 2 and tokens[i].is_punct("-") and tokens[i + 1].kind == "num":
        return f"-{tokens[i + 1].text}"
    return None


def _literal_list(doc: SqlDoc, i: int, j: int) -> list[str] | None:
    """Literals of an `( a, b, ... )` IN list; None for sub-queries or expressions."""
    tokens = doc.tokens
    if j - i < 2 or not tokens[i].is_punct("(") or doc.close_of(i) != j - 1 or doc.is_subquery(i):
        return None
    depth = tokens[i].depth + 1
    bounds = [k for k in range(i + 1, j - 1) if tokens[k].depth == depth and tokens[k].is_punct(",")]
    values: list[str] = []
    for a, b in zip([i + 1, *[k + 1 for k in bounds]], [*bounds, j - 1], strict=False):
        value = _literal(doc, a, b)
        if value is None:
            return None
        values.append(value)
    return values or None


def _number(value: str) -> float | None:
    text = re.sub(r"^N?'(.*)'$", r"\1", value.strip(), flags=re.DOTALL).strip()
    try:
        return float(text)
    except ValueError:
        return None


STANDARD_NEGATIVES = frozenset({-99.0, -98.0, -1.0})


def _exempt_values(values: list[str], is_list: bool) -> bool:
    """-99/-98/-1 alone, or IN/NOT IN lists of negative numbers only (0 is NOT exempt)."""
    numbers = [_number(v) for v in values]
    if any(n is None for n in numbers):
        return False
    if is_list:
        return all(n is not None and n < 0 for n in numbers)
    return numbers[0] in STANDARD_NEGATIVES


# ------------------------------------------------------------------ DWH-ID-01
_NOT_SURROGATE = frozenset({"customerpartyid", "personpartyid"})


def _surrogate_candidate(column: str) -> bool:
    name = column.lower()
    return (
        len(name) > 2 and name.endswith("id") and not name.endswith("_id")
        and not name.startswith("edw") and name not in _NOT_SURROGATE
    )


def _surrogate_message(
    item: FromItem, column: ColumnInfo, metadata: ObjectMetadata, text: str, values: str
) -> str | None:
    """Message when `<Ad>Id` of a user table is a surrogate key, else None.

    (i) the same table has `<Ad>Nk`; (ii) some EDWSKEY/EDW/ERPEDW table carries both `<Ad>Id`
    and `<Ad>Nk` (key / LKP table) while this table has only the Id.
    """
    if item.entry is None or item.entry.type != "U":
        return None
    base = column.name[:-2]
    nk = next((c for c in item.entry.columns if c.name.lower() == f"{base}nk".lower()), None)
    if nk is not None:
        return (f"{text} veri ambarı vekil anahtarı; sabit değer filtresi {nk.name} üzerinden "
                f"yapılmalı (değer: {values})")
    if base.lower() in metadata.surrogate_key_bases:
        return (f"{text} veri ambarı vekil anahtarı; ilgili LKP/anahtar tablosuna {column.name} "
                f"üzerinden join kurup {base}Nk ile filtreleyin (değer: {values})")
    return None


def id_literal_filter(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """Constant filters on surrogate keys (`<Ad>Id` of a user table, see `_surrogate_message`).

    Views (EDWDM views derive Id from Nk), temp tables, CTEs, sub-queries and Ids without any
    catalog `<Ad>Nk` partner are not reported; neither are -99/-98/-1 or lists of negatives.
    """
    if not metadata.available:
        return []
    doc = _doc(sql, obj, metadata)
    findings: list[EngineFinding] = []
    seen: set[int] = set()
    for block in doc.blocks:
        for _clause, (start, stop) in _predicate_ranges(block):
            for atom in atoms(parse_predicate(doc, start, stop)):
                cmp = comparison(doc, atom)
                if cmp is None:
                    continue
                if cmp.op in COMPARISON_OPS:
                    pairs = [(cmp.left, cmp.right), (cmp.right, cmp.left)]
                    candidates = [
                        (col_rng, [v], False) for col_rng, lit_rng in pairs
                        if (v := _literal(doc, *lit_rng)) is not None
                    ]
                elif cmp.op == "IN":
                    values = _literal_list(doc, *cmp.right)
                    candidates = [(cmp.left, values, True)] if values else []
                else:
                    continue
                for col_rng, values, is_list in candidates:
                    expr = column_expr(doc, *col_rng)
                    if expr is None or not _surrogate_candidate(expr.column):
                        continue
                    if _exempt_values(values, is_list):
                        continue
                    resolved = doc.resolve_column(block, expr.alias, expr.column)
                    if resolved is None:
                        continue
                    message = _surrogate_message(
                        *resolved, metadata, expr.text, ", ".join(values)
                    )
                    offset = doc.tokens[atom.i].start
                    if message is None or offset in seen:
                        continue
                    seen.add(offset)
                    findings.append(_finding(doc, offset, message))
    return sorted(findings, key=lambda f: f.line or 0)


# ------------------------------------------------------------------ DWH-CAL-01
DATE_FUNCTIONS = frozenset(
    {"CONVERT", "TRY_CONVERT", "CAST", "TRY_CAST", "FORMAT", "YEAR", "MONTH", "EOMONTH",
     "DATEPART", "DATEADD"}
)
CONVERSION_TARGETS = frozenset(
    {"date", "datetime", "smalldatetime", "datetime2", "varchar", "char", "int"}
)
DATE_STYLES = frozenset({"112", "23"})
_DATE_NAME = re.compile(r"date|period|tarih", re.IGNORECASE)


def _args(doc: SqlDoc, open_index: int, close: int) -> list[tuple[int, int]]:
    depth = doc.tokens[open_index].depth + 1
    cuts = [k for k in range(open_index + 1, close)
            if doc.tokens[k].depth == depth and doc.tokens[k].is_punct(",")]
    return list(zip([open_index + 1, *[k + 1 for k in cuts]], [*cuts, close], strict=False))


def _block_columns(
    doc: SqlDoc, block: FromBlock, i: int, j: int
) -> Iterator[tuple[str, ColumnInfo | None]]:
    """(name, catalog column or None) of this block's own non-staging columns in [i, j)."""
    tokens = doc.tokens
    k = i
    while k < j:
        tok = tokens[k]
        if tok.is_punct("(") and doc.is_subquery(k):
            k = (doc.close_of(k) or k) + 1
            continue
        prev = tokens[k - 1] if k > 0 else None
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if tok.ident and tok.kind != "var" and not (prev and prev.is_punct(".")):
            if nxt is not None and nxt.is_punct(".") and k + 2 < j and tokens[k + 2].ident:
                after = tokens[k + 3] if k + 3 < len(tokens) else None
                item = block.item_for(tok.ident)
                column = tokens[k + 2].ident or ""
                if item is not None and (after is None or not after.is_punct("(")):
                    if not _is_staging(item, doc.database):
                        info = None
                        if item.entry is not None:
                            info = next((c for c in item.entry.columns
                                         if c.name.lower() == column.lower()), None)
                        yield column, info
                k += 3
                continue
            if nxt is None or not nxt.is_punct("("):
                resolved = doc.resolve_column(block, None, tok.ident, inherit=False)
                if resolved is not None and not _is_staging(resolved[0], doc.database):
                    yield resolved[1].name, resolved[1]
        k += 1


def _date_like(name: str, info: ColumnInfo) -> bool:
    family = type_family(info.type_label)
    if family in ("date", "datetime"):
        return True
    return bool(_DATE_NAME.search(name)) and family in ("integer", "ascii", "unicode")


def _date_call(doc: SqlDoc, block: FromBlock, k: int, close: int) -> bool:
    """The call at token k (its `(` at k+1) transforms a date column of this block."""
    word = doc.tokens[k].upper
    conversion = word in ("CONVERT", "TRY_CONVERT", "CAST", "TRY_CAST")
    target, style = "", ""
    region = (k + 2, close)
    if word in ("CONVERT", "TRY_CONVERT"):
        args = _args(doc, k + 1, close)
        if len(args) < 2:
            return False
        target = doc.text(*args[0])
        region = args[1]
        style = doc.text(*args[2]) if len(args) > 2 else ""
    elif word in ("CAST", "TRY_CAST"):
        depth = doc.tokens[k + 1].depth + 1
        as_index = next((m for m in range(close - 1, k + 1, -1)
                         if doc.tokens[m].depth == depth and doc.tokens[m].is_word("AS")), None)
        if as_index is None:
            return False
        target = doc.text(as_index + 1, close)
        region = (k + 2, as_index)
    if conversion and base_type(target) not in CONVERSION_TARGETS:
        return False
    for name, info in _block_columns(doc, block, *region):
        if info is not None:
            if _date_like(name, info):
                return True
        elif conversion and (base_type(target) in DATE_TYPES or style.strip() in DATE_STYLES):
            return True
    return False


CALENDAR_HINT = "EDW.COR.Calendar ile aralık join'i (X >= C.CalendarDate AND X < DATEADD(DAY,1,C.CalendarDate))"


def calendar_date_predicate(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """WHERE/ON comparisons on a converted date column -> suggest a Calendar range join.

    DECLARE/SET, SELECT lists, GROUP BY and ORDER BY are out of scope (only ON/WHERE ranges
    are read); staging (EDWSTG/ERPSTG) columns are ignored. One finding per comparison.
    """
    doc = _doc(sql, obj, metadata)
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    for block in doc.blocks:
        for _clause, (start, stop) in _predicate_ranges(block):
            for atom in atoms(parse_predicate(doc, start, stop)):
                cmp = comparison(doc, atom)
                if cmp is None or cmp.op == "IS":
                    continue
                sides = [cmp.left, cmp.right] + ([cmp.right2] if cmp.right2 else [])
                for i, j in sides:
                    hit = False
                    k = i
                    while k < j and not hit:
                        tok = tokens[k]
                        if tok.is_punct("(") and doc.is_subquery(k):
                            k = (doc.close_of(k) or k) + 1
                            continue
                        if tok.upper in DATE_FUNCTIONS and k + 1 < j and tokens[k + 1].is_punct("("):
                            close = doc.close_of(k + 1)
                            if close is not None and close < j and _date_call(doc, block, k, close):
                                hit = True
                                break
                        k += 1
                    if hit:
                        findings.append(
                            _finding(doc, tokens[i].start,
                                     f"Öneri: {_short(doc.text(i, j))} yerine {CALENDAR_HINT}")
                        )
                        break
    return sorted(findings, key=lambda f: f.line or 0)


V4_CHECKS = {
    "id_literal_filter": id_literal_filter,
    "calendar_date_predicate": calendar_date_predicate,
}
