"""Loads config/scenarios.yaml and turns each entry into concrete dates for
today's run. Pure logic - no DB or HTTP - so it is unit tested directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import yaml

APPOINTMENT_KINDS = ("none", "scheduled", "completed")
DATE_ANCHORS = ("month_start",)

# Appointments are booked at a fixed, office-hours time of day so they never
# land at midnight (Adit/OpenDental both show the time).
APPOINTMENT_TIME = time(10, 0)


@dataclass
class Scenario:
    id: str
    name: str
    first_name: str
    last_name: str
    pat_num: Optional[int]
    due_in_days: int
    appointment: str
    appt_in_days: Optional[int]
    expected_status: list[str]
    # Fixed-day alternatives to the *_in_days offsets ("month_start" = the
    # 1st of the run's month). Resolved into due_in_days/appt_in_days.
    due_on: Optional[str] = None
    appt_on: Optional[str] = None

    # Filled in during the run. set_due_date is the due date the scenario
    # wrote; due_date is where the recall ended up (completing the recall
    # procedure rolls it forward).
    set_due_date: Optional[date] = None
    due_date: Optional[date] = None
    appt_datetime: Optional[datetime] = None
    apt_num: Optional[int] = None
    recall_num: Optional[int] = None
    actual_status: list[str] = field(default_factory=list)
    adit_rows: list[dict] = field(default_factory=list)
    passed: Optional[bool] = None
    error: Optional[str] = None

    @property
    def patient_label(self) -> str:
        suffix = f" (PatNum {self.pat_num})" if self.pat_num else ""
        return f"{self.first_name} {self.last_name}{suffix}"


class ScenarioConfigError(ValueError):
    pass


def _validate(raw: dict, index: int) -> None:
    where = f"scenario #{index + 1} ({raw.get('id', '?')})"
    patient = raw.get("patient") or {}
    if not patient.get("pat_num") and (
        not patient.get("first_name") or not patient.get("last_name")
        or "TODO" in (patient.get("first_name"), patient.get("last_name"))
    ):
        raise ScenarioConfigError(f"{where}: set patient first_name/last_name (or pat_num) in scenarios.yaml")
    for key in ("due_on", "appt_on"):
        if raw.get(key) is not None and raw[key] not in DATE_ANCHORS:
            raise ScenarioConfigError(f"{where}: {key} must be one of {DATE_ANCHORS}, got {raw[key]!r}")
    if raw.get("due_in_days") is None and raw.get("due_on") is None:
        raise ScenarioConfigError(f"{where}: set due_in_days or due_on")
    kind = raw.get("appointment", "none")
    if kind not in APPOINTMENT_KINDS:
        raise ScenarioConfigError(f"{where}: appointment must be one of {APPOINTMENT_KINDS}, got {kind!r}")
    if kind != "none" and raw.get("appt_in_days") is None and raw.get("appt_on") is None:
        raise ScenarioConfigError(f"{where}: appt_in_days or appt_on is required when appointment={kind}")
    if kind == "scheduled" and raw.get("appt_on") is None and raw["appt_in_days"] < 0:
        raise ScenarioConfigError(f"{where}: a scheduled appointment must be today or later")
    if kind == "completed" and raw.get("appt_on") is None and raw["appt_in_days"] > 0:
        raise ScenarioConfigError(f"{where}: a completed appointment cannot be in the future")
    if not raw.get("expected_status"):
        raise ScenarioConfigError(f"{where}: expected_status is required")


def load_scenarios(path: Path) -> list[Scenario]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raws = data.get("scenarios") or []
    if not raws:
        raise ScenarioConfigError(f"No scenarios in {path}")
    scenarios = []
    for i, raw in enumerate(raws):
        _validate(raw, i)
        patient = raw["patient"]
        scenarios.append(Scenario(
            id=str(raw["id"]),
            name=raw.get("name", ""),
            first_name=patient.get("first_name") or "",
            last_name=patient.get("last_name") or "",
            pat_num=patient.get("pat_num"),
            due_in_days=int(raw.get("due_in_days") or 0),
            appointment=raw.get("appointment", "none"),
            appt_in_days=raw.get("appt_in_days"),
            expected_status=[str(s) for s in raw["expected_status"]],
            due_on=raw.get("due_on"),
            appt_on=raw.get("appt_on"),
        ))
    pat_nums = [s.pat_num for s in scenarios if s.pat_num]
    if len(pat_nums) != len(set(pat_nums)):
        raise ScenarioConfigError("Each scenario needs a different patient - one recall per patient is changed")
    return scenarios


def _anchor(name: str, today: date) -> date:
    if name == "month_start":
        return today.replace(day=1)
    raise ScenarioConfigError(f"Unknown date anchor {name!r}")


def resolve_dates(scenario: Scenario, today: date) -> None:
    # Anchored dates are turned into day offsets for this run, so everything
    # downstream (descriptions, "N days ago") works the same either way.
    if scenario.due_on:
        scenario.due_in_days = (_anchor(scenario.due_on, today) - today).days
    if scenario.appt_on:
        scenario.appt_in_days = (_anchor(scenario.appt_on, today) - today).days
    scenario.set_due_date = scenario.due_date = today + timedelta(days=scenario.due_in_days)
    if scenario.appointment != "none":
        day = today + timedelta(days=scenario.appt_in_days)
        scenario.appt_datetime = datetime.combine(day, APPOINTMENT_TIME)
    # Adit only shows "Completed" when the due date and the completed
    # appointment are in the same month - relative offsets can cross a month
    # boundary on some run dates, so this is checked on the real dates.
    if scenario.appointment == "completed" and (
        (scenario.due_date.year, scenario.due_date.month) != (day.year, day.month)
    ):
        raise ScenarioConfigError(
            f"{scenario.id}: completed appointment {day} is not in the due date's month ({scenario.due_date}) "
            "on this run date - adjust due_in_days/appt_in_days"
        )
