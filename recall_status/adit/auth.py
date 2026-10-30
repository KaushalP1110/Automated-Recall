"""Adit login - the same POST {BASE_URL}auth/login flow the dashboard and
Reminder-Sanity-Automation use."""

from __future__ import annotations

import logging

import requests

from config import settings

logger = logging.getLogger("recall_status.adit.auth")


def login(session: requests.Session) -> str:
    """Returns the bearer token sent as the `authorization` header."""
    response = session.post(
        f"{settings.ADIT_BASE_URL}auth/login",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/plain, */*",
            "origin": settings.ADIT_ORIGIN,
            "x-auth-key": settings.ADIT_X_AUTH_KEY or "",
            "x-auth-token": settings.ADIT_X_AUTH_TOKEN or "",
        },
        json={"email": settings.ADIT_USERNAME, "password": settings.ADIT_PASSWORD},
        timeout=settings.ADIT_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Adit login failed with status {response.status_code}")
    token = response.json().get("token")
    if not token:
        raise RuntimeError("Adit login response did not contain a token")
    logger.info("Logged in to Adit as %s", settings.ADIT_USERNAME)
    return token
