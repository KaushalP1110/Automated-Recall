"""HTML report -> PDF -> Google Drive -> Google Chat card.

Every step is best-effort: a missing browser, Drive or Chat setting, or a
failed upload is logged and skipped - publishing never changes a run's
PASS/FAIL result or exit code.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from recall_status.scenarios import Scenario

logger = logging.getLogger("recall_status.publish")


def publish_report(html_path: Path, scenarios: list[Scenario], run_at: datetime) -> dict:
    from recall_status.publish import gchat_notifier, gdrive_uploader, pdf_export

    result: dict[str, Optional[object]] = {"pdf": None, "pdf_url": None, "chat": False}
    try:
        result["pdf"] = pdf_export.html_to_pdf(html_path)
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.error("PDF export failed: %s", exc)
    if result["pdf"]:
        result["pdf_url"] = gdrive_uploader.upload_daily_report(result["pdf"], run_at.astimezone())
    result["chat"] = gchat_notifier.send(scenarios, run_at, result["pdf_url"])
    return result
