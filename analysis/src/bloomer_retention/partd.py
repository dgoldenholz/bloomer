"""Part D: roster-linked person-level analyses (SAP Part D, D1-D8). Every analysis is exploratory.

The roster link (roster_link.py, written at ingest) names, for each linked person, one Survey 3 response and one
Phase 3 response. D2-D7 are person-level analyses over the people whose link is certain; D8 recomputes all of them
over every enumerated alternative assignment and over the variant that also uses the ambiguous links.

Estimands, guards and helpers are shared with Part C wherever they coincide (`_welch`, `_adjusted_intercept`, the
minimum counts) so that the two parts cannot drift apart.
"""
from __future__ import annotations

import math
from dataclasses import asdict

import numpy as np
import pandas as pd
from scipy import stats

from bloomer_retention.crossover import crossover_ttest
from bloomer_retention.matching import (
    best_matching,
    clear_pairs,
    part1_weight,
    restrict_edges,
    same_group_flags,
)
from bloomer_retention.roster_link import NAME_METHODS
from bloomer_retention.partc import (
    CLEAR_MARGIN,
    MIN_LINKED,
    MIN_PER_LEVEL,
    _adjusted_intercept,
    _lookup,
    _present,
    _welch,
)
from bloomer_retention.survey3 import (
    PREFERENCE_BLOOMER,
    PREFERENCE_QUIZ,
    SUBGROUP_FACTORS,
    describe,
    person_totals,
)
from bloomer_retention.survey3_forms import DIFFICULTY_SCORE

MIN_PEOPLE = MIN_LINKED  # an analysis needs at least 5 people (SAP D8), and MIN_PER_LEVEL in each level
# The headline population uses only the two strong name-matching steps; the weaker two are a D8 variant (SAP D1).
HEADLINE_NAME_METHODS = ("name_exact", "name_tokens")
WEAK_NAME_METHODS = tuple(method for method in NAME_METHODS if method not in HEADLINE_NAME_METHODS)
ALL_NAME_METHODS = NAME_METHODS
PERCEIVED_BLOOMER, PERCEIVED_MCQ = "Bloomer", "Tradtional MCQ"  # sic: the Phase 3 form's own spelling
DIFFICULT_RATING = 4  # Q24 ratings of 4 or 5 count as "difficult"
DIFFICULT_OPTIONS = tuple(option for option, score in DIFFICULTY_SCORE.items() if score >= DIFFICULT_RATING)
NOT_DIFFICULT_OPTIONS = tuple(option for option, score in DIFFICULTY_SCORE.items() if score < DIFFICULT_RATING)
POPULATION_COLUMNS = [
    "p3_pid", "s3_pid", "group", "benefit", "pct_bloomer", "pct_mcq", "role", "ai_use", "cme_hours", "preference",
    "bloomer_difficulty", "prior_knowledge", "total_attempts", "total_minutes", "perceived_better",
    "completion_date", "s3_completion_date", "interval_days",
]
# factor -> ((level label, column, values), (level label, column, values)); the first three are Part B's (B7).
CONTRASTS = {
    **{factor: SUBGROUP_FACTORS[factor] for factor in ("role", "ai_use", "cme_hours")},
    "preference": (("Preferred Bloomer (Q25)", "preference", (PREFERENCE_BLOOMER,)),
                   ("Preferred the quiz (Q25)", "preference", (PREFERENCE_QUIZ,))),
    "perceived_better": (("Said Bloomer helped retention more", "perceived_better", (PERCEIVED_BLOOMER,)),
                         ("Said the quiz helped retention more", "perceived_better", (PERCEIVED_MCQ,))),
    "bloomer_difficulty": (("Rated Bloomer difficult (Q24, 4-5)", "bloomer_difficulty", DIFFICULT_OPTIONS),
                           ("Rated Bloomer not difficult (Q24, 1-3)", "bloomer_difficulty", NOT_DIFFICULT_OPTIONS)),
}
CONTRAST_LABELS = {
    "role": "Retention benefit by role",
    "ai_use": "Retention benefit by prior AI use",
    "cme_hours": "Retention benefit by CME hours per week",
    "preference": "Retention benefit by stated preference (Q25)",
    "perceived_better": "Retention benefit by perceived benefit (Phase 3)",
    "bloomer_difficulty": "Retention benefit by rated Bloomer difficulty (Q24)",
}
EQUAL_WEIGHT_LABEL = "Retention benefit, equal group weights"
# D8 tracks one scalar per D2-D7 estimate across assignments.
ESTIMATE_LABELS = {
    "d2_theta_equal_weight": "D2 retention benefit, equal group weights",
    "d2_mean_benefit": "D2 mean retention benefit",
    "d2_median_benefit": "D2 median retention benefit",
    **{f"d3_{factor}": f"D3 {label}, difference in means" for factor, label in CONTRAST_LABELS.items()},
    "d4_adjusted_benefit": "D4 retention benefit adjusted for prior knowledge",
    "d5_point_biserial": "D5 point-biserial correlation of benefit with preferring Bloomer",
    "d6_rho_attempts": "D6 Spearman rho, benefit vs total Bloomer attempts",
    "d6_rho_minutes": "D6 Spearman rho, benefit vs total Bloomer minutes",
    "d7_median_interval": "D7 median retention interval, days",
    "d7_rho_benefit": "D7 Spearman rho, interval vs benefit",
    "d7_rho_bloomer_score": "D7 Spearman rho, interval vs the Bloomer-studied score",
}
ROSTER_STAT_KEYS = ("n_roster_rows", "n_by_name_method", "n_by_method", "n_links", "n_certain",
                    "n_certain_collisions_demoted", "n_ambiguous_groups", "ambiguous_group_sizes", "n_assignments",
                    "assignments_truncated", "n_unmatched_roster", "n_unmatched_roster_phase3",
                    "n_unmatched_roster_survey3", "n_unmatched_phase3", "n_part2_time_unparsed")


# ---- guards and small helpers ---------------------------------------------------------------------------------
def _too_few(n: int) -> dict | None:
    # "contributing", not "linked": callers pass what the analysis actually uses - the two level counts (D3), the
    # decided respondents (D5), the non-missing pairs (D6, D7) - which is usually fewer than the linked people.
    if n < MIN_PEOPLE:
        return {"estimable": False, "n": int(n), "reason": f"fewer than {MIN_PEOPLE} contributing people (n = {n})"}
    return None


def _too_few_in_a_level(counts: dict[str, int]) -> dict | None:
    thin = [f"{label} n = {n}" for label, n in counts.items() if n < MIN_PER_LEVEL]
    if thin:
        return {"estimable": False, "n": int(sum(counts.values())),
                "reason": f"fewer than {MIN_PER_LEVEL} people in a level ({'; '.join(thin)})"}
    return None


def _t_interval(estimate: float, variance: float, df: float) -> dict:
    """Two-sided t 95% CI and P value for an estimate with the given variance and degrees of freedom."""
    half = float(stats.t.ppf(0.975, df) * math.sqrt(variance))
    p_value = float(2 * stats.t.sf(abs(estimate) / math.sqrt(variance), df))
    return {"ci_low": estimate - half, "ci_high": estimate + half, "df": float(df), "p_value": p_value}


def certain_flags(links: pd.DataFrame) -> np.ndarray:
    """The roster link's `certain` column as booleans.

    Raises ValueError when a value is not True or False (a string, a number or a missing value), because a truthy
    cast would read "False" as certain and silently promote an ambiguous link (as matching.same_group_flags does).
    """
    column = links["certain"]
    if not all(isinstance(value, (bool, np.bool_)) for value in column):
        raise ValueError("certain must hold only True or False")
    return column.to_numpy(dtype=bool)


def _spearman(x: pd.Series, y: pd.Series, label: str) -> dict:
    """Spearman rho over the pairs where both values are present, with the Part D guards."""
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    guard = _too_few(len(frame))
    if guard is not None:
        return {"label": label, **guard}
    if frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
        return {"label": label, "estimable": False, "n": int(len(frame)), "reason": "no variance in one of the ranks"}
    result = stats.spearmanr(frame["x"], frame["y"])
    return {"label": label, "estimable": True, "n": int(len(frame)), "rho": float(result.statistic),
            "p_value": float(result.pvalue)}


# ---- D1 population --------------------------------------------------------------------------------------------
def partd_population(links: pd.DataFrame, wide: pd.DataFrame, phase3_pop: pd.DataFrame, survey_pop: pd.DataFrame,
                     name_methods: tuple[str, ...] = HEADLINE_NAME_METHODS) -> tuple[pd.DataFrame, dict]:
    """One row per certain-linked person with both article scores, plus the Part A -> Part D flow.

    benefit = Bloomer-studied minus MCQ-studied 1-month score (group A: pct_b - pct_a; group B: pct_a - pct_b),
    from Part A's per-participant scores. interval_days is the Survey 3 to Phase 3 completion gap (D7).

    `name_methods` selects the roster name-matching steps the population accepts. The headline keeps only the two
    strong ones; D8 repeats the analyses over ALL_NAME_METHODS as its "including weaker name matches" variant.
    """
    linked = links[certain_flags(links)]
    strong = linked["name_method"].isin(name_methods)
    n_weak = int((~strong).sum())
    certain = linked[strong]
    scores = wide.set_index("pid")
    phase3 = phase3_pop.set_index("pid")
    survey = survey_pop.set_index("pid")
    totals = {field: pd.Series(person_totals(survey_pop, field).to_numpy(), index=survey_pop["pid"])
              for field in ("attempts", "minutes")}
    excluded = {"not_in_phase3_population": 0, "not_in_survey3_population": 0, "without_both_scores": 0}
    rows = []
    for s3_pid, p3_pid in zip(certain["s3_pid"], certain["p3_pid"]):
        if p3_pid not in scores.index or p3_pid not in phase3.index:
            excluded["not_in_phase3_population"] += 1
            continue
        if s3_pid not in survey.index:
            excluded["not_in_survey3_population"] += 1
            continue
        score, response, answers = scores.loc[p3_pid], phase3.loc[p3_pid], survey.loc[s3_pid]
        if not (_present(score["pct_a"]) and _present(score["pct_b"])):
            excluded["without_both_scores"] += 1
            continue
        bloomer, mcq = (("pct_b", "pct_a") if score["group"] == "A" else ("pct_a", "pct_b"))
        # Nothing validates completion_date as non-null at ingest; a missing one leaves this person's interval
        # missing (D7 drops it) instead of stopping the whole of Part D.
        gap = pd.Timestamp(response["completion_date"]) - pd.Timestamp(answers["completion_date"])
        rows.append({
            "p3_pid": p3_pid, "s3_pid": s3_pid, "group": score["group"],
            "benefit": float(score[bloomer]) - float(score[mcq]),
            "pct_bloomer": float(score[bloomer]), "pct_mcq": float(score[mcq]),
            **{column: answers[column] for column in
               ("role", "ai_use", "cme_hours", "preference", "bloomer_difficulty", "prior_knowledge")},
            "total_attempts": totals["attempts"].get(s3_pid), "total_minutes": totals["minutes"].get(s3_pid),
            "perceived_better": response["perceived_better"], "completion_date": response["completion_date"],
            "s3_completion_date": answers["completion_date"],
            "interval_days": None if pd.isna(gap) else int(gap.days),
        })
    pop = pd.DataFrame(rows, columns=POPULATION_COLUMNS)
    flow = {
        "phase3_analysed": int(len(phase3_pop)),
        "survey3_analysed": int(len(survey_pop)),
        "roster_links": int(len(links)),
        "certain_links": int(len(linked)),
        "ambiguous_links": int(len(links) - len(linked)),
        "excluded_weak_name_match": n_weak,
        **{f"excluded_{reason}": count for reason, count in excluded.items()},
        "analysed": int(len(pop)),
        "analysed_group_A": int((pop["group"] == "A").sum()),
        "analysed_group_B": int((pop["group"] == "B").sum()),
    }
    return pop, flow


def part1_certain_pairs(links_part1: pd.DataFrame, mcq_scores: pd.DataFrame,
                        survey_pop: pd.DataFrame) -> dict[str, str]:
    """Chain to Part 1: the certain Survey 3 -> MCQ form pairs, i.e. the best date-weighted same-group matching's
    pairs with no rival candidate within +/-24 hours (SAP D1, Part C's clear-pair rule)."""
    mcq_groups, s3_groups = _lookup(mcq_scores, "group"), _lookup(survey_pop, "group")
    edges = restrict_edges(links_part1, "mcq_pid", "s3_pid", mcq_groups, s3_groups)
    weights = (np.array([part1_weight(gap) for gap in edges["gap_hours"]], dtype=float)
               * same_group_flags(edges).astype(float))
    best = best_matching(edges, "mcq_pid", "s3_pid", weights)
    positive = edges[weights > 0].reset_index(drop=True)
    return clear_pairs(positive, best, "mcq_pid", "s3_pid", "gap_hours", CLEAR_MARGIN["part1"])


def link_quality(links: pd.DataFrame, roster_stats: dict, pop: pd.DataFrame, part1_pairs: dict[str, str]) -> dict:
    """D1: roster link counts by method and certainty, people with a chained MCQ form, and the Part D population."""
    certain = links[certain_flags(links)]
    return {
        **{key: roster_stats[key] for key in ROSTER_STAT_KEYS if key in roster_stats},
        "n_ambiguous_links": int(len(links) - len(certain)),
        # Certain only: an ambiguous weak link enters nothing - not the headline, not the D8 "weaker names"
        # variant (certain links only), not any assignment population - so counting it here would misreport it.
        "n_weak_name_links": int(certain["name_method"].isin(WEAK_NAME_METHODS).sum()),
        "n_with_mcq_form": int(pop["s3_pid"].isin(set(part1_pairs)).sum()),
        "n_partd_population": int(len(pop)),
    }


# ---- D2 -------------------------------------------------------------------------------------------------------
def _paper_scores(pop: pd.DataFrame) -> pd.DataFrame:
    """The Part D population in Part A's wide shape: group, the Paper A score and the Paper B score per person.

    Group A studied Paper A with the MCQ and Paper B with Bloomer, group B the other way round (SAP section 2), so
    this inverts the population's Bloomer/MCQ columns back into paper columns for `crossover_ttest`.
    """
    is_a = pop["group"].to_numpy() == "A"
    return pd.DataFrame({
        "group": pop["group"].to_numpy(),
        "pct_a": np.where(is_a, pop["pct_mcq"], pop["pct_bloomer"]),
        "pct_b": np.where(is_a, pop["pct_bloomer"], pop["pct_mcq"]),
    })


def equal_weight_benefit(pop: pd.DataFrame) -> dict:
    """D2: Part A's estimand restricted to the linked people - section 7's closed-form crossover estimator.

    theta = (mean d_B - mean d_A) / 2 weights the two sequence groups equally, which is what removes the article
    (paper) effect (SAP section 6); `benefit_summary`'s per-person mean weights people equally and so keeps that
    effect whenever the groups differ in size. The estimator itself is Part A's `crossover_ttest`, unmodified, so
    the two parts cannot drift apart; it raises on a thin or flat group, which the Part D guards turn into a
    reason.
    """
    frame = _paper_scores(pop)
    counts = {"group A": int((frame["group"] == "A").sum()), "group B": int((frame["group"] == "B").sum())}
    guard = _too_few(len(frame)) or _too_few_in_a_level(counts)
    if guard is not None:
        return guard
    try:
        estimate = crossover_ttest(frame, "pct_a", "pct_b", EQUAL_WEIGHT_LABEL)
    except ValueError as error:  # no within-group variance: the pooled standard error is 0
        return {"estimable": False, "n": int(len(frame)), "reason": str(error)}
    return {"estimable": True, "n": int(len(frame)), **asdict(estimate)}


def benefit_summary(pop: pd.DataFrame) -> dict:
    """D2: the mean per-person retention benefit among the linked people; n, mean (SD), median (IQR) and a
    one-sample t 95% CI against 0. This describes the linked people and is person-weighted: it is not Part A's
    estimand, which `equal_weight_benefit` computes."""
    values = pop["benefit"].dropna().astype(float)
    guard = _too_few(len(values))
    if guard is not None:
        return guard
    summary = describe(values)
    sd = float(values.std(ddof=1))
    variance = sd ** 2 / len(values)
    if not variance > 0:
        return {"estimable": False, "n": int(len(values)), "reason": "no variance in the retention benefit"}
    mean = float(values.mean())
    return {"estimable": True, "n": int(len(values)), "mean": mean, "sd": sd, "median": summary["median"],
            "q1": summary["q1"], "q3": summary["q3"], **_t_interval(mean, variance, len(values) - 1),
            "test": "one-sample t against 0"}


# ---- D3 -------------------------------------------------------------------------------------------------------
def subgroup_contrasts(pop: pd.DataFrame) -> list[dict]:
    """D3: six unadjusted Welch contrasts of the retention benefit, each with the n of both levels."""
    contrasts = []
    for factor, levels in CONTRASTS.items():
        values = {label: pop.loc[pop[column].isin(options), "benefit"].dropna().astype(float).tolist()
                  for label, column, options in levels}
        labels = list(values)
        counts = {label: len(series) for label, series in values.items()}
        entry = {"factor": factor, "label": CONTRAST_LABELS[factor],
                 "levels": [{"level": label, "n": counts[label],
                             "mean": float(np.mean(values[label])) if counts[label] else None} for label in labels]}
        guard = _too_few(sum(counts.values())) or _too_few_in_a_level(counts)
        if guard is not None:
            contrasts.append({**entry, **guard})
            continue
        welch = _welch(values[labels[0]], values[labels[1]])
        if welch is None:
            contrasts.append({**entry, "estimable": False, "n": sum(counts.values()),
                              "reason": "no variance in a level"})
            continue
        difference, variance, df = welch
        contrasts.append({**entry, "estimable": True, "n": sum(counts.values()), "difference": difference,
                          **_t_interval(difference, variance, df), "test": "Welch t, first level minus second"})
    return contrasts


# ---- D4 -------------------------------------------------------------------------------------------------------
def adjusted_benefit(pop: pd.DataFrame, mcq_scores: pd.DataFrame, part1_pairs: dict[str, str]) -> dict:
    """D4: OLS of benefit on group code (+0.5 A, -0.5 B) and prior-knowledge difference, over people whose Survey 3
    response has a certain Part 1 MCQ form. The intercept is the benefit at equal prior knowledge and equal group
    weights, reported beside Part C's C5.1 probabilistic version."""
    prior = _lookup(mcq_scores, "prior_knowledge")
    rows = []
    for record in pop.to_dict("records"):
        mcq_pid = part1_pairs.get(record["s3_pid"])
        if mcq_pid is None or mcq_pid not in prior:
            continue
        if not (_present(record["prior_knowledge"]) and _present(prior[mcq_pid])):
            continue
        rows.append((record["benefit"], 0.5 if record["group"] == "A" else -0.5,
                     float(record["prior_knowledge"]) - float(prior[mcq_pid])))
    n_with_form = int(sum(1 for record in pop.to_dict("records") if record["s3_pid"] in part1_pairs))
    codes = [code for _, code, _ in rows]
    guard = _too_few(len(rows)) or _too_few_in_a_level({"group A": codes.count(0.5), "group B": codes.count(-0.5)})
    if guard is not None:
        return {**guard, "n_with_mcq_form": n_with_form}
    fit = _adjusted_intercept([diff for diff, _, _ in rows], codes, [pk for _, _, pk in rows])
    if fit is None:
        return {"estimable": False, "n": len(rows), "n_with_mcq_form": n_with_form,
                "reason": "rank-deficient design or no residual variance"}
    estimate, variance = fit
    return {"estimable": True, "n": len(rows), "n_with_mcq_form": n_with_form, "estimate": estimate,
            **_t_interval(estimate, variance, len(rows) - 3),
            "test": "OLS intercept, benefit ~ 1 + group code + prior-knowledge difference"}


# ---- D5 -------------------------------------------------------------------------------------------------------
def preference_vs_benefit(pop: pd.DataFrame) -> dict:
    """D5: point-biserial correlation of benefit with preferring Bloomer (Q25), and a 2x2 of preference against a
    benefit above zero with Fisher's exact test."""
    decided = pop[pop["preference"].isin([PREFERENCE_BLOOMER, PREFERENCE_QUIZ])].dropna(subset=["benefit"])
    prefers = (decided["preference"] == PREFERENCE_BLOOMER).to_numpy()
    counts = {"preferred Bloomer": int(prefers.sum()), "preferred the quiz": int((~prefers).sum())}
    table = [[int(((decided["benefit"] > 0) & prefers).sum()), int(((decided["benefit"] <= 0) & prefers).sum())],
             [int(((decided["benefit"] > 0) & ~prefers).sum()), int(((decided["benefit"] <= 0) & ~prefers).sum())]]
    entry = {"counts": counts, "table": table,
             "table_note": "rows: preferred Bloomer, preferred the quiz; columns: benefit above 0, benefit 0 or below"}
    benefit = decided["benefit"].astype(float)
    guard = _too_few(len(decided)) or _too_few_in_a_level(counts)
    if guard is not None:
        return {**entry, **guard}
    if benefit.nunique() < 2:  # a constant benefit makes the correlation nan, with a ConstantInputWarning (as D2)
        return {**entry, "estimable": False, "n": int(len(decided)),
                "reason": "no variance in the retention benefit"}
    result = stats.pointbiserialr(prefers, benefit)
    fisher = stats.fisher_exact(table)
    # scipy's odds ratio is a x d / (b x c) over [[a, b], [c, d]], so only a zero in b or c makes it inf or nan -
    # a zero in a or d gives a finite 0.0, which is a real estimate and is reported as one. inf and nan would
    # otherwise reach the report as None and break its formatting, losing the whole of Part D (SAP D5).
    finite_odds = math.isfinite(float(fisher.statistic))
    return {**entry, "estimable": True, "n": int(len(decided)), "point_biserial": float(result.statistic),
            "p_value": float(result.pvalue),
            "odds_ratio": float(fisher.statistic) if finite_odds else None,
            "fisher_p_value": float(fisher.pvalue),
            "test": "point-biserial correlation; Fisher's exact test on the 2x2"}


# ---- D6 -------------------------------------------------------------------------------------------------------
def usage_vs_benefit(pop: pd.DataFrame) -> dict:
    """D6: Spearman correlations of the retention benefit with total Bloomer attempts and with total minutes."""
    return {
        "attempts": _spearman(pop["total_attempts"], pop["benefit"], "Total Bloomer attempts vs benefit"),
        "minutes": _spearman(pop["total_minutes"], pop["benefit"], "Total Bloomer minutes vs benefit"),
    }


# ---- D7 -------------------------------------------------------------------------------------------------------
def retention_interval(pop: pd.DataFrame) -> dict:
    """D7: days from the Survey 3 completion date to the Phase 3 completion date; median (IQR) and Spearman
    correlations with the benefit and with the Bloomer-studied score."""
    days = pop["interval_days"].dropna().astype(float)
    entry = {"vs_benefit": _spearman(pop["interval_days"], pop["benefit"], "Retention interval vs benefit"),
             "vs_bloomer_score": _spearman(pop["interval_days"], pop["pct_bloomer"],
                                           "Retention interval vs the Bloomer-studied score")}
    guard = _too_few(len(days))
    if guard is not None:
        return {**entry, **guard}
    return {**entry, "estimable": True, **describe(days)}


# ---- D8 -------------------------------------------------------------------------------------------------------
def _scalar_estimates(pop: pd.DataFrame, mcq_scores: pd.DataFrame, part1_pairs: dict[str, str]) -> dict:
    """One scalar per D2-D7 estimate (None when that analysis is not estimable), for the D8 ranges."""
    benefit = benefit_summary(pop)
    adjusted = adjusted_benefit(pop, mcq_scores, part1_pairs)
    preference = preference_vs_benefit(pop)
    usage = usage_vs_benefit(pop)
    interval = retention_interval(pop)

    def value(entry: dict, key: str) -> float | None:
        return float(entry[key]) if entry.get("estimable") and entry.get(key) is not None else None

    estimates = {"d2_theta_equal_weight": value(equal_weight_benefit(pop), "theta"),
                 "d2_mean_benefit": value(benefit, "mean"), "d2_median_benefit": value(benefit, "median")}
    for contrast in subgroup_contrasts(pop):
        estimates[f"d3_{contrast['factor']}"] = value(contrast, "difference")
    estimates["d4_adjusted_benefit"] = value(adjusted, "estimate")
    estimates["d5_point_biserial"] = value(preference, "point_biserial")
    estimates["d6_rho_attempts"] = value(usage["attempts"], "rho")
    estimates["d6_rho_minutes"] = value(usage["minutes"], "rho")
    estimates["d7_median_interval"] = value(interval, "median")
    estimates["d7_rho_benefit"] = value(interval["vs_benefit"], "rho")
    estimates["d7_rho_bloomer_score"] = value(interval["vs_bloomer_score"], "rho")
    return estimates


def alternatives_sensitivity(alternatives: pd.DataFrame, links: pd.DataFrame, wide: pd.DataFrame,
                             phase3_pop: pd.DataFrame, survey_pop: pd.DataFrame, mcq_scores: pd.DataFrame,
                             part1_pairs: dict[str, str]) -> dict:
    """D8: every D2-D7 estimate recomputed over each enumerated assignment, as the range across assignments.

    Each assignment holds the certain links plus one consistent choice for every ambiguous date group, so every
    assignment is a "with ambiguous links" variant; assignment 0 is the primary one and is reported on its own.
    The assignments keep the headline name-matching rule; a further variant adds the weaker name matches back
    under the primary assignment. Every alternative pair keeps its roster entry's Phase 3 row, so the name method
    is looked up by `p3_pid`; a pair whose Phase 3 row is not in `links` is treated as a weak match.
    """
    by_row = dict(zip(links["p3_pid"], links["name_method"]))
    per_assignment: dict[int, dict] = {}
    for assignment_id, frame in alternatives.groupby("assignment_id", sort=True):
        assigned = frame[["s3_pid", "p3_pid"]].assign(
            name_method=[by_row.get(p3, WEAK_NAME_METHODS[0]) for p3 in frame["p3_pid"]],
            method="enumerated", certain=True)
        pop, _ = partd_population(assigned, wide, phase3_pop, survey_pop)
        per_assignment[int(assignment_id)] = {"n": int(len(pop)),
                                              **_scalar_estimates(pop, mcq_scores, part1_pairs)}
    weaker_pop, _ = partd_population(links, wide, phase3_pop, survey_pop, name_methods=ALL_NAME_METHODS)
    weaker = ({"n": int(len(weaker_pop)), **_scalar_estimates(weaker_pop, mcq_scores, part1_pairs)}
              if len(links) else None)
    ranges = {}
    for key in ESTIMATE_LABELS:
        values = [entry[key] for entry in per_assignment.values() if entry.get(key) is not None]
        ranges[key] = {"label": ESTIMATE_LABELS[key], "n_estimable": len(values),
                       "min": min(values) if values else None, "max": max(values) if values else None}
    sizes = [entry["n"] for entry in per_assignment.values()]
    return {
        "n_assignments": len(per_assignment),
        "n_people": {"min": min(sizes) if sizes else None, "max": max(sizes) if sizes else None},
        "ranges": ranges,
        "with_ambiguous": per_assignment.get(0),
        "with_weaker_names": weaker,
    }
