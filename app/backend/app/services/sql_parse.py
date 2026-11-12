"""Small T-SQL structure helpers for the builtin checks (no full parser).

Everything works on the comment-masked text (comments blanked, string literals kept so that a
literal is one token), with offsets equal to the original definition:

- `tokenize`: words, [bracketed]/"quoted" identifiers, @variables, numbers, strings, operators
  and punctuation, each with its parenthesis depth (a `(` and its `)` share the outer depth).
- `SqlDoc.from_blocks`: every FROM clause as a `FromBlock` (items = FROM item, JOIN/APPLY items
  and comma items at the same depth, each with its table reference, alias and ON range), the
  WHERE range that follows it and the SELECT that owns it.
- `parse_predicate`: a boolean tree (Or / And / Atom) of an ON or WHERE range, split at
  top-level AND/OR (BETWEEN ... AND kept together, CASE ... END and sub-queries opaque).
- `comparison` / `column_expr`: the operator and sides of an atom; `alias.column`, a bare
  column, or CAST/CONVERT/TRY_* around one (with its target type).
- `resolve_column`: alias -> FROM item -> catalog entry -> column type.
- `variable_types`: procedure parameters and DECLARE'd variables with their types.
- `type_family`: comparable type groups.

Anything that cannot be resolved returns None; callers never report those (precision first).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property

from app.services.metadata import CatalogEntry, ColumnInfo, ObjectMetadata, cte_names

# ------------------------------------------------------------------ tokens
_TOKEN_RE = re.compile(
    r"""
    (?P<str>N?'(?:[^']|'')*'?)
  | (?P<br>\[(?:[^\]]|\]\])*\]?)
  | (?P<dq>"(?:[^"]|"")*"?)
  | (?P<var>@@?[\w@#$]+)
  | (?P<word>[A-Za-z_#À-￿][\w@#$À-￿]*)
  | (?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<op><=|>=|<>|!=|!<|!>|=|<|>)
  | (?P<punct>[(),.;*+\-/%~&|^:$])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Tok:
    kind: str  # str | br | dq | var | word | num | op | punct
    text: str
    start: int
    end: int
    depth: int

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == "word" else ""

    @property
    def ident(self) -> str | None:
        """Identifier value (brackets removed) for word/br/dq tokens."""
        if self.kind == "word":
            return self.text
        if self.kind == "br":
            return self.text[1:-1].replace("]]", "]")
        if self.kind == "dq":
            return self.text[1:-1].replace('""', '"')
        return None

    def is_word(self, *words: str) -> bool:
        return self.kind == "word" and self.text.upper() in words

    def is_punct(self, text: str) -> bool:
        return self.kind == "punct" and self.text == text


def tokenize(code: str) -> list[Tok]:
    tokens: list[Tok] = []
    depth = 0
    for match in _TOKEN_RE.finditer(code):
        kind = match.lastgroup or "punct"
        text = match.group(0)
        if kind == "punct" and text == ")":
            depth = max(depth - 1, 0)
            tokens.append(Tok(kind, text, match.start(), match.end(), depth))
            continue
        tokens.append(Tok(kind, text, match.start(), match.end(), depth))
        if kind == "punct" and text == "(":
            depth += 1
    return tokens


# ------------------------------------------------------------------ keywords
STATEMENT_START = frozenset(
    {
        "SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "SET", "DECLARE", "IF", "ELSE",
        "WHILE", "BEGIN", "END", "RETURN", "EXEC", "EXECUTE", "PRINT", "TRUNCATE", "DROP",
        "CREATE", "ALTER", "COMMIT", "ROLLBACK", "RAISERROR", "THROW", "GOTO", "OPEN", "FETCH",
        "CLOSE", "DEALLOCATE", "WAITFOR", "BREAK", "CONTINUE", "USE",
    }
)
CLAUSE_END = frozenset(
    {
        "WHERE", "GROUP", "ORDER", "HAVING", "UNION", "EXCEPT", "INTERSECT", "OPTION", "FOR",
        "WINDOW", "WHEN", "THEN", "OUTPUT", "INTO", "VALUES",
    }
)
JOIN_HINTS = frozenset({"HASH", "LOOP", "MERGE", "REMOTE"})
KEYWORDS = frozenset(
    {
        "AND", "OR", "NOT", "NULL", "IS", "IN", "LIKE", "BETWEEN", "EXISTS", "CASE", "WHEN",
        "THEN", "ELSE", "END", "AS", "ON", "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT",
        "RIGHT", "FULL", "OUTER", "CROSS", "APPLY", "TOP", "DISTINCT", "ALL", "ANY", "SOME",
        "ASC", "DESC", "BY", "ORDER", "GROUP", "HAVING", "OVER", "PARTITION", "ROWS", "RANGE",
        "UNBOUNDED", "PRECEDING", "FOLLOWING", "CURRENT", "ROW", "WITH", "COLLATE", "ESCAPE",
        "UNION", "EXCEPT", "INTERSECT", "VALUES", "SET", "INTO", "TRUE", "FALSE",
    }
)
# Date parts and type names are never bare column references.
NOT_COLUMNS = frozenset(
    {
        "YEAR", "YY", "YYYY", "QUARTER", "QQ", "Q", "MONTH", "MM", "M", "DAYOFYEAR", "DY", "Y",
        "DAY", "DD", "D", "WEEK", "WK", "WW", "WEEKDAY", "DW", "HOUR", "HH", "MINUTE", "MI", "N",
        "SECOND", "SS", "S", "MILLISECOND", "MS", "MICROSECOND", "MCS", "NANOSECOND", "NS",
        "ISO_WEEK", "ISOWK", "ISOWW", "INT", "BIGINT", "SMALLINT", "TINYINT", "BIT", "DECIMAL",
        "NUMERIC", "MONEY", "FLOAT", "REAL", "DATE", "DATETIME", "DATETIME2", "SMALLDATETIME",
        "DATETIMEOFFSET", "TIME", "CHAR", "VARCHAR", "NCHAR", "NVARCHAR", "UNIQUEIDENTIFIER",
        "MAX",
    }
)
COMPARISON_OPS = frozenset({"=", "<>", "!=", "<", ">", "<=", ">=", "!<", "!>"})
CONVERSIONS = frozenset({"CAST", "TRY_CAST", "CONVERT", "TRY_CONVERT"})


# ------------------------------------------------------------------ type families
_FAMILIES = {
    "integer": {"tinyint", "smallint", "int", "bigint"},
    "decimal": {"decimal", "numeric", "money", "smallmoney", "float", "real"},
    "ascii": {"char", "varchar"},
    "unicode": {"nchar", "nvarchar"},
    "date": {"date"},
    "datetime": {"datetime", "datetime2", "smalldatetime", "datetimeoffset"},
    "time": {"time"},
    "uniqueidentifier": {"uniqueidentifier"},
    "bit": {"bit"},
}
_FAMILY_OF = {name: family for family, names in _FAMILIES.items() for name in names}
TEXT_TYPES = frozenset({"char", "varchar", "nchar", "nvarchar"})
NUMERIC_TYPES = _FAMILIES["integer"] | _FAMILIES["decimal"]
DATE_TYPES = _FAMILIES["date"] | _FAMILIES["datetime"]


def base_type(type_text: str) -> str:
    """`varchar(50)` -> `varchar`."""
    return re.split(r"[\s(]", type_text.strip(), maxsplit=1)[0].lower()


def type_family(type_text: str | None) -> str | None:
    """Comparable family of a type, or None for unknown/other types (never reported)."""
    if not type_text:
        return None
    return _FAMILY_OF.get(base_type(type_text))


# ------------------------------------------------------------------ document
@dataclass(slots=True)
class FromItem:
    kind: str  # FROM | COMMA | INNER | LEFT | RIGHT | FULL | CROSS | CROSS_APPLY | OUTER_APPLY
    keyword_index: int  # token index of FROM / JOIN / APPLY / comma
    name_parts: tuple[str, ...] | None  # None: derived table / sub-query / function result
    alias: str | None
    start: int  # offset of the table reference (or of the keyword)
    on_range: tuple[int, int] | None = None  # token index range [i, j) of the ON condition
    entry: CatalogEntry | None = None
    is_call: bool = False

    @property
    def label(self) -> str:
        return ".".join(p for p in self.name_parts if p) if self.name_parts else "(alt sorgu)"

    @property
    def keys(self) -> set[str]:
        """Names this item can be referred to with (alias, else the table name)."""
        if self.alias:
            return {self.alias.lower()}
        if self.name_parts:
            return {self.name_parts[-1].lower()}
        return set()


@dataclass(slots=True)
class FromBlock:
    depth: int
    from_index: int
    end_index: int  # exclusive token index
    items: list[FromItem] = field(default_factory=list)
    select_index: int | None = None
    where_range: tuple[int, int] | None = None
    parent: FromBlock | None = None

    @property
    def span(self) -> tuple[int, int]:
        """Token range [SELECT or FROM, end of WHERE or FROM clause)."""
        first = self.select_index if self.select_index is not None else self.from_index
        last = self.where_range[1] if self.where_range else self.end_index
        return first, last

    def item_for(self, alias: str) -> FromItem | None:
        key = alias.lower()
        for item in self.items:
            if key in item.keys:
                return item
        return None


class SqlDoc:
    """Tokens, FROM blocks and alias resolution of one definition."""

    def __init__(self, sql: str, metadata: ObjectMetadata | None = None,
                 database: str = "") -> None:
        from app.services.rule_engine import mask_sql

        self.sql = sql
        self.code = mask_sql(sql, strings=False)
        self.masked = mask_sql(sql)
        self.tokens = tokenize(self.code)
        self.metadata = metadata
        self.database = database
        self._pairs: dict[int, int] = {}
        stack: list[int] = []
        for index, tok in enumerate(self.tokens):
            if tok.is_punct("("):
                stack.append(index)
            elif tok.is_punct(")") and stack:
                self._pairs[stack.pop()] = index
        self._index_at = {tok.start: i for i, tok in enumerate(self.tokens)}

    # -------------------------------------------------------------- basics
    def close_of(self, open_index: int) -> int | None:
        """Index of the `)` closing the `(` at open_index."""
        return self._pairs.get(open_index)

    def index_at(self, offset: int) -> int | None:
        return self._index_at.get(offset)

    def line(self, offset: int) -> int:
        return self.sql.count("\n", 0, offset) + 1

    def text(self, i: int, j: int) -> str:
        """Source text of tokens [i, j), whitespace collapsed."""
        if i >= j:
            return ""
        return re.sub(r"\s+", " ", self.sql[self.tokens[i].start : self.tokens[j - 1].end]).strip()

    def snippet(self, offset: int) -> str:
        from app.services.rule_engine import snippet_at

        return snippet_at(self.sql, offset, offset)

    def is_subquery(self, open_index: int) -> bool:
        nxt = open_index + 1
        return nxt < len(self.tokens) and self.tokens[nxt].is_word("SELECT", "WITH")

    def has_from(self, open_index: int) -> bool:
        """A `( SELECT ... )` with a FROM clause of its own."""
        close = self.close_of(open_index)
        if close is None:
            return False
        depth = self.tokens[open_index].depth + 1
        return any(
            t.is_word("FROM") and t.depth == depth for t in self.tokens[open_index + 1 : close]
        )

    @cached_property
    def ctes(self) -> set[str]:
        return cte_names(self.masked)

    # -------------------------------------------------------------- FROM blocks
    @cached_property
    def blocks(self) -> list[FromBlock]:
        tokens = self.tokens
        blocks: list[FromBlock] = []
        for index, tok in enumerate(tokens):
            if not tok.is_word("FROM"):
                continue
            prev = tokens[index - 1] if index else None
            if prev is not None and prev.is_word("DISTINCT"):
                continue  # IS [NOT] DISTINCT FROM
            if tok.depth > 0 and self._inside_function(index):
                continue  # TRIM(x FROM y) and similar
            block = self._parse_block(index)
            blocks.append(block)
        # parent = innermost enclosing block (by token range): correlated names resolve there
        for block in blocks:
            candidates = [
                other for other in blocks
                if other is not block and other.depth < block.depth
                and other.span[0] < block.from_index < other.span[1]
            ]
            block.parent = max(candidates, key=lambda b: b.depth, default=None)
        return blocks

    def _inside_function(self, index: int) -> bool:
        """The FROM sits in a function's parentheses (not a sub-query)."""
        depth = self.tokens[index].depth
        for back in range(index - 1, -1, -1):
            tok = self.tokens[back]
            if tok.is_punct("(") and tok.depth == depth - 1:
                return not self.is_subquery(back)
        return False

    def _clause_end(self, start: int, depth: int, stop_words: frozenset[str]) -> int:
        """First token index >= start that ends a clause at `depth`."""
        tokens = self.tokens
        case = 0
        for j in range(start, len(tokens)):
            tok = tokens[j]
            if tok.depth < depth:
                return j
            if tok.depth > depth:
                continue
            if tok.is_punct(";"):
                return j
            word = tok.upper
            if word == "CASE":
                case += 1
            elif word == "END" and case:
                case -= 1
            elif case and word in ("WHEN", "THEN", "ELSE"):
                continue
            elif word in stop_words:
                return j
        return len(tokens)

    def _parse_block(self, from_index: int) -> FromBlock:
        tokens = self.tokens
        depth = tokens[from_index].depth
        stop = STATEMENT_START | CLAUSE_END
        end = self._clause_end(from_index + 1, depth, stop)
        block = FromBlock(depth, from_index, end)
        block.select_index = next(
            (k for k in range(from_index - 1, -1, -1)
             if tokens[k].depth == depth and tokens[k].is_word("SELECT")
             or tokens[k].depth < depth),
            None,
        )
        if block.select_index is not None and not tokens[block.select_index].is_word("SELECT"):
            block.select_index = None
        self._read_item(block, from_index, "FROM", from_index + 1)
        case = 0
        j = from_index + 1
        while j < end:
            tok = tokens[j]
            if tok.depth != depth:
                j += 1
                continue
            word = tok.upper
            if word == "CASE":
                case += 1
            elif word == "END" and case:
                case -= 1
            elif case:
                pass
            elif word == "JOIN":
                self._read_item(block, j, self._join_kind(j), j + 1)
            elif word == "APPLY":
                prev = tokens[j - 1].upper if j else ""
                self._read_item(block, j, "OUTER_APPLY" if prev == "OUTER" else "CROSS_APPLY",
                                j + 1)
            elif tok.is_punct(","):
                self._read_item(block, j, "COMMA", j + 1)
            elif word == "ON" and block.items and block.items[-1].on_range is None:
                block.items[-1].on_range = (j + 1, end)
            j += 1
        # close each ON range at the next item keyword
        for current, nxt in zip(block.items, block.items[1:], strict=False):
            if current.on_range is not None:
                last = nxt.keyword_index
                while last > current.on_range[0] and tokens[last - 1].is_word(
                    "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", *JOIN_HINTS
                ):
                    last -= 1
                current.on_range = (current.on_range[0], last)
        if end < len(tokens) and tokens[end].is_word("WHERE") and tokens[end].depth == depth:
            where_end = self._clause_end(end + 1, depth, stop)
            block.where_range = (end + 1, where_end)
        return block

    def _join_kind(self, join_index: int) -> str:
        k = join_index - 1
        while k >= 0 and self.tokens[k].upper in JOIN_HINTS | {"OUTER"}:
            k -= 1
        word = self.tokens[k].upper if k >= 0 else ""
        return word if word in ("LEFT", "RIGHT", "FULL", "CROSS") else "INNER"

    def _read_item(self, block: FromBlock, keyword_index: int, kind: str, at: int) -> None:
        from app.services.builtin_checks import _read_table_ref

        if at >= len(self.tokens):
            return
        tok = self.tokens[at]
        if tok.is_punct("("):
            close = self.close_of(at)
            alias = None
            if close is not None and close + 1 < len(self.tokens):
                nxt = self.tokens[close + 1]
                if nxt.is_word("AS") and close + 2 < len(self.tokens):
                    nxt = self.tokens[close + 2]
                if nxt.ident and nxt.upper not in KEYWORDS | STATEMENT_START | CLAUSE_END:
                    alias = nxt.ident
            block.items.append(FromItem(kind, keyword_index, None, alias, tok.start))
            return
        read = _read_table_ref(self.masked, tok.start)
        if read is None:
            block.items.append(FromItem(kind, keyword_index, None, None, tok.start))
            return
        ref, _ = read
        entry = None
        if self.metadata is not None and not ref.is_call:
            first = ref.parts[0]
            local = first.startswith(("#", "@")) or (
                len(ref.parts) == 1 and first.lower() in self.ctes
            )
            if not local:
                entry = self.metadata.resolve(ref.parts, self.database)
        block.items.append(
            FromItem(kind, keyword_index, tuple(ref.parts), ref.alias, ref.start, None, entry,
                     ref.is_call)
        )

    # -------------------------------------------------------------- scopes
    def block_at(self, offset: int) -> FromBlock | None:
        """Innermost FROM block whose SELECT/FROM/WHERE range contains the offset."""
        best: FromBlock | None = None
        for block in self.blocks:
            first, last = block.span
            start = self.tokens[first].start
            stop = self.tokens[last - 1].end if 0 < last <= len(self.tokens) else len(self.code)
            if start <= offset <= stop and (best is None or block.depth >= best.depth):
                best = block
        return best

    def resolve_column(
        self, block: FromBlock | None, alias: str | None, column: str, inherit: bool = True
    ) -> tuple[FromItem, ColumnInfo] | None:
        """FROM item and catalog column for `alias.column` (or a bare column).

        With `inherit` the enclosing blocks are searched too (correlated sub-queries).
        """
        if alias is None and column.upper() in NOT_COLUMNS:
            return None
        scope = block
        while scope is not None:
            if alias is not None:
                item = scope.item_for(alias)
                if item is not None:
                    found = _column(item, column)
                    return (item, found) if found else None
            else:
                if not scope.items or any(i.entry is None for i in scope.items):
                    return None  # unresolved sources: a bare name is ambiguous
                matches = [(i, c) for i in scope.items if (c := _column(i, column))]
                if len(matches) == 1:
                    return matches[0]
                return None
            scope = scope.parent if inherit else None
        return None


def _column(item: FromItem, column: str) -> ColumnInfo | None:
    if item.entry is None or not item.entry.columns:
        return None
    key = column.lower()
    return next((c for c in item.entry.columns if c.name.lower() == key), None)


# ------------------------------------------------------------------ predicates
@dataclass(slots=True)
class Atom:
    i: int
    j: int


@dataclass(slots=True)
class BoolNode:
    op: str  # AND | OR
    children: list[Node]
    i: int
    j: int
    operator_indexes: list[int]


Node = Atom | BoolNode


def parse_predicate(doc: SqlDoc, i: int, j: int) -> Node | None:
    """Boolean tree of tokens [i, j)."""
    tokens = doc.tokens
    while i < j and tokens[i].is_word("NOT"):
        i += 1
    if i >= j:
        return None
    depth = tokens[i].depth
    for op in ("OR", "AND"):
        cuts = _split_points(doc, i, j, depth, op)
        if cuts:
            bounds = [i, *cuts, j]
            children = [
                node
                for a, b in zip(bounds, bounds[1:], strict=False)
                if (node := parse_predicate(doc, a + (0 if a == i else 1), b)) is not None
            ]
            return BoolNode(op, children, i, j, cuts)
    if tokens[i].is_punct("(") and doc.close_of(i) == j - 1 and not doc.is_subquery(i):
        return parse_predicate(doc, i + 1, j - 1)
    return Atom(i, j)


def _split_points(doc: SqlDoc, i: int, j: int, depth: int, op: str) -> list[int]:
    cuts: list[int] = []
    case = 0
    between = False
    for k in range(i, j):
        tok = doc.tokens[k]
        if tok.depth != depth:
            continue
        word = tok.upper
        if word == "CASE":
            case += 1
        elif word == "END" and case:
            case -= 1
        elif case:
            continue
        elif word == "BETWEEN":
            between = True
        elif word == "AND" and between:
            between = False
        elif word == op:
            cuts.append(k)
    return cuts


def atoms(node: Node | None) -> list[Atom]:
    if node is None:
        return []
    if isinstance(node, Atom):
        return [node]
    return [a for child in node.children for a in atoms(child)]


@dataclass(frozen=True, slots=True)
class Comparison:
    op: str  # = <> ... | BETWEEN | LIKE | IN | IS
    left: tuple[int, int]
    right: tuple[int, int]
    right2: tuple[int, int] | None = None  # BETWEEN upper bound


def comparison(doc: SqlDoc, atom: Atom) -> Comparison | None:
    tokens = doc.tokens
    if atom.i >= atom.j:
        return None
    depth = tokens[atom.i].depth
    case = 0
    for k in range(atom.i, atom.j):
        tok = tokens[k]
        if tok.depth != depth:
            continue
        word = tok.upper
        if word == "CASE":
            case += 1
        elif word == "END" and case:
            case -= 1
        elif case:
            continue
        elif tok.kind == "op" and tok.text in COMPARISON_OPS:
            return Comparison(tok.text, (atom.i, k), (k + 1, atom.j))
        elif word in ("LIKE", "IN", "IS"):
            left_end = k - 1 if k > atom.i and tokens[k - 1].is_word("NOT") else k
            return Comparison(word, (atom.i, left_end), (k + 1, atom.j))
        elif word == "BETWEEN":
            left_end = k - 1 if k > atom.i and tokens[k - 1].is_word("NOT") else k
            for m in range(k + 1, atom.j):
                if tokens[m].depth == depth and tokens[m].is_word("AND"):
                    return Comparison("BETWEEN", (atom.i, left_end), (k + 1, m), (m + 1, atom.j))
            return None
    return None


@dataclass(frozen=True, slots=True)
class ColumnExpr:
    alias: str | None
    column: str
    start: int
    cast_type: str | None = None  # target type when wrapped in CAST/CONVERT
    text: str = ""


def column_expr(doc: SqlDoc, i: int, j: int) -> ColumnExpr | None:
    """`alias.col`, bare `col` or CAST/CONVERT/TRY_* (type) around one; else None."""
    tokens = doc.tokens
    while i < j and tokens[i].is_punct("(") and doc.close_of(i) == j - 1:
        i, j = i + 1, j - 1
    if i >= j:
        return None
    first = tokens[i]
    if first.upper in CONVERSIONS and j - i > 3 and tokens[i + 1].is_punct("("):
        if doc.close_of(i + 1) != j - 1:
            return None
        inner_i, inner_j = i + 2, j - 1
        if first.upper in ("CAST", "TRY_CAST"):
            as_index = next(
                (k for k in range(inner_j - 1, inner_i, -1)
                 if tokens[k].is_word("AS") and tokens[k].depth == tokens[inner_i].depth),
                None,
            )
            if as_index is None:
                return None
            inner = column_expr(doc, inner_i, as_index)
            target = doc.text(as_index + 1, inner_j)
        else:
            comma = next(
                (k for k in range(inner_i, inner_j)
                 if tokens[k].is_punct(",") and tokens[k].depth == tokens[inner_i].depth),
                None,
            )
            if comma is None:
                return None
            second = next(
                (k for k in range(comma + 1, inner_j)
                 if tokens[k].is_punct(",") and tokens[k].depth == tokens[inner_i].depth),
                inner_j,
            )
            inner = column_expr(doc, comma + 1, second)
            target = doc.text(inner_i, comma)
        if inner is None or inner.cast_type is not None:
            return None
        return ColumnExpr(inner.alias, inner.column, inner.start, target, doc.text(i, j))
    if j - i == 3 and tokens[i + 1].is_punct("."):
        alias, column = tokens[i].ident, tokens[i + 2].ident
        if alias and column and tokens[i].kind != "var":
            return ColumnExpr(alias, column, first.start, None, doc.text(i, j))
        return None
    if j - i == 1 and first.ident and first.upper not in KEYWORDS and first.kind != "var":
        if first.text.startswith("#"):
            return None
        return ColumnExpr(None, first.ident, first.start, None, first.text)
    return None


# ------------------------------------------------------------------ variables
_HEADER_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+ALTER\s+)?(?:PROC(?:EDURE)?|FUNCTION)\b(.*?)\bAS\b\s*(?:BEGIN\b|$|\n)",
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    r"(@[\w@#$]+)\s+(?:AS\s+)?([A-Za-z_][\w.]*(?:\s*\(\s*(?:\d+|MAX)(?:\s*,\s*\d+)?\s*\))?)",
    re.IGNORECASE,
)


def variable_types(doc: SqlDoc) -> dict[str, str]:
    """`@name` (lower-cased) -> declared type text, from the header and DECLARE statements."""
    result: dict[str, str] = {}
    header = _HEADER_RE.search(doc.masked)
    if header:
        text = header.group(1)
        if "(" in text and re.match(r"\s*[\w.\[\]]+\s*\(", text):
            text = text[text.index("(") + 1 :]
        for match in _PARAM_RE.finditer(text):
            result.setdefault(match.group(1).lower(), match.group(2))
    tokens = doc.tokens
    for index, tok in enumerate(tokens):
        if not tok.is_word("DECLARE"):
            continue
        k = index + 1
        while k < len(tokens) and tokens[k].kind == "var":
            name = tokens[k].text.lower()
            k += 1
            if k < len(tokens) and tokens[k].is_word("AS"):
                k += 1
            if k >= len(tokens) or tokens[k].kind != "word":
                break
            if tokens[k].is_word("TABLE", "CURSOR"):
                break
            type_start = k
            k += 1
            if k < len(tokens) and tokens[k].is_punct("("):
                close = doc.close_of(k)
                k = (close + 1) if close is not None else k + 1
            result[name] = doc.text(type_start, k)
            # skip "= expression" up to the next top-level comma
            depth = tok.depth
            while k < len(tokens):
                cur = tokens[k]
                if cur.depth < depth or cur.is_punct(";"):
                    break
                if cur.depth == depth and cur.is_punct(","):
                    k += 1
                    break
                if cur.depth == depth and cur.upper in STATEMENT_START and k > type_start + 1:
                    break
                k += 1
            else:
                break
            if k >= len(tokens) or tokens[k].kind != "var":
                break
    return result
