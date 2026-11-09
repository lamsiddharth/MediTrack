"""Application entry point.

This process is the backend: a JSON API and nothing else. The user interface is
a separate React application, served by nginx, which proxies /api through to
here. There are no templates and no server-rendered pages.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from meditrack import config
from meditrack.api import appointments, auth, consultations, dashboard, doctors, notes, patients
from meditrack.seed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("meditrack")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("initialising database at %s", config.DATABASE_URL)
    init_db()
    if config.SECRET_KEY_WAS_GENERATED:
        log.warning(
            "SECRET_KEY is not set, so one was generated for this process. "
            "Sessions will not survive a restart. Set SECRET_KEY in production."
        )
    if config.SEED_PASSWORD == "admin123":
        log.warning(
            "The seeded account is using the default password. "
            "Change it from the Account page, or set SEED_PASSWORD before first run."
        )
    log.info("%s API ready", config.APP_NAME)
    yield


app = FastAPI(
    title=f"{config.APP_NAME} API",
    description="Hospital management system backend.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)

# Session cookie. The React client is served from the same origin via the
# nginx proxy, so a cookie needs no CORS handling and, being HttpOnly, cannot
# be read by scripts the way a token in localStorage can.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    max_age=config.SESSION_MAX_AGE,
    same_site="lax",
    https_only=False,  # served over plain HTTP; see README on putting TLS in front
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(consultations.router)
app.include_router(notes.router)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}
