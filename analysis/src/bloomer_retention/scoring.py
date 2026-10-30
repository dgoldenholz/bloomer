"""Stage 2a: analysis population and item scoring (SAP sections 4, 5 and 9)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd

from bloomer_retention.answer_key import (
    ALLOWED_VALUES,
    DATE_LIMITED_ITEMS,
    ITEM_IDS,
    PAPERS,
    is_correct,
    normalize_response,
    unrecognized_responses,
    valid_items,
)

# group -> paper -> method used on that paper in Part 1 (manuscript Methods, Study Design)
METHOD_BY_GROUP = {"A": {"A": "MCQ", "B": "Bloomer"}, "B": {"A": "Bloomer", "B": "MCQ"}}
CONTAMINATION_COLUMNS = ["reread_a", "reread_b", "used_ai", "discussed"]
PERCEIVED_COLUMNS = ["perceived_better", "useful_bloomer", "useful_mcq"]


def check_responses(df: pd.DataFrame, item_ids: Iterable[str]) -> None:
    problems = {item_id: unrecognized_responses(item_id, df[item_id]) for item_id in item_ids}
    problems = {item_id: bad for item_id, bad in problems.items() if bad}
    if problems:
        raise ValueError(f"responses outside the offered options (form edited?): {problems}")


def check_date_limited(df: pd.DataFrame, date_column: str, a4_offered_from: date) -> None:
    """Stop when a response dated before the cutoff gives a date-limited item's keyed answer (count only, no values).

    The keyed answer was not offered before the form edit, so such a response means the cutoff is set too late.
    """
    before = pd.to_datetime(df[date_column]).dt.date < a4_offered_from
    for item_id in (i for i in DATE_LIMITED_ITEMS if i in df.columns):
        n = int((before & df[item_id].map(lambda v, i=item_id: is_correct(i, v))).sum())
        if n:
            verb = "gives" if n == 1 else "give"
            raise ValueError(f"{n} response{'' if n == 1 else 's'} dated before a4_offered_from "
                             f"({a4_offered_from.isoformat()}) {verb} the keyed {item_id} answer; "
                             "the cutoff date is probably too late")


def phase3_population(phase3: pd.DataFrame, freeze_date: date) -> tuple[pd.DataFrame, dict]:
    after_freeze = pd.to_datetime(phase3["completion_date"]).dt.date > freeze_date
    no_group = ~phase3["group"].isin(["A", "B"])
    kept = phase3[~after_freeze & ~no_group]
    flow = {
        "phase3_deidentified": int(len(phase3)),
        "excluded_after_freeze": int(after_freeze.sum()),
        "excluded_missing_group": int((no_group & ~after_freeze).sum()),
        "analysed": int(len(kept)),
        "analysed_group_A": int((kept["group"] == "A").sum()),
        "analysed_group_B": int((kept["group"] == "B").sum()),
    }
    return kept.reset_index(drop=True), flow


def item_long(pop: pd.DataFrame, a4_offered_from: date) -> pd.DataFrame:
    """One row per participant x item: pid, group, paper, item_id, method, answered, correct, valid.

    valid follows the completion date: A4 is valid only for responses completed on or after a4_offered_from.
    """
    check_responses(pop, ITEM_IDS)
    check_date_limited(pop, "completion_date", a4_offered_from)
    rows = []
    for record in pop.to_dict("records"):
        completed = pd.Timestamp(record["completion_date"]).date()
        scored = {paper: valid_items(paper, completed, a4_offered_from) for paper in PAPERS}
        for item_id in ITEM_IDS:
            paper = item_id[0]
            rows.append({
                "pid": record["pid"],
                "group": record["group"],
                "paper": paper,
                "item_id": item_id,
                "method": METHOD_BY_GROUP[record["group"]][paper],
                "answered": normalize_response(record[item_id]) is not None,
                "correct": is_correct(item_id, record[item_id]),
                "valid": item_id in scored[paper],
            })
    return pd.DataFrame(rows)


def participant_scores(items: pd.DataFrame, pop: pd.DataFrame) -> pd.DataFrame:
    """Per participant: pct_<paper> (primary), pct_answered_<paper> (S4), points5_<paper> (S5), contaminated (S1).

    Percentages use each participant's own valid items (Paper A has 4 before the A4 cutoff and 5 from it).
    """
    valid = items[items["valid"]].groupby(["pid", "paper"])
    correct = valid["correct"].sum().unstack("paper")
    answered = valid["answered"].sum().unstack("paper")
    pct = 100 * correct / valid["correct"].size().unstack("paper")
    pct_answered = 100 * correct / answered.where(answered > 0)
    points5 = items.groupby(["pid", "paper"])["correct"].sum().unstack("paper")

    wide = pop[["pid", "group"]].set_index("pid")
    for paper in PAPERS:
        suffix = paper.lower()
        wide[f"pct_{suffix}"] = pct[paper].astype(float)
        wide[f"pct_answered_{suffix}"] = pct_answered[paper].astype(float)
        wide[f"points5_{suffix}"] = points5[paper].astype(float)
    wide["contaminated"] = pop.set_index("pid")[CONTAMINATION_COLUMNS].eq("Yes").any(axis=1)
    return wide.reset_index()


def item_summary(items: pd.DataFrame) -> pd.DataFrame:
    """D2: percent correct at 1 month per item and Part 1 method (unanswered counted incorrect).

    n, n_correct and pct_correct cover only rows where the item is scored; n_not_scored counts the rest (A4 before
    the cutoff). pct_correct is missing when no row is scored.
    """
    summary = (
        items.assign(scored_correct=items["correct"] & items["valid"], not_scored=~items["valid"])
        .groupby(["item_id", "method"])
        .agg(n=("valid", "sum"), n_correct=("scored_correct", "sum"), n_not_scored=("not_scored", "sum"))
        .reset_index()
    )
    summary["pct_correct"] = 100 * summary["n_correct"] / summary["n"].where(summary["n"] > 0)
    return summary


def perceived_retention(pop: pd.DataFrame) -> dict[str, dict[str, int]]:
    """D3: response counts for the Phase 3 perception items, in scale/form order with "No answer" last."""
    summary = {}
    for column in PERCEIVED_COLUMNS:
        counts = pop[column].fillna("No answer").value_counts()
        form_order = [option for option in ALLOWED_VALUES[column] if option in counts.index]
        other = sorted(str(k) for k in counts.index if k not in ALLOWED_VALUES[column] and k != "No answer")
        blank = ["No answer"] if "No answer" in counts.index else []
        summary[column] = {key: int(counts[key]) for key in [*form_order, *other, *blank]}
    return summary


def _mcq_exclusions(mcq: pd.DataFrame, study_start: date, freeze_date: date) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Start date, pilot rows (started before study_start) and rows started after the freeze date."""
    started = pd.to_datetime(mcq["start_date"]).dt.date
    return started, started < study_start, started > freeze_date


def mcq_scores(mcq: pd.DataFrame, paper: str, study_start: date, freeze_date: date,
               a4_offered_from: date) -> pd.DataFrame:
    """Part 1 MCQ form scores for one article: [pid, group, pct, prior_knowledge, start_date] (the Paper A form is
    group A; start_date is carried through unchanged, as an ISO string, for C1's follow-up-eligible return rates and
    date ranges (SAP v2.6); it does not affect any score).

    Pilot rows and rows started after the freeze are excluded. Each row is scored over its own valid items: A4 counts
    only for rows started on or after a4_offered_from.
    """
    started, pilot, after_freeze = _mcq_exclusions(mcq, study_start, freeze_date)
    kept = mcq[~pilot & ~after_freeze]
    paper_items = [i for i in ITEM_IDS if i[0] == paper]
    check_responses(kept, paper_items)
    check_date_limited(kept, "start_date", a4_offered_from)
    scored = pd.DataFrame([[i in valid_items(paper, day, a4_offered_from) for i in paper_items]
                           for day in started.loc[kept.index]], index=kept.index, columns=paper_items, dtype=bool)
    correct = kept[paper_items].apply(lambda col: col.map(lambda v: is_correct(col.name, v)))
    pct = 100 * (correct & scored).sum(axis=1) / scored.sum(axis=1)
    return pd.DataFrame({"pid": kept["pid"], "group": paper, "pct": pct,
                         "prior_knowledge": kept["prior_knowledge"],
                         "start_date": kept["start_date"]}).reset_index(drop=True)


def part1_mcq_summary(mcq: pd.DataFrame, paper: str, study_start: date, freeze_date: date,
                      a4_offered_from: date) -> dict:
    """D4: unlinked Part 1 MCQ context for one article; pilot rows and rows started after the freeze excluded.

    Each row is scored over its own valid items: A4 counts only for rows started on or after a4_offered_from.
    """
    _, pilot, after_freeze = _mcq_exclusions(mcq, study_start, freeze_date)
    scores = mcq_scores(mcq, paper, study_start, freeze_date, a4_offered_from)
    pct = scores["pct"]
    return {
        "paper": paper,
        "n_pilot_excluded": int(pilot.sum()),
        "n_after_freeze_excluded": int((after_freeze & ~pilot).sum()),
        "n": int(len(scores)),
        "pct_correct_mean": float(pct.mean()) if len(scores) else None,
        "pct_correct_sd": float(pct.std(ddof=1)) if len(scores) > 1 else None,
        "prior_knowledge_median": float(scores["prior_knowledge"].median()) if len(scores) else None,
    }


def cell_descriptives(wide: pd.DataFrame) -> list[dict]:
    """D1: primary score by group x article, labelled with the Part 1 method."""
    rows = []
    for group in PAPERS:
        in_group = wide[wide["group"] == group]
        for paper in PAPERS:
            values = in_group[f"pct_{paper.lower()}"].dropna()
            n = int(len(values))
            rows.append({
                "group": group,
                "paper": paper,
                "method": METHOD_BY_GROUP[group][paper],
                "n": n,
                "mean": float(values.mean()) if n else None,
                "sd": float(values.std(ddof=1)) if n > 1 else None,
                "median": float(values.median()) if n else None,
                "q1": float(values.quantile(0.25)) if n else None,
                "q3": float(values.quantile(0.75)) if n else None,
            })
    return rows
