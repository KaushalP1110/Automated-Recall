"""Sets each scenario's recall + appointment up in OpenDental, and undoes it.

OpenDental's tables are MyISAM, so commit/rollback do nothing - every write
is permanent immediately (confirmed on opendental_123). That's why each row
is added to the state file as soon as it is created, before the next write:
a run that crashes halfway - or a --setup-only run checked by hand in Adit -
can still be undone completely with --cleanup-only.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from config import settings
from recall_status.opendental import db
from recall_status.scenarios import Scenario, resolve_dates

logger = logging.getLogger("recall_status.setup")

STATE_FILE = settings.REPORTS_DIR / "last_run_state.json"


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=_json_default), encoding="utf-8")


def setup_scenarios(scenarios: list[Scenario], today: date) -> dict:
    """Returns the cleanup state. A scenario that can't be set up gets
    `error` and is skipped; the others still run."""
    state: dict = {"created_at": datetime.now(), "patients": []}
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            recall_type = db.get_recall_type(cur, settings.OD_RECALL_TYPE_NUM)
        triggers = recall_type["triggers"]
        code_nums = [t["CodeNum"] for t in triggers]
        logger.info("Recall type %s, trigger procedures %s", recall_type["Description"],
                    ", ".join(t["ProcCode"] for t in triggers))

        for s in scenarios:
            entry: dict = {"scenario": s.id}
            try:
                resolve_dates(s, today)
                with conn.cursor() as cur:
                    patient = db.find_patient(cur, s.first_name, s.last_name, s.pat_num)
                    s.pat_num = patient["PatNum"]
                    s.first_name, s.last_name = patient["FName"].strip(), patient["LName"].strip()
                    entry["pat_num"] = s.pat_num
                    state["patients"].append(entry)

                    others = db.find_other_recall_appointments(cur, s.pat_num, code_nums, today)
                    if others:
                        raise RuntimeError(
                            "patient already has scheduled recall appointment(s) "
                            + ", ".join(f"AptNum {a['AptNum']} on {a['AptDateTime']:%Y-%m-%d}" for a in others)
                            + " - these would change the status, remove them or pick another patient"
                        )

                    recall = db.get_recall(cur, s.pat_num, recall_type["RecallTypeNum"])
                    if recall:
                        entry["recall_snapshot"] = recall
                        s.recall_num = recall["RecallNum"]
                        interval = recall["RecallInterval"] or recall_type["DefaultInterval"]
                    else:
                        s.recall_num = db.create_recall(cur, s.pat_num, recall_type)
                        entry["created_recall_num"] = s.recall_num
                        interval = recall_type["DefaultInterval"]
                    _save_state(state)

                    scheduled_on = s.appt_datetime.date() if s.appointment == "scheduled" else db.MIN_DATE
                    db.set_recall_dates(cur, s.recall_num, s.due_date, scheduled=scheduled_on)

                    if s.appointment != "none":
                        completed = s.appointment == "completed"
                        s.apt_num = db.create_recall_appointment(
                            cur, s.pat_num, s.appt_datetime, completed, triggers,
                            on_created=lambda apt_num: (entry.__setitem__("apt_num", apt_num), _save_state(state)),
                        )
                        if completed:
                            s.due_date = db.apply_completion_to_recall(
                                cur, s.recall_num, s.appt_datetime.date(), interval,
                                settings.OD_ROLL_DUE_DATE_ON_COMPLETE,
                            )
                conn.commit()
                logger.info("%s set up: %s, recall due %s, appointment %s%s", s.id, s.patient_label, s.due_date,
                            s.appointment, f" (AptNum {s.apt_num} on {s.appt_datetime:%Y-%m-%d %H:%M})"
                            if s.apt_num else "")
            except Exception as exc:  # noqa: BLE001 - one bad scenario must not stop the others
                # No rollback on MyISAM - anything already written is in the
                # state file and gets undone by cleanup.
                s.error = f"OpenDental setup failed: {exc}"
                s.passed = False
                logger.error("%s: %s", s.id, s.error)
            _save_state(state)
    finally:
        conn.close()
    return state


def cleanup(state: dict | None = None) -> tuple[int, int]:
    """Deletes the run's appointments. Recalls are kept as the run left them
    unless CLEANUP_RECALLS is on (then they are restored or removed). Best-effort: logs and continues on errors. Returns
    (patients cleaned, patients with errors)."""
    if state is None:
        if not STATE_FILE.exists():
            logger.info("Cleanup: no state file, nothing to undo")
            return 0, 0
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    done = failed = 0
    conn = db.connect()
    try:
        for entry in state.get("patients", []):
            pat_num = entry.get("pat_num")
            try:
                with conn.cursor() as cur:
                    if entry.get("apt_num"):
                        if not db.delete_appointment(cur, entry["apt_num"], pat_num):
                            logger.warning("Cleanup: AptNum %s not found for PatNum %s", entry["apt_num"], pat_num)
                    if settings.CLEANUP_RECALLS:
                        if entry.get("created_recall_num"):
                            db.delete_recall(cur, entry["created_recall_num"], pat_num)
                        elif entry.get("recall_snapshot"):
                            db.restore_recall(cur, entry["recall_snapshot"])
                    elif entry.get("apt_num"):
                        # The appointment is gone, so the kept recall must not
                        # still point at it as scheduled.
                        db.clear_recall_scheduled(cur, pat_num, settings.OD_RECALL_TYPE_NUM)
                conn.commit()
                done += 1
                logger.info("Cleanup: %s (PatNum %s) appointments removed%s", entry["scenario"], pat_num,
                            "" if settings.CLEANUP_RECALLS else ", recall kept")
            except Exception as exc:  # noqa: BLE001 - best-effort
                conn.rollback()
                failed += 1
                logger.error("Cleanup failed for %s (PatNum %s): %s", entry["scenario"], pat_num, exc)
    finally:
        conn.close()
    if failed == 0 and STATE_FILE.exists():
        STATE_FILE.unlink()
    return done, failed


def state_file_path() -> Path:
    return STATE_FILE
