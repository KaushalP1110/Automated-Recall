"""Automated Recall status check: OpenDental -> Adit.

    python runners/run_recall_status_check.py                 full run
    python runners/run_recall_status_check.py --setup-only    set up OpenDental data, then stop (check Adit by hand)
    python runners/run_recall_status_check.py --cleanup-only  undo the last --setup-only / --keep run
    python runners/run_recall_status_check.py --keep          full run, but leave the data in OpenDental

Exit code 0 when every scenario passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from recall_status import report  # noqa: E402
from recall_status.scenarios import load_scenarios  # noqa: E402
from recall_status.setup_and_cleanup import cleanup, setup_scenarios, state_file_path  # noqa: E402

logger = logging.getLogger("recall_status")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup-only", action="store_true")
    mode.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--keep", action="store_true", help="don't clean up OpenDental after the run")
    parser.add_argument("--no-publish", action="store_true", help="skip PDF / Google Drive / Google Chat")
    args = parser.parse_args()

    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if args.cleanup_only:
        done, failed = cleanup()
        print(f"Cleanup: {done} patient(s) cleaned up, {failed} failed")
        return 0 if failed == 0 else 1

    missing = settings.missing_required_config()
    if args.setup_only:
        missing = [m for m in missing if m.startswith("OD_")]
    if missing:
        logger.error("Missing configuration: %s (see .env.example)", ", ".join(missing))
        return 1

    if state_file_path().exists():
        logger.error("%s exists - a previous run was not cleaned up. Run --cleanup-only first.", state_file_path())
        return 1

    scenarios = load_scenarios(settings.SCENARIOS_FILE)
    today = date.today()
    logger.info("Run date %s - %d scenarios", today, len(scenarios))

    state = setup_scenarios(scenarios, today)
    last_write = datetime.now()
    if args.setup_only:
        report.print_summary(scenarios)
        print(f"OpenDental data is set up. Check Adit, then run with --cleanup-only. State: {state_file_path()}")
        return 0 if all(s.error is None for s in scenarios) else 1

    try:
        from recall_status.verify import verify_in_adit
        verify_in_adit(scenarios, last_write)
    except Exception as exc:  # noqa: BLE001 - still report and clean up
        logger.exception("Adit verification failed")
        for s in scenarios:
            if s.passed is None:
                s.passed = False
                s.error = f"Adit verification error: {exc}"

    report.print_summary(scenarios)
    run_at = datetime.now()
    path = report.write_html(scenarios, settings.REPORTS_DIR, run_at=run_at)
    print(f"HTML report: {path}")
    if not args.no_publish:
        from recall_status.publish import publish_report
        outcome = publish_report(path, scenarios, run_at)
        print(f"PDF: {outcome['pdf'] or 'not created'} | Drive: {outcome['pdf_url'] or 'not uploaded'} | "
              f"Google Chat: {'posted' if outcome['chat'] else 'not posted'}")

    if args.keep or not settings.CLEANUP_AFTER_RUN:
        print(f"OpenDental data kept. Undo later with --cleanup-only. State: {state_file_path()}")
    else:
        cleanup(state)

    return 0 if all(s.passed for s in scenarios) else 1


if __name__ == "__main__":
    sys.exit(main())
