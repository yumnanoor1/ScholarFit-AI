"""
Outgoing email over SMTP (settings from backend/.env).

SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_TLS (default true)

Agar SMTP set nahi hai:
- development: email console/log mein print hota hai (taa ke reset link test ho sake)
- production: email nahi bhejta aur link log bhi nahi karta (token leak na ho)
"""
import logging
import os
import smtplib
from email.message import EmailMessage

from app.core.config import is_production

logger = logging.getLogger("fitscholar.email")


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def send_email(to: str, subject: str, text: str) -> bool:
    """Returns True if the email was handed to the SMTP server."""
    if not smtp_configured():
        if is_production():
            logger.error("SMTP is not configured; an email was not sent")
        else:
            # Dev only: show the message so the flow can be tested without a mail server
            print(f"\n----- DEV EMAIL (SMTP not configured) -----\nTo: {to}\nSubject: {subject}\n\n{text}\n-------------------------------------------\n", flush=True)
        return False

    message = EmailMessage()
    message["From"] = os.getenv("SMTP_FROM")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() != "false"
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
            if os.getenv("SMTP_USER"):
                server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            server.send_message(message)
        return True
    except (smtplib.SMTPException, OSError) as error:
        logger.error("Sending an email failed: %s", type(error).__name__)
        return False
