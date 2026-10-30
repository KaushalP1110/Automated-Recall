"""Publish an already-generated run: PDF -> Google Drive -> Google Chat card.

    python runners/publish_report.py reports/output/recall_status_results_<stamp>.json

Re-renders the HTML from the results file (so it has the current design),
then publishes it. Full runs publish automatically - this is for re-sending.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from recall_status.publish import publish_report  # noqa: E402
from recall_status.report import load_results, render_html  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    results = Path(sys.argv[1])
    scenarios, run_at = load_results(results)
    html_path = results.with_name(results.name.replace("recall_status_results_", "recall_status_report_")).with_suffix(".html")
    html_path.write_text(render_html(scenarios, run_at), encoding="utf-8")
    outcome = publish_report(html_path, scenarios, run_at)
    print(f"PDF: {outcome['pdf'] or 'not created'}")
    print(f"Drive: {outcome['pdf_url'] or 'not uploaded'}")
    print(f"Google Chat: {'posted' if outcome['chat'] else 'not posted'}")
    return 0 if outcome["chat"] else 1


if __name__ == "__main__":
    sys.exit(main())
