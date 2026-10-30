"""Public de-identified tables for the open repository, and the published numbers they must reproduce.

The tables hold only what the reported analyses need: item answers, sequence group, survey answers and comment-theme
codes. Every identifier is reassigned at random (fresh randomness each export; the mapping is not kept) and every
indirect identifier (age, gender, region, role, years,
subspecialty, setting, CME habits, AI use, dates and times, cross-form links) is left out. A column outside
PUBLIC_COLUMNS is an error, never a silent addition.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from bloomer_retention.config import StudyConfig, load_config
from bloomer_retention.feedback import THEMES
from bloomer_retention.run import load_verified_csv
from bloomer_retention.scoring import CONTAMINATION_COLUMNS, PERCEIVED_COLUMNS, item_long, mcq_scores, phase3_population
from bloomer_retention.survey3 import survey3_population
from bloomer_retention.survey3_forms import QUESTIONS

SURVEY_ANSWER_COLUMNS = (*[f"{q}_{field}" for q in QUESTIONS
                           for field in ("minutes", "time_status", "attempts", "attempts_status")],
                         "best_comprehension", "quiz_difficulty", "bloomer_difficulty", "preference")
PUBLIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "retention_items": ("respondent", "article", "item", "offered", "answered", "correct"),
    "retention_respondents": ("respondent", "sequence_group", "reread_used_ai_or_discussed", *PERCEIVED_COLUMNS),
    "part1_quiz_scores": ("form", "article", "pct_correct", "prior_knowledge"),
    "survey_after_bloomer": ("respondent", "sequence_group", "bloomer_article", "prior_knowledge",
                             *SURVEY_ANSWER_COLUMNS),
    "comment_themes": ("respondent", "substantive", *THEMES),
}
# Sensitivity analyses the public tables can rerun, by the label prefix they carry in results.json.
SENSITIVITY_KEYS = {"welch": "Welch", "s1_exclusions": "S1 ", "s2_permutation": "S2 ", "s4_answered": "S4 ",
                    "s5_items_correct": "S5 "}
ESTIMATE_FIELDS = ("theta", "ci_low", "ci_high", "p_value", "n_a", "n_b")


def new_ids(pids: pd.Series, prefix: str) -> dict[str, str]:
    """Map each pid to prefix + a 2-digit number in a random order unrelated to submission order.

    The order comes from fresh operating-system randomness and is never stored, so the public IDs cannot be mapped
    back to the study's pids (which follow export order). The prefixes (ret, srv, p1f) differ from the study's own
    pid formats (R01, S01, MA01), so no public ID can be mistaken for a study ID.
    """
    unique = sorted(pids.astype(str).unique())
    order = np.random.default_rng().permutation(len(unique))
    return {unique[j]: f"{prefix}{rank + 1:02d}" for rank, j in enumerate(order)}


def check_columns(tables: dict[str, pd.DataFrame]) -> None:
    for key, df in tables.items():
        if key not in PUBLIC_COLUMNS:
            raise ValueError(f"{key}: not a public table")
        extra = sorted(set(df.columns) - set(PUBLIC_COLUMNS[key]))
        if extra:
            raise ValueError(f"{key}: columns outside the public allowlist: {extra}")


def _manifest(cfg: StudyConfig) -> dict:
    return json.loads(cfg.manifest.read_text())


def build_public_tables(cfg: StudyConfig) -> dict[str, pd.DataFrame]:
    """The analysed populations, as run.py builds them, reduced to the public columns."""
    manifest = _manifest(cfg)
    load = lambda key: load_verified_csv(cfg.root, manifest["outputs"][key])  # noqa: E731
    tables: dict[str, pd.DataFrame] = {}

    pop, _ = phase3_population(load("phase3"), cfg.freeze_date)
    ids = new_ids(pop["pid"], "ret")
    items = item_long(pop, cfg.a4_offered_from)
    tables["retention_items"] = pd.DataFrame({
        "respondent": items["pid"].astype(str).map(ids), "article": items["paper"], "item": items["item_id"],
        "offered": items["valid"].astype(int), "answered": items["answered"].astype(int),
        "correct": items["correct"].astype(int),
    }).sort_values(["respondent", "item"], ignore_index=True)
    # One flag instead of the four answers: it is all the exclusion analysis (S1) uses, and the separate answers
    # could single out a respondent when combined with sequence group and the A4 date flag.
    reported = pop[CONTAMINATION_COLUMNS].eq("Yes").any(axis=1).map({True: "Yes", False: "No"})
    tables["retention_respondents"] = (pop[["pid", "group", *PERCEIVED_COLUMNS]]
                                       .assign(reread_used_ai_or_discussed=reported)
                                       .assign(pid=lambda d: d["pid"].astype(str).map(ids))
                                       .rename(columns={"pid": "respondent", "group": "sequence_group"})
                                       .sort_values("respondent", ignore_index=True))

    forms = pd.concat([mcq_scores(load(f"mcq_part1_{paper}"), paper, cfg.study_start, cfg.freeze_date,
                                  cfg.a4_offered_from).assign(pid=lambda d, p=paper: p + d["pid"].astype(str))
                       for paper in "AB"], ignore_index=True)
    form_ids = new_ids(forms["pid"], "p1f")
    tables["part1_quiz_scores"] = pd.DataFrame({
        "form": forms["pid"].map(form_ids), "article": forms["group"], "pct_correct": forms["pct"],
        "prior_knowledge": forms["prior_knowledge"],
    }).sort_values("form", ignore_index=True)

    if "survey3" in manifest["outputs"]:
        survey, _ = survey3_population(load("survey3"), cfg.study_start, cfg.freeze_date)
        s_ids = new_ids(survey["pid"], "srv")
        tables["survey_after_bloomer"] = (survey[["pid", "group", "bloomer_paper", "prior_knowledge",
                                                  *SURVEY_ANSWER_COLUMNS]]
                                          .assign(pid=lambda d: d["pid"].astype(str).map(s_ids))
                                          .rename(columns={"pid": "respondent", "group": "sequence_group",
                                                           "bloomer_paper": "bloomer_article"})
                                          .sort_values("respondent", ignore_index=True))
        if "feedback_codes" in manifest["outputs"]:
            codes = load("feedback_codes")
            codes = codes[codes["pid"].astype(str).isin(s_ids)]
            tables["comment_themes"] = (codes[["pid", "substantive", *THEMES]]
                                        .assign(pid=lambda d: d["pid"].astype(str).map(s_ids))
                                        .rename(columns={"pid": "respondent"})
                                        .sort_values("respondent", ignore_index=True))
    check_columns(tables)
    return tables


def _estimate(entry: dict) -> dict:
    return {field: entry[field] for field in ESTIMATE_FIELDS}


def expected_results(results: dict, survey3: dict | None) -> dict:
    """The published numbers the public tables must reproduce, copied from the analysis outputs."""
    sensitivity = {key: _estimate(next(e for e in results["sensitivity"] if e["label"].startswith(prefix)))
                   for key, prefix in SENSITIVITY_KEYS.items()}
    expected = {
        "permutation_seed": results["provenance"]["seeds"]["permutation"],
        "retention": {"headline": _estimate(results["primary"]["headline"]), **sensitivity,
                      "perceived": results["perceived_retention"]},
        "part1": {c["paper"]: {"n": c["n"], "pct_correct_mean": c["pct_correct_mean"]}
                  for c in results["part1_context"]},
    }
    if survey3 is not None:
        expected["survey"] = {
            "preference_counts": survey3["adoption"]["counts"],
            "comprehension_counts": survey3["comprehension"]["counts"],
            "difficulty_paired": {k: survey3["difficulty"]["paired"][k]
                                  for k in ("n_pairs", "median_difference", "p_value")},
            "total_minutes": survey3["usage"]["total_minutes"],
            "total_attempts": survey3["usage"]["total_attempts"],
        }
        if survey3.get("feedback"):
            expected["survey"]["comment_themes"] = survey3["feedback"]["themes"]
    return expected


def write_public_tables(tables: dict[str, pd.DataFrame], out_dir: Path, outputs_dir: Path) -> list[Path]:
    check_columns(tables)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for key, df in tables.items():
        path = out_dir / f"{key}.csv"
        df.to_csv(path, index=False)
        written.append(path)
    results = json.loads((outputs_dir / "results.json").read_text())
    survey_path = outputs_dir / "survey3_results.json"
    survey3 = json.loads(survey_path.read_text()) if survey_path.exists() else None
    path = out_dir / "expected_results.json"
    path.write_text(json.dumps(expected_results(results, survey3), indent=2, sort_keys=True) + "\n")
    return [*written, path]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the public de-identified tables and expected_results.json")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    for path in write_public_tables(build_public_tables(cfg), Path(args.out), cfg.outputs_dir):
        print(path)


if __name__ == "__main__":
    main()
