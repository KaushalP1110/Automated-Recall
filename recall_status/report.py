"""Console summary and HTML report for a run.

The HTML report is a single file (inline CSS/SVG, a few lines of JS for the
filter tabs) so it can be attached, uploaded or opened offline. It follows
the viewer's light/dark preference and prints cleanly.

Re-render a report from a saved results file:

    python -m recall_status.report reports/output/recall_status_results_<stamp>.json
"""

from __future__ import annotations

import html
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config import settings
from recall_status.describe import rule_text, setup_text
from recall_status.scenarios import Scenario
from recall_status.status_matcher import status_words


def _result(s: Scenario) -> str:
    if s.passed is True:
        return "PASS"
    if s.passed is False:
        return "FAIL"
    return "NOT VERIFIED"


def print_summary(scenarios: list[Scenario]) -> None:
    print()
    print("=" * 100)
    print("AUTOMATED RECALL STATUS CHECK")
    print("=" * 100)
    for s in scenarios:
        appt = f"{s.appointment} {s.appt_datetime:%Y-%m-%d}" if s.appt_datetime else s.appointment
        print(f"{s.id:<3} {_result(s):<13} {s.name}  -  {s.patient_label}")
        print(f"    {setup_text(s)}")
        print(f"    expected {s.expected_status}  actual {s.actual_status or '-'}")
        if s.error:
            print(f"    {s.error}")
    print("=" * 100)


# --- HTML ------------------------------------------------------------------------

_CSS = """
:root{
  --bg:#f3f5f9;--surface:#ffffff;--surface-2:#f7f8fb;--text:#14213d;--muted:#5d6b82;--line:#e3e8f0;
  --hero-a:#0b2440;--hero-b:#123a63;--hero-c:#1c5a8f;--hero-text:#ffffff;--hero-muted:#b8c7da;
  --brand:#f7941d;--brand-2:#29abe2;
  --pass:#12a150;--pass-soft:#e3f7ec;--pass-ink:#0b7a3b;
  --fail:#e5484d;--fail-soft:#fdecec;--fail-ink:#b4232a;
  --warn:#d68b00;--warn-soft:#fff5dc;--warn-ink:#8a5a00;
  --unsched:#5d6b82;--unsched-soft:#edf0f5;
  --sched:#1f6feb;--sched-soft:#e5efff;
  --overdue:#e2620a;--overdue-soft:#fff0e3;
  --completed:#12a150;--completed-soft:#e3f7ec;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.06);
  --shadow-lg:0 12px 40px rgba(11,36,64,.18);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0a0f1a;--surface:#121a28;--surface-2:#172131;--text:#e7edf6;--muted:#93a1b7;--line:#233046;
  --hero-a:#07172b;--hero-b:#0d2946;--hero-c:#134373;--hero-muted:#9fb3cc;
  --pass:#2fbf6c;--pass-soft:#0f2a1c;--pass-ink:#5ad48f;
  --fail:#f0555a;--fail-soft:#2e1416;--fail-ink:#ff8a8e;
  --warn:#e6a23c;--warn-soft:#2c2210;--warn-ink:#f2c46d;
  --unsched:#a3b0c4;--unsched-soft:#1f2a3b;--sched:#5b9dff;--sched-soft:#13284a;
  --overdue:#ff8f45;--overdue-soft:#35200f;--completed:#2fbf6c;--completed-soft:#0f2a1c;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);--shadow-lg:0 12px 40px rgba(0,0,0,.45);
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.55 "Inter","Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
svg{display:block}
.hero{position:relative;overflow:hidden;color:var(--hero-text);
  background:radial-gradient(1200px 400px at 85% -20%,var(--hero-c),transparent 60%),
             linear-gradient(135deg,var(--hero-a),var(--hero-b));padding:40px 0 96px}
.hero::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.07;
  background-image:radial-gradient(#fff 1px,transparent 1px);background-size:22px 22px}
.wrap{max-width:1200px;margin:0 auto;padding:0 20px;position:relative;z-index:1}
.hero-grid{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:28px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;color:var(--hero-muted)}
.eyebrow .dot{width:8px;height:8px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 4px rgba(247,148,29,.2)}
h1{font-size:34px;line-height:1.15;margin:10px 0 14px;font-weight:750;letter-spacing:-.02em}
.pills{display:flex;flex-wrap:wrap;gap:8px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;font-size:13px;
  background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.14);color:#fff;backdrop-filter:blur(4px)}
.pill svg{width:14px;height:14px;opacity:.8}
.score{display:flex;align-items:center;gap:22px;background:rgba(255,255,255,.07);
  border:1px solid rgba(255,255,255,.14);border-radius:20px;padding:18px 24px}
.ring{position:relative;width:118px;height:118px}
.ring .val{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.ring .big{font-size:28px;font-weight:750;line-height:1}
.ring .lbl{font-size:11px;color:var(--hero-muted);text-transform:uppercase;letter-spacing:.08em;margin-top:4px}
.verdict{display:inline-flex;align-items:center;gap:8px;font-weight:750;font-size:18px;letter-spacing:.04em;
  padding:8px 16px;border-radius:12px}
.verdict svg{width:20px;height:20px}
.verdict.pass{background:var(--pass);color:#fff}.verdict.fail{background:var(--fail);color:#fff}
.score .caption{color:var(--hero-muted);font-size:13px;margin-top:8px;max-width:220px}
main{margin-top:-64px;position:relative;z-index:2;padding-bottom:48px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow);
  display:flex;align-items:center;gap:14px}
.stat .ic{flex:none;width:44px;height:44px;border-radius:12px;display:grid;place-items:center}
.stat .ic svg{width:22px;height:22px}
.stat .n{font-size:26px;font-weight:750;line-height:1.1;font-variant-numeric:tabular-nums}
.stat .l{color:var(--muted);font-size:13px}
.ic.total{background:var(--sched-soft);color:var(--sched)}.ic.pass{background:var(--pass-soft);color:var(--pass)}
.ic.fail{background:var(--fail-soft);color:var(--fail)}.ic.time{background:var(--warn-soft);color:var(--warn)}
.section-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin:36px 0 16px}
h2{font-size:20px;margin:0;letter-spacing:-.01em}
.tabs{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:4px;gap:2px}
.tab{border:0;background:transparent;color:var(--muted);font:inherit;font-weight:600;font-size:13px;padding:7px 14px;
  border-radius:9px;cursor:pointer}
.tab:hover{color:var(--text)}
.tab[aria-pressed="true"]{background:var(--text);color:var(--surface)}
.tab .c{opacity:.7;margin-left:4px;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:18px}
.card{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:18px;
  box-shadow:var(--shadow);overflow:hidden;display:flex;flex-direction:column;transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg)}
.card::before{content:"";position:absolute;left:0;right:0;top:0;height:4px;background:var(--line)}
.card.pass::before{background:linear-gradient(90deg,var(--pass),#6fd99a)}
.card.fail::before{background:linear-gradient(90deg,var(--fail),#ff9a8a)}
.card.nv::before{background:linear-gradient(90deg,var(--warn),#ffd27a)}
.card-body{padding:20px 20px 18px;display:flex;flex-direction:column;gap:16px;flex:1}
.card-top{display:flex;align-items:flex-start;gap:12px}
.sid{flex:none;width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-weight:750;
  background:var(--surface-2);border:1px solid var(--line);color:var(--text)}
.title{flex:1;min-width:0}
.title h3{font-size:15px;line-height:1.35;margin:0 0 4px;font-weight:650}
.patient{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}
.avatar{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:10px;font-weight:700;
  color:#fff;background:linear-gradient(135deg,var(--brand-2),var(--sched))}
.badge{flex:none;display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:999px;font-size:12px;
  font-weight:750;letter-spacing:.03em}
.badge svg{width:14px;height:14px}
.badge.pass{background:var(--pass-soft);color:var(--pass-ink)}.badge.fail{background:var(--fail-soft);color:var(--fail-ink)}
.badge.nv{background:var(--warn-soft);color:var(--warn-ink)}
.setup,.rule{margin:0;font-size:13.5px;line-height:1.55}
.setup{color:var(--text)}
.rule{color:var(--muted);font-size:13px}
.setup .lbl,.rule .lbl{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 7px;border-radius:6px;margin-right:8px;vertical-align:1px}
.setup .lbl{background:var(--sched-soft);color:var(--sched)}
.rule .lbl{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.fact{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.fact .k{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:.06em}
.fact .k svg{width:13px;height:13px}
.fact .v{font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.fact .s{color:var(--muted);font-size:12px}
.fact .s.warn{color:var(--overdue)}
.compare{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;
  border:1px dashed var(--line);border-radius:14px;padding:12px}
.compare .k{color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.compare .mid{width:30px;height:30px;border-radius:50%;display:grid;place-items:center}
.compare .mid svg{width:16px;height:16px}
.compare .mid.pass{background:var(--pass-soft);color:var(--pass)}.compare .mid.fail{background:var(--fail-soft);color:var(--fail)}
.compare .mid.nv{background:var(--warn-soft);color:var(--warn)}
.compare .right{text-align:right}.compare .right .chips{justify-content:flex-end}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:650;white-space:nowrap}
.chip::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.chip.unscheduled{color:var(--unsched);background:var(--unsched-soft)}
.chip.scheduled{color:var(--sched);background:var(--sched-soft)}
.chip.overdue{color:var(--overdue);background:var(--overdue-soft)}
.chip.completed{color:var(--completed);background:var(--completed-soft)}
.chip.raw{color:var(--text);background:var(--surface-2);border:1px solid var(--line)}
.chip.raw::before{display:none}
.none{color:var(--muted);font-style:italic;font-size:13px}
.adit-text{color:var(--muted);font-size:11px;margin-top:5px}
.note{display:flex;gap:10px;border-radius:12px;padding:12px 14px;font-size:13px;background:var(--fail-soft);color:var(--text)}
.note svg{flex:none;width:18px;height:18px;color:var(--fail);margin-top:1px}
.note b{display:block;color:var(--fail-ink);font-size:12px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}
.note.nv{background:var(--warn-soft)}.note.nv svg{color:var(--warn)}.note.nv b{color:var(--warn-ink)}
.info{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;margin-top:36px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:var(--shadow)}
.panel h2{font-size:15px;margin-bottom:14px}
.legend{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.legend li{display:grid;grid-template-columns:118px 1fr;align-items:center;gap:10px;font-size:13px;color:var(--muted)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:8px 16px;margin:0;font-size:13px}
.kv dt{color:var(--muted)}.kv dd{margin:0;font-weight:600}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:14px}
.flow span{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:4px 10px;font-size:12px;font-weight:600}
.flow i{color:var(--muted);font-style:normal}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:36px}
.card[hidden]{display:none}
@media (max-width:520px){
  h1{font-size:26px}.grid{grid-template-columns:1fr}.facts{grid-template-columns:1fr}
  .score{width:100%;justify-content:space-between}.legend li{grid-template-columns:1fr}
}
@page{size:A4;margin:10mm}
@media print{
  body{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .wrap{padding:0 8px}
  .hero{padding:22px 0 70px}.hero-grid{flex-wrap:nowrap;gap:16px}
  h1{font-size:26px;margin:8px 0 10px}.pill{font-size:12px;padding:4px 10px}
  .score{padding:12px 16px;gap:14px}.ring,.ring svg{width:96px;height:96px}.ring .big{font-size:22px}
  .verdict{font-size:15px;padding:6px 12px}.score .caption{font-size:12px;max-width:170px}
  main{margin-top:-54px}
  .stats{grid-template-columns:repeat(4,1fr);gap:10px}.stat{padding:12px;gap:10px}
  .stat .ic{width:36px;height:36px}.stat .n{font-size:20px}
  .section-head{margin:22px 0 12px;break-after:avoid}.tabs{display:none}
  .grid{gap:12px}.card-body{padding:16px;gap:12px}
  .card,.panel,.stat{break-inside:avoid;box-shadow:none}.card:hover{transform:none}
  .info{margin-top:18px}
}
"""

_ICONS = {
    "check": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    "x": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    "clock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
    "pin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/></svg>',
    "db": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="6" rx="7" ry="2.8"/><path d="M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8"/></svg>',
    "list": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
    "tooth": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 5.5C10 4 6 3.5 5 6.5c-1 3 .5 5 1 7.5.4 2.3.8 6 2.5 6 1.5 0 1.6-4.5 3.5-4.5s2 4.5 3.5 4.5c1.7 0 2.1-3.7 2.5-6 .5-2.5 2-4.5 1-7.5-1-3-5-2.5-7-1z"/></svg>',
    "alert": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/></svg>',
}


def _chips(labels: list[str]) -> str:
    """Status texts as coloured chips, one per known status word; anything
    Adit returned that isn't a known word is shown as-is."""
    out = []
    for text in labels:
        words = status_words([text])
        if not words:
            out.append(f"<span class='chip raw'>{html.escape(text)}</span>")
            continue
        for word in ("overdue", "unscheduled", "scheduled", "completed"):
            if word in words:
                out.append(f"<span class='chip {word}'>{word.capitalize()}</span>")
    return f"<div class='chips'>{''.join(out)}</div>" if out else "<span class='none'>Not listed</span>"


def _initials(s: Scenario) -> str:
    return html.escape(((s.first_name[:1] or "?") + (s.last_name[:1] or "")).upper())


def _due_fact(s: Scenario) -> str:
    set_due = s.set_due_date or s.due_date
    value = f"{set_due:%d %b %Y}" if set_due else "-"
    sub = ""
    if s.due_date and set_due and s.due_date != set_due:
        sub = f"<div class='s warn'>Now {s.due_date:%d %b %Y} in OpenDental</div>"
    elif s.due_in_days < 0:
        sub = f"<div class='s warn'>{-s.due_in_days} days past due</div>"
    elif s.due_in_days > 0:
        sub = f"<div class='s'>in {s.due_in_days} days</div>"
    else:
        sub = "<div class='s'>due today</div>"
    return (f"<div class='fact'><div class='k'>{_ICONS['calendar']}Recall due</div>"
            f"<div class='v'>{value}</div>{sub}</div>")


def _appt_fact(s: Scenario) -> str:
    if not s.appt_datetime:
        return (f"<div class='fact'><div class='k'>{_ICONS['clock']}Appointment</div>"
                f"<div class='v'>None</div><div class='s'>not booked</div></div>")
    kind = "Completed" if s.appointment == "completed" else "Scheduled"
    apt = f" &middot; AptNum {s.apt_num}" if s.apt_num else ""
    return (f"<div class='fact'><div class='k'>{_ICONS['clock']}Appointment</div>"
            f"<div class='v'>{s.appt_datetime:%d %b %Y}</div><div class='s'>{kind} {s.appt_datetime:%H:%M}{apt}</div></div>")


def _card(s: Scenario) -> str:
    result = _result(s)
    css = {"PASS": "pass", "FAIL": "fail"}.get(result, "nv")
    icon = {"pass": _ICONS["check"], "fail": _ICONS["x"]}.get(css, _ICONS["alert"])
    raw = (f"<div class='adit-text'>&ldquo;{html.escape(' | '.join(s.actual_status))}&rdquo;</div>"
           if s.actual_status else "")
    note = ""
    if s.error:
        label = "Why it failed" if result == "FAIL" else "Note"
        note = f"<div class='note {css}'>{_ICONS['alert']}<div><b>{label}</b>{html.escape(s.error)}</div></div>"
    return f"""
<article class="card {css}" data-result="{css}">
  <div class="card-body">
    <div class="card-top">
      <div class="sid">{html.escape(s.id)}</div>
      <div class="title"><h3>{html.escape(s.name)}</h3>
        <div class="patient"><span class="avatar">{_initials(s)}</span>{html.escape(f'{s.first_name} {s.last_name}')}
        &middot; PatNum {s.pat_num}</div></div>
      <span class="badge {css}">{icon}{result}</span>
    </div>
    <p class="setup"><span class="lbl">In OpenDental</span>{html.escape(setup_text(s))}</p>
    <div class="facts">{_due_fact(s)}{_appt_fact(s)}</div>
    <div class="compare">
      <div><div class="k">Expected</div>{_chips(s.expected_status)}</div>
      <div class="mid {css}">{icon}</div>
      <div class="right"><div class="k">Adit shows</div>{_chips(s.actual_status)}{raw}</div>
    </div>
    <p class="rule"><span class="lbl">Why</span>{html.escape(rule_text(s))}</p>
    {note}
  </div>
</article>"""


def _ring(passed: int, total: int) -> str:
    r, c = 50, 2 * 3.14159 * 50
    frac = passed / total if total else 0
    colour = "var(--pass)" if passed == total else ("var(--brand)" if passed else "var(--fail)")
    return f"""<div class="ring"><svg viewBox="0 0 120 120" width="118" height="118">
  <circle cx="60" cy="60" r="{r}" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="11"/>
  <circle cx="60" cy="60" r="{r}" fill="none" stroke="{colour}" stroke-width="11" stroke-linecap="round"
    stroke-dasharray="{c * frac:.1f} {c:.1f}" transform="rotate(-90 60 60)"/></svg>
  <div class="val"><div class="big">{passed}/{total}</div><div class="lbl">passed</div></div></div>"""


def render_html(scenarios: list[Scenario], run_at: datetime) -> str:
    total = len(scenarios)
    passed = sum(1 for s in scenarios if s.passed is True)
    failed = sum(1 for s in scenarios if s.passed is False)
    not_verified = total - passed - failed
    overall = "PASS" if passed == total else "FAIL"
    verdict_icon = _ICONS["check"] if overall == "PASS" else _ICONS["x"]
    caption = ("Every scenario shows the expected status in Adit." if overall == "PASS" else
               f"{failed + not_verified} of {total} scenario{'s' if total != 1 else ''} did not show the expected status.")

    stats = [
        ("total", _ICONS["list"], total, "Scenarios"),
        ("pass", _ICONS["check"], passed, "Passed"),
        ("fail", _ICONS["x"], failed, "Failed"),
        ("time", _ICONS["clock"], f"{settings.SYNC_WAIT_SECONDS // 60} min", "Adit sync wait"),
    ]
    stats_html = "".join(f"<div class='stat'><div class='ic {c}'>{i}</div><div><div class='n'>{n}</div>"
                         f"<div class='l'>{l}</div></div></div>" for c, i, n, l in stats)
    tabs = [("all", "All", total), ("pass", "Passed", passed), ("fail", "Failed", failed)]
    if not_verified:
        tabs.append(("nv", "Not verified", not_verified))
    tabs_html = "".join(f"<button class='tab' data-filter='{k}' aria-pressed='{'true' if k == 'all' else 'false'}'>"
                        f"{label}<span class='c'>{n}</span></button>" for k, label, n in tabs)

    legend = "".join(f"<li><span><span class='chip {w}'>{w.capitalize()}</span></span>{html.escape(d)}</li>" for w, d in (
        ("unscheduled", "Due date today or later, no recall appointment booked"),
        ("scheduled", "Appointment booked with the recall type's procedures"),
        ("overdue", "Due date has passed (shown with Scheduled / Unscheduled)"),
        ("completed", "Due date and completed appointment in the same month"),
    ))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automated Recall Status Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700;750&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>
<header class="hero"><div class="wrap"><div class="hero-grid">
  <div>
    <div class="eyebrow"><span class="dot"></span>QA automation &middot; OpenDental &rarr; Adit</div>
    <h1>Automated Recall Status Report</h1>
    <div class="pills">
      <span class="pill">{_ICONS['calendar']}{run_at:%d %b %Y, %H:%M}</span>
      <span class="pill">{_ICONS['pin']}{html.escape(settings.ADIT_LOCATION_NAME)}</span>
      <span class="pill">{_ICONS['db']}OpenDental &middot; {html.escape(settings.OD_DB_NAME)}</span>
      <span class="pill">{_ICONS['tooth']}ProphyRecall</span>
    </div>
  </div>
  <div class="score">{_ring(passed, total)}
    <div><div class="verdict {overall.lower()}">{verdict_icon}{overall}</div><div class="caption">{caption}</div></div>
  </div>
</div></div></header>

<main><div class="wrap">
  <section class="stats">{stats_html}</section>

  <div class="section-head"><h2>Scenarios</h2><div class="tabs" role="group" aria-label="Filter scenarios">{tabs_html}</div></div>
  <section class="grid" id="cards">{''.join(_card(s) for s in scenarios)}</section>

  <section class="info">
    <div class="panel"><h2>What each status means</h2><ul class="legend">{legend}</ul></div>
    <div class="panel"><h2>How this was checked</h2>
      <dl class="kv">
        <dt>Adit report</dt><dd>Engage &rarr; Reports &rarr; Automated Recall</dd>
        <dt>Matched on</dt><dd>PatNum + recall type, in the due date's month</dd>
        <dt>Sync wait</dt><dd>{settings.SYNC_WAIT_SECONDS // 60} min after each OpenDental change</dd>
        <dt>Polling</dt><dd>every {settings.POLL_INTERVAL_SECONDS}s, up to {settings.POLL_TIMEOUT_SECONDS // 60} min</dd>
      </dl>
      <div class="flow"><span>Set recall &amp; appointment in OpenDental</span><i>&rarr;</i><span>Wait for sync</span>
        <i>&rarr;</i><span>Read Adit report</span><i>&rarr;</i><span>Compare</span></div>
    </div>
  </section>
  <footer>Generated by Recall-Status-Automation &middot; {run_at:%d %b %Y %H:%M:%S}</footer>
</div></main>
<script>
document.querySelectorAll('.tab').forEach(function(t){{t.addEventListener('click',function(){{
  var f=t.dataset.filter;
  document.querySelectorAll('.tab').forEach(function(b){{b.setAttribute('aria-pressed',b===t?'true':'false')}});
  document.querySelectorAll('#cards .card').forEach(function(c){{c.hidden=!(f==='all'||c.dataset.result===f)}});
}})}});
</script>
</body></html>"""


def write_html(scenarios: list[Scenario], reports_dir: Path, run_at: Optional[datetime] = None) -> Path:
    run_at = run_at or datetime.now()
    reports_dir.mkdir(parents=True, exist_ok=True)
    page = render_html(scenarios, run_at)
    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"recall_status_report_{stamp}.html"
    path.write_text(page, encoding="utf-8")
    (reports_dir / "latest.html").write_text(page, encoding="utf-8")
    _write_results_json(scenarios, reports_dir / f"recall_status_results_{stamp}.json", run_at)
    return path


# --- results JSON (re-render without re-running) -----------------------------------

_FIELDS = ("id", "name", "first_name", "last_name", "pat_num", "due_in_days", "appointment", "appt_in_days",
           "expected_status", "set_due_date", "due_date", "appt_datetime", "apt_num", "actual_status",
           "passed", "error")


def _to_json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return [_to_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_json(x) for k, x in v.items()}
    return v


def _write_results_json(scenarios: list[Scenario], path: Path, run_at: datetime) -> None:
    data = {"run_at": run_at.isoformat(),
            "scenarios": [{f: _to_json(getattr(s, f)) for f in _FIELDS} for s in scenarios]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_results(path: Path) -> tuple[list[Scenario], datetime]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios = []
    for raw in data["scenarios"]:
        s = Scenario(id=raw["id"], name=raw.get("name", ""), first_name=raw.get("first_name", ""),
                     last_name=raw.get("last_name", ""), pat_num=raw.get("pat_num"),
                     due_in_days=raw.get("due_in_days", 0), appointment=raw.get("appointment", "none"),
                     appt_in_days=raw.get("appt_in_days"), expected_status=raw.get("expected_status", []))
        for key in ("set_due_date", "due_date"):
            if raw.get(key):
                setattr(s, key, date.fromisoformat(raw[key][:10]))
        if raw.get("appt_datetime"):
            s.appt_datetime = datetime.fromisoformat(raw["appt_datetime"])
        s.apt_num, s.actual_status = raw.get("apt_num"), raw.get("actual_status") or []
        s.passed, s.error = raw.get("passed"), raw.get("error")
        scenarios.append(s)
    return scenarios, datetime.fromisoformat(data["run_at"])


if __name__ == "__main__":
    results = Path(sys.argv[1])
    scs, when = load_results(results)
    out = results.with_name(results.name.replace("recall_status_results_", "recall_status_report_")).with_suffix(".html")
    out.write_text(render_html(scs, when), encoding="utf-8")
    print(out)
