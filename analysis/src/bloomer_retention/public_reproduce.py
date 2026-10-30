"""Rerun the reported analyses from the public de-identified tables alone and compare with the published numbers.

Usage: python -m bloomer_retention.public_reproduce --data <folder with the public CSVs and expected_results.json>
Every estimate comes from the same package functions the full analysis used; nothing is recomputed differently.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

from bloomer_retention.crossover import crossover_ttest, crossover_welch, permutation_test
from bloomer_retention.feedback import feedback_themes
from bloomer_retention.public_export import ESTIMATE_FIELDS
from bloomer_retention.scoring import CONTAMINATION_COLUMNS, participant_scores, perceived_retention
from bloomer_retention.survey3 import (COMPREHENSION_BLOOMER, COMPREHENSION_QUIZ, PREFERENCE_BLOOMER,
                                       PREFERENCE_QUIZ, choice_outcome, difficulty, usage)

TOLERANCE = 1e-6


def _read(public_dir: Path, name: str) -> pd.DataFrame | None:
    path = public_dir / f"{name}.csv"
    return pd.read_csv(path, keep_default_na=False, na_values=[""]) if path.exists() else None


def _estimate(est) -> dict:
    """Estimate fields as the published JSON stores them: a NaN (e.g. the permutation test's absent CI) is null."""
    values = {field: getattr(est, field) for field in ESTIMATE_FIELDS}
    return {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in values.items()}


def reproduce(public_dir: Path) -> dict:
    expected = json.loads((public_dir / "expected_results.json").read_text())
    items = _read(public_dir, "retention_items").rename(
        columns={"respondent": "pid", "article": "paper", "item": "item_id", "offered": "valid"})
    items[["valid", "answered", "correct"]] = items[["valid", "answered", "correct"]].astype(bool)
    pop = _read(public_dir, "retention_respondents").rename(columns={"respondent": "pid", "sequence_group": "group"})
    # participant_scores flags a respondent who answered Yes to any of the four questions; the public file carries
    # that single flag, so it stands in for the first question and the others read No.
    pop = pop.assign(**{column: "No" for column in CONTAMINATION_COLUMNS}).assign(
        reread_a=pop["reread_used_ai_or_discussed"])
    wide = participant_scores(items, pop)
    clean = wide[~wide["contaminated"]]
    out = {
        "permutation_seed": expected["permutation_seed"],
        "retention": {
            "headline": _estimate(crossover_ttest(wide, "pct_a", "pct_b", "headline")),
            "welch": _estimate(crossover_welch(wide, "pct_a", "pct_b", "welch")),
            "s1_exclusions": _estimate(crossover_ttest(clean, "pct_a", "pct_b", "s1")),
            "s2_permutation": _estimate(permutation_test(wide, "pct_a", "pct_b", "s2",
                                                         seed=expected["permutation_seed"])),
            "s4_answered": _estimate(crossover_ttest(wide, "pct_answered_a", "pct_answered_b", "s4")),
            "s5_items_correct": _estimate(crossover_ttest(wide, "points5_a", "points5_b", "s5",
                                                          unit="items correct")),
            "perceived": perceived_retention(pop),
        },
    }
    part1 = _read(public_dir, "part1_quiz_scores")
    out["part1"] = {paper: {"n": int(len(g)), "pct_correct_mean": float(g["pct_correct"].mean())}
                    for paper, g in part1.groupby("article")}
    survey = _read(public_dir, "survey_after_bloomer")
    if survey is not None:
        survey = survey.rename(columns={"respondent": "pid", "sequence_group": "group",
                                        "bloomer_article": "bloomer_paper"})
        paired = difficulty(survey)["paired"]
        use = usage(survey)
        out["survey"] = {
            "preference_counts": choice_outcome(survey, "preference", PREFERENCE_BLOOMER, PREFERENCE_QUIZ)["counts"],
            "comprehension_counts": choice_outcome(survey, "best_comprehension", COMPREHENSION_BLOOMER,
                                                   COMPREHENSION_QUIZ)["counts"],
            "difficulty_paired": {k: paired[k] for k in ("n_pairs", "median_difference", "p_value")},
            "total_minutes": use["total_minutes"],
            "total_attempts": use["total_attempts"],
        }
        themes = _read(public_dir, "comment_themes")
        if themes is not None:
            out["survey"]["comment_themes"] = feedback_themes(themes.rename(columns={"respondent": "pid"}),
                                                              survey["pid"])["themes"]
    return out


def compare(computed: dict, expected: dict, path: str = "") -> list[str]:
    """Every place the two nested results differ (numbers within TOLERANCE); [] means a full match."""
    if isinstance(expected, dict):
        if not isinstance(computed, dict):
            return [f"{path}: expected a table, got {computed!r}"]
        problems = [f"{path}.{k}: missing" for k in expected if k not in computed]
        problems += [f"{path}.{k}: not in the published results" for k in computed if k not in expected]
        for k in expected:
            if k in computed:
                problems += compare(computed[k], expected[k], f"{path}.{k}")
        return problems
    if isinstance(expected, (int, float)) and not isinstance(expected, bool) and expected is not None:
        ok = isinstance(computed, (int, float)) and math.isclose(computed, expected, rel_tol=0, abs_tol=TOLERANCE)
        return [] if ok else [f"{path}: computed {computed!r}, published {expected!r}"]
    return [] if computed == expected else [f"{path}: computed {computed!r}, published {expected!r}"]


def _flatten(d: dict, prefix: str = "") -> list[tuple[str, object]]:
    rows = []
    for k, v in d.items():
        rows += _flatten(v, f"{prefix}{k}.") if isinstance(v, dict) else [(f"{prefix}{k}", v)]
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rerun the reported analyses from the public tables")
    parser.add_argument("--data", required=True, help="folder with the public CSVs and expected_results.json")
    args = parser.parse_args(argv)
    public_dir = Path(args.data)
    computed = reproduce(public_dir)
    expected = json.loads((public_dir / "expected_results.json").read_text())
    published = dict(_flatten(expected))
    for key, value in _flatten(computed):
        print(f"{key:55} computed {value!s:>22}   published {published.get(key, '-')!s:>22}")
    problems = compare(computed, expected)
    print("\nAll computed values match the published values." if not problems
          else "\nMismatches:\n" + "\n".join(problems))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
