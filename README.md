# Recall Status Automation

Checks that Adit shows the right **Automated Recall status** for OpenDental
patients. One run sets up five recall scenarios in OpenDental, waits for
Adit to sync, reads **Engage -> Reports -> Automated Recall**, and reports
PASS/FAIL per scenario. It then removes everything it created.

```
python runners/run_recall_status_check.py
```

## Scenarios

All dates are relative to the run date, so the check works on any day
(`config/scenarios.yaml`). The recall type is **ProphyRecall**. "Same recall
type" means the appointment carries that type's trigger procedures
(T1356 Exam + T3541 Prophy, Adult), which is how OpenDental links an
appointment to a recall.

| ID | Scenario | Patient (PatNum) | What's set up in OpenDental | Adit must show |
|---|---|---|---|---|
| S1 | Upcoming recall - not booked | Kaushal Recall (311) | Due in 30 days, no appointment | Unscheduled |
| S2 | Upcoming recall - appointment booked | Krutik Recall (312) | Due in 30 days, appointment booked in 20 days | Scheduled |
| S3 | Missed recall - not booked | Shreya Recall (313) | Was due 15 days ago, no appointment | Overdue + Unscheduled |
| S4 | Missed recall - appointment booked | Devarsh Recall (314) | Was due 15 days ago, appointment booked in 7 days | Overdue + Scheduled |
| S5 | Recall visit completed | Jay Recall (315) | Due on the 1st of the current month, appointment completed that day | Completed |

Status matching uses whole words and an exact set. "Unscheduled" never
counts as "Scheduled", and S2 fails if Adit also says "Overdue".

## What a run does

| Step | What happens | Code |
|---|---|---|
| 1. Setup | For each patient, in the OpenDental DB: create or reuse the ProphyRecall, set its due date, and add the appointment with the trigger procedures (scheduled = TP procedures and `recall.DateScheduled`; completed = appointment and procedures Complete, `DatePrevious` set, due date rolled forward by the interval as OpenDental does) | `recall_status/setup_and_cleanup.py`, `recall_status/opendental/db.py` |
| 2. Verify | Wait 5 min after the last OpenDental write (`RECALL_CHECK_SYNC_WAIT_SECONDS`) so Adit has synced, then log in to Adit and poll the Automated Recall report (`engage/report/recall/get`) until every patient shows the expected status (default: every 60s for up to 30 min, to allow for Adit's sync) | `recall_status/verify.py`, `recall_status/adit/` |
| 3. Report | Console summary and HTML report in `reports/output/` (`latest.html` is always the newest) | `recall_status/report.py` |
| 4. Publish | Report -> PDF (headless Edge/Chrome) -> Google Drive `Recall Report/<YYYY-MM Month>/Automated Recall Report <date>.pdf` -> Google Chat card with an **Open PDF report** button (a Chat webhook can't attach files). A second run the same day replaces that day's PDF as a new version, keeping the same link. Each step is skipped if its settings are missing, and never fails the run. Use `--no-publish` to skip it | `recall_status/publish/` |
| 5. Cleanup | Delete the run's appointments (writing a histappointment "Deleted" row so Adit sees the delete). **Recalls are kept** with the due date the run set, so they stay visible in OpenDental and Adit (`RECALL_CHECK_CLEANUP_RECALLS=true` deletes/restores them instead) | `recall_status/setup_and_cleanup.py` |

Exit code `0` = all scenarios passed, `1` = anything failed (usable as a Jenkins gate).

### Other modes

```
python runners/publish_report.py reports/output/recall_status_results_<stamp>.json   # re-send an earlier run
```

```
python runners/run_recall_status_check.py --setup-only     # set up OpenDental, stop - verify in Adit by hand
python runners/run_recall_status_check.py --cleanup-only   # undo the last --setup-only / --keep run
python runners/run_recall_status_check.py --keep           # full run, leave the data in OpenDental
```

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill it in: OpenDental MySQL, your Adit login, and (for publishing) `GCHAT_WEBHOOK_URL`, `GDRIVE_SERVICE_ACCOUNT_FILE`, `GDRIVE_FOLDER_ID` and `GDRIVE_SHARE_DOMAIN`, the same values Reminder-Sanity-Automation uses. `.env` is gitignored.

## How Adit is read

The check calls the Automated Recall report page's own list request:

```
GET https://engmodapi.adit.com/engage/report/recall/get?locationId=..&organizationId=..&month=September%202026
```

- The report lists recalls by **due-date month**. Each scenario is looked up
  in the month it's due, the month its due date moved to (completing a recall
  rolls it forward), and the month of its appointment.
- Rows are matched on `patient_ehr_id` (OpenDental PatNum) and
  `recall_type_ehr_key` (RecallTypeNum), not on names.
- `recall_status` uses abbreviations: `Unsched`, `Overdue & Unsched`, and
  presumably `Sched`, `Overdue & Sched` and `Completed`. The matcher maps them
  to the full words used in `scenarios.yaml`.

## Things to know

- **S5 is pinned to the 1st of the current month** (`due_on: month_start` / `appt_on: month_start`). On 5 Oct 2026, a recall due and completed on 30 Sep (the previous month) showed `Overdue & Unsched` in Adit, not `Completed`, even though Adit had the visit as the patient's last visit. Keeping S5 in the current month makes it test the normal Completed case on any run date.

- **PDF export on Edge 154.** Edge's `--headless=new` mode exits without writing a PDF on this machine. The exporter falls back to the older `--headless` mode and waits for the file, because Edge's launcher exits before its child process finishes writing.

- **OpenDental's tables are MyISAM.** There are no transactions, so every
  write is permanent immediately. Each row is recorded in
  `reports/output/last_run_state.json` as soon as it's created. A crashed run
  can always be undone with `--cleanup-only`, and a new run refuses to start
  while that file exists.
- **Pre-existing appointments.** If a test patient already has a scheduled
  appointment with the recall's trigger procedures, that scenario is refused
  instead of modified, because the old appointment would decide the status.
- **Deleted procedures stay.** Cleanup marks the run's procedures
  `ProcStatus=6` (Deleted), the same as OpenDental's own delete. It doesn't
  erase them.

## Tests

```
python -m unittest discover -s tests -t .
```

Pure unit tests (status matching, recall interval math, scenario config,
report row matching). They make no DB or Adit calls.
