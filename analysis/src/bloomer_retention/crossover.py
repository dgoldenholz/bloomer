"""Stage 2b: estimators for the Bloomer-minus-MCQ retention contrast (SAP sections 6-8).

Participant-level estimators take the wide frame (pid, group, <paper A score>, <paper B score>) and
estimate theta = mean(Bloomer-article score - MCQ-article score), averaged over the two groups.
"""
from __future__ import annotations

import itertools
import math
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from bloomer_retention.scoring import METHOD_BY_GROUP

PP = "percentage points"


@dataclass(frozen=True)
class Estimate:
    label: str
    estimator: str
    unit: str
    theta: float
    ci_low: float
    ci_high: float
    p_value: float
    n_a: int
    n_b: int
    se: float | None = None
    df: int | float | None = None
    notes: tuple[str, ...] = ()


def not_estimable(label: str, unit: str, reason: str) -> Estimate:
    nan = math.nan
    return Estimate(label=label, estimator="not estimable", unit=unit, theta=nan, ci_low=nan, ci_high=nan,
                    p_value=nan, n_a=0, n_b=0, notes=(reason,))


def _differences(wide: pd.DataFrame, col_a: str, col_b: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Complete pairs plus d = score(paper A) - score(paper B) for group A and group B."""
    sub = wide.dropna(subset=[col_a, col_b])
    d = (sub[col_a] - sub[col_b]).to_numpy(dtype=float)
    in_a = (sub["group"] == "A").to_numpy()
    return sub, d[in_a], d[~in_a]


def _warning_notes(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    return tuple(sorted({str(w.message).splitlines()[0] for w in caught}))


def crossover_ttest(wide: pd.DataFrame, col_a: str, col_b: str, label: str, unit: str = PP,
                    alpha: float = 0.05) -> Estimate:
    """Closed-form 2x2 crossover estimator, pooled-variance t with n_A + n_B - 2 df.

    Group A: d = MCQ - Bloomer. Group B: d = Bloomer - MCQ. theta = (mean d_B - mean d_A) / 2.
    """
    _, d_a, d_b = _differences(wide, col_a, col_b)
    n_a, n_b = len(d_a), len(d_b)
    if n_a < 2 or n_b < 2:
        raise ValueError(f"need at least 2 participants per group; got A={n_a}, B={n_b}")
    theta = (d_b.mean() - d_a.mean()) / 2
    df = n_a + n_b - 2
    pooled = ((n_a - 1) * d_a.var(ddof=1) + (n_b - 1) * d_b.var(ddof=1)) / df
    if pooled == 0:
        raise ValueError("no within-group variance in the paired differences")
    se = 0.5 * math.sqrt(pooled * (1 / n_a + 1 / n_b))
    crit = stats.t.ppf(1 - alpha / 2, df)
    t_stat = theta / se
    return Estimate(
        label=label, estimator=f"crossover t (pooled, {df} df)", unit=unit, theta=float(theta),
        ci_low=float(theta - crit * se), ci_high=float(theta + crit * se),
        p_value=float(2 * stats.t.sf(abs(t_stat), df)), n_a=n_a, n_b=n_b, se=float(se), df=df,
    )


def crossover_welch(wide: pd.DataFrame, col_a: str, col_b: str, label: str, unit: str = PP,
                    alpha: float = 0.05) -> Estimate:
    """Headline theta with unpooled group variances of d and Welch-Satterthwaite df (SAP v2.6 sensitivity)."""
    _, d_a, d_b = _differences(wide, col_a, col_b)
    n_a, n_b = len(d_a), len(d_b)
    if n_a < 2 or n_b < 2:
        raise ValueError(f"need at least 2 participants per group; got A={n_a}, B={n_b}")
    va, vb = d_a.var(ddof=1) / n_a, d_b.var(ddof=1) / n_b
    if va == 0 or vb == 0:
        raise ValueError("no within-group variance in the paired differences")
    theta = (d_b.mean() - d_a.mean()) / 2
    se = 0.5 * math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (n_a - 1) + vb ** 2 / (n_b - 1))
    crit = stats.t.ppf(1 - alpha / 2, df)
    return Estimate(label=label, estimator=f"crossover t (Welch, {df:.1f} df)", unit=unit, theta=float(theta),
                    ci_low=float(theta - crit * se), ci_high=float(theta + crit * se),
                    p_value=float(2 * stats.t.sf(abs(theta / se), df)), n_a=n_a, n_b=n_b, se=float(se),
                    df=round(float(df), 1))


def permutation_test(wide: pd.DataFrame, col_a: str, col_b: str, label: str, seed: int, unit: str = PP,
                     max_exact: int = 200_000, n_draws: int = 100_000) -> Estimate:
    """Permutation test: under no method effect and exchangeability of d between sequence groups, the exact
    two-sided P over all assignments of the observed d values to groups of the observed sizes (SAP S2, relabelled
    in version 2.6; allocation alternated in order of enrollment, not by a random mechanism, and the computation
    is unchanged)."""
    _, d_a, d_b = _differences(wide, col_a, col_b)
    n_a, n_b = len(d_a), len(d_b)
    if n_a < 1 or n_b < 1:
        raise ValueError(f"need at least 1 participant per group; got A={n_a}, B={n_b}")
    d = np.concatenate([d_a, d_b])
    n, total = n_a + n_b, d.sum()
    observed = abs(d_b.mean() - d_a.mean())

    def statistic(a_sums: np.ndarray) -> np.ndarray:
        return np.abs((total - a_sums) / n_b - a_sums / n_a)

    n_assignments = math.comb(n, n_a)
    if n_assignments <= max_exact:
        a_sums = np.array([d[list(idx)].sum() for idx in itertools.combinations(range(n), n_a)])
        p_value = float(np.mean(statistic(a_sums) >= observed - 1e-9))
        note = f"exact over {n_assignments} assignments"
    else:
        rng = np.random.default_rng(seed)
        a_sums = np.array([d[rng.permutation(n)[:n_a]].sum() for _ in range(n_draws)])
        p_value = float((np.sum(statistic(a_sums) >= observed - 1e-9) + 1) / (n_draws + 1))
        note = f"Monte Carlo over {n_draws} assignments"
    nan = math.nan
    return Estimate(label=label, estimator="permutation test", unit=unit,
                    theta=float((d_b.mean() - d_a.mean()) / 2), ci_low=nan, ci_high=nan,
                    p_value=p_value, n_a=n_a, n_b=n_b, notes=(note,))


def to_long(wide: pd.DataFrame, col_a: str, col_b: str) -> pd.DataFrame:
    sub, _, _ = _differences(wide, col_a, col_b)
    rows = []
    for record in sub.to_dict("records"):
        for paper, column in (("A", col_a), ("B", col_b)):
            rows.append({
                "pid": record["pid"],
                "score": float(record[column]),
                "bloomer": int(METHOD_BY_GROUP[record["group"]][paper] == "Bloomer"),
                "paper_b": int(paper == "B"),
                "group_b": int(record["group"] == "B"),
            })
    return pd.DataFrame(rows)


def fit_lmm(wide: pd.DataFrame, col_a: str, col_b: str, label: str, unit: str = PP) -> Estimate:
    """Pre-specified model: score ~ method + article + group + (1 | participant), REML, Wald z.

    Notes always give the final convergence status and the variance components. Optimiser warnings from
    earlier attempts are kept only when the final fit did not converge.
    """
    long = to_long(wide, col_a, col_b)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = smf.mixedlm("score ~ bloomer + paper_b + group_b", long, groups=long["pid"]).fit(reml=True)
    low, high = result.conf_int().loc["bloomer"]
    converged = bool(result.converged)
    notes = (
        f"REML converged: {converged}",
        f"random-intercept variance {float(result.cov_re.iloc[0, 0]):.1f}; "
        f"residual variance {float(result.scale):.1f}",
        *(() if converged else _warning_notes(caught)),
    )
    return Estimate(
        label=label, estimator="linear mixed model (REML, Wald z)", unit=unit,
        theta=float(result.params["bloomer"]), ci_low=float(low), ci_high=float(high),
        p_value=float(result.pvalues["bloomer"]),
        n_a=int(long.loc[long["group_b"] == 0, "pid"].nunique()),
        n_b=int(long.loc[long["group_b"] == 1, "pid"].nunique()),
        se=float(result.bse["bloomer"]), notes=notes,
    )


def fit_gee_items(items: pd.DataFrame, label: str) -> Estimate:
    """S3: item-level logistic GEE, exchangeable within participant, robust SE; odds ratio for Bloomer."""
    data = (
        items[items["valid"]]
        .assign(
            correct=lambda x: x["correct"].astype(int),
            bloomer=lambda x: (x["method"] == "Bloomer").astype(int),
            paper_b=lambda x: (x["paper"] == "B").astype(int),
            group_b=lambda x: (x["group"] == "B").astype(int),
        )
        .sort_values(["pid", "item_id"])
        .reset_index(drop=True)
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = smf.gee("correct ~ bloomer + paper_b + group_b", groups="pid", data=data,
                         family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
    low, high = result.conf_int().loc["bloomer"]
    return Estimate(
        label=label, estimator="item-level logistic GEE (robust SE)", unit="odds ratio",
        theta=float(np.exp(result.params["bloomer"])), ci_low=float(np.exp(low)), ci_high=float(np.exp(high)),
        p_value=float(result.pvalues["bloomer"]),
        n_a=int(data.loc[data["group_b"] == 0, "pid"].nunique()),
        n_b=int(data.loc[data["group_b"] == 1, "pid"].nunique()),
        se=float(result.bse["bloomer"]), notes=_warning_notes(caught),
    )
