"""Posts the Automated Recall result to Google Chat as a card (cardsV2) via
an incoming webhook. A webhook can't carry a file, so the PDF is linked
with an "Open PDF report" button (see publish.publish_report).

The webhook URL's key+token are write access to the space - it comes from
settings (.env) only and is never logged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import requests

from config import settings
from recall_status.describe import short_setup
from recall_status.scenarios import Scenario

logger = logging.getLogger("recall_status.gchat")


def _status(labels: list[str]) -> str:
    return " & ".join(labels) if labels else "not listed"


def build_card(scenarios: list[Scenario], run_at: datetime, pdf_url: Optional[str]) -> dict[str, Any]:
    """Same layout and wording as the team's "Auto-Reminders Sanity update"
    card (Reminder-Sanity-Automation): overall result, one row per scenario
    in plain words ("✅ Shows X · Working fine" / "❌ Expected X · Adit shows
    Y") with its dates underneath, "Needs attention" only
    when something failed, then the PDF button. No top-level "text" - Chat
    shows it above the card, which duplicates every line."""
    passed = sum(1 for s in scenarios if s.passed)
    overall = "PASS" if passed == len(scenarios) else "FAIL"

    def row(title: str, ok: bool, detail: str) -> dict[str, Any]:
        return {"decoratedText": {"topLabel": title, "text": f"{'✅' if ok else '❌'}  {detail}", "wrapText": True}}

    # One row per scenario: what was tested (plain words), the result, and
    # a short line with that scenario's dates.
    status_rows = []
    for s in scenarios:
        expected = _status(s.expected_status)
        if s.passed:
            detail = f"✅  Shows <b>{expected}</b> · Working fine"
        else:
            detail = f"❌  Expected <b>{expected}</b> · Adit shows <b>{_status(s.actual_status)}</b>"
        status_rows.append({"decoratedText": {
            "topLabel": f"{s.id} · {s.name}",
            "text": detail,
            "bottomLabel": short_setup(s),
            "wrapText": True,
        }})

    sections: list[dict[str, Any]] = [
        {"widgets": [row("Overall result", overall == "PASS", f"<b>{overall}</b>  ({passed}/{len(scenarios)} passed)")]},
        {"header": "Scenarios", "widgets": status_rows},
    ]
    failures = [s for s in scenarios if not s.passed]
    if failures:
        sections.append({"header": "Needs attention", "widgets": [
            {"decoratedText": {
                "topLabel": f"{s.id} · {s.name} · {s.first_name} {s.last_name} (PatNum {s.pat_num})",
                "text": f"⚠️  {s.error or f'Expected {_status(s.expected_status)}, Adit shows {_status(s.actual_status)}'}",
                "wrapText": True,
            }} for s in failures
        ]})
    if pdf_url:
        sections.append({"widgets": [{"buttonList": {"buttons": [
            {"text": "Open PDF report", "onClick": {"openLink": {"url": pdf_url}}},
        ]}}]})

    return {"cardsV2": [{
        "cardId": "automated-recall-status-update",
        "card": {
            "header": {"title": "Automated Recall Sanity update",
                       "subtitle": f"{run_at:%b %d, %Y} · {run_at:%I:%M %p}".replace(" 0", " ")},
            "sections": sections,
        },
    }]}


def send(scenarios: list[Scenario], run_at: datetime, pdf_url: Optional[str]) -> bool:
    """Posts the card to every space in GCHAT_WEBHOOK_URL (comma-separated).
    True if at least one post succeeded."""
    if not settings.GCHAT_WEBHOOK_URLS:
        logger.info("GCHAT_WEBHOOK_URL not set - skipping Google Chat")
        return False
    payload = build_card(scenarios, run_at, pdf_url)
    posted = 0
    for i, url in enumerate(settings.GCHAT_WEBHOOK_URLS, 1):
        space = f"space {i} of {len(settings.GCHAT_WEBHOOK_URLS)}"
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            posted += 1
            logger.info("Posted to Google Chat %s (status=%s)", space, response.status_code)
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            logger.error("Failed to post to Google Chat %s: %s%s", space, exc.__class__.__name__,
                         f" (status={status})" if status else "")
    return posted > 0
