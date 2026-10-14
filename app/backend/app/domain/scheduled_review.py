"""Scheduled review rules that need no persistence (sql-review/PRDs/008-scheduled-review-email).

Period validation from a closed set of frequencies (no free cron, rules/57), the next run time in
the period's own time zone with the standard ``zoneinfo`` database, recipient format and domain
checks (Decision 5), the summary e-mail (Decision 1: no SQL text, no code snippet, no attachment)
and the 1/5/15 minute retry schedule of a failed e-mail (Decision 7). Recipient addresses and the
schedule name are never logged.
"""

import html
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.models.review import Severity

SCHEDULE_NAME_MAX_LENGTH = 120
RECIPIENTS_MAX = 20
RECIPIENT_MAX_LENGTH = 254
TIMEZONE_MAX_LENGTH = 64
MONTH_DAY_MAX = 28
EMAIL_RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))

# One look-ahead window covers the longest period (a month) with room to spare.
_SEARCH_DAYS = 400
_TIMEZONE_KEY = re.compile(r"^[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)*$")
_RECIPIENT = re.compile(r"^[a-z0-9._%+'\-]{1,64}@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+$")
_STATUS_LABELS = {
    "running": "Sürüyor",
    "completed": "Tamamlandı",
    "failed": "Hata",
    "cancelled": "Durduruldu",
    "interrupted": "Yarıda kesildi",
}
_SEVERITY_LABELS = ((Severity.HIGH, "Yüksek"), (Severity.MEDIUM, "Orta"), (Severity.LOW, "Düşük"))
_UNGROUPED_LABEL = "Grupsuz kurallar"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduleValidationError(Exception):
    """A rejected definition; the code and Turkish message form the 422 error envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Period:
    """When a definition runs: a frequency, its day, the local time and the IANA time zone.

    ``weekday`` is 0 (Monday) to 6 and set only for weekly runs; ``day_of_month`` is 1 to 28 and
    set only for monthly runs, so every month has the day.
    """

    frequency: Frequency
    hour: int
    minute: int
    timezone: str
    weekday: int | None = None
    day_of_month: int | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Everything a summary e-mail may say about a run (Decision 1).

    There is deliberately no field for reviewed SQL, code snippets, finding descriptions or
    server details: the e-mail cannot carry what the summary does not hold. ``rule_groups`` is
    empty when every rule ran; a ``None`` group in ``finding_counts`` counts ungrouped rules.
    """

    schedule_name: str = field(repr=False)
    run_public_id: str
    started_at: datetime
    timezone: str
    status: str
    rule_groups: tuple[str, ...]
    object_count: int
    finding_counts: Mapping[tuple[str | None, Severity], int]


@dataclass(frozen=True, slots=True)
class SummaryEmail:
    subject: str = field(repr=False)
    text: str = field(repr=False)
    html: str = field(repr=False)


def _invalid(message: str) -> ScheduleValidationError:
    return ScheduleValidationError("schedule_invalid", message)


def normalize_schedule_name(name: str) -> str:
    value = name.strip()
    if not 1 <= len(value) <= SCHEDULE_NAME_MAX_LENGTH or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        raise _invalid(
            f"Tanım adı 1-{SCHEDULE_NAME_MAX_LENGTH} karakter olmalı, satır içermemelidir."
        )
    return value


def fold_name(name: str) -> str:
    """Turkish-aware case folding for name uniqueness per owner (I/ı, İ/i).

    The database index folds only ASCII letters under the C collation; the service compares
    with this key before it writes.
    """

    return name.replace("I", "ı").replace("İ", "i").lower()


def _zone(key: str) -> ZoneInfo:
    if len(key) > TIMEZONE_MAX_LENGTH or not _TIMEZONE_KEY.fullmatch(key):
        raise _invalid("Zaman dilimi geçersiz.")
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        raise _invalid("Zaman dilimi geçersiz.") from None


def validate_period(
    frequency: str,
    *,
    hour: int,
    minute: int,
    timezone: str,
    weekday: int | None = None,
    day_of_month: int | None = None,
) -> Period:
    """The definition's period from the closed set; anything else is ``schedule_invalid``."""

    try:
        kind = Frequency(frequency)
    except ValueError:
        raise _invalid("Periyot günlük, haftalık veya aylık olmalıdır.") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise _invalid("Çalışma saati geçersiz.")
    _zone(timezone)
    if kind is Frequency.WEEKLY:
        if weekday is None or not 0 <= weekday <= 6 or day_of_month is not None:
            raise _invalid("Haftalık periyot için haftanın bir günü seçilmelidir.")
    elif kind is Frequency.MONTHLY:
        if day_of_month is None or not 1 <= day_of_month <= MONTH_DAY_MAX or weekday is not None:
            raise _invalid(
                f"Aylık periyot için ayın 1-{MONTH_DAY_MAX}. günlerinden biri seçilmelidir."
            )
    elif weekday is not None or day_of_month is not None:
        raise _invalid("Günlük periyotta gün seçilmez.")
    return Period(kind, hour, minute, timezone, weekday, day_of_month)


def _runs_on(period: Period, day: date) -> bool:
    if period.frequency is Frequency.WEEKLY:
        return day.weekday() == period.weekday
    if period.frequency is Frequency.MONTHLY:
        return day.day == period.day_of_month
    return True


def next_run_after(period: Period, after: datetime) -> datetime:
    """The first due time strictly after ``after``, in UTC.

    The local wall-clock time is kept across daylight saving changes. A local time the clock
    skips resolves to the instant just after the jump, and a repeated local time to its first
    occurrence, so each day still runs exactly once.
    """

    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    zone = _zone(period.timezone)
    first_day = after.astimezone(zone).date()
    for offset in range(_SEARCH_DAYS):
        day = first_day + timedelta(days=offset)
        if not _runs_on(period, day):
            continue
        local = datetime.combine(day, time(period.hour, period.minute), tzinfo=zone)
        candidate = local.astimezone(UTC)
        if candidate > after:
            return candidate
    raise AssertionError("a valid period always runs within the search window")


def normalize_recipients(
    addresses: Iterable[str], allowed_domains: Sequence[str]
) -> tuple[str, ...]:
    """Lower-cased, de-duplicated recipients in their given order.

    Only an exact allowed domain passes (a subdomain or a look-alike does not); with no allowed
    domain configured every address is refused.
    """

    allowed = {domain.strip().lower() for domain in allowed_domains if domain.strip()}
    recipients: list[str] = []
    for raw in addresses:
        address = raw.strip().lower()
        if len(address) > RECIPIENT_MAX_LENGTH or not _RECIPIENT.fullmatch(address):
            raise ScheduleValidationError("recipient_invalid", "Alıcı e-posta adresi geçersiz.")
        if address.rsplit("@", 1)[1] not in allowed:
            raise ScheduleValidationError(
                "recipient_domain_not_allowed",
                "Alıcı yalnız kurum e-posta alan adlarından olabilir.",
            )
        if address not in recipients:
            recipients.append(address)
    if not recipients:
        raise ScheduleValidationError("recipient_invalid", "En az bir alıcı girilmelidir.")
    if len(recipients) > RECIPIENTS_MAX:
        raise ScheduleValidationError(
            "recipient_invalid", f"En çok {RECIPIENTS_MAX} alıcı girilebilir."
        )
    return tuple(recipients)


def report_link(public_origin: str, run_public_id: str) -> str:
    """The sign-in protected history page of the run; the link alone grants no access."""

    return f"{public_origin.rstrip('/')}/gecmis?run={quote(run_public_id, safe='')}"


def _finding_lines(summary: RunSummary) -> list[str]:
    """One line per selected group, then other groups with findings, ungrouped rules last."""

    found = {group for (group, _), count in summary.finding_counts.items() if count}
    if not found:
        return []
    named = [*summary.rule_groups]
    named += sorted(group for group in found if group is not None and group not in named)
    groups: list[str | None] = [*named, *([None] if None in found else [])]
    return [
        f"{group or _UNGROUPED_LABEL}: "
        + " · ".join(
            f"{label} {summary.finding_counts.get((group, severity), 0)}"
            for severity, label in _SEVERITY_LABELS
        )
        for group in groups
    ]


def build_summary_email(summary: RunSummary, link: str) -> SummaryEmail:
    """Plain-text and HTML summary of a finished run (Requirement 5, Decision 1)."""

    status = _STATUS_LABELS.get(summary.status, summary.status)
    started = summary.started_at.astimezone(_zone(summary.timezone))
    rows = [
        ("Başlangıç", f"{started:%d.%m.%Y %H:%M} ({summary.timezone})"),
        ("Durum", status),
        ("Kural grupları", ", ".join(summary.rule_groups) or "Tüm kurallar"),
        ("İncelenen nesne", str(summary.object_count)),
    ]
    findings = _finding_lines(summary)
    note = "Rapor yalnız uygulamada, oturum açarak görüntülenir."
    text_lines = [f"Zamanlanmış inceleme: {summary.schedule_name}", ""]
    text_lines += [f"{label}: {value}" for label, value in rows]
    text_lines += ["", "Bulgular:", *(findings or ["Bulgu yok."]), "", f"Raporu aç: {link}", note]

    escape = html.escape
    html_rows = "".join(
        f'<tr><th align="left">{escape(label)}</th><td>{escape(value)}</td></tr>'
        for label, value in rows
    )
    html_findings = (
        "".join(f"<li>{escape(line)}</li>" for line in findings) or "<li>Bulgu yok.</li>"
    )
    body = (
        f"<p><strong>Zamanlanmış inceleme: {escape(summary.schedule_name)}</strong></p>"
        f"<table>{html_rows}</table>"
        f"<p>Bulgular:</p><ul>{html_findings}</ul>"
        f'<p><a href="{escape(link)}">Raporu aç</a></p>'
        f"<p>{escape(note)}</p>"
    )
    return SummaryEmail(
        subject=f"Zamanlanmış inceleme: {summary.schedule_name} — {status}",
        text="\n".join(text_lines) + "\n",
        html=f"<!doctype html><html><body>{body}</body></html>",
    )


def email_retry_at(failed_attempts: int, failed_at: datetime) -> datetime | None:
    """When to try again after ``failed_attempts`` failed sends; ``None`` gives up (Decision 7)."""

    if 1 <= failed_attempts <= len(EMAIL_RETRY_DELAYS):
        return failed_at + EMAIL_RETRY_DELAYS[failed_attempts - 1]
    return None
