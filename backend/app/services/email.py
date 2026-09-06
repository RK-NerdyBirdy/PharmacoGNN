"""Outbound email.

Three backends, chosen by settings.EMAIL_BACKEND:
  smtp     -- real SMTP (MailHog in dev on :1025, a real provider in prod)
  memory   -- captured in-process; what the test suite uses
  console  -- logged only

A rule that applies to every template here: **messages carry the minimum
PHI possible**. "Your PharmacoGNN account is ready" is fine; a message listing
someone's medications would be a PHI disclosure over an unencrypted channel we
don't control. Nothing in this module should ever interpolate clinical data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SentMessage:
    to: str
    subject: str
    body: str
    template: str


class EmailBackend:
    async def send(self, message: SentMessage) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class SMTPEmailBackend(EmailBackend):
    async def send(self, message: SentMessage) -> None:
        email = EmailMessage()
        email["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)

        await aiosmtplib.send(
            email,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_START_TLS or None,
            username=settings.SMTP_USERNAME or None,
            password=settings.SMTP_PASSWORD or None,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )


@dataclass
class InMemoryEmailBackend(EmailBackend):
    """Test backend. Keeps everything sent so tests can pull tokens out."""

    outbox: list[SentMessage] = field(default_factory=list)

    async def send(self, message: SentMessage) -> None:
        self.outbox.append(message)

    def clear(self) -> None:
        self.outbox.clear()

    def last_to(self, address: str) -> SentMessage | None:
        for message in reversed(self.outbox):
            if message.to == address:
                return message
        return None


class ConsoleEmailBackend(EmailBackend):
    async def send(self, message: SentMessage) -> None:
        logger.info("EMAIL to=%s subject=%s\n%s", message.to, message.subject, message.body)


def _build_backend() -> EmailBackend:
    match settings.EMAIL_BACKEND:
        case "memory":
            return InMemoryEmailBackend()
        case "console":
            return ConsoleEmailBackend()
        case _:
            return SMTPEmailBackend()


_backend: EmailBackend = _build_backend()


def get_backend() -> EmailBackend:
    """Tests reach for this to inspect/clear the in-memory outbox."""
    return _backend


async def send_message(message: SentMessage) -> None:
    await _backend.send(message)


# --- Templates ---------------------------------------------------------------


def build_invite_email(to: str, token: str) -> SentMessage:
    link = f"{settings.APP_BASE_URL.rstrip('/')}/activate?token={token}"
    hours = settings.INVITE_TOKEN_TTL_HOURS
    body = (
        "You've been invited to PharmacoGNN by your clinician.\n\n"
        "Use the link below to set your password and access your account:\n\n"
        f"{link}\n\n"
        f"This link can only be used once and expires in {hours} hours.\n"
        "If it expires, ask your clinician to send a new one.\n\n"
        "If you weren't expecting this, you can ignore this message.\n"
    )
    return SentMessage(
        to=to, subject="Set up your PharmacoGNN account", body=body, template="patient_invite"
    )
