"""Builtin checks of the v3 rule set ("DWH Kodlama ve Performans", RULES_SPEC_v13.md).

Each check is a pure function `(sql, masked, obj, metadata) -> list[EngineFinding]` built on
`app.services.sql_parse`. Anything that cannot be resolved (unknown alias, column without
catalog type, temp/CTE sources...) is never reported: precision over recall.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.services.builtin_checks import ObjectRef
from app.services.metadata import ObjectMetadata, parse_name_at
from app.services.rule_engine import EngineFinding
from app.services.sql_parse import (
    CLAUSE_END,
    COMPARISON_OPS,
    STATEMENT_START,
    TEXT_TYPES,
    ColumnExpr,
    FromBlock,
    SqlDoc,
    atoms,
    base_type,
    column_expr,
    comparison,
    parse_predicate,
    type_family,
    variable_types,
)

MAX_TEXT = 120


def _doc(sql: str, obj: ObjectRef, metadata: ObjectMetadata) -> SqlDoc:
    return SqlDoc(sql, metadata if metadata.available else None, obj.database)


def _short(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _finding(doc: SqlDoc, offset: int, message: str) -> EngineFinding:
    return EngineFinding(doc.line(offset), doc.snippet(offset), message)


def _predicate_ranges(block: FromBlock) -> Iterator[tuple[str, tuple[int, int]]]:
    for item in block.items:
        if item.on_range is not None and item.on_range[0] < item.on_range[1]:
            yield "ON", item.on_range
    if block.where_range is not None and block.where_range[0] < block.where_range[1]:
        yield "WHERE", block.where_range


# ------------------------------------------------------------------ DWH-JOIN-01
def left_then_inner_join(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """An INNER (or plain) JOIN after a LEFT JOIN in the same FROM block."""
    doc = SqlDoc(sql)
    findings: list[EngineFinding] = []
    for block in doc.blocks:
        seen_left = False
        for item in block.items:
            if item.kind == "LEFT":
                seen_left = True
            elif item.kind == "INNER" and seen_left:
                offset = doc.tokens[item.keyword_index].start
                findings.append(
                    _finding(doc, offset, f"LEFT JOIN'den sonra INNER JOIN: {item.label}")
                )
    return sorted(findings, key=lambda f: f.line or 0)


# ------------------------------------------------------------------ DWH-SQL-02
_LIST_STOP = STATEMENT_START | CLAUSE_END | {"FROM"}


def select_list_subquery(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """`(SELECT ... FROM ...)` inside a SELECT column list.

    Constant sub-queries without FROM (`(SELECT NULL)` in OVER, `(SELECT 1)`) and the
    variable assignment `SELECT @x = (SELECT ...)` without a FROM clause are not reported.
    """
    doc = SqlDoc(sql)
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    seen: set[int] = set()
    for index, tok in enumerate(tokens):
        if not tok.is_word("SELECT"):
            continue
        end = doc._clause_end(index + 1, tok.depth, _LIST_STOP)
        has_from = end < len(tokens) and tokens[end].is_word("FROM")
        assigns = (
            index + 2 < len(tokens) and tokens[index + 1].kind == "var"
            and tokens[index + 2].text == "="
        )
        if assigns and not has_from:
            continue
        for k in range(index + 1, end):
            if tokens[k].is_punct("(") and doc.is_subquery(k) and doc.has_from(k) and k not in seen:
                seen.add(k)
                close = doc.close_of(k) or k
                findings.append(
                    _finding(doc, tokens[k].start,
                             f"SELECT listesinde alt sorgu: {_short(doc.text(k, close + 1))}")
                )
    return findings


# ------------------------------------------------------------------ DWH-INS-01
_INSERT = re.compile(r"\bINSERT\s+(?:INTO\s+)?", re.IGNORECASE)
_TABLOCK_HINT = re.compile(r"\s*WITH\s*\(([^)]*)\)", re.IGNORECASE)
INSERT_EXEMPT_DATABASES = frozenset({"edwutil"})  # log / control tables
_VALUES = re.compile(r"\s*VALUES\b", re.IGNORECASE)


def _values_insert(masked: str, pos: int) -> bool:
    """`[ (columns) ] VALUES (...)` follows the target (and its hint)."""
    from app.services.builtin_checks import _matching_paren, _skip_ws

    pos = _skip_ws(masked, pos)
    if masked[pos : pos + 1] == "(":
        close = _matching_paren(masked, pos)
        if close == -1:
            return False
        pos = close + 1
    return _VALUES.match(masked, pos) is not None


def tablock_physical_insert(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """INSERT into a user table (catalog type U) without WITH (TABLOCK/TABLOCKX).

    Not reported: single-row `INSERT ... VALUES (...)` and targets in EDWUTIL (log/control
    tables such as OPR.DMExecutionStepTimeControl).
    """
    if not metadata.available:
        return []
    doc = SqlDoc(sql)
    findings: list[EngineFinding] = []
    for match in _INSERT.finditer(masked):
        parsed = parse_name_at(masked, match.end())
        if parsed is None:
            continue
        parts, end = parsed
        if parts[0].startswith(("#", "@")):
            continue
        entry = metadata.resolve(parts, obj.database)
        if entry is None or entry.type != "U":
            continue
        if entry.database.lower() in INSERT_EXEMPT_DATABASES:
            continue
        hint = _TABLOCK_HINT.match(masked, end)
        if hint and re.search(r"\bTABLOCKX?\b", hint.group(1), re.IGNORECASE):
            continue
        if _values_insert(masked, hint.end() if hint else end):
            continue
        findings.append(
            _finding(doc, match.start(),
                     f"{entry.label} fiziksel tablo; INSERT WITH (TABLOCK) eksik")
        )
    return findings


# ------------------------------------------------------------------ type helpers
def _effective_type(doc: SqlDoc, block: FromBlock, expr: ColumnExpr) -> str | None:
    if expr.cast_type:
        return expr.cast_type
    resolved = doc.resolve_column(block, expr.alias, expr.column)
    return resolved[1].type_label if resolved else None


# ------------------------------------------------------------------ DWH-JOIN-02
def join_column_type_mismatch(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """`a.X = b.Y` in ON where the two columns belong to different type families."""
    if not metadata.available:
        return []
    doc = _doc(sql, obj, metadata)
    findings: list[EngineFinding] = []
    for block in doc.blocks:
        for item in block.items:
            if item.on_range is None:
                continue
            for atom in atoms(parse_predicate(doc, *item.on_range)):
                cmp = comparison(doc, atom)
                if cmp is None or cmp.op != "=":
                    continue
                left, right = column_expr(doc, *cmp.left), column_expr(doc, *cmp.right)
                if left is None or right is None or left.alias is None or right.alias is None:
                    continue
                left_type = _effective_type(doc, block, left)
                right_type = _effective_type(doc, block, right)
                left_family, right_family = type_family(left_type), type_family(right_type)
                if left_family and right_family and left_family != right_family:
                    findings.append(
                        _finding(doc, doc.tokens[atom.i].start,
                                 f"{left.text} ({left_type}) = {right.text} ({right_type})"
                                 " — tipler farklı")
                    )
    return findings


# ------------------------------------------------------------------ DWH-PERF-01
SARGABLE_BREAKERS = frozenset(
    {
        "CAST", "CONVERT", "TRY_CAST", "TRY_CONVERT", "ISNULL", "COALESCE", "NULLIF", "YEAR",
        "MONTH", "DAY", "DATEPART", "DATENAME", "DATEADD", "DATEDIFF", "EOMONTH", "FORMAT",
        "LEFT", "RIGHT", "SUBSTRING", "LTRIM", "RTRIM", "TRIM", "UPPER", "LOWER", "REPLACE",
        "LEN", "ABS", "ROUND", "FLOOR", "CEILING",
    }
)


# Staging databases carry no indexes, so converting their columns costs nothing (team decision).
STAGING_DATABASES = frozenset({"edwstg", "erpstg"})


# The calendar table is the date reference itself: functions on its own columns
# (e.g. C.CalendarDate = EOMONTH(C.CalendarDate)) are the intended usage (team decision).
CALENDAR_TABLES = frozenset({("cor", "calendar")})


def _is_staging(item: FromItem | None, default_database: str) -> bool:
    """True when conversions/functions on this source's columns are accepted.

    Staging tables (EDWSTG/ERPSTG, no indexes) and the EDW.COR.Calendar reference table.
    """
    if item is None:
        return False
    if item.entry is not None:
        database, schema, name = item.entry.database, item.entry.schema, item.entry.name
    else:
        parts = item.name_parts or ()
        if not parts:
            return False
        name = parts[-1]
        schema = parts[-2] if len(parts) >= 2 else ""
        database = parts[0] if len(parts) == 3 else default_database
    if (schema.lower(), name.lower()) in CALENDAR_TABLES:
        return True
    return database.lower() in STAGING_DATABASES


def _has_column(doc: SqlDoc, block: FromBlock, i: int, j: int) -> bool:
    """A column of this block's own sources among tokens [i, j) (sub-queries skipped).

    Columns of enclosing blocks (correlated outer references) are constants for this query
    and do not make it non-sargable. Columns of staging tables (EDWSTG/ERPSTG) are ignored:
    those tables have no indexes, so a conversion on them loses nothing.
    """
    tokens = doc.tokens
    k = i
    while k < j:
        tok = tokens[k]
        if tok.is_punct("(") and doc.is_subquery(k):
            k = (doc.close_of(k) or k) + 1
            continue
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        prev = tokens[k - 1] if k > 0 else None
        if tok.ident and tok.kind != "var" and not (prev and prev.is_punct(".")):
            if nxt is not None and nxt.is_punct(".") and k + 2 < j and tokens[k + 2].ident:
                after = tokens[k + 3] if k + 3 < len(tokens) else None
                item = block.item_for(tok.ident)
                if (after is None or not after.is_punct("(")) and item is not None:
                    if not _is_staging(item, doc.database):
                        return True
                k += 3
                continue
            if nxt is None or not nxt.is_punct("("):
                resolved = doc.resolve_column(block, None, tok.ident, inherit=False)
                if resolved is not None and not _is_staging(resolved[0], doc.database):
                    return True
        k += 1
    return False


NULL_SAFE_FUNCTIONS = frozenset({"ISNULL", "COALESCE"})


def _is_scd_merge(obj: ObjectRef) -> bool:
    return obj.schema.lower() == "scd" and obj.name.lower().startswith("mrg")


def non_sargable_predicates(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """A column inside CAST/CONVERT/ISNULL/YEAR/... in an ON or WHERE comparison."""
    doc = _doc(sql, obj, metadata)
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    seen: set[int] = set()
    # SCD merge procedures (scd.mrg<Şema><Tablo>) compare source and target rows with
    # ISNULL/COALESCE for change detection; that is accepted (team decision).
    null_safe_ok = _is_scd_merge(obj)
    for block in doc.blocks:
        for clause, (start, stop) in _predicate_ranges(block):
            label = "Join kolonunda dönüşüm" if clause == "ON" else "Filtre kolonunda fonksiyon"
            for atom in atoms(parse_predicate(doc, start, stop)):
                cmp = comparison(doc, atom)
                if cmp is None or cmp.op == "IS":
                    continue
                sides = [cmp.left, cmp.right] + ([cmp.right2] if cmp.right2 else [])
                for i, j in sides:
                    k = i
                    while k < j:
                        tok = tokens[k]
                        if tok.is_punct("(") and doc.is_subquery(k):
                            k = (doc.close_of(k) or k) + 1
                            continue
                        # Optional-parameter pattern: ISNULL(@Period, Period) / COALESCE(@p, col)
                        # falls back to the column only when the variable is NULL (team decision).
                        variable_first = (tok.upper in NULL_SAFE_FUNCTIONS and k + 2 < j
                                          and tokens[k + 2].kind == "var")
                        if (tok.upper in SARGABLE_BREAKERS and k + 1 < j
                                and tokens[k + 1].is_punct("(")
                                and not variable_first
                                and not (null_safe_ok and tok.upper in NULL_SAFE_FUNCTIONS)):
                            close = doc.close_of(k + 1)
                            if close is not None and close < j:
                                if _has_column(doc, block, k + 2, close) and tok.start not in seen:
                                    seen.add(tok.start)
                                    findings.append(
                                        _finding(doc, tok.start,
                                                 f"{label}: {_short(doc.text(k, close + 1))}")
                                    )
                                    k = close + 1
                                    continue
                        k += 1
    return sorted(findings, key=lambda f: f.line or 0)


# ------------------------------------------------------------------ DWH-PERF-03
def _column_set(doc: SqlDoc, i: int, j: int) -> frozenset[str]:
    tokens = doc.tokens
    found: set[str] = set()
    k = i
    while k < j:
        tok = tokens[k]
        if tok.is_punct("(") and doc.is_subquery(k):
            k = (doc.close_of(k) or k) + 1
            continue
        prev = tokens[k - 1] if k > 0 else None
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if tok.ident and tok.kind != "var" and not (prev and prev.is_punct(".")):
            from app.services.sql_parse import KEYWORDS

            if nxt is not None and nxt.is_punct(".") and k + 2 < j and tokens[k + 2].ident:
                found.add(f"{tok.ident}.{tokens[k + 2].ident}".lower())
                k += 3
                continue
            if (nxt is None or not nxt.is_punct("(")) and tok.upper not in KEYWORDS:
                found.add(tok.ident.lower())
        k += 1
    return frozenset(found)


def or_in_predicates(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """OR in a JOIN condition; OR between different columns in WHERE (CASE excluded)."""
    from app.services.sql_parse import BoolNode

    doc = SqlDoc(sql)
    findings: list[EngineFinding] = []

    def walk(node: object, clause: str, reported: bool = False) -> None:
        if not isinstance(node, BoolNode):
            return
        if node.op == "OR" and not reported:
            offset = doc.tokens[node.operator_indexes[0]].start
            text = _short(doc.text(node.i, node.j))
            if clause == "ON":
                findings.append(_finding(doc, offset, f"JOIN koşulunda OR kullanılmış: {text}"))
                reported = True
            else:
                sets = {_column_set(doc, c.i, c.j) for c in node.children}
                if len(sets) > 1:
                    findings.append(
                        _finding(doc, offset, f"WHERE koşulunda farklı alanlar OR ile bağlanmış: {text}")
                    )
                    reported = True
        # ORs nested in a reported OR group belong to the same finding
        for child in node.children:
            walk(child, clause, reported)

    for block in doc.blocks:
        for clause, (start, stop) in _predicate_ranges(block):
            walk(parse_predicate(doc, start, stop), clause)
    return sorted(findings, key=lambda f: f.line or 0)


# ------------------------------------------------------------------ DWH-PERF-07
_CALL = re.compile(
    r"(?<![\w.\]@#$])((?:\[(?:[^\]]|\]\])+\]|[A-Za-z_][\w$#@]*)"
    r"(?:\s*\.\s*(?:\[(?:[^\]]|\]\])+\]|[A-Za-z_][\w$#@]*)){1,2})\s*\("
)
_QUERY_KEYWORDS = frozenset(
    {"SELECT", "SET", "DECLARE", "RETURN", "IF", "WHILE", "PRINT", "EXEC", "EXECUTE", "INSERT",
     "UPDATE", "DELETE", "MERGE"}
)
_NOT_IN_QUERY = frozenset({"DECLARE", "RETURN", "IF", "WHILE", "PRINT", "EXEC", "EXECUTE"})


def scalar_udf_in_query(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """Calls of scalar UDFs (catalog type FN) inside queries.

    Not reported: `SET @x = fn()`, `DECLARE @x ... = fn()`, `SELECT @x = fn()` (a SELECT that
    only assigns variables), `RETURN fn()` and IF/WHILE/PRINT/EXEC conditions/arguments.
    """
    if not metadata.available:
        return []
    from app.services.metadata import parse_name_text

    doc = SqlDoc(sql)
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    for match in _CALL.finditer(masked):
        parts = parse_name_text(match.group(1))
        if not parts:
            continue
        entry = metadata.resolve(parts, obj.database)
        if entry is None or entry.type != "FN":
            continue
        index = doc.index_at(match.start())
        if index is None:
            continue
        depth = tokens[index].depth
        owner = next(
            (k for k in range(index - 1, -1, -1)
             if tokens[k].depth <= depth and tokens[k].upper in _QUERY_KEYWORDS),
            None,
        )
        if owner is not None:
            word = tokens[owner].upper
            after = tokens[owner + 1] if owner + 1 < len(tokens) else None
            assigns = (
                after is not None and after.kind == "var" and owner + 2 < len(tokens)
                and tokens[owner + 2].text == "="
            )
            if word in _NOT_IN_QUERY or (word in ("SET", "SELECT") and assigns):
                continue
        findings.append(
            _finding(doc, match.start(), f"Sorgu içinde scalar fonksiyon çağrısı: {entry.label}")
        )
    return findings


# ------------------------------------------------------------------ DWH-SQL-06
_WINDOW = frozenset({"ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE"})


def window_order_by_type(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """ROW_NUMBER/RANK/DENSE_RANK/NTILE ordered by a constant or a text column."""
    doc = _doc(sql, obj, metadata)
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    for index, tok in enumerate(tokens):
        if tok.upper not in _WINDOW or index + 1 >= len(tokens) or not tokens[index + 1].is_punct("("):
            continue
        close = doc.close_of(index + 1)
        if close is None or close + 2 >= len(tokens) or not tokens[close + 1].is_word("OVER"):
            continue
        open_over = close + 2
        if not tokens[open_over].is_punct("("):
            continue
        end_over = doc.close_of(open_over)
        if end_over is None:
            continue
        depth = tokens[open_over].depth + 1
        order = next(
            (k for k in range(open_over + 1, end_over - 1)
             if tokens[k].depth == depth and tokens[k].is_word("ORDER")
             and tokens[k + 1].is_word("BY")),
            None,
        )
        if order is None:
            continue
        block = doc.block_at(tok.start)
        start = order + 2
        bounds = [k for k in range(start, end_over) if tokens[k].depth == depth
                  and tokens[k].is_punct(",")]
        for i, j in zip([start, *[b + 1 for b in bounds]], [*bounds, end_over], strict=False):
            while j > i and tokens[j - 1].is_word("ASC", "DESC"):
                j -= 1
            if i >= j:
                continue
            text = doc.text(i, j)
            if _constant(doc, i, j):
                findings.append(_finding(doc, tokens[i].start, f"Sıralama sabit/belirsiz: {text}"))
                continue
            expr = column_expr(doc, i, j)
            if expr is None or block is None:
                continue
            type_text = _effective_type(doc, block, expr)
            if type_text and base_type(type_text) in TEXT_TYPES:
                findings.append(
                    _finding(doc, tokens[i].start, f"{expr.text} ({type_text}) metin tipinde")
                )
    return findings


def _constant(doc: SqlDoc, i: int, j: int) -> bool:
    tokens = doc.tokens
    if j - i == 1:
        return tokens[i].kind in ("num", "str") or tokens[i].is_word("NULL")
    if tokens[i].is_punct("(") and doc.close_of(i) == j - 1:
        if doc.is_subquery(i):
            return not doc.has_from(i) and j - i <= 5
        return _constant(doc, i + 1, j - 1)
    return False


# ------------------------------------------------------------------ DWH-DATE-01
_DATE_NAME = re.compile(r"date|period|tarih", re.IGNORECASE)


def _checked_variables(doc: SqlDoc) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, type_text in variable_types(doc).items():
        family = type_family(type_text)
        base = base_type(type_text)
        if family in ("date", "datetime") or (
            base in ("int", "bigint", "varchar", "char") and _DATE_NAME.search(name)
        ):
            result[name] = type_text
    return result


SCD_VALIDITY_COLUMNS = frozenset({"edwvalidfrom", "edwvaliduntil"})


def date_variable_type_mismatch(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """A date-like variable compared in ON/WHERE with a column of another type family."""
    if not metadata.available:
        return []
    doc = _doc(sql, obj, metadata)
    variables = _checked_variables(doc)
    if not variables:
        return []
    tokens = doc.tokens
    findings: list[EngineFinding] = []
    seen: set[tuple[int, str]] = set()

    def variable(rng: tuple[int, int]) -> str | None:
        i, j = rng
        if j - i == 1 and tokens[i].kind == "var" and tokens[i].text.lower() in variables:
            return tokens[i].text
        return None

    def check(block: FromBlock, var: str, rng: tuple[int, int], offset: int) -> None:
        expr = column_expr(doc, *rng)
        if expr is None:
            return
        column_type = _effective_type(doc, block, expr)
        var_type = variables[var.lower()]
        a, b = type_family(var_type), type_family(column_type)
        if a and b and a != b and (offset, var.lower()) not in seen:
            seen.add((offset, var.lower()))
            if expr.column.lower() in SCD_VALIDITY_COLUMNS:
                message = (
                    f"SCD filtresi için DATETIME değişken kullanın: {var} ({var_type}) ↔ "
                    f"{expr.text} ({column_type}). Örn. DECLARE @DataDateDT DATETIME = {var}"
                )
            else:
                message = f"{var} ({var_type}) ↔ {expr.text} ({column_type})"
            findings.append(_finding(doc, offset, message))

    for block in doc.blocks:
        for _clause, (start, stop) in _predicate_ranges(block):
            for atom in atoms(parse_predicate(doc, start, stop)):
                cmp = comparison(doc, atom)
                if cmp is None:
                    continue
                offset = tokens[atom.i].start
                if cmp.op in COMPARISON_OPS:
                    if (var := variable(cmp.left)) is not None:
                        check(block, var, cmp.right, offset)
                    elif (var := variable(cmp.right)) is not None:
                        check(block, var, cmp.left, offset)
                elif cmp.op == "BETWEEN" and cmp.right2 is not None:
                    if (var := variable(cmp.left)) is not None:
                        check(block, var, cmp.right, offset)
                        check(block, var, cmp.right2, offset)
                    else:
                        for bound in (cmp.right, cmp.right2):
                            if (var := variable(bound)) is not None:
                                check(block, var, cmp.left, offset)
    return findings


# ------------------------------------------------------------------ DWH-PF-01
SIBLING_SUFFIXES = ("PersonnelExcluded", "PersonnelMasked")
def _with_history(*bases: str) -> frozenset[str]:
    return frozenset(name.lower() for base in bases for name in (base, f"{base}History"))


LKP_TABLES = _with_history("LKPCustomerParty", "LKPPersonParty", "LKPIdentityNumber")
# LKPIdentityNumber only masks identity numbers; next to an EDWDM source it is allowed.
PERSONNEL_LKP_TABLES = _with_history("LKPCustomerParty", "LKPPersonParty")
IDENTITY_COLUMNS = frozenset({"customerpartyid", "personpartyid"})


def personnel_siblings(obj: ObjectRef) -> list[tuple[str, str, str]]:
    return [(obj.database, obj.schema, f"{obj.name}{suffix}") for suffix in SIBLING_SUFFIXES]


def personnel_flag_view_source(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """EDWDM main views with Personnel* derivatives must expose a correctly sourced PersonnelFlag."""
    if not metadata.available or metadata.self_entry is None:
        return []
    if not any(metadata.lookup(*sibling) for sibling in personnel_siblings(obj)):
        return []
    own_columns = {c.name.lower() for c in metadata.self_entry.columns}
    if not own_columns & IDENTITY_COLUMNS:
        return []  # the view does not identify customers: PersonnelFlag is not required
    findings: list[EngineFinding] = []
    own_key = metadata.self_entry.key
    referenced = metadata.referenced_entries()
    lkp = [
        e for e in referenced
        if e.database.lower() == "edwutil" and e.schema.lower() == "dtg"
        and e.name.lower() in LKP_TABLES
    ]
    dm_sources = [
        e for e in referenced
        if e.database.lower() == "edwdm" and e.type in ("U", "V") and e.key != own_key
        and any(c.name.lower() == "personnelflag" for c in e.columns)
    ]
    if "personnelflag" not in own_columns:
        findings.append(EngineFinding(None, obj.name, "Asıl view PersonnelFlag kolonunu sunmuyor"))
    personnel_lkp = [e for e in lkp if e.name.lower() in PERSONNEL_LKP_TABLES]
    if dm_sources and personnel_lkp:
        lkp = personnel_lkp
        match = re.search(rf"\b{re.escape(lkp[0].name)}\b", masked, re.IGNORECASE)
        line = masked.count("\n", 0, match.start()) + 1 if match else None
        from app.services.rule_engine import snippet_at

        snippet = snippet_at(sql, match.start(), match.end()) if match else lkp[0].label
        findings.append(
            EngineFinding(
                line, snippet,
                f"EDWDM kaynağı ({dm_sources[0].label}) PersonnelFlag içeriyor; "
                "EDWUTIL.DTG LKP tabloları kullanılmamalı",
            )
        )
    if not dm_sources and not lkp:
        findings.append(
            EngineFinding(
                None, obj.name,
                "View doğrudan EDW'den okuyor; PersonnelFlag EDWUTIL.DTG LKP tablolarıyla "
                "hesaplanmalı",
            )
        )
    return findings


V3_CHECKS = {
    "left_then_inner_join": left_then_inner_join,
    "select_list_subquery": select_list_subquery,
    "tablock_physical_insert": tablock_physical_insert,
    "join_column_type_mismatch": join_column_type_mismatch,
    "non_sargable_predicates": non_sargable_predicates,
    "or_in_predicates": or_in_predicates,
    "scalar_udf_in_query": scalar_udf_in_query,
    "window_order_by_type": window_order_by_type,
    "date_variable_type_mismatch": date_variable_type_mismatch,
    "personnel_flag_view_source": personnel_flag_view_source,
}

