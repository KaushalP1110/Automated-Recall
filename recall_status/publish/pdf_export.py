"""Renders an HTML report to PDF with a headless Chromium browser (Microsoft
Edge or Google Chrome) - no extra Python dependency, since Edge ships with
every Windows machine this runs on (dev boxes and the Jenkins agent).

The browser is launched with its own throwaway --user-data-dir: without it,
an already-open Edge/Chrome window swallows the headless launch (it just
hands the command to the running instance and exits) and no PDF is written.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger("recall_status.pdf_export")

_BROWSER_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
]


def find_browser() -> Optional[str]:
    """PDF_BROWSER_PATH if set, else the first installed Edge/Chrome."""
    if settings.PDF_BROWSER_PATH:
        return settings.PDF_BROWSER_PATH
    for candidate in _BROWSER_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html_path: Path, pdf_path: Optional[Path] = None, timeout_seconds: int = 120) -> Path:
    """Writes html_path as a PDF (next to it, same stem, unless pdf_path is
    given) and returns the PDF path. Raises RuntimeError if no browser is
    found or the browser didn't produce a PDF."""
    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve() if pdf_path else html_path.with_suffix(".pdf")
    browser = find_browser()
    if not browser:
        raise RuntimeError("No Edge/Chrome browser found for PDF export - set PDF_BROWSER_PATH")

    pdf_path.unlink(missing_ok=True)
    # "--headless=new" first, then the legacy "--headless": Edge 154 on the
    # QA machine exits 0 without writing anything in the new mode (confirmed
    # 2026-09-30) but prints fine in the legacy one.
    errors = []
    for mode in ("--headless=new", "--headless"):
        with tempfile.TemporaryDirectory(prefix="recall_status_pdf_", ignore_cleanup_errors=True) as profile_dir:
            command = [
                browser, mode, "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={profile_dir}", "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
            # The launcher can exit before its child process has written the
            # PDF (seen with Edge 154) - give it time to appear.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not (pdf_path.exists() and pdf_path.stat().st_size > 0):
                time.sleep(0.5)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            break
        errors.append(f"{mode}: exit={completed.returncode} {completed.stderr.strip()[-200:]}")
    else:
        raise RuntimeError("Browser did not write a PDF - " + " | ".join(errors))
    logger.info("PDF report written to %s", pdf_path)
    return pdf_path
