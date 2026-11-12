"""Rule engine: evaluates one rule against one SQL object.

Regex rules run locally, builtin rules run the checks of `app.services.builtin_checks`
over catalog metadata, LLM rules are delegated to `app.services.llm`. All produce
`EngineFinding` values (1-based line or None, snippet, message).

Applicability (`applies_to`: object_types, databases, name_pattern) decides whether a check
exists at all (and is counted in total_checks); preconditions (`precondition_met`,
`metadata.metadata_precondition_met`) only decide whether an applicable check can finish
without findings and without calling the LLM.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.builtin_checks import ObjectRef
    from app.services.llm import LlmConfig
    from app.services.metadata import ObjectMetadata

SNIPPET_MAX = 500
# Builtin checks that work on the text alone (no catalog metadata is collected for them).
TEXT_ONLY_BUILTINS = frozenset({"left_then_inner_join", "select_list_subquery", "or_in_predicates"})
MAX_FINDINGS_PER_CHECK = 500


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """The parts of a rule the engine needs (works for live rules and snapshots)."""

    code: str
    name: str
    kind: str = "regex"
    description: str = ""
    pattern: str | None = None
    match_mode: str = "match"
    target: str = "definition"
    ignore_case: bool = True
    ignore_comments: bool = True
    llm_prompt: str | None = None
    object_types: Sequence[str] = field(default_factory=tuple)
    builtin_check: str | None = None
    precondition: str | None = None
    metadata_precondition: str | None = None
    requires_metadata: bool = False
    databases: Sequence[str] = field(default_factory=tuple)
    name_pattern: str | None = None

    @property
    def needs_metadata(self) -> bool:
        """Catalog metadata must be collected before this rule can run."""
        if self.requires_metadata or self.metadata_precondition:
            return True
        return self.kind == "builtin" and self.builtin_check not in TEXT_ONLY_BUILTINS

    @classmethod
    def from_obj(cls, obj: object) -> RuleSpec:
        return cls(
            code=getattr(obj, "code"),
            name=getattr(obj, "name"),
            kind=getattr(obj, "kind"),
            description=getattr(obj, "description") or "",
            pattern=getattr(obj, "pattern"),
            match_mode=getattr(obj, "match_mode") or "match",
            target=getattr(obj, "target") or "definition",
            ignore_case=bool(getattr(obj, "ignore_case")),
            ignore_comments=bool(getattr(obj, "ignore_comments")),
            llm_prompt=getattr(obj, "llm_prompt"),
            object_types=tuple(getattr(obj, "object_types") or ()),
            builtin_check=getattr(obj, "builtin_check", None),
            precondition=getattr(obj, "precondition", None),
            metadata_precondition=getattr(obj, "metadata_precondition", None),
            requires_metadata=bool(getattr(obj, "requires_metadata", False)),
            databases=tuple(getattr(obj, "databases", None) or ()),
            name_pattern=getattr(obj, "name_pattern", None),
        )


@dataclass(frozen=True, slots=True)
class EngineFinding:
    line: int | None
    snippet: str
    message: str


class RuleError(Exception):
    """A rule cannot be evaluated (invalid pattern, LLM failure...). Message is Turkish.

    `findings` holds partial results (e.g. the LLM chunks that succeeded) to keep anyway.
    """

    def __init__(self, message: str = "", findings: list[EngineFinding] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


PRECONDITION_FLAGS = re.IGNORECASE | re.DOTALL | re.MULTILINE


def compile_optional(pattern: str | None, flags: int, label: str) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, flags)
    except re.error as error:
        raise RuleError(f"Geçersiz düzenli ifade ({label}): {error}") from None


def applies_to(
    rule: RuleSpec,
    object_type: str | None,
    database: str | None = None,
    object_name: str | None = None,
) -> bool:
    """object_types AND databases AND name_pattern must match; empty/None means "all".

    `object_name` is "schema.name". An unknown value (None) is not filtered. An invalid
    name_pattern makes the rule inapplicable.
    """
    if rule.object_types and object_type is not None and object_type not in rule.object_types:
        return False
    if rule.databases and database is not None:
        wanted = {db.strip().casefold() for db in rule.databases}
        if database.strip().casefold() not in wanted:
            return False
    if rule.name_pattern and object_name is not None:
        try:
            pattern = compile_optional(rule.name_pattern, re.IGNORECASE, "name_pattern")
        except RuleError:
            return False
        if pattern is not None and pattern.search(object_name) is None:
            return False
    return True


def applies_to_object(rule: RuleSpec, database: str, schema: str, name: str, object_type: str) -> bool:
    """Applicability of a rule to an analysed object; the runner and total_checks use this."""
    return applies_to(rule, object_type, database, f"{schema}.{name}")


def precondition_met(rule: RuleSpec, sql: str, masked: str | None = None) -> bool:
    """The rule's text precondition on the masked (ignore_comments) or raw definition."""
    pattern = compile_optional(rule.precondition, PRECONDITION_FLAGS, "precondition")
    if pattern is None:
        return True
    if rule.ignore_comments:
        haystack = masked if masked is not None else mask_sql(sql)
    else:
        haystack = sql
    return pattern.search(haystack) is not None


# ------------------------------------------------------------------ masking
def mask_sql(sql: str, strings: bool = True) -> str:
    """Blank out comments and string literals, keeping length and newlines.

    `--` line comments, `/* */` block comments (nested) and single-quoted strings
    (with `''` escapes) become spaces; `\\n`/`\\r` are kept so offsets and line numbers
    of the masked text equal those of the original. Bracketed and double-quoted
    identifiers are left as they are (a `--` inside `[...]` is not a comment).
    With `strings=False` only comments are blanked.
    """
    out = list(sql)
    n = len(sql)
    i = 0

    def blank(start: int, end: int) -> None:
        for k in range(start, end):
            if out[k] not in "\r\n":
                out[k] = " "

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            end = n if end == -1 else end
            blank(i, end)
            i = end
        elif ch == "/" and nxt == "*":
            depth = 1
            j = i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            blank(i, j)
            i = j
        elif ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            if strings:
                blank(i, j)
            i = j
        elif ch in "[\"":
            close = "]" if ch == "[" else '"'
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if j + 1 < n and sql[j + 1] == close:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            i = j
        else:
            i += 1
    return "".join(out)


# ------------------------------------------------------------------ regex
def compile_pattern(rule: RuleSpec) -> re.Pattern[str]:
    if not rule.pattern:
        raise RuleError("Regex kuralı için desen (pattern) zorunludur.")
    flags = re.MULTILINE | (re.IGNORECASE if rule.ignore_case else 0)
    try:
        return re.compile(rule.pattern, flags)
    except re.error as error:
        raise RuleError(f"Geçersiz düzenli ifade: {error}") from None


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def snippet_at(original: str, start: int, end: int) -> str:
    """The full source line(s) covered by [start, end), trimmed, at most SNIPPET_MAX chars."""
    if end > start and original[end - 1] == "\n":
        end -= 1
    line_start = original.rfind("\n", 0, start) + 1
    line_end = original.find("\n", max(end, start))
    line_end = len(original) if line_end == -1 else line_end
    text = original[line_start:line_end].strip()
    if len(text) > SNIPPET_MAX:
        text = text[: SNIPPET_MAX - 1] + "…"
    return text


def _message(rule: RuleSpec) -> str:
    return rule.description.strip() or rule.name


def _code_matches(pattern: re.Pattern[str], sql: str) -> list[re.Match[str]]:
    """Matches for ignore_comments: comments are never seen, strings never start a match.

    Matches of the fully masked text (comments and strings blanked) are joined by matches of
    the comment-masked text that start in code, so a pattern may still look into a string
    literal it follows (e.g. `EdwStatus = '1'`). Sorted by offset.
    """
    masked = mask_sql(sql)
    comments_masked = mask_sql(sql, strings=False)
    found = {m.start(): m for m in pattern.finditer(masked)}
    for match in pattern.finditer(comments_masked):
        start = match.start()
        in_string = start < len(sql) and masked[start] != comments_masked[start]
        if not in_string and start not in found:
            found[start] = match
    return [found[start] for start in sorted(found)]


def run_regex(rule: RuleSpec, sql: str, object_name: str = "") -> list[EngineFinding]:
    pattern = compile_pattern(rule)
    message = _message(rule)

    if rule.target == "name":
        found = pattern.search(object_name or "") is not None
        if rule.match_mode == "absent":
            return [] if found else [EngineFinding(None, object_name, message)]
        return [EngineFinding(None, object_name, message)] if found else []

    matches = _code_matches(pattern, sql) if rule.ignore_comments else pattern.finditer(sql)
    if rule.match_mode == "absent":
        if next(iter(matches), None) is None:
            return [EngineFinding(None, "", message)]
        return []

    findings: list[EngineFinding] = []
    seen_lines: set[int] = set()
    for match in matches:
        line = line_of(sql, match.start())
        if line in seen_lines:
            continue
        seen_lines.add(line)
        findings.append(EngineFinding(line, snippet_at(sql, match.start(), match.end()), message))
        if len(findings) >= MAX_FINDINGS_PER_CHECK:
            break
    return findings


# ------------------------------------------------------------------ dispatcher
@dataclass(frozen=True, slots=True)
class CheckContext:
    """The analysed object and its catalog metadata (builtin and metadata-aware LLM rules)."""

    obj: ObjectRef
    metadata: ObjectMetadata
    masked: str | None = None


def default_context(object_name: str, database: str = "") -> CheckContext:
    """Context without catalog access (rule test endpoint)."""
    from app.services.builtin_checks import ObjectRef as _ObjectRef
    from app.services.metadata import empty_metadata

    schema, _, name = (object_name or "dbo.TestNesnesi").rpartition(".")
    return CheckContext(_ObjectRef(database, schema or "dbo", name), empty_metadata())


def run_builtin(rule: RuleSpec, sql: str, context: CheckContext) -> list[EngineFinding]:
    from app.services.builtin_checks import BUILTIN_CHECKS

    check = BUILTIN_CHECKS.get(rule.builtin_check or "")
    if check is None:
        raise RuleError(f"Bilinmeyen yerleşik kontrol: {rule.builtin_check or '-'}")
    masked = context.masked if context.masked is not None else mask_sql(sql)
    return check(sql, masked, context.obj, context.metadata)[:MAX_FINDINGS_PER_CHECK]


def run_rule(
    rule: RuleSpec,
    sql: str,
    object_name: str = "",
    llm_config: LlmConfig | None = None,
    context: CheckContext | None = None,
) -> list[EngineFinding]:
    """Evaluate one rule (preconditions are the caller's job). Raises RuleError on failure."""
    if rule.kind == "regex":
        return run_regex(rule, sql, object_name)
    if rule.kind == "builtin":
        return run_builtin(rule, sql, context or default_context(object_name))
    if rule.kind == "llm":
        from app.services import llm

        if llm_config is None:
            raise RuleError("LLM ayarları etkin değil veya eksik.")
        if not (rule.llm_prompt or "").strip():
            raise RuleError("LLM kuralı için kural tanımı (llm_prompt) zorunludur.")
        metadata_text = None
        if rule.requires_metadata:
            from app.services.metadata import empty_metadata, format_for_llm

            metadata_text = format_for_llm(context.metadata if context else empty_metadata())
        try:
            return llm.review(llm_config, rule, sql, object_name, metadata_text)
        except llm.LlmError as error:
            raise RuleError(str(error), error.findings) from None
    raise RuleError(f"Bilinmeyen kural türü: {rule.kind}")

