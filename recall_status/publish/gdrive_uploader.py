"""Uploads the daily PDF report to Google Drive with a service account and
returns its browser link, so the Google Chat card can link to it (an
incoming webhook can only post JSON text/cards - it cannot carry a file
attachment).

Layout under GDRIVE_FOLDER_ID - a "Recall Report" folder (GDRIVE_REPORT_FOLDER_NAME),
one folder per month inside it, one PDF per day:

    Recall Report/
        2026-09 September/
            Automated Recall Report 2026-09-30.pdf

The Recall Report and month folders are created on first use. A second run on the same day
replaces that day's PDF as a new revision of the same Drive file (same
link; Drive's version history keeps the earlier run) rather than adding a
duplicate.

GDRIVE_FOLDER_ID must be a Shared Drive (or a folder on one) that the
service account is a member of (Content manager or above). Service accounts
have no Drive storage quota of their own, so uploading into a folder in a
person's My Drive fails with "Service Accounts do not have storage quota".

The service-account JSON key is a credential - GDRIVE_SERVICE_ACCOUNT_FILE
is read from settings (env-var/`.env` only) and the key file must never be
committed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger("recall_status.gdrive_uploader")

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_ALL_DRIVES = {"supportsAllDrives": "true"}


def is_configured() -> bool:
    return bool(settings.GDRIVE_SERVICE_ACCOUNT_FILE and settings.GDRIVE_FOLDER_ID)


def month_folder_name(run_time: datetime) -> str:
    return run_time.strftime("%Y-%m %B")


def daily_report_name(run_time: datetime) -> str:
    return f"Automated Recall Report {run_time.strftime('%Y-%m-%d')}.pdf"


def _session():
    # Imported lazily so the rest of the suite runs without google-auth
    # installed when Drive upload isn't configured.
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        settings.GDRIVE_SERVICE_ACCOUNT_FILE, scopes=_SCOPES,
    )
    return AuthorizedSession(credentials)


def _find_child(session, parent_id: str, name: str, folder: bool) -> Optional[str]:
    """Oldest non-trashed item called `name` directly under parent_id.
    Queries by name and checks the parent client-side: the "'X' in parents"
    search index was observed 2026-09-25 lagging seconds behind a fresh
    upload (it didn't list a folder created moments earlier, so a second
    upload made a duplicate), while the name index was already current."""
    mime_clause = f"mimeType = '{_FOLDER_MIME}'" if folder else f"mimeType != '{_FOLDER_MIME}'"
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    response = session.get(_FILES_URL, params={
        **_ALL_DRIVES,
        "includeItemsFromAllDrives": "true",
        "corpora": "allDrives",
        "q": f"name = '{escaped}' and {mime_clause} and trashed = false",
        "fields": "files(id,parents)",
        "orderBy": "createdTime",
        "pageSize": "100",
    }, timeout=30)
    response.raise_for_status()
    for item in response.json().get("files", []):
        if parent_id in item.get("parents", []):
            return item["id"]
    return None


def _get_or_create_folder(session, parent_id: str, name: str) -> str:
    existing = _find_child(session, parent_id, name, folder=True)
    if existing:
        return existing
    response = session.post(_FILES_URL, params={**_ALL_DRIVES, "fields": "id"},
                            json={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}, timeout=30)
    response.raise_for_status()
    logger.info("Created Drive folder %r", name)
    return response.json()["id"]


def _create_file(session, parent_id: str, name: str, content: bytes, mime_type: str) -> dict:
    boundary = f"recall-status-{uuid.uuid4().hex}"
    metadata = {"name": name, "parents": [parent_id]}
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    response = session.post(
        _UPLOAD_URL,
        params={**_ALL_DRIVES, "uploadType": "multipart", "fields": "id,webViewLink"},
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _replace_file_content(session, file_id: str, content: bytes, mime_type: str) -> dict:
    response = session.patch(
        f"{_UPLOAD_URL}/{file_id}",
        params={**_ALL_DRIVES, "uploadType": "media", "fields": "id,webViewLink"},
        headers={"Content-Type": mime_type},
        data=content,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _share_with_domain(session, file_id: str, name: str) -> None:
    response = session.post(
        f"{_FILES_URL}/{file_id}/permissions",
        params=_ALL_DRIVES,
        json={"type": "domain", "role": "reader", "domain": settings.GDRIVE_SHARE_DOMAIN},
        timeout=30,
    )
    if not response.ok:
        logger.warning("Uploaded %s but domain share failed (status=%s): %s",
                       name, response.status_code, response.text[:300])


def upload_daily_report(pdf_path: Path, run_time: Optional[datetime] = None) -> Optional[str]:
    """Uploads pdf_path as that day's report inside that month's folder and
    returns its webViewLink. Returns None (logged, never raises) if Drive
    isn't configured or the upload fails - a missing link should never fail
    the recall check itself. If GDRIVE_SHARE_DOMAIN is set, the file is also
    shared read-only with everyone in that Google Workspace domain."""
    if not is_configured():
        logger.info("GDRIVE_SERVICE_ACCOUNT_FILE / GDRIVE_FOLDER_ID not set - skipping Drive upload")
        return None

    run_time = run_time or datetime.now().astimezone()
    name = daily_report_name(run_time)
    try:
        session = _session()
        report_root = _get_or_create_folder(session, settings.GDRIVE_FOLDER_ID, settings.GDRIVE_REPORT_FOLDER_NAME)
        folder_id = _get_or_create_folder(session, report_root, month_folder_name(run_time))
        content = Path(pdf_path).read_bytes()

        existing_id = _find_child(session, folder_id, name, folder=False)
        if existing_id:
            uploaded = _replace_file_content(session, existing_id, content, "application/pdf")
            logger.info("Replaced today's Drive report %s with a new revision (id=%s)", name, existing_id)
        else:
            uploaded = _create_file(session, folder_id, name, content, "application/pdf")
            logger.info("Uploaded %s to Google Drive (id=%s)", name, uploaded["id"])
        # On every upload, not just create: a file first uploaded before
        # GDRIVE_SHARE_DOMAIN was set stays members-only otherwise. Re-adding
        # an existing domain permission is a no-op on Drive's side.
        if settings.GDRIVE_SHARE_DOMAIN:
            _share_with_domain(session, uploaded["id"], name)
        return uploaded.get("webViewLink")
    except Exception as exc:  # noqa: BLE001 - best-effort, see docstring
        logger.error("Failed to upload %s to Google Drive: %s", name, exc)
        return None
