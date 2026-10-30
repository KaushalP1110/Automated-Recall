"""Pure unit tests - no OpenDental, Adit or network calls."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from config import settings
from recall_status.adit.recall_report_client import RecallReportClient, month_label
from recall_status.opendental.recall_interval import add_interval, unpack
from recall_status.scenarios import ScenarioConfigError, load_scenarios, resolve_dates
from recall_status.verify import scenario_months
from recall_status.status_matcher import status_words, statuses_match


class StatusMatcherTest(unittest.TestCase):
    def test_unscheduled_is_not_scheduled(self):
        self.assertEqual(status_words(["Unscheduled"]), {"unscheduled"})
        self.assertFalse(statuses_match(["Scheduled"], ["Unscheduled"]))

    def test_combined_text_matches_two_labels(self):
        self.assertTrue(statuses_match(["Overdue", "Unscheduled"], ["Overdue - Unscheduled"]))
        self.assertTrue(statuses_match(["Overdue", "Scheduled"], ["overdue", "SCHEDULED"]))

    def test_extra_status_fails(self):
        self.assertFalse(statuses_match(["Scheduled"], ["Overdue & Scheduled"]))
        self.assertFalse(statuses_match(["Overdue", "Scheduled"], ["Scheduled"]))

    def test_adit_abbreviations(self):
        self.assertTrue(statuses_match(["Unscheduled"], ["Unsched"]))
        self.assertTrue(statuses_match(["Overdue", "Unscheduled"], ["Overdue & Unsched"]))
        self.assertTrue(statuses_match(["Overdue", "Scheduled"], ["Overdue & Sched"]))
        self.assertFalse(statuses_match(["Scheduled"], ["Unsched"]))
        self.assertFalse(statuses_match(["Unscheduled"], ["Overdue & Unsched"]))

    def test_nothing_shown_fails(self):
        self.assertFalse(statuses_match(["Completed"], []))


class RecallIntervalTest(unittest.TestCase):
    def test_six_months(self):
        self.assertEqual(unpack(393216), (0, 6, 0, 0))
        self.assertEqual(add_interval(date(2026, 9, 30), 393216), date(2027, 3, 30))

    def test_month_end_clamps(self):
        self.assertEqual(add_interval(date(2026, 8, 31), 6 << 16), date(2027, 2, 28))

    def test_weeks_and_days(self):
        self.assertEqual(add_interval(date(2026, 9, 30), (1 << 8) | 3), date(2026, 10, 10))


class ScenariosTest(unittest.TestCase):
    def test_project_scenarios_load_and_resolve(self):
        scenarios = load_scenarios(settings.SCENARIOS_FILE)
        self.assertEqual([s.id for s in scenarios], ["S1", "S2", "S3", "S4", "S5"])
        today = date(2026, 9, 30)
        for s in scenarios:
            resolve_dates(s, today)
        s1, s2, s3, s4, s5 = scenarios
        self.assertGreaterEqual(s1.due_date, today)
        self.assertIsNone(s1.appt_datetime)
        self.assertGreater(s2.appt_datetime.date(), today)
        self.assertLess(s3.due_date, today)
        self.assertLess(s4.due_date, today)
        self.assertGreater(s4.appt_datetime.date(), today)
        self.assertLessEqual(s5.appt_datetime.date(), today)
        self.assertEqual((s5.appt_datetime.year, s5.appt_datetime.month), (s5.due_date.year, s5.due_date.month))

    def _load(self, body):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.yaml"
            path.write_text(body, encoding="utf-8")
            return load_scenarios(path)

    def test_placeholder_patient_rejected(self):
        with self.assertRaises(ScenarioConfigError):
            self._load('scenarios:\n  - {id: X, patient: {first_name: TODO, last_name: TODO},'
                       ' due_in_days: 1, appointment: none, expected_status: [Unscheduled]}\n')

    def test_future_completed_appointment_rejected(self):
        with self.assertRaises(ScenarioConfigError):
            self._load('scenarios:\n  - {id: X, patient: {pat_num: 1}, due_in_days: 1, appointment: completed,'
                       ' appt_in_days: 3, expected_status: [Completed]}\n')

    def test_duplicate_patient_rejected(self):
        row = ('  - {id: X, patient: {pat_num: 1}, due_in_days: 1, appointment: none,'
               ' expected_status: [Unscheduled]}\n')
        with self.assertRaises(ScenarioConfigError):
            self._load("scenarios:\n" + row + row)


class _FakeClient(RecallReportClient):
    def __init__(self, months):
        self.months, self.calls = months, []

    def get_month(self, month):
        self.calls.append(month)
        return self.months.get(month, [])


class RecallReportTest(unittest.TestCase):
    ROW = {"patient_ehr_id": "313", "recall_type_ehr_key": "1", "recall_status": "Overdue & Unsched"}

    def test_month_label(self):
        self.assertEqual(month_label(date(2026, 9, 15)), "September 2026")

    def test_matches_patnum_and_recall_type_only(self):
        client = _FakeClient({"September 2026": [
            self.ROW,
            {**self.ROW, "recall_type_ehr_key": "7"},
            {**self.ROW, "patient_ehr_id": "31"},
        ]})
        rows = client.find_rows(313, 1, ["September 2026"])
        self.assertEqual([r["recall_type_ehr_key"] for r in rows], ["1"])

    def test_month_fetched_once_per_cache(self):
        client = _FakeClient({"September 2026": [self.ROW]})
        cache = {}
        client.find_rows(313, 1, ["September 2026"], cache)
        client.find_rows(314, 1, ["September 2026", "September 2026"], cache)
        self.assertEqual(client.calls, ["September 2026"])

    def test_completed_checked_in_due_month_only(self):
        s5 = load_scenarios(settings.SCENARIOS_FILE)[4]
        resolve_dates(s5, date(2026, 9, 30))
        s5.due_date = date(2027, 3, 30)  # even if the due date was rolled forward
        self.assertEqual(scenario_months(s5), ["September 2026"])

    def test_scheduled_checked_in_due_and_appointment_months(self):
        s4 = load_scenarios(settings.SCENARIOS_FILE)[3]
        resolve_dates(s4, date(2026, 9, 30))
        self.assertEqual(scenario_months(s4), ["September 2026", "October 2026"])

    def test_completed_must_share_due_month(self):
        s5 = load_scenarios(settings.SCENARIOS_FILE)[4]
        s5.due_on = s5.appt_on = None
        s5.due_in_days, s5.appt_in_days = 1, 0  # due Oct 1, completed Sep 30
        with self.assertRaises(ScenarioConfigError):
            resolve_dates(s5, date(2026, 9, 30))


class DescribeTest(unittest.TestCase):
    def setUp(self):
        from recall_status.describe import rule_text, setup_text
        self.setup_text, self.rule_text = setup_text, rule_text
        self.scs = load_scenarios(settings.SCENARIOS_FILE)
        for s in self.scs:
            resolve_dates(s, date(2026, 9, 30))

    def test_setup_sentences(self):
        from recall_status.scenarios import Scenario
        def make(due, kind="none", appt=None):
            s = Scenario(id="X", name="", first_name="A", last_name="B", pat_num=1, due_in_days=due,
                         appointment=kind, appt_in_days=appt, expected_status=["Unscheduled"])
            resolve_dates(s, date(2026, 9, 30))
            return s
        self.assertEqual(self.setup_text(make(30)), "Recall is due on 30 Oct 2026 (in 30 days), and no appointment is booked.")
        self.assertIn("booked for 20 Oct 2026", self.setup_text(make(30, "scheduled", 20)))
        self.assertEqual(self.setup_text(make(-15)), "Recall was due on 15 Sep 2026 (15 days ago), and no appointment is booked.")
        today = self.setup_text(make(0, "completed", 0))
        self.assertIn("Recall is due today (30 Sep 2026)", today)
        self.assertIn("is completed", today)
        self.assertIn("(1 day ago)", self.setup_text(make(-1)))

    def test_rules_name_the_expected_status(self):
        for s in self.scs:
            rule = self.rule_text(s)
            for label in s.expected_status:
                self.assertIn(label, rule)


class GChatCardTest(unittest.TestCase):
    def test_card_lists_every_scenario_and_pdf_button(self):
        from recall_status.publish.gchat_notifier import build_card
        scs = load_scenarios(settings.SCENARIOS_FILE)
        for s in scs:
            resolve_dates(s, date(2026, 9, 30))
            s.passed, s.actual_status = True, s.expected_status
        scs[4].passed, scs[4].actual_status, scs[4].error = False, [], "not listed"
        card = build_card(scs, datetime(2026, 9, 30, 12, 35), "https://drive.example/pdf")["cardsV2"][0]["card"]
        text = str(card)
        self.assertIn("FAIL", text)
        self.assertIn("4/5", text)
        for s in scs:
            self.assertIn(f"{s.id} · {s.name}", text)
        self.assertIn("Working fine", text)
        from recall_status.describe import short_setup
        for s in scs:
            self.assertIn(short_setup(s), text)
        self.assertIn("Needs attention", text)
        self.assertIn("Jay Recall", text)
        self.assertIn("https://drive.example/pdf", text)


class MonthStartAnchorTest(unittest.TestCase):
    def _s5(self, today):
        s5 = load_scenarios(settings.SCENARIOS_FILE)[4]
        resolve_dates(s5, today)
        return s5

    def test_s5_is_first_of_current_month(self):
        for today in (date(2026, 10, 5), date(2026, 10, 31), date(2027, 1, 2)):
            s5 = self._s5(today)
            self.assertEqual(s5.due_date, today.replace(day=1))
            self.assertEqual(s5.appt_datetime.date(), today.replace(day=1))
            self.assertEqual(s5.due_in_days, -(today.day - 1))

    def test_s5_on_the_first_is_today(self):
        s5 = self._s5(date(2026, 11, 1))
        self.assertEqual(s5.due_in_days, 0)
        self.assertEqual(s5.appt_datetime.date(), date(2026, 11, 1))

    def test_bad_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.yaml"
            path.write_text("scenarios:\n  - {id: X, patient: {pat_num: 1}, due_on: yesterday, appointment: none,"
                            " expected_status: [Unscheduled]}\n", encoding="utf-8")
            with self.assertRaises(ScenarioConfigError):
                load_scenarios(path)


if __name__ == "__main__":
    unittest.main()
