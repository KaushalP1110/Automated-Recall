"""OpenDental's packed recall interval (recall.RecallInterval /
recalltype.DefaultInterval): one int holding years, months, weeks and days,
one byte each - e.g. 393216 = 6 << 16 = 6 months."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def unpack(value: int) -> tuple[int, int, int, int]:
    """Returns (years, months, weeks, days)."""
    return (value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def add_interval(start: date, value: int) -> date:
    """start + interval, the way OpenDental adds it: calendar years and
    months first (clamped to the month's last day), then weeks and days."""
    years, months, weeks, days = unpack(value)
    month_index = start.month - 1 + months
    year = start.year + years + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day) + timedelta(weeks=weeks, days=days)
