"""Password hashing and the session-based login check.

Intentionally plain: one account, a signed session cookie, no tokens, no roles.
The one thing not simplified away is password hashing, because storing a
password in the clear is never worth the lines it saves.
"""

from __future__ import annotations

import bcrypt
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import User

SESSION_USER_KEY = "user_id"


class NotLoggedIn(Exception):
    """Raised when a page needs a login. Handled app-wide as a redirect."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # A malformed hash in the database should read as "wrong password"
        # rather than a 500.
        return False


def login_session(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id


def logout_session(request: Request) -> None:
    request.session.clear()


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    """Dependency for any page that requires a login."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise NotLoggedIn

    user = session.get(User, user_id)
    if user is None:
        # The account referenced by the cookie is gone; treat as logged out.
        request.session.clear()
        raise NotLoggedIn

    return user


def redirect_to_login(request: Request) -> RedirectResponse:
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    target = "/login" if nxt in ("/", "/login") else f"/login?next={nxt}"
    return RedirectResponse(target, status_code=303)
