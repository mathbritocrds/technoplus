"""Explicit dependencies shared by the business and accounting domains."""
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI


@dataclass(frozen=True, kw_only=True)
class AppServices:
    app: FastAPI
    db: Callable[[], AbstractContextManager[Any]]
    admin: Callable[..., Any]
    admin_context: Callable[..., dict]
    principal: Callable[..., dict]
    manager_or_admin: Callable[..., dict]
    employee_principal: Callable[..., dict]
    rows: Callable[[Iterable[Any]], list[dict]]
    utcnow: Callable[[], datetime]
    iso: Callable[[datetime], str]
    local: Callable[[datetime], datetime]
    day_range: Callable[[date], tuple[datetime, datetime]]
    booking_time: Callable[[str], str]
    timesheet_data: Callable[..., Any]
    quote: Callable[[str], str]
    csv_safe: Callable[[Any], Any]
    postgres_url: Callable[[], str]
