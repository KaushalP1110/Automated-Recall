"""Plain-English descriptions of a scenario for the report: what was set up
in OpenDental (with the real dates of this run) and why that should give the
expected Adit status."""

from __future__ import annotations

from datetime import date

from recall_status.scenarios import Scenario


def _d(day: date) -> str:
    return day.strftime("%d %b %Y").lstrip("0")


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def setup_text(s: Scenario) -> str:
    """e.g. 'Recall was due on 15 Sep 2026 (15 days ago) and no appointment is booked.'"""
    due = s.set_due_date or s.due_date
    if due is None:
        return ""
    if s.due_in_days > 0:
        due_part = f"Recall is due on {_d(due)} (in {_days(s.due_in_days)})"
    elif s.due_in_days == 0:
        due_part = f"Recall is due today ({_d(due)})"
    else:
        due_part = f"Recall was due on {_d(due)} ({_days(-s.due_in_days)} ago)"

    if s.appointment == "none" or not s.appt_datetime:
        appt_part = "no appointment is booked"
    elif s.appointment == "scheduled":
        appt_part = f"a Prophy recall appointment is booked for {_d(s.appt_datetime.date())}"
    else:
        appt_part = f"the Prophy recall appointment on {_d(s.appt_datetime.date())} is completed"
    return f"{due_part}, and {appt_part}."


def rule_text(s: Scenario) -> str:
    """Why this setup should show the expected status in Adit."""
    overdue = s.due_in_days < 0
    if s.appointment == "completed":
        return "The recall appointment was completed in the same month the recall was due, so Adit should show Completed."
    if s.appointment == "scheduled":
        if overdue:
            return "The due date has passed, but an appointment is booked, so Adit should show Overdue and Scheduled."
        return "An appointment is booked for this recall, so Adit should show Scheduled."
    if overdue:
        return "The due date has passed and nothing is booked, so Adit should show Overdue and Unscheduled."
    return "The due date hasn't passed yet and nothing is booked, so Adit should show Unscheduled."


def short_setup(s: Scenario) -> str:
    """One compact line for Chat, e.g. 'Due 10 Sep 2026 (20 days ago) · Appointment booked for 10 Oct 2026'."""
    due = s.set_due_date or s.due_date
    if due is None:
        return ""
    if s.due_in_days > 0:
        when = f"in {_days(s.due_in_days)}"
    elif s.due_in_days == 0:
        when = "today"
    else:
        when = f"{_days(-s.due_in_days)} ago"
    if s.appointment == "none" or not s.appt_datetime:
        appt = "No appointment"
    elif s.appointment == "scheduled":
        appt = f"Appointment booked for {_d(s.appt_datetime.date())}"
    else:
        appt = f"Appointment completed on {_d(s.appt_datetime.date())}"
    return f"Due {_d(due)} ({when}) · {appt}"
