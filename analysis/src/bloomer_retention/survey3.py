"""Survey 3 analyses: adoption co-primary, comprehension, difficulty, usage, Table 1, subgroups (SAP Part B, B3-B7)."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd
from scipy import stats

from bloomer_retention.scoring import _mcq_exclusions
from bloomer_retention.survey3_forms import (
    DIFFICULTY_SCORE,
    GROUP_BY_BLOOMER_PAPER,
    OPTIONS,
    QUESTION_LABELS,
    QUESTIONS,
)

VALUE_COLUMNS = [
    "age", "gender", "region", "role", "years", "subspecialty", "setting", "ai_use", "cme_hours", "cme_format",
    "bloomer_paper", "prior_knowledge", *[f"{q}_{field}" for q in QUESTIONS for field in ("minutes", "attempts")],
    "best_comprehension", "quiz_difficulty", "bloomer_difficulty", "preference",
]
STATUS_COLUMNS = [f"{q}_{field}" for q in QUESTIONS for field in ("time_status", "attempts_status")]
GROUPS = ("A", "B")
ATTENDING = ("ABPN-certified neurologist",)
TRAINEE = ("Neurology resident", "Neurology fellow")
TABLE1_CATEGORICAL = ("gender", "region", "role", "subspecialty", "setting", "ai_use", "cme_hours", "cme_format")
PREFERENCE_BLOOMER, PREFERENCE_QUIZ = "Bloomer-AI", "A 5-question quiz"
COMPREHENSION_BLOOMER, COMPREHENSION_QUIZ = "Bloomer", "The 5-question quiz"
SUBGROUP_FACTORS = {  # factor -> ((level label, column, values), (level label, column, values))
    "role": (("Attending (ABPN-certified)", "role", ATTENDING), ("Trainee (resident or fellow)", "role", TRAINEE)),
    "ai_use": (("AI use very often or often", "ai_use", ("Very Often", "Often")),
               ("AI use sometimes or never", "ai_use", ("Sometimes", "Never"))),
    "cme_hours": (("CME under 3 hours per week", "cme_hours", ("Less than 1 hour", "1-2 hours")),
                  ("CME 3 or more hours per week", "cme_hours", ("3-5 hours", "More than 5"))),
    "group": (("Group A (Bloomer on Paper B)", "group", ("A",)), ("Group B (Bloomer on Paper A)", "group", ("B",))),
}


def survey3_population(survey: pd.DataFrame, study_start: date, freeze_date: date) -> tuple[pd.DataFrame, dict]:
    """Drop pilot rows (started before study_start), blank submissions and rows completed after the freeze date."""
    pilot = pd.to_datetime(survey["start_date"]).dt.date < study_start
    blank = survey[VALUE_COLUMNS].isna().all(axis=1) & survey[STATUS_COLUMNS].eq("blank").all(axis=1)
    after_freeze = pd.to_datetime(survey["completion_date"]).dt.date > freeze_date
    kept = survey[~pilot & ~blank & ~after_freeze].copy()
    kept["group"] = kept["bloomer_paper"].map(GROUP_BY_BLOOMER_PAPER)
    flow = {
        "survey3_deidentified": int(len(survey)),
        "excluded_pilot": int(pilot.sum()),
        "excluded_blank": int((blank & ~pilot).sum()),
        "excluded_after_freeze": int((after_freeze & ~pilot & ~blank).sum()),
        "analysed": int(len(kept)),
        "analysed_group_A": int((kept["group"] == "A").sum()),
        "analysed_group_B": int((kept["group"] == "B").sum()),
        "analysed_without_bloomer_paper": int(kept["group"].isna().sum()),
    }
    return kept.reset_index(drop=True), flow


def describe(values: pd.Series) -> dict:
    """n, median, IQR (linear quantiles) and mean of the non-missing values."""
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    n = int(len(clean))
    if not n:
        return {"n": 0, "median": None, "q1": None, "q3": None, "mean": None}
    return {"n": n, "median": float(clean.median()), "q1": float(clean.quantile(0.25)),
            "q3": float(clean.quantile(0.75)), "mean": float(clean.mean())}


def proportion_test(n_bloomer: int, n_quiz: int) -> dict:
    """Bloomer / (Bloomer + quiz): Clopper-Pearson 95% CI and exact two-sided binomial test against 0.5."""
    n = n_bloomer + n_quiz
    result = {"n_bloomer": int(n_bloomer), "n_quiz": int(n_quiz), "n_decided": int(n)}
    if n == 0:
        return {**result, "proportion": None, "ci_low": None, "ci_high": None, "p_value": None,
                "effect_vs_half": None}
    test = stats.binomtest(n_bloomer, n, 0.5)
    ci = test.proportion_ci(confidence_level=0.95, method="exact")
    return {**result, "proportion": n_bloomer / n, "ci_low": float(ci.low), "ci_high": float(ci.high),
            "p_value": float(test.pvalue), "effect_vs_half": n_bloomer / n - 0.5}


def _counts(values: pd.Series, options: tuple[str, ...]) -> dict[str, int]:
    counts = {option: int((values == option).sum()) for option in options}
    counts["blank"] = int(values.isna().sum())
    return counts


def choice_outcome(pop: pd.DataFrame, column: str, bloomer_option: str, quiz_option: str) -> dict:
    """Co-primary (Q25) and comprehension (Q22): answer counts, decided-respondent test, all-respondent CI."""
    counts = _counts(pop[column], OPTIONS[column])
    n_answered = int(len(pop) - counts["blank"])
    all_respondents = {"n_bloomer": counts[bloomer_option], "n_answered": n_answered,
                       "proportion": None, "ci_low": None, "ci_high": None}
    if n_answered:
        ci = stats.binomtest(counts[bloomer_option], n_answered, 0.5).proportion_ci(method="exact")
        all_respondents.update(proportion=counts[bloomer_option] / n_answered, ci_low=float(ci.low),
                               ci_high=float(ci.high))
    return {
        "bloomer_option": bloomer_option,
        "quiz_option": quiz_option,
        "counts": counts,
        "decided": proportion_test(counts[bloomer_option], counts[quiz_option]),
        "all_respondents": all_respondents,
        "by_group": {group: _counts(pop.loc[pop["group"] == group, column], OPTIONS[column]) for group in GROUPS},
    }


def wilcoxon_procedure(x: pd.Series, y: pd.Series, p_auto: float) -> str:
    """Name the procedure scipy's method="auto" used, by re-running the normal approximation and comparing P.

    scipy 1.17: exact when there are no ties or zero differences (up to 50 pairs), a permutation test over all
    sign assignments for up to 13 pairs otherwise, else the normal approximation.
    """
    asymptotic = float(stats.wilcoxon(x, y, zero_method="wilcox", method="asymptotic").pvalue)
    if math.isclose(p_auto, asymptotic, rel_tol=0.0, abs_tol=1e-12):
        return "normal approximation with tie- and zero-corrected variance, no continuity correction"
    difference = (x.astype(float) - y.astype(float)).to_numpy()
    nonzero = abs(difference[difference != 0])
    if (difference == 0).any() or len(set(nonzero)) < len(nonzero):
        return "permutation test over all sign assignments"
    return "exact"


def difficulty(pop: pd.DataFrame) -> dict:
    """Quiz (Q23) vs Bloomer (Q24) difficulty, 1 = not at all ... 5 = very difficult; paired Wilcoxon signed-rank."""
    quiz = pop["quiz_difficulty"].map(DIFFICULTY_SCORE)
    bloomer = pop["bloomer_difficulty"].map(DIFFICULTY_SCORE)

    def item(scores: pd.Series) -> dict:
        summary = describe(scores)
        n = summary["n"]
        summary["pct_difficult"] = 100 * float((scores >= 4).sum()) / n if n else None
        summary["n_no_opinion"] = int((pop[scores.name] == "no opinon").sum())
        return summary

    both = quiz.notna() & bloomer.notna()
    difference = (bloomer - quiz)[both]
    paired = {"n_pairs": int(both.sum()), "n_nonzero": int((difference != 0).sum()),
              "median_difference": float(difference.median()) if both.any() else None,
              "statistic": None, "p_value": None, "method": None,
              "test": "Wilcoxon signed-rank (zero_method=wilcox, method=auto), Bloomer minus quiz"}
    if paired["n_nonzero"]:
        test = stats.wilcoxon(bloomer[both], quiz[both], zero_method="wilcox", method="auto")
        paired.update(statistic=float(test.statistic), p_value=float(test.pvalue),
                      method=wilcoxon_procedure(bloomer[both], quiz[both], float(test.pvalue)))
    return {"quiz": item(quiz.rename("quiz_difficulty")), "bloomer": item(bloomer.rename("bloomer_difficulty")),
            "paired": paired}


def _status_counts(values: pd.Series) -> dict[str, int]:
    return {status: int((values == status).sum()) for status in ("ok", "blank", "unparsed")}


def person_totals(pop: pd.DataFrame, field: str) -> pd.Series:
    """Per-person total of "attempts" or "minutes" over the three Bloomer questions; missing unless all three are.

    Complete cases only, as in B6; Part D uses the same totals per person (SAP D6).
    """
    values = pop[[f"{q}_{field}" for q in QUESTIONS]].astype(float)
    return values.sum(axis=1).where(values.notna().all(axis=1))


def usage(pop: pd.DataFrame) -> dict:
    """Attempts and minutes per Bloomer question, per-person totals over complete cases, and the completion proxy."""
    per_question = {}
    for q in QUESTIONS:
        attempts = pop[f"{q}_attempts"].astype(float)
        summary = describe(attempts)
        summary["pct_more_than_one"] = 100 * float((attempts > 1).sum()) / summary["n"] if summary["n"] else None
        per_question[q] = {
            "label": QUESTION_LABELS[q],
            "attempts": summary,
            "minutes": describe(pop[f"{q}_minutes"]),
            "attempts_status": _status_counts(pop[f"{q}_attempts_status"]),
            "time_status": _status_counts(pop[f"{q}_time_status"]),
        }
    entered = pop[STATUS_COLUMNS].ne("blank").all(axis=1)
    over = (pop[[f"{q}_minutes" for q in QUESTIONS]] > 60).any(axis=1)
    return {
        "per_question": per_question,
        "total_attempts": describe(person_totals(pop, "attempts")),
        "total_minutes": describe(person_totals(pop, "minutes")),
        "completion_proxy": {"n_complete": int(entered.sum()), "n": int(len(pop)),
                             "pct": 100 * float(entered.mean()) if len(pop) else None,
                             "definition": "time and attempts entered for all three questions (not mastery)"},
        # extreme usage (SAP v2.6): any single Bloomer question reported over 60 minutes, and the
        # per-person total-minutes median recomputed excluding those respondents.
        "n_any_question_over_60": int(over.sum()),
        "total_minutes_excl_over_60": describe(person_totals(pop[~over], "minutes")),
    }


def quiz_elapsed(mcq_by_paper: dict[str, pd.DataFrame], study_start: date | None = None,
                 freeze_date: date | None = None) -> dict:
    """SAP v2.6: Microsoft Forms elapsed minutes per Part 1 MCQ form (form open to submit; includes any reading).

    When `study_start` and `freeze_date` are given, each form is restricted first to the same population
    `mcq_scores`/`part1_mcq_summary` analyse (pilot rows started before `study_start` and rows started after
    `freeze_date` excluded), reusing `_mcq_exclusions` rather than duplicating its logic - the manuscript reports
    this beside the analysed Part 1 forms, not the full unfiltered export. Without them, every row is pooled.

    Implausible entries (completion before start or over 24 h) are already missing in `elapsed_min`
    (set at ingest); `n_implausible` here just counts them.
    """
    frames = mcq_by_paper.values()
    if study_start is not None or freeze_date is not None:
        kept = []
        for frame in frames:
            _, pilot, after_freeze = _mcq_exclusions(frame, study_start, freeze_date)
            kept.append(frame[~pilot & ~after_freeze])
        frames = kept
    values = pd.concat([f["elapsed_min"] for f in frames])
    return {"minutes": describe(values), "n_forms": int(len(values)), "n_implausible": int(values.isna().sum())}


def _percentages(counts: dict[str, int], denominator: int) -> dict:
    """Each level as a percent of the respondents in that column, with the denominator recorded beside it.

    The denominator is every respondent in the group, blanks included, so a column's levels sum to 100%. It is
    written out rather than left implicit so that a report never has to choose one (SAP B6).
    """
    return {"denominator": denominator,
            "levels": {option: (100 * n / denominator if denominator else None) for option, n in counts.items()}}


def table1(pop: pd.DataFrame) -> dict:
    frames = {"overall": pop, **{group: pop[pop["group"] == group] for group in GROUPS}}
    counts = {column: {name: _counts(frame[column], OPTIONS[column]) for name, frame in frames.items()}
              for column in TABLE1_CATEGORICAL}
    return {
        "n": {name: int(len(frame)) for name, frame in frames.items()},
        "categorical": counts,
        "categorical_pct": {column: {name: _percentages(counts[column][name], int(len(frame)))
                                     for name, frame in frames.items()}
                            for column in TABLE1_CATEGORICAL},
        "numeric": {
            "age": {name: describe(frame["age"]) for name, frame in frames.items()},
            "prior_knowledge": {name: describe(frame["prior_knowledge"]) for name, frame in frames.items()},
            "years_attending": {name: describe(frame.loc[frame["role"].isin(ATTENDING), "years"])
                                for name, frame in frames.items()},
            "years_trainee": {name: describe(frame.loc[frame["role"].isin(TRAINEE), "years"])
                              for name, frame in frames.items()},
        },
    }


def subgroups(pop: pd.DataFrame) -> dict:
    """Exploratory: preference for Bloomer among decided respondents by factor level, Fisher's exact test (2x2)."""
    decided = pop[pop["preference"].isin([PREFERENCE_BLOOMER, PREFERENCE_QUIZ])]
    factors = []
    for factor, levels in SUBGROUP_FACTORS.items():
        rows = []
        for label, column, values in levels:
            in_level = decided[decided[column].isin(values)]
            n_bloomer = int((in_level["preference"] == PREFERENCE_BLOOMER).sum())
            rows.append({"level": label, "n_bloomer": n_bloomer, "n_quiz": int(len(in_level)) - n_bloomer,
                         "pct_bloomer": 100 * n_bloomer / len(in_level) if len(in_level) else None})
        table = [[row["n_bloomer"], row["n_quiz"]] for row in rows]
        odds_ratio = p_value = None
        if all(sum(row) for row in table):
            test = stats.fisher_exact(table)
            odds_ratio, p_value = float(test.statistic), float(test.pvalue)
        factors.append({"factor": factor, "levels": rows, "odds_ratio": odds_ratio, "p_value": p_value})
    subspecialty = {option: {"n_bloomer": int(((decided["subspecialty"] == option)
                                                & (decided["preference"] == PREFERENCE_BLOOMER)).sum()),
                             "n_quiz": int(((decided["subspecialty"] == option)
                                            & (decided["preference"] == PREFERENCE_QUIZ)).sum())}
                    for option in OPTIONS["subspecialty"]}
    return {"factors": factors, "subspecialty": subspecialty}


def prior_knowledge_context(pop: pd.DataFrame, mcq: dict[str, pd.DataFrame], study_start: date,
                            freeze_date: date) -> dict:
    """Bloomer-article rating (Survey 3) vs MCQ-article rating (Part 1 MCQ forms), by paper; unlinked."""
    context = {}
    for paper in ("A", "B"):
        started = pd.to_datetime(mcq[paper]["start_date"]).dt.date
        in_window = (started >= study_start) & (started <= freeze_date)
        context[f"Paper {paper}"] = {
            "bloomer_article_rating": describe(pop.loc[pop["bloomer_paper"] == f"Paper {paper}", "prior_knowledge"]),
            "mcq_article_rating": describe(mcq[paper].loc[in_window, "prior_knowledge"]),
        }
    return context
