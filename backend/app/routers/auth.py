from typing import Optional
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, PasswordResetToken
from app.schemas.user import (
    GoogleCredential, GoogleLinkRequest, UserCreate, UserResponse, Token, ForgotPasswordRequest, ResetPasswordRequest,
    MessageResponse,
)
from app.core.rate_limit import (
    GOOGLE_FAILURES_BY_IP, LOGIN_FAILURES_BY_ACCOUNT, LOGIN_FAILURES_BY_ACCOUNT_AND_IP, LOGIN_FAILURES_BY_IP,
    REGISTRATIONS_BY_IP, RESET_EMAILS_BY_ADDRESS, RESET_FAILURES_BY_IP, RESET_REQUESTS_BY_IP, client_ip, refuse_if_blocked,
)
from app.core.security import decode_access_token, hash_password, issue_session_token, session_is_current, verify_password
from app.services.email_service import send_email
from app.services.google_identity import GoogleIdentity, GoogleTokenRejected, GoogleUnavailable, verify_google_credential

RESET_TOKEN_MINUTES = 30
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
# Same reply whether or not the email has an account, so the endpoint can't be used to find users
FORGOT_PASSWORD_REPLY = "If an account exists for that email, we've sent a link to reset the password."
GOOGLE_UNAVAILABLE = "Google sign-in is unavailable right now. Please try again, or use your email and password."
LINK_REQUIRED = "An account already uses this email. Enter its password once to link your Google account."
GOOGLE_ALREADY_LINKED = "This account or Google identity is already linked to a different sign-in."


# Compared when the email is unknown, so both cases take the same time
_UNKNOWN_ACCOUNT_HASH = hash_password(secrets.token_urlsafe(32))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(user_data: UserCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new student account"""
    ip = client_ip(request)
    refuse_if_blocked((REGISTRATIONS_BY_IP, ip))
    REGISTRATIONS_BY_IP.hit(ip)
    email = user_data.email.strip().lower()

    # Check if the email already exists
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This email is already registered"
        )

    # Create the new user
    new_user = User(
        email=email,
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
        role="student",
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Another request may have registered the same address after the pre-check
        existing = db.query(User).filter(func.lower(User.email) == email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email is already registered",
            ) from None
        raise
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Log in and get a JWT token. Only failed attempts count towards the limits."""
    ip = client_ip(request)
    account = form_data.username.strip().lower()
    pair = f"{account}|{ip}"
    refuse_if_blocked((LOGIN_FAILURES_BY_ACCOUNT_AND_IP, pair), (LOGIN_FAILURES_BY_ACCOUNT, account), (LOGIN_FAILURES_BY_IP, ip))

    user = db.query(User).filter(func.lower(User.email) == account).first()
    password_matches = verify_password(form_data.password, user.hashed_password if user else _UNKNOWN_ACCOUNT_HASH)

    if not user or not password_matches:
        LOGIN_FAILURES_BY_ACCOUNT_AND_IP.hit(pair)
        LOGIN_FAILURES_BY_ACCOUNT.hit(account)
        LOGIN_FAILURES_BY_IP.hit(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    LOGIN_FAILURES_BY_ACCOUNT_AND_IP.reset(pair)
    return {"access_token": issue_session_token(user), "token_type": "bearer"}


def _verified_google_identity(credential: str, ip: str) -> GoogleIdentity:
    refuse_if_blocked((GOOGLE_FAILURES_BY_IP, ip))
    try:
        return verify_google_credential(credential)
    except GoogleTokenRejected as rejected:
        GOOGLE_FAILURES_BY_IP.hit(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(rejected))
    except GoogleUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=GOOGLE_UNAVAILABLE)


def _account_with_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(func.lower(User.email) == email).order_by(User.id).first()


def _account_with_google_sub(db: Session, sub: str) -> Optional[User]:
    return db.query(User).filter(User.google_sub == sub).first()


def _link_required() -> HTTPException:
    # Only the verified owner of this Google email reaches this, so it reveals nothing new about who has an account
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "link_required", "message": LINK_REQUIRED})


def _create_google_account(db: Session, identity: GoogleIdentity, ip: str) -> User:
    refuse_if_blocked((REGISTRATIONS_BY_IP, ip))
    REGISTRATIONS_BY_IP.hit(ip)
    # Google signs this person in, so no password exists. A random hash can never match one, and still
    # lets the session stamp and a later password reset work as they do for every other account
    user = User(
        email=identity.email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        full_name=identity.name,
        role="student",
        google_sub=identity.sub,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two first sign-ins at once: the unique columns let only one through
        db.rollback()
        winner = _account_with_google_sub(db, identity.sub)
        if winner:
            return winner
        raise _link_required()
    db.refresh(user)
    return user


@router.post("/google", response_model=Token)
def google_sign_in(data: GoogleCredential, request: Request, db: Session = Depends(get_db)):
    """Sign in with a Google ID token. A new person gets a student account. An existing unlinked
    email is never joined automatically: registration doesn't verify emails, so it could belong to anyone."""
    ip = client_ip(request)
    identity = _verified_google_identity(data.credential, ip)

    user = _account_with_google_sub(db, identity.sub)
    if not user:
        existing = _account_with_email(db, identity.email)
        if existing and existing.google_sub:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=GOOGLE_ALREADY_LINKED)
        if existing:
            raise _link_required()
        user = _create_google_account(db, identity, ip)

    return {"access_token": issue_session_token(user), "token_type": "bearer"}


@router.post("/google/link", response_model=Token)
def link_google_account(data: GoogleLinkRequest, request: Request, db: Session = Depends(get_db)):
    """Join a verified Google identity to the existing account with its email, once the account's password
    is proven. Password guesses here count towards the same limits as /login."""
    ip = client_ip(request)
    identity = _verified_google_identity(data.credential, ip)

    pair = f"{identity.email}|{ip}"
    refuse_if_blocked((LOGIN_FAILURES_BY_ACCOUNT_AND_IP, pair), (LOGIN_FAILURES_BY_ACCOUNT, identity.email), (LOGIN_FAILURES_BY_IP, ip))

    user = _account_with_email(db, identity.email)
    password_matches = verify_password(data.password, user.hashed_password if user else _UNKNOWN_ACCOUNT_HASH)
    if not user or not password_matches:
        LOGIN_FAILURES_BY_ACCOUNT_AND_IP.hit(pair)
        LOGIN_FAILURES_BY_ACCOUNT.hit(identity.email)
        LOGIN_FAILURES_BY_IP.hit(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    LOGIN_FAILURES_BY_ACCOUNT_AND_IP.reset(pair)

    if user.google_sub != identity.sub:
        owner = _account_with_google_sub(db, identity.sub)
        if user.google_sub or owner:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=GOOGLE_ALREADY_LINKED)
        user.google_sub = identity.sub
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=GOOGLE_ALREADY_LINKED)

    return {"access_token": issue_session_token(user), "token_type": "bearer"}


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Get the current user from the token (used by protected routes)"""
    invalid = HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(token)
    user_id = str(payload.get("sub", "")) if payload else ""
    if not user_id.isdecimal():
        raise invalid
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not session_is_current(payload, user.hashed_password):
        raise invalid
    return user


def get_optional_user(token: Optional[str] = Depends(optional_oauth2_scheme), db: Session = Depends(get_db)) -> Optional[User]:
    """The signed-in user, or None for a visitor. A bad token is still refused, never treated as a visitor."""
    return get_current_user(token, db) if token else None


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """View your own account"""
    return current_user

@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(data: ForgotPasswordRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    """Email a one-time password reset link. Always returns the same message."""
    ip = client_ip(request)
    refuse_if_blocked((RESET_REQUESTS_BY_IP, ip))
    RESET_REQUESTS_BY_IP.hit(ip)

    # Counted for every address, known or not. Over the limit the reply stays the same and nothing is sent
    address = data.email.strip().lower()
    if RESET_EMAILS_BY_ADDRESS.retry_after(address):
        return {"message": FORGOT_PASSWORD_REPLY}
    RESET_EMAILS_BY_ADDRESS.hit(address)

    user = db.query(User).filter(func.lower(User.email) == address).first()
    if user:
        now = datetime.now(timezone.utc)
        # Purane unused links band karo, sirf naya link valid rahe
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({PasswordResetToken.used_at: now})

        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=now + timedelta(minutes=RESET_TOKEN_MINUTES),
        ))
        db.commit()

        link = f"{FRONTEND_URL}/reset-password?token={token}"
        body = (
            f"Hi {user.full_name},\n\n"
            "We received a request to reset your FitScholars password. Open this link to choose a new one:\n\n"
            f"{link}\n\n"
            f"The link works once and expires in {RESET_TOKEN_MINUTES} minutes. "
            "If you didn't ask for this, you can ignore this email; your password stays the same.\n\n"
            "FitScholars"
        )
        # Sent after the response, so response time doesn't reveal whether the account exists
        background_tasks.add_task(send_email, user.email, "Reset your FitScholars password", body)

    return {"message": FORGOT_PASSWORD_REPLY}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Set a new password using a valid, unused reset token. The new hash ends every earlier sign-in."""
    ip = client_ip(request)
    refuse_if_blocked((RESET_FAILURES_BY_IP, ip))
    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _hash_token(data.token))
        .first()
    )
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at if record else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not record or record.used_at is not None or expires_at < now:
        RESET_FAILURES_BY_IP.hit(ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Please request a new one.",
        )

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired.")

    user.hashed_password = hash_password(data.new_password)
    record.used_at = now
    db.commit()
    return {"message": "Your password has been reset. You can now sign in with your new password."}
