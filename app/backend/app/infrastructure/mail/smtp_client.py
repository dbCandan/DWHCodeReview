"""Summary e-mail over the corporate SMTP relay (sql-review/PRDs/008-scheduled-review-email).

Standard library only (``smtplib``, ``ssl``, ``email``): no new dependency. Every connection is
encrypted and verified against the configured CA bundle or the image's system trust store (which
carries the organization root CA): implicit TLS, or STARTTLS that the server must offer; nothing
is ever sent in plain text. The relay host must resolve to private addresses only; the
deployment's egress policy is the authoritative boundary, this check is defence in depth.
The blocking client runs in a worker thread. Recipient addresses, the subject and the body are
never logged; failures surface as a stable code.
"""

import asyncio
import smtplib
import socket
import ssl
from collections.abc import Sequence
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid
from typing import Literal

from app.domain.scheduled_review import SummaryEmail
from app.infrastructure.llm.network import is_private_address, tls_context

SmtpSecurity = Literal["starttls", "tls"]


class MailDeliveryError(Exception):
    """A send that did not reach the relay; ``code`` is safe to store and to log.

    ``smtp_address_not_allowed``: the relay host resolves outside the private ranges;
    ``smtp_unreachable``: connection or timeout failure; ``smtp_tls_failed``: no STARTTLS or a
    TLS/certificate failure; ``smtp_auth_failed``: the relay refused the credentials;
    ``smtp_rejected``: the relay refused the sender, every recipient or the message;
    ``smtp_failed``: any other SMTP protocol failure.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SmtpMailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        security: SmtpSecurity,
        sender: str,
        username: str = "",
        password: str = "",
        ca_bundle: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._security = security
        self._sender = sender
        self._username = username
        self._password = password
        self._ca_bundle = ca_bundle
        self._timeout = timeout_seconds

    async def send(self, recipients: Sequence[str], email: SummaryEmail) -> int:
        """Send one message to every recipient; return how many the relay refused.

        A refusal of some recipients still delivers to the others and is not retried; a refusal
        of all of them raises ``smtp_rejected``.
        """

        message = self._message(recipients, email)
        return await asyncio.to_thread(self._deliver, list(recipients), message)

    def _message(self, recipients: Sequence[str], email: SummaryEmail) -> EmailMessage:
        message = EmailMessage(policy=SMTP)
        message["Subject"] = email.subject
        message["From"] = self._sender
        message["To"] = ", ".join(recipients)
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=self._sender.rsplit("@", 1)[-1])
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        return message

    def _deliver(self, recipients: list[str], message: EmailMessage) -> int:
        self._require_private_host()
        context = tls_context(self._ca_bundle)
        try:
            client = self._connect(context)
            try:
                if self._username:
                    client.login(self._username, self._password)
                refused = client.send_message(message, from_addr=self._sender, to_addrs=recipients)
            finally:
                try:
                    client.quit()
                except (smtplib.SMTPException, OSError):
                    client.close()
        except MailDeliveryError:
            raise
        except smtplib.SMTPAuthenticationError:
            raise MailDeliveryError("smtp_auth_failed") from None
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError,
        ):
            raise MailDeliveryError("smtp_rejected") from None
        except (ssl.SSLError, smtplib.SMTPNotSupportedError):
            raise MailDeliveryError("smtp_tls_failed") from None
        except (smtplib.SMTPServerDisconnected, OSError):
            raise MailDeliveryError("smtp_unreachable") from None
        except smtplib.SMTPException:
            raise MailDeliveryError("smtp_failed") from None
        return len(refused)

    def _connect(self, context: ssl.SSLContext) -> smtplib.SMTP:
        if self._security == "tls":
            return smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout, context=context)
        client = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
        try:
            client.ehlo()
            if not client.has_extn("starttls"):
                raise MailDeliveryError("smtp_tls_failed")
            client.starttls(context=context)
            client.ehlo()
        except BaseException:
            client.close()
            raise
        return client

    def _require_private_host(self) -> None:
        try:
            infos = socket.getaddrinfo(self._host, self._port, type=socket.SOCK_STREAM)
        except OSError:
            raise MailDeliveryError("smtp_unreachable") from None
        addresses = {str(info[4][0]) for info in infos}
        if not addresses or not all(is_private_address(address) for address in addresses):
            raise MailDeliveryError("smtp_address_not_allowed")
