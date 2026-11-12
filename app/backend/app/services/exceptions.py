"""Rule exceptions (finding suppression).

An exception matches a finding when every filled field matches: database / schema /
object_name by case-insensitive equality, snippet_pattern by an IGNORECASE regex search in
"snippet\\nmessage". The runner loads the matchers once per analysis run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

EMPTY_EXCEPTION = (
    "İstisna en az bir nesne alanı veya ifade deseni içermeli; kuralı tamamen kapatmak için "
    "kuralı pasifleştirin."
)
REASON_MAX = 500


class ExceptionError(ValueError):
    """Invalid exception input; the message is Turkish."""


def clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def compile_snippet_pattern(pattern: str | None) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise ExceptionError(f"Geçersiz düzenli ifade (snippet_pattern): {error}") from None


def validate(
    database: str | None, schema: str | None, object_name: str | None,
    snippet_pattern: str | None, reason: str,
) -> None:
    if not any((database, schema, object_name, snippet_pattern)):
        raise ExceptionError(EMPTY_EXCEPTION)
    if not reason.strip():
        raise ExceptionError("İstisna nedeni zorunludur.")
    if len(reason.strip()) > REASON_MAX:
        raise ExceptionError(f"İstisna nedeni en fazla {REASON_MAX} karakter olabilir.")
    for value, label in ((database, "Veritabanı"), (schema, "Şema"), (object_name, "Nesne")):
        if value and len(value) > 128:
            raise ExceptionError(f"{label} adı en fazla 128 karakter olabilir.")
    compile_snippet_pattern(snippet_pattern)


@dataclass(frozen=True, slots=True)
class ExceptionMatcher:
    database: str | None
    schema: str | None
    object_name: str | None
    pattern: re.Pattern[str] | None

    @classmethod
    def from_row(cls, row: models.RuleException) -> ExceptionMatcher:
        def fold(value: str | None) -> str | None:
            value = clean(value)
            return value.casefold() if value else None

        return cls(
            fold(row.database), fold(row.schema), fold(row.object_name),
            compile_snippet_pattern(clean(row.snippet_pattern)),
        )

    def matches(self, database: str, schema: str, name: str, snippet: str, message: str) -> bool:
        if self.database is not None and self.database != database.casefold():
            return False
        if self.schema is not None and self.schema != schema.casefold():
            return False
        if self.object_name is not None and self.object_name != name.casefold():
            return False
        if self.pattern is not None and self.pattern.search(f"{snippet}\n{message}") is None:
            return False
        return True


def load_matchers(session: Session, rule_ids: Iterable[int | None]) -> dict[int, list[ExceptionMatcher]]:
    """rule_id -> matchers of its exceptions (invalid stored patterns are skipped)."""
    ids = {rule_id for rule_id in rule_ids if rule_id is not None}
    result: dict[int, list[ExceptionMatcher]] = {}
    if not ids:
        return result
    rows = session.scalars(
        select(models.RuleException).where(models.RuleException.rule_id.in_(ids))
    )
    for row in rows:
        try:
            matcher = ExceptionMatcher.from_row(row)
        except ExceptionError:
            continue
        result.setdefault(row.rule_id, []).append(matcher)
    return result
