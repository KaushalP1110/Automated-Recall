"""Polls Adit Engage -> Reports -> Automated Recall until every scenario's
patient shows the expected status, or the timeout passes. Adit only sees
the OpenDental changes after its sync runs, so the first polls usually
find the old status (or no row).

The report is filtered by due-date month, so each scenario is looked up in
every month its recall could be listed under (the due date's month and the
appointment's month). A completed recall is only checked in its due date's
month: Adit shows "Completed" when the due date and the completed
appointment are in the same month. A row is matched on PatNum + recall type.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import requests

from config import settings
from recall_status.adit.auth import login
from recall_status.adit.recall_report_client import RecallReportClient, month_label
from recall_status.scenarios import Scenario
from recall_status.status_matcher import statuses_match

logger = logging.getLogger("recall_status.verify")


def scenario_months(s: Scenario) -> list[str]:
    if s.appointment == "completed":
        # "Completed" is shown in the due date's own month only.
        return [month_label(s.set_due_date)]
    days = [d for d in (s.set_due_date, s.due_date, s.appt_datetime.date() if s.appt_datetime else None) if d]
    return list(dict.fromkeys(month_label(d) for d in days))


def _check(client: RecallReportClient, s: Scenario, cache: dict) -> bool:
    rows = client.find_rows(s.pat_num, settings.OD_RECALL_TYPE_NUM, scenario_months(s), cache)
    s.adit_rows = rows
    s.actual_status = [row.get("recall_status") or "" for row in rows]
    return any(statuses_match(s.expected_status, [row.get("recall_status") or ""]) for row in rows)


def wait_for_sync(last_write: datetime) -> None:
    """Sleeps until SYNC_WAIT_SECONDS after the last OpenDental write, so the
    first report check happens after Adit's sync rather than before it."""
    ready_at = last_write + timedelta(seconds=settings.SYNC_WAIT_SECONDS)
    remaining = (ready_at - datetime.now()).total_seconds()
    if remaining > 0:
        logger.info("Waiting %ds for Adit to sync (last OpenDental write %s, first check at %s)",
                    remaining, f"{last_write:%H:%M:%S}", f"{ready_at:%H:%M:%S}")
        time.sleep(remaining)


def verify_in_adit(scenarios: list[Scenario], last_write: datetime) -> None:
    pending = [s for s in scenarios if s.error is None]
    if not pending:
        return
    wait_for_sync(last_write)
    session = requests.Session()
    client = RecallReportClient(session, login(session))

    deadline = time.monotonic() + settings.POLL_TIMEOUT_SECONDS
    attempt = 0
    while pending:
        attempt += 1
        cache: dict[str, list[dict]] = {}  # fresh report data every poll
        for s in list(pending):
            try:
                matched = _check(client, s, cache)
            except requests.RequestException as exc:
                logger.warning("%s: Adit request failed (%s) - will retry", s.id, exc)
                continue
            if matched:
                s.passed = True
                pending.remove(s)
                logger.info("%s PASS: %s shows %s", s.id, s.patient_label, s.actual_status)
        if not pending or time.monotonic() >= deadline:
            break
        logger.info("Poll %d: waiting on %s - next check in %ss", attempt,
                    ", ".join(f"{s.id} (now {s.actual_status or 'not listed'})" for s in pending),
                    settings.POLL_INTERVAL_SECONDS)
        time.sleep(settings.POLL_INTERVAL_SECONDS)

    for s in pending:
        s.passed = False
        months = ", ".join(scenario_months(s))
        s.error = (f"Adit showed {s.actual_status} after {settings.POLL_TIMEOUT_SECONDS}s"
                   if s.adit_rows else
                   f"Not listed in Automated Recall ({months}) after {settings.POLL_TIMEOUT_SECONDS}s")
        logger.error("%s FAIL: %s", s.id, s.error)
