from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import (
    clear_session_cookie,
    create_session,
    get_current_user,
    hash_password,
    revoke_session,
    set_session_cookie,
    verify_password,
)
from app.config import GOOGLE_CLIENT_ID, SESSION_COOKIE_NAME
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class OAuthLoginRequest(BaseModel):
    provider: str
    id_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str

    class Config:
        from_attributes = True


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    existing = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if existing:
        raise HTTPException(409, "Email already registered")

    user = User(
        email=body.email.lower().strip(),
        name=body.name.strip(),
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    raw_token, expires_at = create_session(db, user)
    set_session_cookie(response, raw_token, expires_at)
    return user


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")

    raw_token, expires_at = create_session(db, user)
    set_session_cookie(response, raw_token, expires_at)
    return user


def verify_google_id_token(id_token: str) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth is not configured")
    try:
        return google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception as exc:  # pragma: no cover - handled in tests via patch
        raise HTTPException(401, "Invalid Google ID token") from exc


@router.post("/oauth", response_model=UserResponse)
def oauth_login(body: OAuthLoginRequest, response: Response, db: Session = Depends(get_db)):
    if body.provider.lower() != "google":
        raise HTTPException(400, "Unsupported OAuth provider")

    token_data = verify_google_id_token(body.id_token)
    email = (token_data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, "Email not provided by OAuth provider")
    name = token_data.get("name") or email.split("@")[0]

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            email=email,
            name=name,
            hashed_password=hash_password(secrets.token_urlsafe(16)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not user.is_active:
            raise HTTPException(403, "User account is inactive")
        if name and user.name != name:
            user.name = name
            db.commit()

    raw_token, expires_at = create_session(db, user)
    set_session_cookie(response, raw_token, expires_at)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    clear_session_cookie(response)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user
