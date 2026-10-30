"""Part C: cross-phase analyses without identifiers (SAP Part C, C1-C5). Every analysis is exploratory.

C1-C3 need no linking. C4 and C5 are recomputed in every sampled matching (matching.py) and pooled with Rubin's
rules over the draws in which they are estimable, beside the same analyses on random-reference matchings.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

from bloomer_retention.crossover import PP, crossover_ttest
from bloomer_retention.matching import (
    all_pairs_edges,
    best_matching,
    clear_pairs,
    part1_weight,
    phase3_weight,
    reference_weights,
    restrict_edges,
    same_group_flags,
    sample_matchings,
    stable_pair_count,
)
from bloomer_retention.start_form import START_OPTIONS
from bloomer_retention.survey3 import ATTENDING, PREFERENCE_BLOOMER, PREFERENCE_QUIZ, TRAINEE
from bloomer_retention.survey3_forms import DIFFICULTY_SCORE

GROUPS = ("A", "B")
ROLE_OPTIONS = START_OPTIONS["role"]
MIN_LINKED = 5  # a draw with fewer linked people is not estimable (SAP C7)
MIN_PER_LEVEL = 2  # nor with fewer than 2 in any level or group the analysis needs
Z_95 = 1.96
REFERENCE_BAND = (2.5, 97.5)  # "differs from random matching" when the percentile is outside (SAP C7)
CLEAR_MARGIN = {"part1": 24.0, "phase3": 3.0}  # hours, days
SEED_OFFSETS = {"date_part1": 0, "reference_part1": 1, "group_check_with_dates": 2, "group_check_without_dates": 3,
                "date_phase3": 4, "reference_phase3": 5}
# key -> (SAP section, label, unit, pooling scale)
LINKED_ESTIMANDS = {
    "prior_knowledge_difference": ("C4.1", "Prior knowledge, MCQ article (MCQ form) minus Bloomer article (Survey 3)",
                                   "rating points (1-10)", "mean"),
    "score_by_preference": ("C4.2", "Immediate MCQ score, preferred Bloomer minus preferred quiz (Q25)", PP, "mean"),
    "score_vs_quiz_difficulty": ("C4.3", "Immediate MCQ score vs quiz difficulty (Q23), Spearman rho", "rho",
                                 "fisher_z"),
    "adjusted_theta": ("C5.1", "Retention theta adjusted for prior knowledge (Bloomer minus MCQ at equal prior "
                               "knowledge, equal group weights)", PP, "mean"),
    "forgetting_mcq_arm": ("C5.2", "Forgetting on the MCQ-studied article in matched forms: 1 month minus immediate",
                           PP, "mean"),
    "diff_by_preference": ("C5.3", "Bloomer minus MCQ retention, preferred Bloomer minus preferred quiz (Q25)", PP,
                           "mean"),
    "diff_by_role": ("C5.3", "Bloomer minus MCQ retention, attendings minus trainees", PP, "mean"),
}
# Static notes for analyses that barely depend on who is paired with whom (SAP C4.1, C5.2); no statistic behind them.
ESTIMAND_NOTES = {
    "prior_knowledge_difference": (
        "When every Survey 3 form is matched, the paired mean difference depends only on which MCQ forms are drawn, "
        "not on who is paired with whom, so it restates the unlinked group comparison of prior-knowledge ratings and "
        "adds no person-level evidence."),
    "forgetting_mcq_arm": (
        "This mean barely depends on who is paired with whom: when (nearly) every Phase 3 form is matched in each "
        "draw, it is the mean 1-month score minus the mean immediate score of MCQ forms drawn in proportion to the "
        "Phase 3 group sizes. It restates the unlinked C3 comparison weighted by Phase 3 group sizes, so it adds no "
        "person-level evidence."),
}


# ---- small helpers ------------------------------------------------------------------------------------------
def _present(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value)) and value is not pd.NA


def _lookup(frame: pd.DataFrame, column: str) -> dict:
    return dict(zip(frame["pid"], frame[column]))


def _counts(values: pd.Series, options: tuple[str, ...]) -> dict[str, int]:
    counts = {option: int((values == option).sum()) for option in options}
    counts["blank"] = int(values.isna().sum())
    return counts


def _quantiles(values: list[float], transform: Callable[[float], float] = float) -> dict:
    if not values:
        return {"median": None, "p2_5": None, "p97_5": None}
    array = np.asarray(values, dtype=float)
    return {"median": transform(float(np.median(array))), "p2_5": transform(float(np.percentile(array, 2.5))),
            "p97_5": transform(float(np.percentile(array, 97.5)))}


def _mean_variance(values: list[float]) -> tuple[float, float] | None:
    """Mean and its variance from the one-sample (or paired) t: var / n."""
    x = np.asarray(values, dtype=float)
    if len(x) < MIN_LINKED:
        return None
    variance = float(x.var(ddof=1) / len(x))
    return (float(x.mean()), variance) if variance > 0 else None


def _welch(first: list[float], second: list[float]) -> tuple[float, float, float] | None:
    """Difference in means (first - second), its Welch variance and Welch-Satterthwaite df."""
    x, y = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if len(x) < MIN_PER_LEVEL or len(y) < MIN_PER_LEVEL:
        return None
    vx, vy = x.var(ddof=1) / len(x), y.var(ddof=1) / len(y)
    variance = vx + vy
    if not variance > 0:
        return None
    df = variance ** 2 / (vx ** 2 / (len(x) - 1) + vy ** 2 / (len(y) - 1))
    return float(x.mean() - y.mean()), float(variance), float(df)


def _linked_welch(first: list[float], second: list[float]) -> tuple[float, float] | None:
    if len(first) + len(second) < MIN_LINKED:
        return None
    result = _welch(first, second)
    return None if result is None else result[:2]


def _spearman_z(x: list[float], y: list[float]) -> tuple[float, float] | None:
    """Spearman rho on Fisher's z with variance 1 / (n - 3)."""
    if len(x) < MIN_LINKED or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    rho = float(stats.spearmanr(x, y).statistic)
    if not math.isfinite(rho) or abs(rho) >= 1:
        return None
    return math.atanh(rho), 1 / (len(x) - 3)


def _adjusted_intercept(diff: list[float], code: list[float], pk_diff: list[float]) -> tuple[float, float] | None:
    """OLS of diff on 1 + group code (+0.5 A, -0.5 B) + uncentred pk_diff: the intercept and its variance."""
    n = len(diff)
    x = np.column_stack([np.ones(n), np.asarray(code, dtype=float), np.asarray(pk_diff, dtype=float)])
    if n < MIN_LINKED or np.linalg.matrix_rank(x) < 3:
        return None
    y = np.asarray(diff, dtype=float)
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    residual = y - x @ beta
    variance = float(residual @ residual / (n - 3) * xtx_inv[0, 0])
    return (float(beta[0]), variance) if variance > 0 else None


# ---- C1 ------------------------------------------------------------------------------------------------------
ELIGIBLE_DAYS = 28  # follow-up-eligible Part 1 forms: start_date on or before freeze_date minus this many days (SAP v2.6)


def _return_rates(part1: dict[str, int], returned: dict[str, int]) -> dict:
    by_group = {group: {"n_part1": part1[group], "n_returned": returned[group],
                        "pct": 100 * returned[group] / part1[group] if part1[group] else None} for group in GROUPS}
    table = [[returned[group], part1[group] - returned[group]] for group in GROUPS]
    p_value, note = None, None
    if any(cell < 0 for row in table for cell in row):
        note = "more returns than Part 1 MCQ forms in a group (the forms are unlinked); Fisher's exact test not run"
    elif all(part1[group] for group in GROUPS):
        p_value = float(stats.fisher_exact(table).pvalue)
    return {"by_group": by_group, "p_value": p_value, "test": "Fisher's exact test, group A vs group B",
            "note": note}


def _role_mix(roles: pd.Series) -> dict[str, dict]:
    counts = _counts(roles, ROLE_OPTIONS)
    return {role: {"n": n, "pct": 100 * n / len(roles) if len(roles) else None} for role, n in counts.items()}


def _npi_unmatched_flags(start: pd.DataFrame) -> pd.Series:
    """start.csv's `npi_unmatched` as booleans (SAP v3.2); all False for a file written before the column existed."""
    if "npi_unmatched" not in start.columns:
        return pd.Series(False, index=start.index)
    flags = start["npi_unmatched"].map(lambda value: {True: True, False: False, "True": True,
                                                      "False": False}.get(value))
    if flags.isna().any():
        raise ValueError(f"start.csv: {int(flags.isna().sum())} npi_unmatched value(s) neither True nor False")
    return flags.astype(bool)


def flow_and_returns(start: pd.DataFrame, mcq_scores_by_paper: dict[str, pd.DataFrame], survey_pop: pd.DataFrame,
                     phase3_pop: pd.DataFrame, study_start: date, freeze_date: date) -> dict:
    """C1: signups by role, form counts by group and in total, return rates by group with Fisher's exact P, role mix.

    Start signups exclude pilot rows (signup_date before study_start), signups after freeze_date and (SAP v3.2) the
    remaining signups flagged `npi_unmatched`, each row counted under the first of those rules that applies;
    analysed signups answering No to US-based are counted and stay in every count (SAP C6). Part 1 counts are the
    MCQ form populations (Paper A form = group A); Survey 3 and Phase 3 use their analysis populations.

    returns_eligible and date_ranges (SAP v2.6 C1): the denominator is restricted to Part 1 MCQ forms
    started on or before freeze_date minus ELIGIBLE_DAYS, inclusive (cutoff), so a return is counted only when there
    was enough time for one; the numerator is still the full Phase 3 population.
    """
    signup = pd.to_datetime(start["signup_date"]).dt.date
    pilot, after_freeze = signup < study_start, signup > freeze_date
    npi_unmatched = _npi_unmatched_flags(start) & ~pilot & ~after_freeze
    signups = start[~pilot & ~after_freeze & ~npi_unmatched]
    # Each total counts its own population, never the two groups added up: a Survey 3 response without a Bloomer
    # paper belongs to no group but is still in the population (survey3_without_group below counts them).
    part1 = {group: int(len(mcq_scores_by_paper[group])) for group in GROUPS}
    part1["total"] = int(sum(len(mcq_scores_by_paper[group]) for group in GROUPS))  # one MCQ form file per paper
    survey = {group: int((survey_pop["group"] == group).sum()) for group in GROUPS}
    survey["total"] = int(len(survey_pop))
    phase3 = {group: int((phase3_pop["group"] == group).sum()) for group in GROUPS}
    phase3["total"] = int(len(phase3_pop))
    cutoff = freeze_date - timedelta(days=ELIGIBLE_DAYS)
    eligible = {g: int((pd.to_datetime(mcq_scores_by_paper[g]["start_date"]).dt.date <= cutoff).sum())
               for g in GROUPS}
    eligible["total"] = eligible["A"] + eligible["B"]
    part1_dates = pd.concat([mcq_scores_by_paper[g]["start_date"] for g in GROUPS])
    p3_dates = phase3_pop["completion_date"]
    return {
        "start": {"deidentified": int(len(start)), "excluded_pilot": int(pilot.sum()),
                  "excluded_after_freeze": int((after_freeze & ~pilot).sum()),
                  "excluded_npi_unmatched": int(npi_unmatched.sum()), "analysed": int(len(signups)),
                  "analysed_not_us_based": int((signups["us_based"] == "No").sum()),
                  "by_role": _counts(signups["role"], ROLE_OPTIONS)},
        "counts_by_group": {"part1_mcq": part1, "survey3": survey, "phase3": phase3},
        "survey3_without_group": int(survey_pop["group"].isna().sum()),
        "returns": {"survey3": _return_rates(part1, survey), "phase3": _return_rates(part1, phase3)},
        "role_mix": {"signup": _role_mix(signups["role"]), "survey3": _role_mix(survey_pop["role"])},
        "returns_eligible": {"cutoff": cutoff.isoformat(), "part1_eligible": eligible,
                             "phase3": _return_rates(eligible, phase3)},
        "date_ranges": {"part1": [str(part1_dates.min()), str(part1_dates.max())],
                        "phase3": [str(p3_dates.min()), str(p3_dates.max())] if len(p3_dates) else [None, None]},
    }


# ---- C2 ------------------------------------------------------------------------------------------------------
def _ci_excludes_zero(estimate) -> bool:
    return estimate.ci_low > 0 or estimate.ci_high < 0


def tipping_point(wide: pd.DataFrame, max_k: int = 5) -> dict:
    """C2: relabel every size-k subset of one group's Phase 3 responses as the other group and recompute the headline
    crossover t, for k = 1 ... min(max_k, n_source - 2), in both directions.

    Per k: number of subsets, subsets not estimable, min and max theta, the share of estimable subsets whose 95% CI
    excludes 0 and the numbers whose CI lies wholly above 0 (ci_low > 0) and wholly below 0 (ci_high < 0); per
    direction the smallest k at which any subset's CI excludes 0 (None if none), a worst case, not an estimate.
    """
    complete = wide.dropna(subset=["pct_a", "pct_b"]).reset_index(drop=True)
    try:
        head = crossover_ttest(complete, "pct_a", "pct_b", "observed")
        observed = {"theta": head.theta, "ci_low": head.ci_low, "ci_high": head.ci_high, "p_value": head.p_value}
    except ValueError:
        observed = None
    groups = complete["group"].to_numpy(dtype=object)
    directions = {}
    for source, target in (("B", "A"), ("A", "B")):
        members = np.flatnonzero(groups == source)
        rows, smallest = [], None
        for k in range(1, min(max_k, len(members) - 2) + 1):
            thetas, n_excludes, n_above, n_below, n_not_estimable = [], 0, 0, 0, 0
            for subset in itertools.combinations(members, k):
                relabelled = groups.copy()
                relabelled[list(subset)] = target
                try:
                    estimate = crossover_ttest(complete.assign(group=relabelled), "pct_a", "pct_b", "tipping point")
                except ValueError:
                    n_not_estimable += 1
                    continue
                thetas.append(estimate.theta)
                n_excludes += _ci_excludes_zero(estimate)
                n_above += estimate.ci_low > 0
                n_below += estimate.ci_high < 0
            rows.append({"k": k, "n_subsets": math.comb(len(members), k), "n_not_estimable": n_not_estimable,
                         "theta_min": min(thetas) if thetas else None, "theta_max": max(thetas) if thetas else None,
                         "share_ci_excludes_zero": n_excludes / len(thetas) if thetas else None,
                         "n_ci_above_zero": int(n_above), "n_ci_below_zero": int(n_below)})
            if smallest is None and n_excludes:
                smallest = k
        directions[f"{source}_to_{target}"] = {"n_source": int(len(members)), "by_k": rows,
                                               "smallest_k_ci_excludes_zero": smallest}
    observed_excludes = None if observed is None else bool(observed["ci_low"] > 0 or observed["ci_high"] < 0)
    return {"observed": observed, "observed_ci_excludes_zero": observed_excludes, "max_k": max_k,
            "directions": directions}


# ---- C3 ------------------------------------------------------------------------------------------------------
def forgetting_unlinked(mcq_scores_by_paper: dict[str, pd.DataFrame], wide: pd.DataFrame) -> dict:
    """C3: per paper, 1-month MCQ-studied score (group A on Paper A, group B on Paper B) minus the Part 1 immediate
    score on that paper, with a Welch 95% CI. Different respondents: a comparison of groups, not of people."""
    result = {}
    for paper in GROUPS:
        immediate = mcq_scores_by_paper[paper]["pct"].dropna().astype(float).tolist()
        month = wide.loc[wide["group"] == paper, f"pct_{paper.lower()}"].dropna().astype(float).tolist()
        row = {"paper": paper, "group": paper, "n_immediate": len(immediate),
               "mean_immediate": float(np.mean(immediate)) if immediate else None, "n_one_month": len(month),
               "mean_one_month": float(np.mean(month)) if month else None,
               "difference": None, "ci_low": None, "ci_high": None, "df": None}
        welch = _welch(month, immediate)
        if welch is not None:
            difference, variance, df = welch
            half = stats.t.ppf(0.975, df) * math.sqrt(variance)
            row.update(difference=difference, ci_low=difference - half, ci_high=difference + half, df=df)
        result[paper] = row
    return result



def forgetting_pooled(mcq_scores_by_paper: dict[str, pd.DataFrame], wide: pd.DataFrame) -> dict:
    """C3 pooled (v2.5): equal-weight mean over the two articles of the C3 difference, so the article cancels as it
    does in the primary estimand. Welch-Satterthwaite df over the four variance components. Different respondents:
    a comparison of forms, not of people."""
    parts, n_imm, n_month = [], 0, 0
    for paper in GROUPS:
        immediate = mcq_scores_by_paper[paper]["pct"].dropna().astype(float).to_numpy()
        month = wide.loc[wide["group"] == paper, f"pct_{paper.lower()}"].dropna().astype(float).to_numpy()
        n_imm, n_month = n_imm + len(immediate), n_month + len(month)
        parts.append((month, immediate))
    row = {"n_immediate": n_imm, "n_one_month": n_month,
           "difference": None, "ci_low": None, "ci_high": None, "df": None}
    if any(len(x) < MIN_PER_LEVEL for pair in parts for x in pair):
        return row
    comps = [(x.var(ddof=1) / len(x) / 4, len(x)) for pair in parts for x in pair]
    variance = sum(c for c, _ in comps)
    if not variance > 0:
        return row
    df = variance ** 2 / sum(c ** 2 / (n - 1) for c, n in comps)
    difference = float(np.mean([m.mean() - i.mean() for m, i in parts]))
    half = stats.t.ppf(0.975, df) * math.sqrt(variance)
    row.update(difference=difference, ci_low=difference - half, ci_high=difference + half, df=float(df))
    return row

# ---- pooling -------------------------------------------------------------------------------------------------
def rubin(estimates: list[float], variances: list[float]) -> dict:
    """Rubin's rules over M draws: q = mean q_m; T = mean u_m + (1 + 1/M) b; 95% CI q +/- 1.96 sqrt(T).

    Needs M >= 2 (the between-draw variance b is otherwise undefined); with fewer the estimate is None.
    """
    q, u = np.asarray(estimates, dtype=float), np.asarray(variances, dtype=float)
    m = int(len(q))
    if m < 2:
        return {"m": m, "estimate": None, "within_variance": None, "between_variance": None, "total_variance": None,
                "ci_low": None, "ci_high": None}
    q_bar, u_bar, b = float(q.mean()), float(u.mean()), float(q.var(ddof=1))
    total = u_bar + (1 + 1 / m) * b
    half = Z_95 * math.sqrt(total)
    return {"m": m, "estimate": q_bar, "within_variance": u_bar, "between_variance": b, "total_variance": total,
            "ci_low": q_bar - half, "ci_high": q_bar + half}


def reference_percentile(value: float | None, reference: list[float]) -> float | None:
    """Percentile of value among the reference per-draw estimates; ties count half.

    Values within 1e-9 (absolute or relative) count as ties, so an estimate that does not depend on the matching
    (for example a mean over people who are all matched in every draw) sits at the 50th percentile instead of
    wherever floating-point noise puts it.
    """
    if value is None or not reference:
        return None
    array = np.asarray(reference, dtype=float)
    tie = np.isclose(array, value, rtol=1e-9, atol=1e-9)
    return float(100 * (np.sum((array < value) & ~tie) + 0.5 * np.sum(tie)) / len(array))


# ---- C4 and C5 per matching ----------------------------------------------------------------------------------
def part1_person_estimates(s3_to_mcq: dict[str, str], mcq_scores: pd.DataFrame,
                           survey_pop: pd.DataFrame) -> dict[str, tuple[float, float] | None]:
    """C4.1-C4.3 in one Survey 3 -> MCQ matching: (estimate, variance), or None when not estimable.

    C4.1 MCQ-article minus Bloomer-article prior knowledge (paired t); C4.2 immediate MCQ score, preferred Bloomer
    minus preferred quiz (Welch); C4.3 Spearman rho of immediate score and quiz difficulty on Fisher's z.
    """
    mcq_pct, mcq_prior = _lookup(mcq_scores, "pct"), _lookup(mcq_scores, "prior_knowledge")
    s3_prior, preference = _lookup(survey_pop, "prior_knowledge"), _lookup(survey_pop, "preference")
    difficulty = _lookup(survey_pop, "quiz_difficulty")
    pairs = [(s3, mcq) for s3, mcq in sorted(s3_to_mcq.items()) if s3 in s3_prior and mcq in mcq_pct]
    prior_difference = [float(mcq_prior[m]) - float(s3_prior[s]) for s, m in pairs
                        if _present(mcq_prior[m]) and _present(s3_prior[s])]
    scored = [(s, float(mcq_pct[m])) for s, m in pairs if _present(mcq_pct[m])]
    bloomer = [pct for s, pct in scored if preference[s] == PREFERENCE_BLOOMER]
    quiz = [pct for s, pct in scored if preference[s] == PREFERENCE_QUIZ]
    rated = [(pct, DIFFICULTY_SCORE[difficulty[s]]) for s, pct in scored if difficulty[s] in DIFFICULTY_SCORE]
    return {
        "prior_knowledge_difference": _mean_variance(prior_difference),
        "score_by_preference": _linked_welch(bloomer, quiz),
        "score_vs_quiz_difficulty": _spearman_z([pct for pct, _ in rated], [score for _, score in rated]),
    }


def phase3_person_estimates(p3_to_mcq: dict[str, str], s3_to_mcq: dict[str, str], wide: pd.DataFrame,
                            phase3_pop: pd.DataFrame, mcq_scores: pd.DataFrame,
                            survey_pop: pd.DataFrame) -> dict[str, tuple[float, float] | None]:
    """C5.1-C5.3 in one draw (Phase 3 -> MCQ matching plus the Survey 3 -> MCQ matching of the same draw).

    diff = Bloomer-studied minus MCQ-studied 1-month score (group A: pct_b - pct_a; group B: pct_a - pct_b).
    C5.1 intercept of OLS diff ~ 1 + group code + pk_diff (people with a linked Survey 3); C5.2 1-month score on the
    MCQ form's article minus the immediate score (one-sample t); C5.3 Welch differences in diff by preference and by
    role (attendings minus trainees), from the linked Survey 3.
    """
    in_population = set(phase3_pop["pid"])
    group, pct_a, pct_b = _lookup(wide, "group"), _lookup(wide, "pct_a"), _lookup(wide, "pct_b")
    mcq_group, mcq_pct, mcq_prior = (_lookup(mcq_scores, "group"), _lookup(mcq_scores, "pct"),
                                     _lookup(mcq_scores, "prior_knowledge"))
    s3_prior, preference, role = (_lookup(survey_pop, "prior_knowledge"), _lookup(survey_pop, "preference"),
                                  _lookup(survey_pop, "role"))
    mcq_to_s3 = {mcq: s3 for s3, mcq in s3_to_mcq.items() if s3 in s3_prior}
    people = []  # (p3 pid, mcq pid, linked s3 pid or None, diff)
    for p3, mcq in sorted(p3_to_mcq.items()):
        if p3 not in in_population or p3 not in group or mcq not in mcq_group:
            continue
        if not (_present(pct_a[p3]) and _present(pct_b[p3])):
            continue
        diff = pct_b[p3] - pct_a[p3] if group[p3] == "A" else pct_a[p3] - pct_b[p3]
        people.append((p3, mcq, mcq_to_s3.get(mcq), float(diff)))

    adjusted_rows = [(diff, 0.5 if group[p3] == "A" else -0.5, float(s3_prior[s3]) - float(mcq_prior[mcq]))
                     for p3, mcq, s3, diff in people
                     if s3 is not None and _present(s3_prior[s3]) and _present(mcq_prior[mcq])]
    codes = [code for _, code, _ in adjusted_rows]
    adjusted = None
    if min(codes.count(0.5), codes.count(-0.5)) >= MIN_PER_LEVEL:
        adjusted = _adjusted_intercept([d for d, _, _ in adjusted_rows], codes, [pk for _, _, pk in adjusted_rows])

    forgetting = [float(pct_a[p3] if mcq_group[mcq] == "A" else pct_b[p3]) - float(mcq_pct[mcq])
                  for p3, mcq, _, _ in people if _present(mcq_pct[mcq])]
    linked = [(s3, diff) for _, _, s3, diff in people if s3 is not None]
    return {
        "adjusted_theta": adjusted,
        "forgetting_mcq_arm": _mean_variance(forgetting),
        "diff_by_preference": _linked_welch([d for s, d in linked if preference[s] == PREFERENCE_BLOOMER],
                                            [d for s, d in linked if preference[s] == PREFERENCE_QUIZ]),
        "diff_by_role": _linked_welch([d for s, d in linked if role[s] in ATTENDING],
                                      [d for s, d in linked if role[s] in TRAINEE]),
    }


def group_label_mismatch(p3_to_mcq: dict[str, str], mcq_groups: dict[str, str],
                         p3_groups: dict[str, str]) -> float | None:
    """C5.4: share of matched Phase 3 people whose MCQ form group differs from their self-reported group."""
    matched = [(p3, mcq) for p3, mcq in p3_to_mcq.items() if p3 in p3_groups and mcq in mcq_groups]
    if len(matched) < MIN_LINKED:
        return None
    return sum(mcq_groups[mcq] != p3_groups[p3] for p3, mcq in matched) / len(matched)


# ---- linked analyses over many draws ------------------------------------------------------------------------
def _link_quality(edges: pd.DataFrame, weights: np.ndarray, matchings: list[dict[str, str]], right_col: str,
                  gap_col: str, margin: float, n_left: int, n_right: int) -> dict:
    positive = edges[weights > 0].reset_index(drop=True)
    best = best_matching(edges, "mcq_pid", right_col, weights)
    gap = {(left, right): g for left, right, g in zip(edges["mcq_pid"], edges[right_col], edges[gap_col])}
    best_gaps = np.asarray([gap[(left, right)] for right, left in best.items()], dtype=float)
    matched = [len(matching) for matching in matchings]
    return {
        "n_left_in_population": n_left,
        "n_right_in_population": n_right,
        "n_candidate_edges": int(len(edges)),
        "n_positive_weight_edges": int(len(positive)),
        "n_right_with_candidate": int(positive[right_col].nunique()),
        "best_matching": {"n_pairs": len(best),
                          "gap_median": float(np.median(best_gaps)) if len(best_gaps) else None,
                          "gap_q1": float(np.percentile(best_gaps, 25)) if len(best_gaps) else None,
                          "gap_q3": float(np.percentile(best_gaps, 75)) if len(best_gaps) else None},
        "clear_pairs": len(clear_pairs(positive, best, "mcq_pid", right_col, gap_col, margin)),
        "clear_margin": margin,
        "stable_pairs": stable_pair_count(matchings),
        "matched_per_draw": {"median": float(np.median(matched)) if matched else None,
                             "min": min(matched) if matched else None, "max": max(matched) if matched else None},
    }


def _pooled(values: list[tuple[float, float]], draws: int, scale: str) -> dict:
    pooled = rubin([e for e, _ in values], [v for _, v in values])
    transform = math.tanh if scale == "fisher_z" else float
    summary = {"n_draws": draws, "n_estimable": len(values), "share_estimable": len(values) / draws if draws else None,
               **pooled, **_quantiles([e for e, _ in values], transform)}
    if scale == "fisher_z":
        summary["estimate_z"] = pooled["estimate"]
        for key in ("estimate", "ci_low", "ci_high"):
            summary[key] = None if pooled[key] is None else math.tanh(pooled[key])
    return summary


def linked_analyses(links_part1: pd.DataFrame, links_phase3: pd.DataFrame, mcq_scores: pd.DataFrame,
                    survey_pop: pd.DataFrame, phase3_pop: pd.DataFrame, wide: pd.DataFrame, draws: int,
                    seed: int) -> dict:
    """C4 and C5 over date-weighted and random-reference matchings, the group-label check, and link quality.

    Edges touching a pid outside the analysis populations are dropped. Date weights: Part 1 exp(-gap/24 h), Phase 3
    banded (matching.py), both only for same-group edges. Reference: weight 1 for every same-group pair regardless
    of gap. Seeds: SEED_OFFSETS added to seed. Each estimand is pooled (Rubin) over its estimable date-based draws and
    compared with the reference per-draw estimates; the group-label check (C5.4) ignores group and is summarised as
    the median and 2.5th-97.5th percentiles across draws, with dates and without.
    """
    seeds = {name: seed + offset for name, offset in SEED_OFFSETS.items()}
    mcq_groups = _lookup(mcq_scores, "group")
    s3_groups, p3_groups = _lookup(survey_pop, "group"), _lookup(phase3_pop, "group")
    part1_edges = restrict_edges(links_part1, "mcq_pid", "s3_pid", mcq_groups, s3_groups)
    phase3_edges = restrict_edges(links_phase3, "mcq_pid", "p3_pid", mcq_groups, p3_groups)
    part1_same = same_group_flags(part1_edges).astype(float)
    phase3_gap_weights = np.array([phase3_weight(g) for g in phase3_edges["gap_days"]], dtype=float)
    part1_weights = np.array([part1_weight(g) for g in part1_edges["gap_hours"]], dtype=float) * part1_same
    phase3_weights = phase3_gap_weights * same_group_flags(phase3_edges).astype(float)
    part1_reference = all_pairs_edges(mcq_groups, s3_groups, left_col="mcq_pid", right_col="s3_pid")
    phase3_reference = all_pairs_edges(mcq_groups, p3_groups, left_col="mcq_pid", right_col="p3_pid")

    families = {
        "date": (sample_matchings(part1_edges, "mcq_pid", "s3_pid", part1_weights, draws, seeds["date_part1"]),
                 sample_matchings(phase3_edges, "mcq_pid", "p3_pid", phase3_weights, draws, seeds["date_phase3"])),
        "reference": (sample_matchings(part1_reference, "mcq_pid", "s3_pid",
                                       reference_weights(part1_reference, True), draws, seeds["reference_part1"]),
                      sample_matchings(phase3_reference, "mcq_pid", "p3_pid",
                                       reference_weights(phase3_reference, True), draws, seeds["reference_phase3"])),
    }
    values: dict[str, dict[str, list]] = {family: {key: [] for key in LINKED_ESTIMANDS} for family in families}
    both_links = []
    for family, (part1_draws, phase3_draws) in families.items():
        for s3_to_mcq, p3_to_mcq in zip(part1_draws, phase3_draws):
            estimates = {**part1_person_estimates(s3_to_mcq, mcq_scores, survey_pop),
                         **phase3_person_estimates(p3_to_mcq, s3_to_mcq, wide, phase3_pop, mcq_scores, survey_pop)}
            for key, value in estimates.items():
                if value is not None:
                    values[family][key].append(value)
            if family == "date":
                linked_mcq = set(s3_to_mcq.values())
                both_links.append(sum(mcq in linked_mcq for mcq in p3_to_mcq.values()))

    results = {}
    for key, (section, label, unit, scale) in LINKED_ESTIMANDS.items():
        date_summary = _pooled(values["date"][key], draws, scale)
        reference_estimates = [estimate for estimate, _ in values["reference"][key]]
        on_scale = date_summary["estimate_z"] if scale == "fisher_z" else date_summary["estimate"]
        percentile = reference_percentile(on_scale, reference_estimates)
        inside = None if percentile is None else REFERENCE_BAND[0] <= percentile <= REFERENCE_BAND[1]
        results[key] = {
            "section": section, "label": label, "unit": unit, "scale": scale,
            "date": date_summary, "reference": _pooled(values["reference"][key], draws, scale),
            "reference_percentile": percentile,
            "no_evidence_dates_add_information": inside,  # v1.5 flag, kept; the report uses the negation below
            "differs_from_random_matching": None if inside is None else not inside,
            "note": ESTIMAND_NOTES.get(key),
        }

    with_dates = sample_matchings(phase3_edges, "mcq_pid", "p3_pid", phase3_gap_weights, draws,
                                  seeds["group_check_with_dates"])
    without_dates = sample_matchings(phase3_reference, "mcq_pid", "p3_pid", reference_weights(phase3_reference, False),
                                     draws, seeds["group_check_without_dates"])
    group_check = {}
    for name, matchings in (("with_dates", with_dates), ("without_dates", without_dates)):
        shares = [share for share in (group_label_mismatch(m, mcq_groups, p3_groups) for m in matchings)
                  if share is not None]
        group_check[name] = {"n_draws": draws, "n_estimable": len(shares),
                             "share_estimable": len(shares) / draws if draws else None, **_quantiles(shares)}

    part1_draws, phase3_draws = families["date"]
    quality = {
        "part1": _link_quality(part1_edges, part1_weights, part1_draws, "s3_pid", "gap_hours", CLEAR_MARGIN["part1"],
                               len(mcq_groups), len(s3_groups)),
        "phase3": _link_quality(phase3_edges, phase3_weights, phase3_draws, "p3_pid", "gap_days",
                                CLEAR_MARGIN["phase3"], len(mcq_groups), len(p3_groups)),
    }
    quality["phase3"]["matched_with_survey3_per_draw"] = {
        "median": float(np.median(both_links)) if both_links else None,
        "min": min(both_links) if both_links else None, "max": max(both_links) if both_links else None}
    return {
        "draws": draws,
        "seeds": seeds,
        "link_quality": quality,
        "estimates": results,
        "group_label_check": group_check,
        "per_draw": {"adjusted_theta": {family: [estimate for estimate, _ in values[family]["adjusted_theta"]]
                                        for family in families}},
    }
