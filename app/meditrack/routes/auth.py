"""Login, logout, and changing your own password."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import User
from meditrack.security import (
    current_user,
    hash_password,
    login_session,
    logout_session,
    verify_password,
)
from meditrack.templating import templates

router = APIRouter()


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirects, so ?next= cannot send a user
    off to another host after login."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


@router.get("/login")
async def login_form(request: Request, next: str | None = None):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": _safe_next(next), "error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    session: Session = Depends(get_session),
):
    user = session.scalar(select(User).where(User.username == username.strip()))

    if user is None or not verify_password(password, user.password_hash):
        # Deliberately identical message for an unknown user and a wrong
        # password, so this cannot be used to discover valid usernames.
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": _safe_next(next), "error": "Incorrect username or password."},
            status_code=401,
        )

    user.last_login_at = datetime.now(timezone.utc)
    session.commit()

    login_session(request, user)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
async def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/account")
async def account(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "error": None, "ok": None}
    )


@router.post("/account/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    def render(error: str | None = None, ok: str | None = None, status: int = 200):
        return templates.TemplateResponse(
            request, "account.html", {"user": user, "error": error, "ok": ok}, status_code=status
        )

    if not verify_password(current_password, user.password_hash):
        return render(error="Your current password is not correct.", status=400)
    if new_password != confirm_password:
        return render(error="The new passwords do not match.", status=400)
    if len(new_password) < 8:
        return render(error="Use at least 8 characters.", status=400)
    if new_password == current_password:
        return render(error="The new password is the same as the current one.", status=400)

    # Re-attach to this session before writing: current_user resolved it on a
    # different session instance.
    db_user = session.get(User, user.id)
    db_user.password_hash = hash_password(new_password)
    session.commit()

    return render(ok="Password changed.")
