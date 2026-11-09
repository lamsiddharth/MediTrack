"""Shared Jinja2 environment, plus the formatting filters the templates use."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from meditrack import config

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _date(value: date | datetime | None, fmt: str = "%d %b %Y") -> str:
    return value.strftime(fmt) if value else "—"


def _datetime(value: datetime | None, fmt: str = "%d %b %Y, %H:%M") -> str:
    return value.strftime(fmt) if value else "—"


def _time(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else "—"


def _money(value: Decimal | float | None) -> str:
    return f"₹{Decimal(str(value or 0)):,.2f}"


def _nl2br(value: str | None) -> str:
    """Render stored newlines as line breaks. Autoescaping still applies to the
    text itself; only the <br> tags are injected."""
    if not value:
        return "—"
    from markupsafe import Markup, escape

    return Markup("<br>").join(escape(line) for line in value.splitlines())


templates.env.filters["date"] = _date
templates.env.filters["datetime"] = _datetime
templates.env.filters["time"] = _time
templates.env.filters["money"] = _money
templates.env.filters["nl2br"] = _nl2br
templates.env.globals["app_name"] = config.APP_NAME
