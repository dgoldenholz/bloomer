"""Parse Survey 3 free-text numeric answers (SAP Part B, section B2).

Raw text never leaves this module: callers write only the parsed number and a status.
Statuses: "ok" (parsed), "blank" (no answer), "unparsed" (text that matches no rule).
"""
from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd

from bloomer_retention.answer_key import normalize_text

OK, BLANK, UNPARSED = "ok", "blank", "unparsed"

_NUM = r"(\d+(?:\.\d+)?)"
_SECONDS = r"(?:s|sec|secs|second|seconds)"
_MINUTES = r"(?:m|min|mins|minut\w*)"
_HOURS = r"(?:h|hr|hrs|hour|hours)"
_UNIT_FACTOR = {"seconds": 1 / 60, "minutes": 1.0, "hours": 60.0}


def _text(value: object) -> str | None:
    text = normalize_text(value)
    return text.casefold() if text else None


def _unit(word: str | None) -> str:
    if not word:
        return "minutes"
    for name, pattern in (("seconds", _SECONDS), ("minutes", _MINUTES), ("hours", _HOURS)):
        if re.fullmatch(pattern, word):
            return name
    raise ValueError(word)


def parse_minutes(value: object) -> tuple[float | None, str]:
    """Time spent on one Bloomer question, in minutes."""
    if isinstance(value, dt.time):  # Excel turns a typed "m:ss" into a time of day: hour = minutes, minute = seconds
        return value.hour + value.minute / 60 + value.second / 3600, OK
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value):
            return None, BLANK
        return (float(value), OK) if value >= 0 else (None, UNPARSED)
    text = _text(value)
    if text is None:
        return None, BLANK
    if m := re.fullmatch(rf"(\d+):(\d{{1,2}})(?:\s*{_MINUTES})?", text):
        minutes, seconds = int(m.group(1)), int(m.group(2))
        return (minutes + seconds / 60, OK) if seconds < 60 else (None, UNPARSED)
    if m := re.fullmatch(r"(\d+)\.(\d{2})", text):
        minutes, seconds = int(m.group(1)), int(m.group(2))
        return (minutes + seconds / 60, OK) if seconds < 60 else (None, UNPARSED)
    unit_words = rf"({_SECONDS}|{_MINUTES}|{_HOURS})"
    if m := re.fullmatch(rf"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*{unit_words}?", text):
        low, high = float(m.group(1)), float(m.group(2))
        return (low + high) / 2 * _UNIT_FACTOR[_unit(m.group(3))], OK
    if m := re.fullmatch(rf"{_NUM}\s*{unit_words}?", text):
        return float(m.group(1)) * _UNIT_FACTOR[_unit(m.group(2))], OK
    return None, UNPARSED


def parse_attempts(value: object) -> tuple[float | None, str]:
    """Number of attempts on one Bloomer question: a positive whole number, or a range a-b (midpoint)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value):
            return None, BLANK
        return (float(value), OK) if value >= 1 and float(value).is_integer() else (None, UNPARSED)
    text = _text(value)
    if text is None:
        return None, BLANK
    if m := re.fullmatch(r"(\d+)(?:\.0+)?", text):
        count = int(m.group(1))
        return (float(count), OK) if count >= 1 else (None, UNPARSED)
    if m := re.fullmatch(r"(\d+)\s*-\s*(\d+)", text):
        low, high = int(m.group(1)), int(m.group(2))
        return ((low + high) / 2, OK) if 1 <= low <= high else (None, UNPARSED)
    return None, UNPARSED


def _one_integer(value: object, allowed_words: str, low: int, high: int) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value) or not float(value).is_integer():
            return None
        number = int(value)
    else:
        text = _text(value)
        if text is None:
            return None
        m = re.fullmatch(rf"(?:(?:{allowed_words})\s*-?\s*)?(\d+)\s*(?:{allowed_words})?", text)
        if not m:
            return None
        number = int(m.group(1))
    return number if low <= number <= high else None


def parse_age(value: object) -> int | None:
    """Age in whole years (18-100); anything else, including names typed into the field, is missing."""
    return _one_integer(value, r"years?\s*old|years?|yrs?|yo|y", 18, 100)


def parse_years(value: object) -> int | None:
    """Years in practice or PGY year (0-60): accepts '3', '3 years', 'PGY-4', 'pgy4', 'Phy4'."""
    return _one_integer(value, r"pgy|phy|years?|yrs?", 0, 60)


def parse_prior_knowledge(value: object) -> int | None:
    """Prior-knowledge rating on the form's 1-10 scale."""
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number) or not float(number).is_integer() or not 1 <= number <= 10:
        return None
    return int(number)
