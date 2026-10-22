"""The summary e-mail's readiness and the test send through HTTP and a real-TCP fake relay.

sql-review/PRDs/008-scheduled-review-email Requirement 10 and Decision 13, 14 (Acceptance 5): only
the super admin reads the status and sends a test; without a relay the answer is "not
configured"; the test goes over verified TLS to one corporate address and carries no report
data; a relay failure answers with its stable code; addresses never reach a log line.
"""

import secrets
from collections.abc import AsyncIterator, Iterator
from email import message_from_bytes
from email.policy import default
from pathlib import Path

import pytest

from app.api.scheduled_reviews.router import get_mail_sender
from app.infrastructure.mail.smtp_client import SmtpMailSender
from app.main import app
from app.services import scheduled_email_check
from tests.fakes.llm_server import TestPki as Pki
from tests.fakes.llm_server import write_pki
from tests.fakes.smtp_server import FakeSmtpServer
from tests.integration.conftest import (
    AuthHarness,
    RecordingHandler,
    RoleSessions,
    SuperAdmin,
)

pytestmark = pytest.mark.integration

DOMAIN = "kurum.example"
LOGIN = ("reviewx-relay", secrets.token_urlsafe(18))


@pytest.fixture
def pki(tmp_path: Path) -> Pki:
    return write_pki(tmp_path / "pki")


@pytest.fixture
async def relay(pki: Pki) -> AsyncIterator[FakeSmtpServer]:
    server = await FakeSmtpServer(pki=pki, accepted_login=LOGIN).start()
    try:
        yield server
    finally:
        await server.close()


@pytest.fixture(autouse=True)
def fresh_cooldown() -> Iterator[None]:
    scheduled_email_check._last_test.clear()
    yield
    scheduled_email_check._last_test.clear()
    app.dependency_overrides.pop(get_mail_sender, None)


def _use_relay(port: int, pki: Pki) -> None:
    sender = SmtpMailSender(
        host="127.0.0.1",
        port=port,
        security="starttls",
        sender=f"reviewx@{DOMAIN}",
        username=LOGIN[0],
        password=LOGIN[1],
        ca_bundle=str(pki.ca_path),
        timeout_seconds=5.0,
    )
    app.dependency_overrides[get_mail_sender] = lambda: sender


async def _admin(auth: AuthHarness, admin: SuperAdmin) -> dict[str, str]:
    response = await auth.login(admin.username, admin.password)
    assert response.status_code == 200, response.text
    return auth.auth_headers(response.json())


def _url(auth: AuthHarness, path: str = "") -> str:
    return f"{auth.prefix}/scheduled-review-settings/email{path}"


async def test_only_the_super_admin_reads_the_status_and_sends_a_test(
    auth: AuthHarness, role_sessions: RoleSessions
) -> None:
    auth.use_settings(mail_allowed_domains=DOMAIN)
    for session in (await role_sessions.reviewer(), await role_sessions.reviewer()):
        assert (await auth.client.get(_url(auth), headers=session.headers)).status_code == 403
        sent = await auth.client.post(
            _url(auth, "/test"),
            json={"recipient": f"ali@{DOMAIN}"},
            headers=session.headers,
        )
        assert sent.status_code == 403


async def test_without_a_relay_the_status_and_the_test_say_not_configured(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    auth.use_settings(mail_allowed_domains=f"{DOMAIN}, ornek.example", scheduler_enabled=True)
    headers = await _admin(auth, super_admin)

    status = (await auth.client.get(_url(auth), headers=headers)).json()
    assert status == {
        "scheduler_enabled": True,
        "smtp_configured": False,
        "smtp_security": "starttls",
        "allowed_domains": [DOMAIN, "ornek.example"],
        # The fixture's own address is outside the allowed domains.
        "suggested_recipient": None,
    }
    sent = await auth.client.post(
        _url(auth, "/test"), json={"recipient": f"ali@{DOMAIN}"}, headers=headers
    )
    assert sent.status_code == 200
    assert sent.json() == {"status": "not_configured", "error_code": None}


async def test_the_recipient_must_be_one_corporate_address(
    auth: AuthHarness, super_admin: SuperAdmin
) -> None:
    auth.use_settings(mail_allowed_domains=DOMAIN)
    headers = await _admin(auth, super_admin)
    for recipient, code in (
        ("ali@disari.example", "recipient_domain_not_allowed"),
        (f"ali@sub.{DOMAIN}", "recipient_domain_not_allowed"),
        ("bir adres", "recipient_invalid"),
    ):
        sent = await auth.client.post(
            _url(auth, "/test"), json={"recipient": recipient}, headers=headers
        )
        assert sent.status_code == 422, recipient
        assert sent.json()["detail"]["code"] == code


async def test_the_test_mail_goes_over_tls_and_carries_no_report_data(
    auth: AuthHarness,
    super_admin: SuperAdmin,
    relay: FakeSmtpServer,
    pki: Pki,
    recorded_logs: RecordingHandler,
) -> None:
    auth.use_settings(mail_allowed_domains=DOMAIN)
    _use_relay(relay.port, pki)
    headers = await _admin(auth, super_admin)
    assert (await auth.client.get(_url(auth), headers=headers)).json()["smtp_configured"] is True

    sent = await auth.client.post(
        _url(auth, "/test"),
        json={"recipient": f"Ayse@{DOMAIN.upper()}"},
        headers=headers,
    )
    assert sent.json() == {"status": "sent", "error_code": None}
    [mail] = relay.received
    assert (mail.tls, mail.login, mail.recipients) == (
        True,
        LOGIN[0],
        [f"ayse@{DOMAIN}"],
    )
    message = message_from_bytes(mail.data, policy=default)
    assert message["Subject"] == "Zamanlanmış inceleme: deneme e-postası"
    text = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "deneme" in text and "gecmis?run=" not in text

    # Decision 14: one test per super admin in the cooldown window.
    again = await auth.client.post(
        _url(auth, "/test"), json={"recipient": f"ayse@{DOMAIN}"}, headers=headers
    )
    assert again.status_code == 429
    assert again.json()["detail"]["code"] == "email_test_too_soon"

    [event] = recorded_logs.events("scheduled_review.email_test")
    assert event["outcome"] == "sent" and event["error_code"] is None
    logged = " ".join(str(record.__dict__) for record in recorded_logs.records)
    assert "ayse@" not in logged.lower()


async def test_a_relay_failure_answers_with_its_stable_code(
    auth: AuthHarness, super_admin: SuperAdmin, pki: Pki
) -> None:
    auth.use_settings(mail_allowed_domains=DOMAIN)
    # Nothing listens on this port: the relay is unreachable.
    _use_relay(1, pki)
    headers = await _admin(auth, super_admin)
    sent = await auth.client.post(
        _url(auth, "/test"), json={"recipient": f"ali@{DOMAIN}"}, headers=headers
    )
    assert sent.status_code == 200
    assert sent.json() == {"status": "failed", "error_code": "smtp_unreachable"}
