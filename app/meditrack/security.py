"""Password hashing and the session-based login check.

Intentionally plain: one account, a signed session cookie, no tokens, no roles.
The client is a React application served from the same origin, so a cookie is
simpler and safer than storing a token in the browser where scripts can read it.

The one thing not simplified away is password hashing, because storing a
password in the clear is never worth the lines it saves.
"""

from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import User

SESSION_USER_KEY = "user_id"


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


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency for any endpoint that requires a login.

    Returns 401 rather than redirecting: the caller is an API client, and the
    React router decides what to show the user.
    """
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")

    user = session.get(User, user_id)
    if user is None:
        # The account referenced by the cookie is gone; treat as signed out.
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")

    return user
