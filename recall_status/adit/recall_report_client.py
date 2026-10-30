"""Engage -> Reports -> Automated Recall.

The report page's own list call, captured from the browser 2026-09-30:

    GET {ENGMODAPI}engage/report/recall/get?locationId=..&organizationId=..&month=September%202026

It returns every recall whose DUE DATE falls in `month`, one row per
patient + recall type:

    {"status": true, "message": "Patient found with due dates", "data": [
        {"patient_ehr_id": "252",          <- OpenDental PatNum
         "recall_type_ehr_key": "1",       <- OpenDental RecallTypeNum
         "recall_type": "ProphyRecall",
         "due_date": "2026-09-03T00:00:00.000Z",
         "recall_status": "Overdue & Unsched",
         "completed_at": null, "next_appointment_time": null,
         "first_name": "Krish", "last_name": "Patel", ...}]}

Status labels are abbreviated ("Unsched", "Overdue & Unsched"); see
status_matcher for how they are compared.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

import requests

from config import settings

logger = logging.getLogger("recall_status.adit.recall_report")


def month_label(day: date) -> str:
    """The report's month filter, e.g. 'September 2026'."""
    return day.strftime("%B %Y")


class RecallReportClient:
    def __init__(self, session: requests.Session, token: str) -> None:
        self._session = session
        self._token = token

    def get_month(self, month: str) -> list[dict]:
        response = self._session.get(
            settings.ADIT_RECALL_REPORT_URL,
            params={"locationId": settings.ADIT_LOCATION_ID, "organizationId": settings.ADIT_ORGANIZATION_ID,
                    "month": month},
            headers={"accept": "application/json, text/plain, */*", "origin": settings.ADIT_ORIGIN,
                     "authorization": self._token},
            timeout=settings.ADIT_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        # A month with no due recalls comes back as status=false +
        # "Patient not found with due dates" - that's an empty month, not an error.
        if payload.get("status") is False and "not found" in (payload.get("message") or "").lower():
            return []
        if payload.get("status") is False:
            raise RuntimeError(f"recall/get returned status=false: {payload.get('message')}")
        return payload.get("data") or []

    def find_rows(self, pat_num: int, recall_type_num: int, months: Iterable[str],
                  cache: Optional[dict[str, list[dict]]] = None) -> list[dict]:
        """Every report row for this patient + recall type across `months`.
        `cache` (month -> rows) lets one poll share a month's fetch between
        scenarios."""
        cache = {} if cache is None else cache
        found = []
        for month in dict.fromkeys(months):
            if month not in cache:
                cache[month] = self.get_month(month)
            for row in cache[month]:
                if str(row.get("patient_ehr_id")) == str(pat_num) \
                        and str(row.get("recall_type_ehr_key")) == str(recall_type_num):
                    found.append({**row, "_month": month})
        return found
