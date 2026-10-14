"""Scheduled review rules that need no persistence.

sql-review/PRDs/008-scheduled-review-email Requirement 1, 2, 5 and Decision 1, 5, 7 (Acceptance 1):
period validation without free cron, the next run time in the period's time zone (daylight saving
included), recipient format and domain checks, the summary e-mail that carries no SQL and the
1/5/15 minute e-mail retry schedule.
"""

from dataclasses import fields
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.models.review import Severity
from app.domain.scheduled_review import (
    EMAIL_RETRY_DELAYS,
    RECIPIENTS_MAX,
    SCHEDULE_NAME_MAX_LENGTH,
    Frequency,
    RunSummary,
    ScheduleValidationError,
    build_summary_email,
    email_retry_at,
    next_run_after,
    normalize_recipients,
    normalize_schedule_name,
    report_link,
    validate_period,
)

pytestmark = pytest.mark.unit

DOMAINS = ("kurum.example", "ornek.example")


def _code(call: object) -> str:
    assert isinstance(call, ScheduleValidationError)
    return call.code


# --- name -------------------------------------------------------------------------------------


def test_the_name_is_trimmed_and_limited_to_120_characters() -> None:
    assert normalize_schedule_name("  Gece taraması  ") == "Gece taraması"
    assert normalize_schedule_name("a" * SCHEDULE_NAME_MAX_LENGTH) == "a" * 120
    for bad in ("", "   ", "a" * 121, "satır\nkırılımı", "sekme\tvar"):
        with pytest.raises(ScheduleValidationError) as error:
            normalize_schedule_name(bad)
        assert error.value.code == "schedule_invalid"


# --- period -----------------------------------------------------------------------------------


def test_daily_weekly_and_monthly_periods_are_accepted() -> None:
    daily = validate_period("daily", hour=7, minute=30, timezone="Europe/Istanbul")
    assert (daily.frequency, daily.weekday, daily.day_of_month) == (Frequency.DAILY, None, None)
    weekly = validate_period("weekly", hour=8, minute=0, timezone="Europe/Istanbul", weekday=0)
    assert weekly.weekday == 0
    monthly = validate_period("monthly", hour=6, minute=0, timezone="UTC", day_of_month=28)
    assert monthly.day_of_month == 28


@pytest.mark.parametrize(
    "arguments",
    [
        {"frequency": "*/5 * * * *", "hour": 1, "minute": 0, "timezone": "UTC"},
        {"frequency": "hourly", "hour": 1, "minute": 0, "timezone": "UTC"},
        {"frequency": "daily", "hour": 24, "minute": 0, "timezone": "UTC"},
        {"frequency": "daily", "hour": -1, "minute": 0, "timezone": "UTC"},
        {"frequency": "daily", "hour": 1, "minute": 60, "timezone": "UTC"},
        {"frequency": "daily", "hour": 1, "minute": 0, "timezone": "Mars/Olympus"},
        {"frequency": "daily", "hour": 1, "minute": 0, "timezone": "../../etc/passwd"},
        {"frequency": "daily", "hour": 1, "minute": 0, "timezone": "UTC", "weekday": 1},
        {"frequency": "weekly", "hour": 1, "minute": 0, "timezone": "UTC"},
        {"frequency": "weekly", "hour": 1, "minute": 0, "timezone": "UTC", "weekday": 7},
        {"frequency": "weekly", "hour": 1, "minute": 0, "timezone": "UTC", "day_of_month": 3},
        {"frequency": "monthly", "hour": 1, "minute": 0, "timezone": "UTC"},
        {"frequency": "monthly", "hour": 1, "minute": 0, "timezone": "UTC", "day_of_month": 29},
        {"frequency": "monthly", "hour": 1, "minute": 0, "timezone": "UTC", "day_of_month": 0},
    ],
)
def test_free_cron_and_out_of_range_periods_are_refused(arguments: dict[str, object]) -> None:
    with pytest.raises(ScheduleValidationError) as error:
        validate_period(**arguments)  # type: ignore[arg-type]
    assert error.value.code == "schedule_invalid"


def test_the_next_daily_run_is_today_when_the_time_is_ahead_and_tomorrow_otherwise() -> None:
    period = validate_period("daily", hour=7, minute=30, timezone="Europe/Istanbul")
    # 04:00 UTC is 07:00 in Istanbul (UTC+3, no daylight saving).
    assert next_run_after(period, datetime(2026, 10, 6, 4, 0, tzinfo=UTC)) == datetime(
        2026, 10, 6, 4, 30, tzinfo=UTC
    )
    # Exactly the due time is not "after"; the next one is a day later.
    assert next_run_after(period, datetime(2026, 10, 6, 4, 30, tzinfo=UTC)) == datetime(
        2026, 10, 7, 4, 30, tzinfo=UTC
    )


def test_the_next_weekly_and_monthly_runs_fall_on_the_chosen_day() -> None:
    monday = validate_period("weekly", hour=9, minute=0, timezone="UTC", weekday=0)
    # 2026-10-07 is a Wednesday.
    assert next_run_after(monday, datetime(2026, 10, 7, tzinfo=UTC)) == datetime(
        2026, 10, 12, 9, 0, tzinfo=UTC
    )
    fifth = validate_period("monthly", hour=2, minute=15, timezone="UTC", day_of_month=5)
    assert next_run_after(fifth, datetime(2026, 10, 7, tzinfo=UTC)) == datetime(
        2026, 11, 5, 2, 15, tzinfo=UTC
    )
    assert next_run_after(fifth, datetime(2026, 12, 6, tzinfo=UTC)) == datetime(
        2027, 1, 5, 2, 15, tzinfo=UTC
    )


def test_the_local_hour_is_kept_across_daylight_saving_changes() -> None:
    period = validate_period("daily", hour=8, minute=0, timezone="Europe/Berlin")
    # Summer time (UTC+2) ends on 2026-10-25: 08:00 local moves from 06:00 to 07:00 UTC.
    assert next_run_after(period, datetime(2026, 10, 24, 7, 0, tzinfo=UTC)) == datetime(
        2026, 10, 25, 7, 0, tzinfo=UTC
    )
    assert next_run_after(period, datetime(2026, 10, 23, 7, 0, tzinfo=UTC)) == datetime(
        2026, 10, 24, 6, 0, tzinfo=UTC
    )


def test_a_local_time_skipped_by_the_clock_change_still_runs_once_that_day() -> None:
    # 2027-03-28 02:30 does not exist in Berlin (clocks jump from 02:00 to 03:00).
    period = validate_period("daily", hour=2, minute=30, timezone="Europe/Berlin")
    after = datetime(2027, 3, 27, 12, 0, tzinfo=UTC)
    first = next_run_after(period, after)
    assert first.date() == date(2027, 3, 28)
    second = next_run_after(period, first)
    assert second == datetime(2027, 3, 29, 0, 30, tzinfo=UTC)


def test_a_naive_reference_time_is_refused() -> None:
    period = validate_period("daily", hour=1, minute=0, timezone="UTC")
    with pytest.raises(ValueError):
        next_run_after(period, datetime(2026, 10, 7))  # noqa: DTZ001


# --- recipients -------------------------------------------------------------------------------


def test_recipients_are_lowercased_deduplicated_and_kept_in_order() -> None:
    assert normalize_recipients(
        [" Ayse.Yilmaz@Kurum.Example", "ali@ornek.example", "ayse.yilmaz@kurum.example"],
        DOMAINS,
    ) == ("ayse.yilmaz@kurum.example", "ali@ornek.example")


@pytest.mark.parametrize(
    ("addresses", "code"),
    [
        ([], "recipient_invalid"),
        (["ayse"], "recipient_invalid"),
        (["ayse@"], "recipient_invalid"),
        (["a b@kurum.example"], "recipient_invalid"),
        (["ayse@kurum.example\r\nBcc: x@dis.com"], "recipient_invalid"),
        (["x" * 250 + "@ornek.example"], "recipient_invalid"),
        (["ayse@gmail.com"], "recipient_domain_not_allowed"),
        (["ayse@sahte-kurum.example"], "recipient_domain_not_allowed"),
        (["ayse@kurum.example.dis.com"], "recipient_domain_not_allowed"),
        (["ayse@alt.kurum.example"], "recipient_domain_not_allowed"),
    ],
)
def test_malformed_and_outside_recipients_are_refused(addresses: list[str], code: str) -> None:
    with pytest.raises(ScheduleValidationError) as error:
        normalize_recipients(addresses, DOMAINS)
    assert error.value.code == code


def test_no_allowed_domain_refuses_every_recipient() -> None:
    with pytest.raises(ScheduleValidationError) as error:
        normalize_recipients(["ayse@kurum.example"], ())
    assert error.value.code == "recipient_domain_not_allowed"


def test_the_recipient_list_is_bounded() -> None:
    many = [f"k{index}@ornek.example" for index in range(RECIPIENTS_MAX + 1)]
    assert len(normalize_recipients(many[:-1], DOMAINS)) == RECIPIENTS_MAX
    with pytest.raises(ScheduleValidationError) as error:
        normalize_recipients(many, DOMAINS)
    assert error.value.code == "recipient_invalid"


# --- summary e-mail ---------------------------------------------------------------------------


def _summary(**overrides: object) -> RunSummary:
    values: dict[str, object] = {
        "schedule_name": "Gece <taraması>",
        "run_public_id": "run-123",
        "started_at": datetime(2026, 10, 7, 4, 30, tzinfo=UTC),
        "timezone": "Europe/Istanbul",
        "status": "completed",
        "rule_groups": ("Güvenlik", "Performans"),
        "object_count": 12,
        "finding_counts": {
            ("Güvenlik", Severity.HIGH): 2,
            ("Güvenlik", Severity.LOW): 1,
            (None, Severity.MEDIUM): 3,
        },
    }
    values.update(overrides)
    return RunSummary(**values)  # type: ignore[arg-type]


def test_the_summary_carries_no_field_for_sql_text_or_code_snippets() -> None:
    names = {field.name for field in fields(RunSummary)}
    assert names == {
        "schedule_name",
        "run_public_id",
        "started_at",
        "timezone",
        "status",
        "rule_groups",
        "object_count",
        "finding_counts",
    }


def test_the_summary_e_mail_lists_the_run_groups_counts_and_report_link() -> None:
    link = report_link("https://reviewx.kurum.example", "run-123")
    assert link == "https://reviewx.kurum.example/gecmis?run=run-123"
    email = build_summary_email(_summary(), link)

    assert email.subject == "Zamanlanmış inceleme: Gece <taraması> — Tamamlandı"
    assert "Başlangıç: 07.10.2026 07:30 (Europe/Istanbul)" in email.text
    assert "Kural grupları: Güvenlik, Performans" in email.text
    assert "İncelenen nesne: 12" in email.text
    assert "Güvenlik: Yüksek 2 · Orta 0 · Düşük 1" in email.text
    assert "Grupsuz kurallar: Yüksek 0 · Orta 3 · Düşük 0" in email.text
    assert f"Raporu aç: {link}" in email.text
    assert "oturum açarak" in email.text
    # The user-chosen name is escaped in the HTML part.
    assert "Gece &lt;taraması&gt;" in email.html
    assert "<taraması>" not in email.html
    assert f'href="{link}"' in email.html


def test_a_run_without_groups_or_findings_says_so() -> None:
    email = build_summary_email(
        _summary(rule_groups=(), finding_counts={}, status="failed"), "https://x/gecmis?run=r"
    )
    assert email.subject.endswith("— Hata")
    assert "Kural grupları: Tüm kurallar" in email.text
    assert "Bulgu yok." in email.text


# --- e-mail retries ---------------------------------------------------------------------------


def test_a_failed_e_mail_is_retried_after_1_5_and_15_minutes_then_given_up() -> None:
    now = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    assert EMAIL_RETRY_DELAYS == (
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=15),
    )
    assert email_retry_at(1, now) == now + timedelta(minutes=1)
    assert email_retry_at(2, now) == now + timedelta(minutes=5)
    assert email_retry_at(3, now) == now + timedelta(minutes=15)
    assert email_retry_at(4, now) is None
