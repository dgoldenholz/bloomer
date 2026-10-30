"""Retention (Phase 3) -> registration (Start form) link from a study-team worksheet (SAP Part F, version 2.7).

The Part 1 MCQ forms are anonymous, so the only record a retention response can be tied to is the registration
(Start form) row. The study team matched every Phase 3 row to a Start row in a private worksheet, by registration
email or tracker name where the records allowed, and by timing otherwise.

Private: the worksheet holds names and emails. Only its two row-number columns and `match_method` are read; no
other column is selected, and nothing from it is printed. Errors name counts only. The link frame carries
pseudonymous pids and a two-level basis label - no name, email, date or row number.

Part F reports counts and a five-number interval summary only, never a per-person row, never a cross-tabulation
with an outcome, and never a group or assignment comparison (deferred by the author).

Version 3.0 (final analysis) adds three optional worksheet columns, read only when present: the sequence group in
the study team's assignment email, the date the study team received the participant's Bloomer summary (Part 1
done) and the date the retention link was sent. A row whose match_method is "none" has no registration row. The
link frame then also carries the assignment group and two whole-day intervals, and the summary adds the
assignment-versus-self-report agreement as counts and the two interval summaries. Dates are never written: only
day counts, as the registration interval already allowed.
"""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from bloomer_retention.answer_key import normalize_text
from bloomer_retention.start_form import START_OPTIONS

PHASE3_ROW = "phase3_row"  # 1-based row order in the raw Phase 3 export
START_ROW = "CONFIRMED_start_row (fill in)"  # 1-based row order in the raw Start export
MATCH_METHOD = "match_method"
WORKSHEET_COLUMNS = (PHASE3_ROW, START_ROW, MATCH_METHOD)  # the only columns ever read, with the three below
ASSIGNED_GROUP, PART1_DATE, LINK_SENT_DATE = "assigned_group", "part1_date", "link_sent_date"  # SAP v3.0, optional
FOLLOWUP_WORKSHEET_COLUMNS = (ASSIGNED_GROUP, PART1_DATE, LINK_SENT_DATE)
RECORD_METHODS = frozenset(("registration email", "tracker name", "retention form name"))  # v3.0 adds the last
NO_LINK_METHOD = "none"  # SAP v3.0: a retention row the study team could not tie to any registration
LINK_BASES = ("record", "timing")  # record: email or a name; timing: decided by the study team on timing
LINK_COLUMNS = ["phase3_pid", "start_pid", "link_basis"]
FOLLOWUP_COLUMNS = ["assigned_group", "part1_to_retention_days", "link_to_retention_days"]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def link_basis(method: object) -> str:
    """'record' for a registration-email or tracker-name match, 'timing' for anything else."""
    text = normalize_text(method)
    return "record" if text is not None and text.casefold() in RECORD_METHODS else "timing"


def _unlinked(method: object) -> bool:
    text = normalize_text(method)
    return text is not None and text.casefold() == NO_LINK_METHOD


def _row_numbers(values: pd.Series, label: str, n_raw: int, allow_blank: pd.Series | None = None) -> list[int | None]:
    """Whole 1-based row numbers; a blank is allowed (as None) only where `allow_blank` is True."""
    numbers = pd.to_numeric(values, errors="coerce")
    blank_ok = numbers.isna() & (allow_blank if allow_blank is not None else False)
    bad = int(((numbers.isna() & ~blank_ok) | (numbers.notna() & (numbers % 1 != 0))).sum())
    if bad:
        raise ValueError(f"registration worksheet: {_plural(bad, f'{label} row number')} blank or not whole")
    given = int((~numbers.isna() & (allow_blank if allow_blank is not None else False)).sum())
    if given:
        raise ValueError(f"registration worksheet: {_plural(given, f'{label} row number')} given for a "
                         f"'{NO_LINK_METHOD}' match")
    rows = [None if pd.isna(n) else int(n) for n in numbers]
    present = [n for n in rows if n is not None]
    out_of_range = sum(1 for n in present if not 1 <= n <= n_raw)
    if out_of_range:
        raise ValueError(f"registration worksheet: {_plural(out_of_range, f'{label} row number')} outside 1 to "
                         f"{n_raw}")
    repeated = len(present) - len(set(present))
    if repeated:
        raise ValueError(f"registration worksheet: {_plural(repeated, f'repeated {label} row number')}")
    return rows


def _pid_by_row(positions: Sequence[int], pids: Sequence[str]) -> dict[int, str]:
    """1-based raw row number -> pid, from the 0-based raw positions of the kept rows in output (pid) order."""
    if len(positions) != len(pids):
        raise ValueError(f"registration link needs aligned frames: {_plural(len(positions), 'kept row')} for "
                         f"{_plural(len(pids), 'pid')}")
    return {int(position) + 1: str(pid) for position, pid in zip(positions, pids)}


def _group(value: object) -> str:
    text = normalize_text(value)
    if text is None:
        return ""
    if text.upper() not in ("A", "B"):
        raise ValueError("registration worksheet: an assignment group is neither A nor B")
    return text.upper()


def _days(later: object, earlier: object) -> object:
    """Whole days from `earlier` to `later`; blank when either is missing."""
    if earlier is None or pd.isna(earlier) or later is None or pd.isna(later):
        return pd.NA
    try:
        return int((pd.Timestamp(later).normalize() - pd.Timestamp(earlier).normalize()).days)
    except (ValueError, TypeError):
        raise ValueError("registration worksheet: a follow-up date is not a date") from None


def build_registration_links(worksheet: pd.DataFrame, *, phase3_positions: Sequence[int], phase3_pids: Sequence[str],
                             n_phase3_raw: int, start_positions: Sequence[int], start_pids: Sequence[str],
                             n_start_raw: int, phase3_completion: Sequence[str] | None = None
                             ) -> tuple[pd.DataFrame, dict]:
    """Worksheet -> ([phase3_pid, start_pid, link_basis], stats).

    `*_positions` are the 0-based positions, in the raw export, of the rows ingest kept, listed in the order of
    `*_pids` (after any duplicate removal and the reorder by completion time). A worksheet row number names a raw
    row by its 1-based position, so it maps to the pid of the kept row at that position; a row ingest dropped
    raises. Stats are counts only.
    """
    missing = [column for column in WORKSHEET_COLUMNS if column not in worksheet.columns]
    if missing:
        raise ValueError("registration worksheet is missing columns: " + ", ".join(missing))
    followup = all(column in worksheet.columns for column in FOLLOWUP_WORKSHEET_COLUMNS)
    if followup and phase3_completion is None:
        raise ValueError("registration worksheet has follow-up columns but no Phase 3 completion dates were given")
    keep = [*WORKSHEET_COLUMNS, *(FOLLOWUP_WORKSHEET_COLUMNS if followup else ())]
    sheet = worksheet.loc[:, keep]  # every other column (names, emails, notes) is dropped here
    phase3_rows = _row_numbers(sheet[PHASE3_ROW], "Phase 3", n_phase3_raw)
    start_rows = _row_numbers(sheet[START_ROW], "Start", n_start_raw,
                              allow_blank=sheet[MATCH_METHOD].map(_unlinked).astype(bool))
    phase3_pid, start_pid = _pid_by_row(phase3_positions, phase3_pids), _pid_by_row(start_positions, start_pids)
    dropped = sum(1 for row in phase3_rows if row not in phase3_pid)
    if dropped:
        raise ValueError(f"registration worksheet names {_plural(dropped, 'Phase 3 row')} that ingest dropped")
    dropped = sum(1 for row in start_rows if row is not None and row not in start_pid)
    if dropped:
        raise ValueError(f"registration worksheet names {_plural(dropped, 'Start row')} that ingest dropped")
    links = pd.DataFrame({"phase3_pid": [phase3_pid[row] for row in phase3_rows],
                          "start_pid": ["" if row is None else start_pid[row] for row in start_rows],
                          "link_basis": ["" if row is None else link_basis(method)
                                         for row, method in zip(start_rows, sheet[MATCH_METHOD])]},
                         columns=LINK_COLUMNS)
    if followup:
        completion = dict(zip(phase3_pids, phase3_completion))
        done = [completion[pid] for pid in links["phase3_pid"]]
        links["assigned_group"] = [_group(value) for value in sheet[ASSIGNED_GROUP]]
        links["part1_to_retention_days"] = pd.array(
            [_days(end, start) for end, start in zip(done, sheet[PART1_DATE])], dtype="Int64")
        links["link_to_retention_days"] = pd.array(
            [_days(end, start) for end, start in zip(done, sheet[LINK_SENT_DATE])], dtype="Int64")
    links = links.sort_values("phase3_pid", kind="stable").reset_index(drop=True)
    registered = links[links["start_pid"] != ""]
    stats = {"n_worksheet_rows": int(len(sheet)), "n_links": int(len(registered)),
             "n_by_basis": {basis: int((registered["link_basis"] == basis).sum()) for basis in LINK_BASES},
             "n_phase3_unlinked": int(len(phase3_pid) - len(registered))}
    if followup:
        stats["n_assigned_group"] = int((links["assigned_group"] != "").sum())
        stats["n_part1_date"] = int(links["part1_to_retention_days"].notna().sum())
        stats["n_link_sent_date"] = int(links["link_to_retention_days"].notna().sum())
    return links, stats


def _five_numbers(values: pd.Series) -> dict:
    """n, median, q1, q3 (linear quantiles), min and max of the non-missing values."""
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if clean.empty:
        return {"n": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}
    return {"n": int(len(clean)), "median": float(clean.median()), "q1": float(clean.quantile(0.25)),
            "q3": float(clean.quantile(0.75)), "min": float(clean.min()), "max": float(clean.max())}


def _option_counts(values: pd.Series, options: Sequence[str]) -> dict[str, int]:
    text = values.map(normalize_text)
    counts = {option: int((text == option).sum()) for option in options}
    counts["missing"] = int(text.isna().sum())
    return counts


INTERVAL_LABEL = ("Days from registration (Start form signup date) to the retention (Phase 3) completion date: an "
                  "upper bound on the Part 1 to retention interval, since Part 1 followed registration")


PART1_INTERVAL_LABEL = ("Days from the study team's receipt of the participant's Bloomer summary (Part 1 done) to "
                        "the retention completion date, from the study team's records (SAP v3.0)")
LINK_INTERVAL_LABEL = ("Days from the study team sending the retention link to the retention completion date, from "
                       "the study team's records (SAP v3.0)")


def _assignment_agreement(rows: pd.DataFrame, phase3_pop: pd.DataFrame) -> dict:
    """Counts of the assignment-email group against the self-reported group, over rows with a recorded group."""
    merged = rows.merge(phase3_pop[["pid", "group"]], left_on="phase3_pid", right_on="pid")
    recorded = merged[merged["assigned_group"].fillna("") != ""]  # read back from CSV, a blank is NaN
    agree = int((recorded["assigned_group"] == recorded["group"]).sum())
    return {"n_population": int(len(phase3_pop)), "n_recorded": int(len(recorded)),
            "n_not_recorded": int(len(phase3_pop) - len(recorded)), "n_agree": agree,
            "n_disagree": int(len(recorded) - agree)}


def followup_summary(links: pd.DataFrame, phase3_pop: pd.DataFrame) -> dict | None:
    """SAP v3.0: assignment-email agreement and the two record-based intervals; None without follow-up columns."""
    if not all(column in links.columns for column in FOLLOWUP_COLUMNS):
        return None
    rows = links[links["phase3_pid"].isin(set(phase3_pop["pid"]))]
    part1 = pd.to_numeric(rows["part1_to_retention_days"], errors="coerce")
    sent = pd.to_numeric(rows["link_to_retention_days"], errors="coerce")
    return {
        "assignment": _assignment_agreement(rows, phase3_pop),
        "part1_to_retention_days": {"label": PART1_INTERVAL_LABEL, **_five_numbers(part1),
                                    "n_negative": int((part1 < 0).sum())},
        "link_to_retention_days": {"label": LINK_INTERVAL_LABEL, **_five_numbers(sent),
                                   "n_negative": int((sent < 0).sum())},
    }


def assigned_groups(links: pd.DataFrame) -> dict[str, str]:
    """phase3 pid -> assignment-email group, for the rows that have one (SAP v3.0, sensitivity S7)."""
    if "assigned_group" not in links.columns:
        return {}
    rows = links[links["assigned_group"].fillna("") != ""]
    return dict(zip(rows["phase3_pid"], rows["assigned_group"]))


def registration_link_summary(links: pd.DataFrame, phase3_pop: pd.DataFrame, start: pd.DataFrame) -> dict:
    """SAP Part F: counts and the registration-to-retention interval over the analysed Phase 3 population.

    The population is Part A's analysed Phase 3 population; nothing else is excluded. Counts only: no per-person
    row, no outcome. With the v3.0 follow-up columns, the assignment-email group is compared with the self-reported
    group as counts.
    """
    population = set(phase3_pop["pid"])
    followup = followup_summary(links, phase3_pop) if "group" in phase3_pop.columns else None
    links = links[links["start_pid"].fillna("") != ""]
    linked = links[links["phase3_pid"].isin(population)]
    if linked["phase3_pid"].duplicated().any() or linked["start_pid"].duplicated().any():
        raise ValueError("registration links pair a Phase 3 or Start pid more than once")
    unknown = int((~linked["start_pid"].isin(set(start["pid"]))).sum())
    if unknown:
        raise ValueError(f"{_plural(unknown, 'registration link')} name a Start pid not in start.csv")
    merged = (linked.merge(phase3_pop[["pid", "completion_date"]], left_on="phase3_pid", right_on="pid")
              .drop(columns="pid")
              .merge(start[["pid", "signup_date", "us_based", "role"]], left_on="start_pid", right_on="pid"))
    days = (pd.to_datetime(merged["completion_date"]) - pd.to_datetime(merged["signup_date"])).dt.days
    return {
        "population": "Part A analysed Phase 3 population",
        "n_population": int(len(population)),
        "n_linked": int(len(merged)),
        "n_unlinked": int(len(population) - len(merged)),
        "n_by_basis": {basis: int((merged["link_basis"] == basis).sum()) for basis in LINK_BASES},
        "interval_days": {"label": INTERVAL_LABEL, **_five_numbers(days),
                          "n_negative": int((days < 0).sum())},
        "us_based": _option_counts(merged["us_based"], START_OPTIONS["us_based"]),
        "role": _option_counts(merged["role"], START_OPTIONS["role"]),
        "note": ("Counts only; no group or assignment comparison (deferred by the author)." if followup is None else
                 "Counts only; the assignment-email group is compared with the self-reported group as counts "
                 "(SAP v3.0)."),
        **({"followup": followup} if followup is not None else {}),
    }
