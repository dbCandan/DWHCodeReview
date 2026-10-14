"""The SMTP adapter against a real-TCP fake relay with its own test CA.

sql-review/PRDs/008-scheduled-review-email Requirement 5 (Acceptance 1): the summary is delivered
only over verified TLS, with the configured login, to every recipient; a relay without STARTTLS,
an untrusted certificate, refused credentials or recipients, an unreachable or silent relay and a
public relay address each end in a stable failure code and nothing is sent in plain text.
"""

import asyncio
import secrets
import socket
from collections.abc import AsyncIterator
from email import message_from_bytes
from email.message import Message
from email.policy import default
from pathlib import Path

import pytest

from app.domain.scheduled_review import SummaryEmail
from app.infrastructure.mail.smtp_client import MailDeliveryError, SmtpMailSender
from tests.fakes.llm_server import TestPki as Pki
from tests.fakes.llm_server import write_pki
from tests.fakes.smtp_server import FakeSmtpServer

pytestmark = pytest.mark.integration

EMAIL = SummaryEmail(
    subject="Zamanlanmış inceleme: Gece taraması — Tamamlandı",
    text="Zamanlanmış inceleme: Gece taraması\n\nRaporu aç: https://x.example/gecmis?run=r\n",
    html="<!doctype html><html><body><p>Gece taraması</p></body></html>",
)
RECIPIENTS = ["ayse@kurum.example", "ali@kurum.example"]
# Test-process credentials; nothing committed is a usable password.
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


def _sender(port: int, pki: Pki, **overrides: object) -> SmtpMailSender:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": port,
        "security": "starttls",
        "sender": "reviewx@kurum.example",
        "username": LOGIN[0],
        "password": LOGIN[1],
        "ca_bundle": str(pki.ca_path),
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SmtpMailSender(**values)  # type: ignore[arg-type]


def _parts(data: bytes) -> tuple[Message, str, str]:
    message = message_from_bytes(data, policy=default)
    # SMTP carries CRLF line ends; compare the content, not the wire format.
    text = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    html = message.get_body(("html",)).get_content()  # type: ignore[union-attr]
    return message, text.replace("\r\n", "\n"), html.replace("\r\n", "\n")


async def test_the_summary_is_delivered_over_starttls_with_login(
    relay: FakeSmtpServer, pki: Pki
) -> None:
    refused = await _sender(relay.port, pki).send(RECIPIENTS, EMAIL)

    assert refused == 0
    [mail] = relay.received
    assert (mail.tls, mail.login, mail.sender) == (True, LOGIN[0], "reviewx@kurum.example")
    assert mail.recipients == RECIPIENTS
    message, text, html = _parts(mail.data)
    assert message["Subject"] == EMAIL.subject
    assert message["Auto-Submitted"] == "auto-generated"
    assert text == EMAIL.text
    assert html.strip() == EMAIL.html
    # Decision 1: no attachment, only the plain-text and HTML alternatives.
    assert message.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in message.iter_parts()] == [  # type: ignore[attr-defined]
        "text/plain",
        "text/html",
    ]


async def test_a_relay_without_starttls_gets_nothing(relay: FakeSmtpServer, pki: Pki) -> None:
    relay.offer_starttls = False
    with pytest.raises(MailDeliveryError) as error:
        await _sender(relay.port, pki).send(RECIPIENTS, EMAIL)
    assert error.value.code == "smtp_tls_failed"
    assert relay.received == []


async def test_an_untrusted_relay_certificate_gets_nothing(
    relay: FakeSmtpServer, pki: Pki, tmp_path: Path
) -> None:
    other = write_pki(tmp_path / "other-ca")
    with pytest.raises(MailDeliveryError) as error:
        await _sender(relay.port, pki, ca_bundle=str(other.ca_path)).send(RECIPIENTS, EMAIL)
    assert error.value.code == "smtp_tls_failed"
    assert relay.received == []


async def test_refused_credentials_and_recipients_have_their_own_codes(
    relay: FakeSmtpServer, pki: Pki
) -> None:
    with pytest.raises(MailDeliveryError) as login:
        await _sender(relay.port, pki, password="wrong").send(RECIPIENTS, EMAIL)
    relay.reject_recipients = True
    with pytest.raises(MailDeliveryError) as recipients:
        await _sender(relay.port, pki).send(RECIPIENTS, EMAIL)
    assert (login.value.code, recipients.value.code) == ("smtp_auth_failed", "smtp_rejected")
    assert relay.received == []


async def test_an_unreachable_or_silent_relay_is_reported(pki: Pki) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = int(probe.getsockname()[1])
    with pytest.raises(MailDeliveryError) as closed:
        await _sender(closed_port, pki).send(RECIPIENTS, EMAIL)

    async def silent(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(5)
        writer.close()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    try:
        port = int(server.sockets[0].getsockname()[1])
        with pytest.raises(MailDeliveryError) as silent_error:
            await _sender(port, pki, timeout_seconds=0.5).send(RECIPIENTS, EMAIL)
    finally:
        server.close()
    assert (closed.value.code, silent_error.value.code) == ("smtp_unreachable", "smtp_unreachable")


async def test_a_public_relay_address_is_refused_before_connecting(
    relay: FakeSmtpServer, pki: Pki
) -> None:
    with pytest.raises(MailDeliveryError) as error:
        await _sender(relay.port, pki, host="8.8.8.8").send(RECIPIENTS, EMAIL)
    assert error.value.code == "smtp_address_not_allowed"
    assert relay.connections == 0
