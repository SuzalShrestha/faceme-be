from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import (
    GOOGLE_OAUTH_CLIENT_IDS,
    SESSION_COOKIE_DOMAIN,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    SESSION_MAX_AGE_SECONDS,
)
from app.database import get_db
from app.models import SessionToken, User


class GoogleOAuthProfile(TypedDict):
    email: str
    name: str
    subject: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return raw_token, expires_at


def revoke_session(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    db.query(SessionToken).filter(SessionToken.token_hash == _hash_token(raw_token)).delete()
    db.commit()


def set_session_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        expires=expires_at,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        domain=SESSION_COOKIE_DOMAIN,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        domain=SESSION_COOKIE_DOMAIN,
        path="/",
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def verify_google_oauth_token(raw_token: str) -> GoogleOAuthProfile:
    if not GOOGLE_OAUTH_CLIENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        payload = google_id_token.verify_oauth2_token(
            raw_token,
            google_requests.Request(),
            audience=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token") from exc

    if payload.get("aud") not in GOOGLE_OAUTH_CLIENT_IDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")
    if payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    email = (payload.get("email") or "").lower().strip()
    if not email or not payload.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account email must be verified",
        )

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    name = (payload.get("name") or email.split("@", 1)[0]).strip() or email
    return {"email": email, "name": name, "subject": subject}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise credentials_exception

    now = datetime.now(timezone.utc)
    session = (
        db.query(SessionToken)
        .filter(SessionToken.token_hash == _hash_token(raw_token), SessionToken.expires_at > now)
        .first()
    )
    if session is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception

    session.last_seen_at = now
    db.commit()
    return user
