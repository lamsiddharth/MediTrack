"""Application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from meditrack import config
from meditrack.routes import appointments, auth, consultations, dashboard, doctors, patients
from meditrack.security import NotLoggedIn, redirect_to_login
from meditrack.seed import init_db
from meditrack.templating import templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("meditrack")

BASE_DIR = Path(__file__).parent


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
    log.info("%s ready", config.APP_NAME)
    yield


app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    max_age=config.SESSION_MAX_AGE,
    same_site="lax",
    https_only=False,  # served over plain HTTP; see README on putting TLS in front
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.exception_handler(NotLoggedIn)
async def _not_logged_in(request: Request, _exc: NotLoggedIn):
    """Send anyone without a session to the login page, remembering where they were."""
    return redirect_to_login(request)


@app.exception_handler(404)
async def _not_found(request: Request, _exc):
    return templates.TemplateResponse(request, "404.html", status_code=404)


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(consultations.router)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}
