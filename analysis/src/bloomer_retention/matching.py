"""Plausible matchings between anonymous forms (SAP Part C, C7).

Edges are link candidates (left = MCQ form pid, right = Survey 3 or Phase 3 pid). The sampler draws many
one-to-one matchings with probability proportional to a date-based weight; the random reference draws them with
equal weights regardless of the gap. The best matching and its clear pairs are secondary readouts.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

PART1_SCALE_HOURS = 24.0
PHASE3_FULL_DAYS = (28.0, 45.0)  # weight 1
PHASE3_PARTIAL_DAYS = (21.0, 60.0)  # weight 0.25 outside the full band and within these bounds
PHASE3_PARTIAL_WEIGHT = 0.25


def part1_weight(gap_hours: float) -> float:
    """Survey 3 start - MCQ completion: exp(-gap / 24 h)."""
    return math.exp(-gap_hours / PART1_SCALE_HOURS)


def phase3_weight(gap_days: float) -> float:
    """Phase 3 start - MCQ completion: 1 for 28-45 days, 0.25 for 21 to <28 or >45 to 60 days, else 0."""
    if PHASE3_FULL_DAYS[0] <= gap_days <= PHASE3_FULL_DAYS[1]:
        return 1.0
    if PHASE3_PARTIAL_DAYS[0] <= gap_days <= PHASE3_PARTIAL_DAYS[1]:
        return PHASE3_PARTIAL_WEIGHT
    return 0.0


def restrict_edges(edges: pd.DataFrame, left_col: str, right_col: str, left_pids: Iterable[str],
                   right_pids: Iterable[str]) -> pd.DataFrame:
    """Edges whose two pids are both in the analysis populations."""
    keep = edges[left_col].isin(set(left_pids)) & edges[right_col].isin(set(right_pids))
    return edges[keep].reset_index(drop=True)


def _positive_candidates(edges: pd.DataFrame, left_col: str, right_col: str,
                         weights: np.ndarray) -> tuple[list[str], list[str], list[tuple[np.ndarray, np.ndarray]]]:
    weights = np.asarray(weights, dtype=float)
    if len(weights) != len(edges):
        raise ValueError(f"expected {len(edges)} weights; got {len(weights)}")
    rights = sorted(edges[right_col].unique())
    positive = weights > 0
    lefts = sorted(edges.loc[positive, left_col].unique())
    left_index = {pid: i for i, pid in enumerate(lefts)}
    per_right: dict[str, tuple[list[int], list[float]]] = {pid: ([], []) for pid in rights}
    for left, right, weight in zip(edges.loc[positive, left_col], edges.loc[positive, right_col], weights[positive]):
        per_right[right][0].append(left_index[left])
        per_right[right][1].append(float(weight))
    candidates = [(np.array(per_right[pid][0], dtype=int), np.array(per_right[pid][1])) for pid in rights]
    return rights, lefts, candidates


def sample_matchings(edges: pd.DataFrame, left_col: str, right_col: str, weights: np.ndarray, draws: int,
                     seed: int) -> list[dict[str, str]]:
    """Per draw, right pids in a random order each choose one unused left pid with probability proportional to the
    positive edge weights; a right pid with no unused positive-weight left stays unmatched (omitted).

    Returns one {right pid: left pid} mapping per draw. Seeded with numpy.random.default_rng(seed).
    """
    rights, lefts, candidates = _positive_candidates(edges, left_col, right_col, weights)
    rng = np.random.default_rng(seed)
    matchings = []
    for _ in range(draws):
        used = np.zeros(len(lefts), dtype=bool)
        matching = {}
        for r in rng.permutation(len(rights)):
            index, weight = candidates[r]
            available = np.where(used[index], 0.0, weight)
            total = available.sum()
            if total <= 0:
                continue
            cumulative = np.cumsum(available)
            k = int(np.searchsorted(cumulative, rng.random() * total, side="right"))
            k = min(k, int(np.flatnonzero(available)[-1]))  # guard against rounding at the top of the range
            used[index[k]] = True
            matching[rights[r]] = lefts[index[k]]
        matchings.append(dict(sorted(matching.items())))
    return matchings


def same_group_flags(edges: pd.DataFrame) -> np.ndarray:
    """The same_group column as a boolean array.

    Raises ValueError when any value is not True or False (a string, a number, NaN or a missing value), because a
    truthy cast would turn such values into same-group pairs and silently enable matching across groups.
    """
    column = edges["same_group"]
    if not all(isinstance(value, (bool, np.bool_)) for value in column):
        raise ValueError("same_group must hold only True or False")
    return column.to_numpy(dtype=bool)


def reference_weights(edges: pd.DataFrame, require_same_group: bool) -> np.ndarray:
    """Random reference: weight 1 for every eligible edge regardless of gap (same group only when required)."""
    if require_same_group:
        return same_group_flags(edges).astype(float)
    return np.ones(len(edges))


def all_pairs_edges(left_pids_groups: dict[str, str | None], right_pids_groups: dict[str, str | None], *,
                    left_col: str = "left_pid", right_col: str = "right_pid") -> pd.DataFrame:
    """Every (left, right) pair with no gap window, for the random reference; same_group is False when either
    group is unknown. Sorted by (left, right)."""
    rows = [(left, right, isinstance(left_group, str) and left_group == right_group)
            for left, left_group in sorted(left_pids_groups.items())
            for right, right_group in sorted(right_pids_groups.items())]
    edges = pd.DataFrame(rows, columns=[left_col, right_col, "same_group"])
    edges["same_group"] = edges["same_group"].astype(bool)
    return edges


def best_matching(edges: pd.DataFrame, left_col: str, right_col: str, weights: np.ndarray) -> dict[str, str]:
    """One-to-one matching over positive-weight edges by scipy.optimize.linear_sum_assignment on -log(weight).

    Non-edges carry a cost larger than twice the summed edge costs, so the assignment first maximises the number
    of pairs and then minimises the summed -log(weight) among matchings of that size.
    """
    weights = np.asarray(weights, dtype=float)
    positive = weights > 0
    sub = edges[positive]
    if sub.empty:
        return {}
    rights = sorted(sub[right_col].unique())
    lefts = sorted(sub[left_col].unique())
    row = {pid: i for i, pid in enumerate(rights)}
    col = {pid: j for j, pid in enumerate(lefts)}
    cost = -np.log(weights[positive])
    matrix = np.full((len(rights), len(lefts)), 2 * np.abs(cost).sum() + 1.0)
    real = np.zeros_like(matrix, dtype=bool)
    for left, right, c in zip(sub[left_col], sub[right_col], cost):
        matrix[row[right], col[left]] = c
        real[row[right], col[left]] = True
    rows, cols = linear_sum_assignment(matrix)
    return {rights[r]: lefts[c] for r, c in zip(rows, cols) if real[r, c]}


def clear_pairs(edges: pd.DataFrame, best: dict[str, str], left_col: str, right_col: str, gap_col: str,
                margin: float) -> dict[str, str]:
    """Best-matching pairs with no other edge for either pid whose gap is within +/- margin of the pair's gap.

    Pass the edges the best matching was drawn from (positive weight only); margin is 24 h for Part 1 and 3 days
    for Phase 3. For the right pid, a rival edge means another MCQ completion within the margin; for the left pid,
    another form start within the margin.
    """
    gap = {(left, right): g for left, right, g in zip(edges[left_col], edges[right_col], edges[gap_col])}
    clear = {}
    for right, left in best.items():
        own = gap[(left, right)]
        rival = any(abs(g - own) <= margin for (other_left, other_right), g in gap.items()
                    if (other_right == right) != (other_left == left))
        if not rival:
            clear[right] = left
    return clear


def stable_pair_count(matchings: list[dict[str, str]], threshold: float = 0.9) -> int:
    """Number of (right, left) pairs present in at least `threshold` of the draws."""
    if not matchings:
        return 0
    counts = Counter(pair for matching in matchings for pair in matching.items())
    return sum(n >= threshold * len(matchings) - 1e-9 for n in counts.values())
