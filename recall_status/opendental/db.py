"""Direct OpenDental (MySQL) reads and writes for the recall scenarios.

Writes mirror what OpenDental itself stores when a user does the same thing
in the UI, because Adit syncs from these tables:

- Recall due date: recall.DateDue (and DateDueCalc, so OpenDental treats it
  as the calculated date rather than a manual override).
- "Appointment with the same recall type": an appointment whose attached
  procedures are the recall type's trigger codes (recalltrigger). OpenDental
  then sets recall.DateScheduled to the appointment date.
- Completed: appointment AptStatus=2 and its procedures ProcStatus=2; the
  recall's DatePrevious becomes the procedure date and (optionally) the due
  date rolls forward by the recall interval.
- Every created/deleted appointment gets a histappointment row, as the UI
  writes - without the "Deleted" one Adit never sees a delete.

Only rows this run creates are deleted, and a patient's recall is restored
from the snapshot taken before the run.

The tables are MyISAM: commit()/rollback() are accepted but nothing is
transactional - each statement is permanent as soon as it runs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable, Optional

import pymysql
import pymysql.cursors

from config import settings
from recall_status.opendental.recall_interval import add_interval

logger = logging.getLogger("recall_status.opendental")

# Fixed OpenDental enums.
APT_STATUS_SCHEDULED = 1
APT_STATUS_COMPLETE = 2
PROC_STATUS_TP = 1
PROC_STATUS_COMPLETE = 2
PROC_STATUS_DELETED = 6
HIST_ACTION_CREATED = 0
HIST_ACTION_DELETED = 4
PAT_STATUS_PATIENT = 0

MIN_DATE = date(1, 1, 1)

_HIST_APPOINTMENT_COLUMNS = (
    "AptNum, PatNum, AptStatus, Pattern, Confirmed, TimeLocked, Op, Note, ProvNum, ProvHyg, "
    "AptDateTime, NextAptNum, UnschedStatus, IsNewPatient, ProcDescript, Assistant, ClinicNum, "
    "IsHygiene, DateTimeArrived, DateTimeSeated, DateTimeDismissed, InsPlan1, InsPlan2, "
    "DateTimeAskedToArrive, ProcsColored, ColorOverride, AppointmentTypeNum, SecUserNumEntry, "
    "SecDateTEntry, Priority, ProvBarText, PatternSecondary, SecurityHash, ItemOrderPlanned"
)

_RECALL_RESTORE_COLUMNS = ("DateDue", "DateDueCalc", "DatePrevious", "DateScheduled", "RecallInterval",
                           "RecallStatus", "IsDisabled", "Note")


def connect():
    return pymysql.connect(
        host=settings.OD_DB_HOST, port=settings.OD_DB_PORT, user=settings.OD_DB_USER,
        password=settings.OD_DB_PASSWORD, database=settings.OD_DB_NAME,
        connect_timeout=5, cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


# --- generic insert ---------------------------------------------------------------

_column_cache: dict[str, list[dict]] = {}


def _zero_value(mysql_type: str) -> Any:
    t = mysql_type.lower()
    if t.startswith("datetime") or t.startswith("timestamp"):
        return "0001-01-01 00:00:00"
    if t.startswith("date"):
        return "0001-01-01"
    if t.startswith("time"):
        return "00:00:00"
    if any(t.startswith(p) for p in ("char", "varchar", "text", "tinytext", "mediumtext", "longtext", "blob")):
        return ""
    return 0


def insert_row(cur, table: str, values: dict[str, Any]) -> int:
    """INSERT with every NOT NULL column that has no default filled with its
    type's zero value (0 / '' / 0001-01-01), which is what OpenDental writes
    for unused fields. Reading the columns at run time keeps this working
    across OpenDental versions that add columns."""
    if table not in _column_cache:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        _column_cache[table] = cur.fetchall()
    row = dict(values)
    for col in _column_cache[table]:
        name = col["Field"]
        if name in row or "auto_increment" in (col["Extra"] or ""):
            continue
        if col["Null"] == "NO" and col["Default"] is None:
            row[name] = _zero_value(col["Type"])
    names = ", ".join(f"`{n}`" for n in row)
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(f"INSERT INTO `{table}` ({names}) VALUES ({placeholders})", list(row.values()))
    return cur.lastrowid


# --- lookups ------------------------------------------------------------------------

def find_patient(cur, first_name: str, last_name: str, pat_num: Optional[int]) -> dict:
    if pat_num:
        cur.execute("SELECT PatNum, FName, LName, PatStatus FROM patient WHERE PatNum=%s", (pat_num,))
        rows = cur.fetchall()
    else:
        cur.execute(
            "SELECT PatNum, FName, LName, PatStatus FROM patient "
            "WHERE LOWER(FName)=LOWER(%s) AND LOWER(LName)=LOWER(%s) AND PatStatus=%s",
            (first_name, last_name, PAT_STATUS_PATIENT),
        )
        rows = cur.fetchall()
    if not rows:
        raise LookupError(f"No active patient found for {first_name} {last_name} (PatNum={pat_num})")
    if len(rows) > 1:
        nums = ", ".join(str(r["PatNum"]) for r in rows)
        raise LookupError(f"{first_name} {last_name} matches several patients (PatNum {nums}) - set pat_num")
    if rows[0]["PatStatus"] != PAT_STATUS_PATIENT:
        raise LookupError(f"PatNum {rows[0]['PatNum']} is not an active patient (PatStatus={rows[0]['PatStatus']})")
    return rows[0]


def get_recall_type(cur, recall_type_num: int) -> dict:
    cur.execute("SELECT RecallTypeNum, Description, DefaultInterval FROM recalltype WHERE RecallTypeNum=%s",
                (recall_type_num,))
    row = cur.fetchone()
    if not row:
        raise LookupError(f"recalltype {recall_type_num} does not exist")
    cur.execute(
        "SELECT pc.CodeNum, pc.ProcCode, pc.AbbrDesc, pc.ProcTime FROM recalltrigger rt "
        "JOIN procedurecode pc ON pc.CodeNum=rt.CodeNum WHERE rt.RecallTypeNum=%s ORDER BY pc.ProcCode",
        (recall_type_num,),
    )
    row["triggers"] = cur.fetchall()
    if not row["triggers"]:
        raise LookupError(f"recalltype {row['Description']} has no trigger procedures (recalltrigger)")
    return row


def get_recall(cur, pat_num: int, recall_type_num: int) -> Optional[dict]:
    cur.execute("SELECT * FROM recall WHERE PatNum=%s AND RecallTypeNum=%s ORDER BY RecallNum LIMIT 1",
                (pat_num, recall_type_num))
    return cur.fetchone()


def find_other_recall_appointments(cur, pat_num: int, code_nums: list[int], today: date) -> list[dict]:
    """Pre-existing appointments that would change the patient's recall
    status on their own: scheduled (today or later) appointments carrying
    this recall type's trigger procedures. The run refuses to touch them."""
    placeholders = ", ".join(["%s"] * len(code_nums))
    cur.execute(
        f"SELECT DISTINCT a.AptNum, a.AptDateTime, a.AptStatus FROM appointment a "
        f"JOIN procedurelog p ON p.AptNum=a.AptNum "
        f"WHERE a.PatNum=%s AND a.AptStatus=%s AND DATE(a.AptDateTime)>=%s "
        f"AND p.CodeNum IN ({placeholders}) AND p.ProcStatus<>%s",
        (pat_num, APT_STATUS_SCHEDULED, today, *code_nums, PROC_STATUS_DELETED),
    )
    return cur.fetchall()


# --- writes -----------------------------------------------------------------------

def create_recall(cur, pat_num: int, recall_type: dict) -> int:
    return insert_row(cur, "recall", {
        "PatNum": pat_num,
        "RecallTypeNum": recall_type["RecallTypeNum"],
        "RecallInterval": recall_type["DefaultInterval"],
        "DateDue": MIN_DATE, "DateDueCalc": MIN_DATE, "DatePrevious": MIN_DATE, "DateScheduled": MIN_DATE,
        "DisableUntilDate": MIN_DATE, "IsDisabled": 0, "Note": "",
    })


def set_recall_dates(cur, recall_num: int, due: date, scheduled: date = MIN_DATE,
                     previous: Optional[date] = None) -> None:
    sets = ["DateDue=%s", "DateDueCalc=%s", "DateScheduled=%s", "IsDisabled=0"]
    params: list[Any] = [due, due, scheduled]
    if previous is not None:
        sets.append("DatePrevious=%s")
        params.append(previous)
    params.append(recall_num)
    cur.execute(f"UPDATE recall SET {', '.join(sets)} WHERE RecallNum=%s", params)


def create_recall_appointment(cur, pat_num: int, apt_dt: datetime, completed: bool, triggers: list[dict],
                              on_created: Optional[Callable[[int], Any]] = None) -> int:
    """One appointment with the recall type's trigger procedures attached.
    `on_created(apt_num)` runs right after the appointment row exists, so the
    caller can record it for cleanup before the procedures are written."""
    status = APT_STATUS_COMPLETE if completed else APT_STATUS_SCHEDULED
    now = datetime.now().replace(microsecond=0)
    pattern = "".join(t["ProcTime"] or "/X/" for t in triggers)
    descript = ", ".join(t["AbbrDesc"] or t["ProcCode"] for t in triggers)
    apt_num = insert_row(cur, "appointment", {
        "PatNum": pat_num,
        "AptStatus": status,
        "Pattern": pattern,
        "Confirmed": settings.OD_UNCONFIRMED_DEFNUM,
        "Op": settings.OD_OPERATORY_NUM,
        "ProvNum": settings.OD_PROV_NUM,
        "AptDateTime": apt_dt,
        "IsHygiene": 1,
        "ProcDescript": descript,
        "Note": "Recall status automation",
        "SecUserNumEntry": settings.OD_USER_NUM,
        "SecDateTEntry": now,
        "DateTimeAskedToArrive": "0001-01-01 00:00:00",
    })
    if on_created:
        on_created(apt_num)
    for t in triggers:
        insert_row(cur, "procedurelog", {
            "PatNum": pat_num,
            "AptNum": apt_num,
            "CodeNum": t["CodeNum"],
            "ProcDate": apt_dt.date(),
            "ProcStatus": PROC_STATUS_COMPLETE if completed else PROC_STATUS_TP,
            "ProvNum": settings.OD_PROV_NUM,
            "ProcFee": 0,
            "UnitQty": 1,
            "DateTP": now.date(),
            "DateEntryC": now.date(),
            "DateComplete": apt_dt.date() if completed else MIN_DATE,
            "IcdVersion": 10,
            "SecUserNumEntry": settings.OD_USER_NUM,
            "SecDateEntry": now,
        })
    _write_hist(cur, apt_num, HIST_ACTION_CREATED)
    return apt_num


def _write_hist(cur, apt_num: int, action: int) -> None:
    cur.execute(
        f"INSERT INTO histappointment (HistUserNum, HistDateTStamp, HistApptAction, ApptSource, "
        f"DateTStamp, {_HIST_APPOINTMENT_COLUMNS}) "
        f"SELECT %s, NOW(), %s, 0, NOW(), {_HIST_APPOINTMENT_COLUMNS} FROM appointment WHERE AptNum=%s",
        (settings.OD_USER_NUM, action, apt_num),
    )


def apply_completion_to_recall(cur, recall_num: int, completed_on: date, interval: int, roll_due: bool) -> date:
    """What OpenDental does to the recall when its procedure is completed.
    Returns the recall's resulting due date."""
    next_due = add_interval(completed_on, interval)
    if roll_due:
        cur.execute(
            "UPDATE recall SET DatePrevious=%s, DateDueCalc=%s, DateDue=%s, DateScheduled=%s WHERE RecallNum=%s",
            (completed_on, next_due, next_due, MIN_DATE, recall_num),
        )
        return next_due
    cur.execute("UPDATE recall SET DatePrevious=%s, DateScheduled=%s WHERE RecallNum=%s",
                (completed_on, MIN_DATE, recall_num))
    cur.execute("SELECT DateDue FROM recall WHERE RecallNum=%s", (recall_num,))
    return cur.fetchone()["DateDue"]


# --- cleanup ------------------------------------------------------------------------

def delete_appointment(cur, apt_num: int, pat_num: int) -> bool:
    """Deletes an appointment this run created, the way OpenDental's delete
    does, and marks its (run-created) procedures deleted."""
    cur.execute("SELECT PatNum FROM appointment WHERE AptNum=%s FOR UPDATE", (apt_num,))
    row = cur.fetchone()
    if not row or int(row["PatNum"]) != int(pat_num):
        return False
    _write_hist(cur, apt_num, HIST_ACTION_DELETED)
    cur.execute("UPDATE procedurelog SET ProcStatus=%s, AptNum=0 WHERE AptNum=%s AND PatNum=%s",
                (PROC_STATUS_DELETED, apt_num, pat_num))
    cur.execute("DELETE FROM apptfield WHERE AptNum=%s", (apt_num,))
    cur.execute("DELETE FROM appointment WHERE AptNum=%s AND PatNum=%s", (apt_num, pat_num))
    return True


def restore_recall(cur, snapshot: dict) -> None:
    sets = ", ".join(f"{c}=%s" for c in _RECALL_RESTORE_COLUMNS)
    cur.execute(f"UPDATE recall SET {sets} WHERE RecallNum=%s",
                [snapshot[c] for c in _RECALL_RESTORE_COLUMNS] + [snapshot["RecallNum"]])


def clear_recall_scheduled(cur, pat_num: int, recall_type_num: int) -> None:
    cur.execute("UPDATE recall SET DateScheduled=%s WHERE PatNum=%s AND RecallTypeNum=%s",
                (MIN_DATE, pat_num, recall_type_num))


def delete_recall(cur, recall_num: int, pat_num: int) -> None:
    cur.execute("DELETE FROM recall WHERE RecallNum=%s AND PatNum=%s", (recall_num, pat_num))
