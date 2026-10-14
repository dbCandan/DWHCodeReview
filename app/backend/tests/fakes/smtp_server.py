"""A real-TCP fake SMTP server with STARTTLS (sql-review 008-scheduled-review-email tests).

It speaks just enough SMTP for the adapter: EHLO, STARTTLS with the test CA of
``tests.fakes.llm_server.write_pki``, AUTH PLAIN, MAIL, RCPT, DATA and QUIT. Each accepted
message is recorded with its envelope; switches make it refuse a recipient, refuse the login or
offer no STARTTLS so the adapter's failure classes can be observed.
"""

import asyncio
import base64
import ssl
from dataclasses import dataclass, field

from tests.fakes.llm_server import TestPki


@dataclass
class ReceivedMail:
    sender: str
    recipients: list[str]
    data: bytes
    tls: bool
    login: str | None


@dataclass
class FakeSmtpServer:
    pki: TestPki | None = None
    offer_starttls: bool = True
    reject_recipients: bool = False
    accepted_login: tuple[str, str] | None = None
    received: list[ReceivedMail] = field(default_factory=list)
    connections: int = 0
    _server: asyncio.Server | None = None

    async def start(self) -> "FakeSmtpServer":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        tls = False
        login: str | None = None
        sender = ""
        recipients: list[str] = []

        async def reply(line: str) -> None:
            writer.write(line.encode("ascii") + b"\r\n")
            await writer.drain()

        try:
            await reply("220 fake.smtp ESMTP")
            while True:
                raw = await reader.readline()
                if not raw:
                    return
                line = raw.decode("utf-8").rstrip("\r\n")
                verb = line.split(" ", 1)[0].upper()
                if verb in {"EHLO", "HELO"}:
                    lines = ["fake.smtp"]
                    if self.offer_starttls and not tls and self.pki is not None:
                        lines.append("STARTTLS")
                    if tls or self.pki is None:
                        lines.append("AUTH PLAIN")
                    for index, text in enumerate(lines):
                        await reply(f"250{'-' if index < len(lines) - 1 else ' '}{text}")
                elif verb == "STARTTLS" and self.pki is not None:
                    await reply("220 ready for TLS")
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(self.pki.certificate_path, self.pki.key_path)
                    await writer.start_tls(context)
                    tls = True
                elif verb == "AUTH":
                    encoded = line.split(" ", 2)[2]
                    _, user, password = base64.b64decode(encoded).decode("utf-8").split("\0")
                    if self.accepted_login == (user, password):
                        login = user
                        await reply("235 accepted")
                    else:
                        await reply("535 authentication failed")
                elif verb == "MAIL":
                    sender = line.split(":", 1)[1].strip().strip("<>").split(">")[0]
                    await reply("250 ok")
                elif verb == "RCPT":
                    if self.reject_recipients:
                        await reply("550 no such user")
                    else:
                        recipients.append(line.split(":", 1)[1].strip().strip("<>"))
                        await reply("250 ok")
                elif verb == "DATA":
                    await reply("354 go ahead")
                    data = bytearray()
                    while (chunk := await reader.readline()) not in (b".\r\n", b""):
                        data += chunk
                    self.received.append(
                        ReceivedMail(sender, list(recipients), bytes(data), tls, login)
                    )
                    await reply("250 queued")
                elif verb == "RSET":
                    recipients.clear()
                    await reply("250 ok")
                elif verb == "QUIT":
                    await reply("221 bye")
                    return
                else:
                    await reply("502 not implemented")
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError):
            return
        finally:
            writer.close()
