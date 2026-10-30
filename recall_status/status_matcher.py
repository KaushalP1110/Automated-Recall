"""Compares the status Adit shows for a patient with what the scenario expects.

Adit's Automated Recall report abbreviates its labels ("Unsched",
"Overdue & Unsched"), so both sides are reduced to a set of known status
words - abbreviations mapped to the full word - and compared exactly:

- whole words only: "Unsched" never counts as "Sched";
- exact set: a patient expected to be just "Scheduled" fails if Adit also
  says "Overdue".
"""

from __future__ import annotations

import re
from typing import Iterable

_ALIASES = {
    "unscheduled": "unscheduled", "unsched": "unscheduled",
    "scheduled": "scheduled", "sched": "scheduled",
    "overdue": "overdue",
    "completed": "completed", "complete": "completed",
}


def status_words(texts: Iterable[str]) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for word in re.findall(r"[a-z]+", (text or "").lower()):
            if word in _ALIASES:
                words.add(_ALIASES[word])
    return words


def statuses_match(expected: Iterable[str], actual: Iterable[str]) -> bool:
    expected_words = status_words(expected)
    return bool(expected_words) and expected_words == status_words(actual)
