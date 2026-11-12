"""Built-in deterministic checks (rule kind "builtin").

Each check is a pure function of the object definition, its comment/string-masked text, the
object identity and its catalog metadata, so it is unit-testable without SQL Server.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.services.metadata import (
    CatalogEntry,
    ColumnInfo,
    ObjectMetadata,
    cte_names,
    parse_name_at,
)
from app.services.rule_engine import EngineFinding, line_of, snippet_at


@dataclass(frozen=True, slots=True)
class ObjectRef:
    database: str
    schema: str
    name: str
    type: str | None = None


BuiltinCheck = Callable[[str, str, ObjectRef, ObjectMetadata], list[EngineFinding]]

# ------------------------------------------------------------------ helpers
_WS = " \t\r\n"


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _WS:
        pos += 1
    return pos


def _matching_paren(text: str, open_pos: int) -> int:
    """Offset of the `)` closing the `(` at open_pos, or -1."""
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


# ------------------------------------------------------------------ NOLOCK
_TABLE_HINTS = frozenset(
    {
        "nolock", "readuncommitted", "readcommitted", "readcommittedlock", "readpast",
        "repeatableread", "serializable", "holdlock", "updlock", "xlock", "rowlock",
        "paglock", "tablock", "tablockx", "nowait", "index", "forceseek", "forcescan",
        "noexpand", "snapshot", "keepidentity", "keepdefaults", "ignore_constraints",
        "ignore_triggers", "spatial_window_max_cells",
    }
)
_NOT_ALIAS = frozenset(
    {
        "where", "on", "join", "inner", "left", "right", "full", "outer", "cross", "apply",
        "group", "order", "having", "union", "except", "intersect", "with", "set", "option",
        "select", "insert", "update", "delete", "merge", "when", "then", "else", "end", "as",
        "pivot", "unpivot", "output", "into", "values", "from", "if", "begin", "return",
        "declare", "exec", "execute", "truncate", "drop", "create", "alter", "while", "for",
        "using", "go", "commit", "rollback", "print", "raiserror", "throw", "open", "fetch",
        "close", "deallocate", "tablesample", "not", "and", "or", "natural", "window",
    }
)
_FROM_JOIN = re.compile(r"\b(FROM|JOIN)\b", re.IGNORECASE)
_ALIAS = re.compile(r"(AS\s+)?(\[(?:[^\]]|\]\])+\]|[A-Za-z_][\w$#@]*)", re.IGNORECASE)
_WITH_PAREN = re.compile(r"WITH\s*\(", re.IGNORECASE)
_NOLOCK = re.compile(r"\b(?:NOLOCK|READUNCOMMITTED)\b", re.IGNORECASE)
_DML_TARGET = re.compile(
    r"\b(?:UPDATE\s+(?!STATISTICS\b)|DELETE\s+)(?:TOP\s*\([^)]*\)\s*(?:PERCENT\s+)?)?"
    r"(?:FROM\s+)?",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\(|\)|;|\b[A-Za-z_]+\b")
_STATEMENT_START = frozenset(
    {
        "insert", "update", "delete", "merge", "truncate", "exec", "execute", "declare", "if",
        "while", "return", "drop", "create", "alter", "begin", "print", "select", "else",
        "commit", "rollback", "raiserror", "throw",
    }
)


@dataclass(frozen=True, slots=True)
class TableRef:
    parts: tuple[str, ...]
    start: int
    alias: str | None
    hints: str | None
    is_call: bool


def _is_hint_list(content: str) -> bool:
    words = re.findall(r"[A-Za-z_]+", content)
    return bool(words) and words[0].lower() in _TABLE_HINTS


def _read_table_ref(masked: str, pos: int) -> tuple[TableRef, int] | None:
    parsed = parse_name_at(masked, pos)
    if parsed is None:
        return None
    parts, end = parsed
    p = _skip_ws(masked, end)
    hints: str | None = None
    if p < len(masked) and masked[p] == "(":
        close = _matching_paren(masked, p)
        content = masked[p + 1 : close] if close != -1 else ""
        if close == -1 or not _is_hint_list(content):
            return TableRef(tuple(parts), pos, None, None, True), end
        hints = content  # legacy "T (NOLOCK)"
        p = _skip_ws(masked, close + 1)
    alias: str | None = None
    match = _ALIAS.match(masked, p)
    if match is not None:
        word = match.group(2).strip("[]")
        if match.group(1) or word.lower() not in _NOT_ALIAS:
            alias = word
            p = _skip_ws(masked, match.end())
    if hints is None:
        with_match = _WITH_PAREN.match(masked, p)
        open_pos = with_match.end() - 1 if with_match else (p if masked[p : p + 1] == "(" else -1)
        if open_pos != -1:
            close = _matching_paren(masked, open_pos)
            content = masked[open_pos + 1 : close] if close != -1 else ""
            if close != -1 and (with_match or _is_hint_list(content)):
                hints = content
                p = close + 1
    return TableRef(tuple(parts), pos, alias, hints, False), p


def _statement_end(masked: str, start: int) -> int:
    """Rough end of the statement starting before `start` (depth-0 `;` or next statement)."""
    depth = 0
    case_depth = 0
    for match in _TOKEN.finditer(masked, start):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                return match.start()
        elif depth > 0:
            continue
        elif token == ";":
            return match.start()
        else:
            word = token.lower()
            if word == "case":
                case_depth += 1
            elif word == "end":
                if case_depth == 0:
                    return match.start()
                case_depth -= 1
            elif word in _STATEMENT_START and not (word == "else" and case_depth):
                return match.start()
    return len(masked)


@dataclass(frozen=True, slots=True)
class _Target:
    parts: tuple[str, ...]
    start: int
    end: int


def _dml_targets(masked: str) -> list[_Target]:
    targets: list[_Target] = []
    for match in _DML_TARGET.finditer(masked):
        parsed = parse_name_at(masked, match.end())
        if parsed is None:
            continue
        parts, end = parsed
        targets.append(
            _Target(tuple(p.lower() for p in parts), match.start(), _statement_end(masked, end))
        )
    return targets


def _is_target(ref: TableRef, entry: CatalogEntry, targets: list[_Target],
               metadata: ObjectMetadata, database: str) -> bool:
    written = tuple(p.lower() for p in ref.parts)
    for target in targets:
        if not target.start <= ref.start <= target.end:
            continue
        if len(target.parts) == 1:
            name = target.parts[0]
            if (ref.alias and ref.alias.lower() == name) or written[-1] == name:
                return True
        elif target.parts == written or metadata.resolve(target.parts, database) is entry:
            return True
    return False


def table_references(masked: str) -> list[TableRef]:
    """Every name read after FROM/JOIN (and comma-separated FROM items)."""
    refs: list[TableRef] = []
    for match in _FROM_JOIN.finditer(masked):
        pos = match.end()
        while True:
            pos = _skip_ws(masked, pos)
            if pos >= len(masked) or masked[pos] == "(":
                break  # derived table / subquery
            read = _read_table_ref(masked, pos)
            if read is None:
                break
            ref, pos = read
            refs.append(ref)
            nxt = _skip_ws(masked, pos)
            if match.group(1).upper() == "FROM" and masked[nxt : nxt + 1] == "," and not ref.is_call:
                pos = nxt + 1
                continue
            break
    return refs


def nolock_physical_tables(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """Physical (user table) references without a NOLOCK/READUNCOMMITTED hint."""
    if not metadata.available:
        return []
    ctes = cte_names(masked)
    targets = _dml_targets(masked)
    findings: list[EngineFinding] = []
    for ref in table_references(masked):
        if ref.is_call or ref.parts[0][:1] in ("#", "@"):
            continue
        if len(ref.parts) == 1 and ref.parts[0].lower() in ctes:
            continue
        if ref.hints is not None and _NOLOCK.search(ref.hints):
            continue
        entry = metadata.resolve(ref.parts, obj.database)
        if entry is None or entry.type != "U":
            continue
        if _is_target(ref, entry, targets, metadata, obj.database):
            continue
        findings.append(
            EngineFinding(
                line_of(masked, ref.start),
                snippet_at(sql, ref.start, ref.start),
                f"{entry.label} fiziksel tablo; WITH (NOLOCK) eksik",
            )
        )
    return findings


# ------------------------------------------------------------------ derived views
DERIVED_SUFFIXES = ("PersonnelMasked", "PersonnelExcluded", "Masked")
PERSONNEL_SUFFIXES = ("PersonnelMasked", "PersonnelExcluded")
PERSONNEL_FLAG = "personnelflag"
MAX_NAMES = 15


def derived_suffix(name: str) -> str | None:
    """Longest derived-view suffix of `name` (case-insensitive), or None."""
    for suffix in DERIVED_SUFFIXES:
        if name.lower().endswith(suffix.lower()) and len(name) > len(suffix):
            return name[-len(suffix) :]
    return None


def main_view_of(obj: ObjectRef) -> tuple[str, str, str] | None:
    suffix = derived_suffix(obj.name)
    if suffix is None:
        return None
    return obj.database, obj.schema, obj.name[: -len(suffix)]


def _names(columns: list[str]) -> str:
    shown = ", ".join(columns[:MAX_NAMES])
    return shown + (f" … (+{len(columns) - MAX_NAMES})" if len(columns) > MAX_NAMES else "")


def _column_line(masked: str, sql: str, column: str) -> tuple[int | None, str]:
    match = re.search(rf"(?<![\w$#@])\[?{re.escape(column)}\]?(?![\w$#@])", masked, re.IGNORECASE)
    if match is None:
        return None, column
    return line_of(masked, match.start()), snippet_at(sql, match.start(), match.end())


def _references_main(masked: str, database: str, schema: str, main: str) -> bool:
    def part(value: str) -> str:
        return rf"(?:\[{re.escape(value)}\]|{re.escape(value)})"

    pattern = (
        rf"(?<![\w\].$#@])(?:{part(database)}\s*\.\s*)?{part(schema)}\s*\.\s*{part(main)}"
        r"(?![\w$#@])"
    )
    return re.search(pattern, masked, re.IGNORECASE) is not None


def derived_view_consistency(
    sql: str, masked: str, obj: ObjectRef, metadata: ObjectMetadata
) -> list[EngineFinding]:
    """vXMasked / vXPersonnelExcluded / vXPersonnelMasked must mirror vX (see RULES_SPEC 5).

    Without catalog metadata only the "reads the main view" text check runs; the
    PersonnelFlag = 0 filter is required only when the main view has a PersonnelFlag column.
    """
    suffix = derived_suffix(obj.name)
    if suffix is None:
        return []
    main = obj.name[: -len(suffix)]
    main_label = f"{obj.schema}.{main}"
    findings: list[EngineFinding] = []

    main_entry: CatalogEntry | None = None
    if metadata.available:
        main_entry = metadata.lookup(obj.database, obj.schema, main)
        if main_entry is None:
            return [EngineFinding(None, main_label, f"Asıl view bulunamadı: {main_label}")]

    if not _references_main(masked, obj.database, obj.schema, main):
        findings.append(
            EngineFinding(
                None,
                main_label,
                f"Türev view asıl view'dan okumuyor: {obj.database}.{main_label} referansı yok.",
            )
        )

    own = metadata.self_entry.columns if metadata.self_entry is not None else []
    if main_entry is not None and own:
        findings.extend(_compare_columns(sql, masked, main_entry.columns, own))

    # The filter is required only when the main view exposes PersonnelFlag (aggregated main
    # views without customer rows have none); unknown main columns -> not reported.
    main_has_flag = main_entry is not None and any(
        c.name.lower() == PERSONNEL_FLAG for c in main_entry.columns
    )
    if (
        main_has_flag
        and suffix.lower() in (s.lower() for s in PERSONNEL_SUFFIXES)
        and not re.search(r"PersonnelFlag\]?\s*=\s*0(?!\d)", masked, re.IGNORECASE)
    ):
        findings.append(
            EngineFinding(
                None,
                "",
                "Personnel türevinde PersonnelFlag = 0 filtresi yok "
                "(WHERE T1.PersonnelFlag = 0 uygulanmalı).",
            )
        )
    return findings


def _compare_columns(
    sql: str, masked: str, main_columns: list[ColumnInfo], own_columns: list[ColumnInfo]
) -> list[EngineFinding]:
    findings: list[EngineFinding] = []
    flag = next((c for c in own_columns if c.name.lower() == PERSONNEL_FLAG), None)
    if flag is not None:
        line, snippet = _column_line(masked, sql, flag.name)
        findings.append(
            EngineFinding(
                line,
                snippet,
                "Türev view PersonnelFlag kolonunu sunmamalı; bu kolon yalnız asıl view'da bulunur.",
            )
        )
    main = [c for c in main_columns if c.name.lower() != PERSONNEL_FLAG]
    own = [c for c in own_columns if c.name.lower() != PERSONNEL_FLAG]
    main_by_name = {c.name: c for c in main}
    own_by_name = {c.name: c for c in own}

    # Exact names match; names equal only case-insensitively are paired and reported once.
    pairs: dict[str, str] = {name: name for name in main_by_name if name in own_by_name}
    unmatched_own = {n.lower(): n for n in own_by_name if n not in main_by_name}
    for name in main_by_name:
        if name in pairs:
            continue
        other = unmatched_own.pop(name.lower(), None)
        if other is not None:
            pairs[name] = other
            line, snippet = _column_line(masked, sql, other)
            findings.append(
                EngineFinding(
                    line,
                    snippet,
                    "Kolon adı yalnızca büyük/küçük harf farkıyla farklı: "
                    f"asıl '{name}', türev '{other}'",
                )
            )
    paired_own = set(pairs.values())
    missing = [c.name for c in main if c.name not in pairs]
    extra = [c.name for c in own if c.name not in paired_own]
    if missing:
        findings.append(
            EngineFinding(None, _names(missing),
                          f"Asıl view'da olup türevde eksik kolonlar: {_names(missing)}")
        )
    if extra:
        line, snippet = _column_line(masked, sql, extra[0])
        findings.append(
            EngineFinding(line, snippet,
                          f"Türevde olup asıl view'da olmayan kolonlar: {_names(extra)}")
        )

    main_order = [c.name for c in main if c.name in pairs]
    reverse = {own_name: main_name for main_name, own_name in pairs.items()}
    own_order = [reverse[c.name] for c in own if c.name in reverse]
    if main_order != own_order:
        moved = [a for a, b in zip(main_order, own_order, strict=False) if a != b]
        line, snippet = _column_line(masked, sql, pairs[moved[0]]) if moved else (None, "")
        findings.append(
            EngineFinding(line, snippet,
                          f"Kolon sırası asıl view ile farklı: {_names(moved)}")
        )

    for main_name, own_name in pairs.items():
        expected, actual = main_by_name[main_name], own_by_name[own_name]
        if expected.type_key == actual.type_key:
            continue
        # Team standard: a column masked with NULL in a derived view may change type
        # (NULL AS [X] becomes int); that difference is accepted and not reported.
        if _is_null_masked(masked, own_name):
            continue
        line, snippet = _column_line(masked, sql, own_name)
        message = (
            f"Kolon tipi farklı: {own_name} türevde {actual.type_label}, "
            f"asıl view'da {expected.type_label}."
        )
        findings.append(EngineFinding(line, snippet, message))
    return findings


def _is_null_masked(masked: str, column: str) -> bool:
    """True when the derived view outputs the column as a NULL mask.

    Accepted forms: ``NULL AS [X]``, ``NULL [X]``, ``CAST(NULL AS <tip>) AS [X]`` and
    ``CONVERT(<tip>, NULL) AS [X]`` (the alias keyword and brackets are optional).
    """
    name = rf"\[?{re.escape(column)}\]?(?![\w$#@])"
    patterns = (
        rf"\bNULL\s+(?:AS\s+)?{name}",
        rf"\bCAST\s*\(\s*NULL\s+AS\s+[^()]*(?:\([^()]*\))?\s*\)\s*(?:AS\s+)?{name}",
        rf"\bCONVERT\s*\(\s*[^,()]*(?:\([^()]*\))?\s*,\s*NULL\s*\)\s*(?:AS\s+)?{name}",
    )
    return any(re.search(p, masked, re.IGNORECASE) for p in patterns)


# ------------------------------------------------------------------ registry
BUILTIN_CHECKS: dict[str, BuiltinCheck] = {
    "nolock_physical_tables": nolock_physical_tables,
    "derived_view_consistency": derived_view_consistency,
}


def related_objects(check: str | None, obj: ObjectRef) -> list[tuple[str, str, str]]:
    """Extra catalog objects a builtin check needs besides the referenced ones."""
    if check == "derived_view_consistency":
        main = main_view_of(obj)
        return [main] if main else []
    if check == "personnel_flag_view_source":
        from app.services.perf_checks import personnel_siblings

        return personnel_siblings(obj)
    return []


def _register_v3() -> None:
    from app.services.perf_checks import V3_CHECKS
    from app.services.v4_checks import V4_CHECKS

    BUILTIN_CHECKS.update(V3_CHECKS)
    BUILTIN_CHECKS.update(V4_CHECKS)


_register_v3()
