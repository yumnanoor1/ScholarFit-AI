from datetime import datetime, timedelta
from jose import JWTError, jwt
import hashlib
import hmac
from passlib.context import CryptContext
import logging
import os
import secrets
from dotenv import load_dotenv

from app.core.config import is_production

load_dotenv()

logger = logging.getLogger(__name__)

MIN_SECRET_KEY_LENGTH = 32


def _load_secret_key() -> str:
    """JWT signing key sirf configuration (SECRET_KEY env / .env) se aata hai.
    Production mein key missing ya weak ho to app start hi nahi hoga.
    Development mein har process ke liye random key banti hai (restart par
    login dobara karna padega) - koi public default key use nahi hoti."""
    key = os.getenv("SECRET_KEY", "").strip()

    if key and len(key) >= MIN_SECRET_KEY_LENGTH:
        return key
    if is_production():
        raise RuntimeError(
            f"SECRET_KEY must be set to at least {MIN_SECRET_KEY_LENGTH} characters when APP_ENV=production"
        )
    logger.warning(
        "SECRET_KEY is missing or shorter than %d characters; using a temporary random key. "
        "Tokens will stop working when the server restarts. Set SECRET_KEY in backend/.env.",
        MIN_SECRET_KEY_LENGTH,
    )
    return secrets.token_urlsafe(64)


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Password hashing setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Plain password ko hash karo"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Password match karo"""
    return pwd_context.verify(plain_password, hashed_password)


def password_stamp(hashed_password: str) -> str:
    """Acts as the session version: it changes with the password, ending every earlier sign-in"""
    return hmac.new(SECRET_KEY.encode(), hashed_password.encode(), hashlib.sha256).hexdigest()[:32]


def session_is_current(payload: dict, hashed_password: str) -> bool:
    """A token with no stamp predates this check, so it can't be shown to be current and is refused."""
    stamp = payload.get("pwd")
    return isinstance(stamp, str) and hmac.compare_digest(stamp, password_stamp(hashed_password))


def issue_session_token(user) -> str:
    return create_access_token({"sub": str(user.id), "email": user.email, "pwd": password_stamp(user.hashed_password)})


def create_access_token(data: dict) -> str:
    """JWT token banao"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """JWT token decode karo"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None