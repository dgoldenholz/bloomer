"""Candidate links between anonymous forms by timestamp (SAP Part C, C6), computed at ingest.

Each file has one row per candidate pair within a gap window and carries only pseudonymous pids, the gap rounded
to 0.1 (hours or days) and whether the two forms name the same group. No clock time is ever written, and the
private timestamps passed in are held in memory by ingest only. The files are nevertheless not timestamp-free in
effect: together with the dates in the other de-identified files, the gaps allow approximate reconstruction of each
form's submission time, so treat them as sensitive as timestamps and never share them, even if survey3.csv is ever
released (SAP C6). Population rules are applied at analysis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bloomer_retention.survey3_forms import GROUP_BY_BLOOMER_PAPER

PART1_MAX_HOURS = 336  # Survey 3 start 0-14 days after the MCQ form completion
PHASE3_MIN_DAYS = 14  # Phase 3 start 14-75 days after the MCQ form completion
PHASE3_MAX_DAYS = 75


def _candidate_pairs(mcq_times: dict[str, pd.DataFrame], right_times: pd.DataFrame, right_groups: dict,
                     right_col: str, gap_col: str, unit: np.timedelta64, low: float, high: float) -> pd.DataFrame:
    """Every (MCQ pid, right pid) with low <= right start - MCQ completion <= high; the MCQ form's paper is its group."""
    frames = []
    right_start = right_times["start_time"].to_numpy(dtype="datetime64[ns]")
    right_pids = right_times["pid"].to_numpy()
    for paper in ("A", "B"):
        left = mcq_times[paper]
        completion = left["completion_time"].to_numpy(dtype="datetime64[ns]")
        gap = (right_start[None, :] - completion[:, None]) / unit
        rows, cols = np.nonzero((gap >= low) & (gap <= high))
        frames.append(pd.DataFrame({
            "mcq_pid": left["pid"].to_numpy()[rows],
            right_col: right_pids[cols],
            gap_col: np.round(gap[rows, cols], 1),
            "same_group": [right_groups.get(pid) == paper for pid in right_pids[cols]],
        }))
    links = pd.concat(frames, ignore_index=True)
    links["same_group"] = links["same_group"].astype(bool)
    return links.sort_values(["mcq_pid", right_col], kind="stable").reset_index(drop=True)


def part1_links(mcq_times: dict[str, pd.DataFrame], survey3: pd.DataFrame,
                survey3_times: pd.DataFrame) -> pd.DataFrame:
    """[mcq_pid, s3_pid, gap_hours, same_group]: Survey 3 start - MCQ completion, 0-336 h.

    MCQ Paper A form = group A; the Survey 3 group follows its Bloomer paper, and a row without one never has
    the same group.
    """
    groups = dict(zip(survey3["pid"], survey3["bloomer_paper"].map(GROUP_BY_BLOOMER_PAPER)))
    return _candidate_pairs(mcq_times, survey3_times, groups, "s3_pid", "gap_hours", np.timedelta64(1, "h"),
                            0, PART1_MAX_HOURS)


def phase3_links(mcq_times: dict[str, pd.DataFrame], phase3: pd.DataFrame,
                 phase3_times: pd.DataFrame) -> pd.DataFrame:
    """[mcq_pid, p3_pid, gap_days, same_group]: Phase 3 start - MCQ completion, 14-75 days; self-reported group."""
    groups = dict(zip(phase3["pid"], phase3["group"]))
    return _candidate_pairs(mcq_times, phase3_times, groups, "p3_pid", "gap_days", np.timedelta64(1, "D"),
                            PHASE3_MIN_DAYS, PHASE3_MAX_DAYS)
