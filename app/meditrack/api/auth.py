"""Authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import User
from meditrack.schemas import LoginIn, PasswordChangeIn, UserOut
from meditrack.security import (
    current_user,
    hash_password,
    login_session,
    logout_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginIn, request: Request, session: Session = Depends(get_session)
):
    user = session.scalar(select(User).where(User.username == payload.username.strip()))

    if user is None or not verify_password(payload.password, user.password_hash):
        # Deliberately identical for an unknown user and a wrong password, so
        # this cannot be used to discover valid usernames.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    session.commit()

    login_session(request, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request):
    logout_session(request)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.post("/password", response_model=UserOut)
async def change_password(
    payload: PasswordChangeIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is not correct.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters.")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=400, detail="The new password is the same as the current one."
        )

    db_user = session.get(User, user.id)
    db_user.password_hash = hash_password(payload.new_password)
    session.commit()
    return db_user
