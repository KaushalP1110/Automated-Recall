"""
Central configuration for the Automated Recall status check.

Everything is env-var driven (read from the real environment first, then
.env) so the same code runs on a laptop and on Jenkins. Secrets (DB and
Adit passwords, x-auth key/token) are never hardcoded - see .env.example.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader - only fills variables not already set, so a real
    exported env var always wins over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


# --- OpenDental MySQL ---------------------------------------------------------
OD_DB_HOST = os.environ.get("OD_DB_HOST", "127.0.0.1")
OD_DB_PORT = int(os.environ.get("OD_DB_PORT", "3306"))
OD_DB_USER = os.environ.get("OD_DB_USER", "root")
OD_DB_PASSWORD = os.environ.get("OD_DB_PASSWORD", "")
OD_DB_NAME = os.environ.get("OD_DB_NAME", "opendental_123")

# ProphyRecall on opendental_123 (recalltype.RecallTypeNum=1). Its trigger
# procedures (recalltrigger) are read from the DB at run time, not hardcoded -
# currently T1356 Exam + T3541 Prophy, Adult.
OD_RECALL_TYPE_NUM = int(os.environ.get("OD_RECALL_TYPE_NUM", "1"))
OD_PROV_NUM = int(os.environ.get("OD_PROV_NUM", "1"))            # Default Provider (DOC)
OD_OPERATORY_NUM = int(os.environ.get("OD_OPERATORY_NUM", "5"))  # Hygiene Op 1
OD_UNCONFIRMED_DEFNUM = int(os.environ.get("OD_UNCONFIRMED_DEFNUM", "19"))
OD_USER_NUM = int(os.environ.get("OD_USER_NUM", "1"))            # Admin - recorded as SecUserNumEntry/HistUserNum

# When a recall procedure is completed, OpenDental normally rolls DateDue
# forward by the recall interval. Adit's Automated Recall only shows
# "Completed" when the due date and the completed appointment are in the SAME
# month (checked in that due month's report), so the due date is left where
# the scenario put it. Set true to see what Adit does with the rolled date.
OD_ROLL_DUE_DATE_ON_COMPLETE = _bool("OD_ROLL_DUE_DATE_ON_COMPLETE", False)

# --- Adit ---------------------------------------------------------------------
ENVIRONMENT = os.environ.get("RECALL_CHECK_ENV", "Live")
_BASE_URLS = {"Live": "https://api.adit.com/", "Beta": "https://betaapi.adit.com/"}
ADIT_BASE_URL = os.environ.get("ADIT_BASE_URL", _BASE_URLS.get(ENVIRONMENT, _BASE_URLS["Live"]))
ADIT_ORIGIN = os.environ.get("ADIT_ORIGIN", "https://app.adit.com")
ADIT_USERNAME = os.environ.get("ADIT_USERNAME")
ADIT_PASSWORD = os.environ.get("ADIT_PASSWORD")
ADIT_X_AUTH_KEY = os.environ.get("ADIT_X_AUTH_KEY")
ADIT_X_AUTH_TOKEN = os.environ.get("ADIT_X_AUTH_TOKEN")

# Kaushal_houston_plivo on Live - the location synced with opendental_123.
ADIT_ORGANIZATION_ID = os.environ.get("ADIT_ORGANIZATION_ID", "eb95e6b2-dde6-4efb-8963-fb3ae25a3751")
ADIT_LOCATION_NAME = os.environ.get("ADIT_LOCATION_NAME", "Kaushal_Houston_plivo")  # shown in the report
ADIT_LOCATION_ID = os.environ.get("ADIT_LOCATION_ID", "bae31335-de73-47f9-a7c1-e1916072136d")

# Engage -> Reports -> Automated Recall: the report page's own list call
# (captured from the browser 2026-09-30) - see recall_status/adit/recall_report_client.py.
_ENGMODAPI_URLS = {"Live": "https://engmodapi.adit.com/", "Beta": "https://betacronar.adit.com/"}
ADIT_RECALL_REPORT_URL = os.environ.get(
    "ADIT_RECALL_REPORT_URL",
    _ENGMODAPI_URLS.get(ENVIRONMENT, _ENGMODAPI_URLS["Live"]) + "engage/report/recall/get",
)

ADIT_HTTP_TIMEOUT_SECONDS = int(os.environ.get("ADIT_HTTP_TIMEOUT_SECONDS", "60"))

# --- Waiting for Adit to sync the OpenDental changes -----------------------------
# Adit needs ~5 minutes to sync OpenDental changes, so the first report check
# waits this long after the last OpenDental write (per QA guidance).
SYNC_WAIT_SECONDS = int(os.environ.get("RECALL_CHECK_SYNC_WAIT_SECONDS", "300"))
POLL_INTERVAL_SECONDS = int(os.environ.get("RECALL_CHECK_POLL_INTERVAL_SECONDS", "60"))
POLL_TIMEOUT_SECONDS = int(os.environ.get("RECALL_CHECK_POLL_TIMEOUT_SECONDS", "1800"))

# --- Cleanup ------------------------------------------------------------------------
# After the report: delete the appointments this run created and put each
# patient's recall back the way it was before the run.
CLEANUP_AFTER_RUN = _bool("RECALL_CHECK_CLEANUP", True)
# Recalls are NOT deleted or restored by cleanup (QA direction): each test
# patient keeps the recall with the due date the last run set, so it stays
# visible in OpenDental and in Adit's Automated Recall report after the run.
# Only the run's appointments are removed. Set true to also delete/restore recalls.
CLEANUP_RECALLS = _bool("RECALL_CHECK_CLEANUP_RECALLS", False)

# --- Publishing: PDF -> Google Drive -> Google Chat card -------------------------
# Same Chat space / service account / Shared Drive as Reminder-Sanity-Automation.
# A Chat incoming webhook can't carry a file, so the PDF goes to Drive and the
# card links to it. Each step is skipped (never fails the run) when unset.
GCHAT_WEBHOOK_URL = os.environ.get("GCHAT_WEBHOOK_URL")
# One or more Chat spaces, comma-separated in GCHAT_WEBHOOK_URL - the card is
# posted to each.
GCHAT_WEBHOOK_URLS = [u.strip() for u in (GCHAT_WEBHOOK_URL or "").split(",") if u.strip()]
GDRIVE_SERVICE_ACCOUNT_FILE = os.environ.get("GDRIVE_SERVICE_ACCOUNT_FILE")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID")
GDRIVE_SHARE_DOMAIN = os.environ.get("GDRIVE_SHARE_DOMAIN")
# Drive layout: <GDRIVE_FOLDER_ID>/<this>/<YYYY-MM Month>/Automated Recall Report <date>.pdf
GDRIVE_REPORT_FOLDER_NAME = os.environ.get("GDRIVE_REPORT_FOLDER_NAME", "Recall Report")
PDF_BROWSER_PATH = os.environ.get("PDF_BROWSER_PATH")

SCENARIOS_FILE = Path(os.environ.get("RECALL_CHECK_SCENARIOS_FILE", str(PROJECT_ROOT / "config" / "scenarios.yaml")))
REPORTS_DIR = Path(os.environ.get("RECALL_CHECK_REPORTS_DIR", str(PROJECT_ROOT / "reports" / "output")))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

REQUIRED_ENV_VARS = ("OD_DB_PASSWORD", "ADIT_USERNAME", "ADIT_PASSWORD", "ADIT_X_AUTH_KEY", "ADIT_X_AUTH_TOKEN")


def missing_required_config() -> list[str]:
    return [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
