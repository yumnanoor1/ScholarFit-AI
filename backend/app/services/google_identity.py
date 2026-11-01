"""
Verifies a Google ID token with Google's library. Everything FitScholar trusts about a Google user comes from
the verified claims returned here, never from the browser. Tokens are never logged.
"""
import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from google.auth import exceptions as google_errors
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

load_dotenv()

logger = logging.getLogger(__name__)

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleTokenRejected(Exception):
    """The token is invalid, expired, or doesn't prove a verified email. The message is safe to show."""


class GoogleUnavailable(Exception):
    """Sign-in isn't configured, or Google's signing keys couldn't be fetched. Worth trying again."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


def verify_google_credential(credential: str) -> GoogleIdentity:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise GoogleUnavailable()

    try:
        # Checks the signature, expiry and that the token was issued for this client
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    except google_errors.TransportError as error:
        logger.warning("Google signing keys could not be fetched: %s", type(error).__name__)
        raise GoogleUnavailable() from None
    except (ValueError, google_errors.GoogleAuthError):
        raise GoogleTokenRejected("Google sign-in could not be verified. Please try again.") from None

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenRejected("Google sign-in could not be verified. Please try again.")
    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleTokenRejected("Google sign-in could not be verified. Please try again.")
    if claims.get("email_verified") is not True:
        raise GoogleTokenRejected("Your Google email address isn't verified, so it can't be used to sign in.")

    name = (claims.get("name") or "").strip() or email.split("@")[0]
    return GoogleIdentity(sub=sub, email=email, name=name)
