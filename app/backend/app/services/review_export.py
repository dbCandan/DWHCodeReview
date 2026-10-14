"""CSV and fix-comment SQL files of a stored run (sql-review 005 Requirement 7-10).

Ported from the previous application's ``frontend/src/components/ExportMenu.tsx``
(``buildReviewResultsCsv``, ``buildReviewResultsSql`` and ``buildSqlReviewCommentHeader``) and
now built on the server from the stored run. Changes the PRD requires: CSV cells that a
spreadsheet would run as a formula get a leading ``'``; false-positive marks leave the SQL
comment block; every "Satir N" in that block is the real line of the downloaded file on which
source line N stands, computed from the file itself instead of the source's "-1" shift.
The rule's named group is the last CSV column and stands next to the rule in the SQL comment
(005 Requirement 7-8 and Decision 9, sql-review/PRDs/007-rule-group-selection).
Nothing here touches the network, a database or a file.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

CSV_HEADERS = (
    "generated_at",
    "database",
    "schema",
    "name",
    "object_type",
    "rule_id",
    "tier",
    "status",
    "severity",
    "description",
    "line_reference",
    "code_snippet",
    "false_positive",
    "rule_group",
)
# JavaScript's String.prototype.trim and \s set, so the files match the previous exports.
JS_WHITESPACE = "\t\n\v\f\r             " "     　﻿"
_JS_WHITESPACE_RUN = re.compile(f"[{re.escape(JS_WHITESPACE)}]+")
_CSV_QUOTE_NEEDED = re.compile(r"[\",\n\r]")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_LINE_REFERENCE = re.compile(
    r"\b([Ss][Aa][Tt][ıIiİ][Rr])(\s+)(\d+(?:\s*[–-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[–-]\s*\d+)?)*)"
)
_NUMBER = re.compile(r"\d+")
SQL_COMMENT_TITLE = "SQL Review - Duzeltilmesi Gereken Yerler"
SQL_COMMENT_NOTE = (
    'Not: Asagidaki "Satir" degerleri bu dosyadaki mutlak satir numaralaridir '
    "(SSMS satir no ile ayni)."
)


@dataclass(frozen=True, slots=True)
class ExportRuleResult:
    rule_id: str
    tier: str
    status: str
    severity: str
    description: str = field(repr=False)
    line_reference: str
    code_snippet: str = field(repr=False)
    false_positive: bool
    # Names of the rule's groups in the pinned version, in group order (007 Requirement 7).
    rule_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportFinding:
    rule_id: str
    severity: str
    description: str = field(repr=False)
    line_reference: str
    code_snippet: str = field(repr=False)
    false_positive: bool
    # Names of the rule's groups in the pinned version, in group order (007 Requirement 7).
    rule_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportObject:
    database: str
    schema: str
    name: str
    object_type: str
    error: str
    parse_warning: str
    rule_results: Sequence[ExportRuleResult]
    findings: Sequence[ExportFinding]
    source_sql: str = field(default="", repr=False)


def js_trim(value: str) -> str:
    return value.strip(JS_WHITESPACE)


def _protect_formula(value: str) -> str:
    """Requirement 7: a leading ' keeps a spreadsheet from running the cell as a formula."""

    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _csv_field(value: str | None) -> str:
    text = _protect_formula(value or "")
    if _CSV_QUOTE_NEEDED.search(text):
        return '"' + text.replace('"', '""') + '"'
    return text


def _csv_line(fields: Sequence[str | None]) -> str:
    return ",".join(_csv_field(value) for value in fields)


def _fail_rule_marked(item: ExportObject, result: ExportRuleResult) -> bool:
    if result.status.strip().upper() != "FAIL":
        return False
    if result.false_positive:
        return True
    return any(
        finding.false_positive for finding in item.findings if finding.rule_id == result.rule_id
    )


def results_csv_header() -> str:
    return "\ufeff" + _csv_line(CSV_HEADERS)


def results_csv_error_row(generated_at: str, database: str, review_error: str) -> str:
    error_row = [generated_at, database, "", "", "", "", "", "", "", review_error, "", ""]
    return _csv_line([*error_row, "false", ""])


def results_csv_rows(
    objects: Sequence[ExportObject], *, generated_at: str, database: str = ""
) -> list[str]:
    """The rows of some objects of a run; a large run is written chunk by chunk."""

    lines: list[str] = []
    for item in objects:
        row_database = js_trim(item.database) or database
        meta = " | ".join(part for part in (item.error, item.parse_warning) if part)
        prefix = [generated_at, row_database, item.schema, item.name, item.object_type]

        def finding_row(
            finding: ExportFinding, prefix: list[str] = prefix, meta: str = meta
        ) -> str:
            description = " — ".join(part for part in (meta, finding.description) if part)
            return _csv_line(
                [
                    *prefix,
                    finding.rule_id,
                    "",
                    "FAIL",
                    finding.severity,
                    description,
                    finding.line_reference,
                    finding.code_snippet,
                    "true" if finding.false_positive else "false",
                    _group_cell(finding.rule_groups),
                ]
            )

        if item.rule_results:
            for result in item.rule_results:
                details = (
                    [finding for finding in item.findings if finding.rule_id == result.rule_id]
                    if result.status.strip().upper() == "FAIL"
                    else []
                )
                if details:
                    lines.extend(finding_row(finding) for finding in details)
                    continue
                description = " — ".join(part for part in (meta, result.description) if part)
                lines.append(
                    _csv_line(
                        [
                            *prefix,
                            result.rule_id,
                            result.tier,
                            result.status,
                            result.severity,
                            description,
                            result.line_reference,
                            result.code_snippet,
                            "true" if _fail_rule_marked(item, result) else "false",
                            _group_cell(result.rule_groups),
                        ]
                    )
                )
        elif item.findings:
            lines.extend(finding_row(finding) for finding in item.findings)
        else:
            lines.append(_csv_line([*prefix, "", "", "", "", meta, "", "", "false", ""]))
    return lines


def build_results_csv(
    objects: Sequence[ExportObject],
    *,
    generated_at: str,
    database: str = "",
    review_error: str | None = None,
) -> str:
    """``buildReviewResultsCsv``: UTF-8 BOM, CRLF, one row per finding or rule result."""

    header = results_csv_header()
    if not objects and review_error:
        return f"{header}\r\n{results_csv_error_row(generated_at, database, review_error)}"
    rows = results_csv_rows(objects, generated_at=generated_at, database=database)
    return "\r\n".join([header, *rows])


def _object_title(item: ExportObject) -> str:
    database = js_trim(item.database)
    if database:
        return f"[{database}] {item.schema}.{item.name} ({item.object_type})"
    return f"{item.schema}.{item.name} ({item.object_type})"


def _note(description: str) -> str:
    text = js_trim(description) or "Aciklama yok"
    return _JS_WHITESPACE_RUN.sub(" ", text.replace("|", "¦"))


def _location(reference: str) -> str:
    # One comment line per item: a line break inside a model reference would shift the file.
    return _JS_WHITESPACE_RUN.sub(" ", js_trim(reference))


def _group_names(rule_groups: tuple[str, ...]) -> list[str]:
    names = (_JS_WHITESPACE_RUN.sub(" ", js_trim(name)) for name in rule_groups)
    return [name for name in names if name]


def _group_cell(rule_groups: tuple[str, ...]) -> str:
    """The CSV ``rule_group`` cell: group names joined with ``; `` (005 Decision 9)."""

    return "; ".join(_group_names(rule_groups))


def _rule_label(rule_id: str, rule_groups: tuple[str, ...]) -> str:
    """``Kural01 (Güvenlik, Performans)``; an ungrouped rule stays ``Kural01`` (Requirement 8)."""

    names = _group_names(rule_groups)
    return f"{rule_id} ({', '.join(names)})" if names else rule_id


def _comment_items(item: ExportObject) -> list[tuple[str, str, str]]:
    """(rule, raw line reference, note) lines of one object; false positives never appear."""

    lines = [
        (
            _rule_label(finding.rule_id, finding.rule_groups),
            _location(finding.line_reference),
            _note(finding.description),
        )
        for finding in item.findings
        if not finding.false_positive
    ]
    if lines:
        return lines
    return [
        (
            _rule_label(result.rule_id, result.rule_groups),
            _location(result.line_reference),
            _note(result.description),
        )
        for result in item.rule_results
        if result.status.strip().upper() == "FAIL" and not _fail_rule_marked(item, result)
    ]


@dataclass(frozen=True, slots=True)
class _SourcePlacement:
    """Where one object's reviewed text stands in the body of the downloaded file."""

    body_offset: int
    trimmed: str = field(repr=False)
    leading: int
    line_starts: tuple[int, ...]


def _line_starts(source: str) -> tuple[int, ...]:
    """Offsets of the lines the model numbered (``str.splitlines``, as the prompt does)."""

    starts: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        starts.append(offset)
        offset += len(line)
    return tuple(starts)


def _file_line_mapper(
    placement: _SourcePlacement, body_first_line: int, body: str
) -> Callable[[int], int]:
    source_first_line = body_first_line + body.count("\n", 0, placement.body_offset)

    def file_line(number: int) -> int:
        starts = placement.line_starts
        if not starts or number < 1:
            return source_first_line
        if number > len(starts):
            return file_line(len(starts)) + (number - len(starts))
        offset = starts[number - 1] - placement.leading
        if offset <= 0:
            return source_first_line
        return source_first_line + placement.trimmed.count("\n", 0, offset)

    return file_line


def shift_line_reference(reference: str, file_line: Callable[[int], int]) -> str:
    """Rewrite every number after "Satır"/"Satir" (single, range or list) to its file line."""

    def rewrite(match: re.Match[str]) -> str:
        numbers = _NUMBER.sub(lambda number: str(file_line(int(number.group(0)))), match.group(3))
        return f"{match.group(1)}{match.group(2)}{numbers}"

    return _LINE_REFERENCE.sub(rewrite, reference)


def build_sql_export(objects: Sequence[ExportObject], *, script: bool) -> str | None:
    """The fix-comment block over the reviewed text; None when no text was stored."""

    placements: dict[int, _SourcePlacement] = {}
    if script:
        source = objects[0].source_sql if objects else ""
        body = js_trim(source)
        if body:
            placements[0] = _SourcePlacement(
                0, body, len(source) - len(source.lstrip(JS_WHITESPACE)), _line_starts(source)
            )
    else:
        chunks: list[str] = []
        offset = 0
        for index, item in enumerate(objects):
            trimmed = js_trim(item.source_sql)
            if not trimmed:
                continue
            if chunks:
                offset += len("\n\nGO\n\n")
            title = f"-- {_object_title(item)}\n"
            placements[index] = _SourcePlacement(
                offset + len(title),
                trimmed,
                len(item.source_sql) - len(item.source_sql.lstrip(JS_WHITESPACE)),
                _line_starts(item.source_sql),
            )
            chunk = f"{title}{trimmed}"
            chunks.append(chunk)
            offset += len(chunk)
        body = "\n\nGO\n\n".join(chunks)
        # The chunks are trimmed and start with "--", so trimming the joined body keeps offsets.
        body = js_trim(body)
    if not body:
        return None

    sections: list[tuple[int, str, list[tuple[str, str, str]]]] = [
        (index, _object_title(item), _comment_items(item)) for index, item in enumerate(objects)
    ]
    sections = [section for section in sections if section[2]]
    header_lines = ["/*", SQL_COMMENT_TITLE, SQL_COMMENT_NOTE]
    for _, title, items in sections:
        header_lines.extend(["", title, *("" for _ in items)])
    if not sections:
        header_lines.extend(["", "Tespit edilen duzeltme maddesi yok."])
    header_lines.append("*/")
    body_first_line = "\n".join(header_lines).count("\n") + 2

    lines = ["/*", SQL_COMMENT_TITLE, SQL_COMMENT_NOTE]
    for index, title, items in sections:
        placement = placements.get(index)
        mapper = None if placement is None else _file_line_mapper(placement, body_first_line, body)
        lines.extend(["", title])
        for rule_id, reference, note in items:
            location = reference or "Satir bilgisi yok"
            if mapper is not None and reference:
                location = shift_line_reference(location, mapper)
            lines.append(f"- {rule_id} — {location} — {note}")
    if not sections:
        lines.extend(["", "Tespit edilen duzeltme maddesi yok."])
    lines.append("*/")
    return js_trim("\n".join(lines) + "\n" + body)
