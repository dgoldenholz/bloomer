"""SAP Part G (v3.1): counts of free-text comment themes among analysed Survey 3 respondents.

The comments stay in a private worksheet outside the repository. Only the pid and the 0/1 theme codes are read
(usecols), so no comment text reaches any output.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

POSITIVE_THEMES = ("engagement", "prefers_writing", "teaching")
BARRIER_THEMES = ("unclear_expectations", "grader_feedback", "effort_time", "task_design")
THEMES = POSITIVE_THEMES + BARRIER_THEMES
CODE_COLUMNS = ("pid", "substantive", *THEMES)


def read_feedback_codes(path: Path, survey_pids: Iterable[str]) -> pd.DataFrame:
    sheet = pd.read_excel(path, usecols=lambda column: column in CODE_COLUMNS, dtype={"pid": str})
    missing = [c for c in CODE_COLUMNS if c not in sheet.columns]
    if missing:
        raise ValueError(f"feedback worksheet is missing: {', '.join(missing)}")
    codes = sheet[list(CODE_COLUMNS)].copy()
    for column in ("substantive", *THEMES):
        values = codes[column].fillna(0)
        if not values.isin([0, 1]).all():
            raise ValueError(f"feedback worksheet column {column} must hold 0 or 1")
        codes[column] = values.astype(int)
    unknown = sorted(set(codes["pid"]) - set(survey_pids))
    if unknown:
        raise ValueError(f"feedback worksheet has {len(unknown)} pid(s) not in Survey 3")
    if codes["pid"].duplicated().any():
        raise ValueError("feedback worksheet repeats a pid")
    if (codes[list(THEMES)].sum(axis=1).gt(0) & codes["substantive"].eq(0)).any():
        raise ValueError("a theme is coded on a comment marked not substantive")
    return codes.reset_index(drop=True)


def feedback_themes(codes: pd.DataFrame, population_pids: Iterable[str]) -> dict:
    population = set(population_pids)
    kept = codes[codes["pid"].isin(population) & codes["substantive"].eq(1)]
    return {
        "basis": "SAP Part G; counts only, comment text never read",
        "n_population": len(population),
        "n_substantive": int(len(kept)),
        "n_outside_population": int((~codes["pid"].isin(population) & codes["substantive"].eq(1)).sum()),
        "themes": {theme: int(kept[theme].sum()) for theme in THEMES},
        "n_any_positive": int(kept[list(POSITIVE_THEMES)].sum(axis=1).gt(0).sum()),
        "n_any_barrier": int(kept[list(BARRIER_THEMES)].sum(axis=1).gt(0).sum()),
    }
