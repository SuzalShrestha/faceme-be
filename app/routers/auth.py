from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    verify_google_oauth_token,
)
from app.config import SESSION_COOKIE_NAME
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


class GoogleOAuthLoginRequest(BaseModel):
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


@router.post("/oauth/google", response_model=UserResponse)
def login_with_google(
    body: GoogleOAuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    profile = verify_google_oauth_token(body.id_token)
    user = db.query(User).filter(User.email == profile["email"]).first()
    if user is None:
        user = User(
            email=profile["email"],
            name=profile["name"],
            hashed_password=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    if not user.is_active:
        raise HTTPException(403, "User account is inactive")

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
