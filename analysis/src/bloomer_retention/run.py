"""Stage 2 (shareable): de-identified CSVs -> retention outputs (results.json, report.md, fig_retention.*); when
Survey 3 is configured, survey3_results.json, survey3_report.md and fig_survey3.*; when the Start form and the
link candidate files are present (SAP Part C), partc_results.json, partc_report.md and fig_partc.*; and when the
roster link file is present (SAP Part D), partd_results.json, partd_report.md and fig_partd.*."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from bloomer_retention.config import load_config
from bloomer_retention.feedback import feedback_themes
from bloomer_retention.crossover import (
    PP,
    Estimate,
    crossover_ttest,
    crossover_welch,
    fit_gee_items,
    fit_lmm,
    not_estimable,
    permutation_test,
)
from bloomer_retention.ingest import sha256_file
from bloomer_retention.labels import ASSIGNED_GROUP_LABEL, PERMUTATION_LABEL, WELCH_LABEL
from bloomer_retention.partc import (flow_and_returns, forgetting_pooled, forgetting_unlinked, linked_analyses,
                                     tipping_point)
from bloomer_retention.partc_report import build_partc_results, plot_partc, render_partc_report
from bloomer_retention.partd import (
    adjusted_benefit,
    alternatives_sensitivity,
    benefit_summary,
    equal_weight_benefit,
    link_quality,
    part1_certain_pairs,
    partd_population,
    preference_vs_benefit,
    retention_interval,
    subgroup_contrasts,
    usage_vs_benefit,
)
from bloomer_retention.partd_report import build_partd_results, plot_partd, render_partd_report
from bloomer_retention.registration_link import assigned_groups, registration_link_summary
from bloomer_retention.report import build_results, plot_retention, provenance, render_report, write_json
from bloomer_retention.survey3 import (
    COMPREHENSION_BLOOMER,
    COMPREHENSION_QUIZ,
    PREFERENCE_BLOOMER,
    PREFERENCE_QUIZ,
    choice_outcome,
    difficulty,
    prior_knowledge_context,
    quiz_elapsed,
    subgroups,
    survey3_population,
    table1,
    usage,
)
from bloomer_retention.survey3_report import build_survey3_results, plot_survey3, render_survey3_report
from bloomer_retention.scoring import (
    cell_descriptives,
    item_long,
    item_summary,
    mcq_scores,
    part1_mcq_summary,
    participant_scores,
    perceived_retention,
    phase3_population,
)


def load_verified_csv(root: Path, entry: dict) -> pd.DataFrame:
    path = root / entry["file"]
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise ValueError(f"{entry['file']} does not match data/manifest.json "
                         f"({actual[:12]} != {entry['sha256'][:12]}); re-run ingest")
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


NON_FINITE = "non-finite estimate (for example perfect separation or no variance)"


def attempt(label: str, unit: str, fit: Callable[[], Estimate]) -> Estimate:
    """Run a fit; errors and non-finite results become 'not estimable' rows instead of stopping the run."""
    try:
        est = fit()
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as err:
        return not_estimable(label, unit, str(err))
    ci_required = est.estimator != "permutation test"
    if not (math.isfinite(est.theta) and math.isfinite(est.p_value)) or (
        ci_required and not (math.isfinite(est.ci_low) and math.isfinite(est.ci_high))
    ):
        return not_estimable(label, unit, NON_FINITE)
    return est


class UncommittedChangesError(RuntimeError):
    """Stage 2 would stamp outputs with a code version that no commit reproduces."""


def study_seeds(cfg) -> dict[str, int]:
    """The seeds stage 2 uses, stamped into every results file so a report can state them (SAP section 14).

    Part C's per-family linkage seeds are derived from `linkage_seed` and are already written out in full under
    `partc_results.linked.seeds`; only the base seeds live here.
    """
    return {"permutation": cfg.permutation_seed}


def _load_checked(config_path: str | Path, allow_dirty: bool):
    """Config, manifest and provenance; refuses to continue on uncommitted code, config or SAP."""
    cfg = load_config(config_path)
    manifest = json.loads(cfg.manifest.read_text(encoding="utf-8"))
    prov = provenance(cfg.root, Path(config_path).resolve(), manifest, seeds=study_seeds(cfg))
    if prov["code_commit"].endswith("+dirty") and not allow_dirty:
        raise UncommittedChangesError(
            f"refusing to write outputs: code/config/SAP have uncommitted changes ({prov['code_commit']}); "
            "commit first or pass --allow-dirty"
        )
    return cfg, manifest, prov


def run_analysis(config_path: str | Path, allow_dirty: bool = False) -> dict:
    cfg, manifest, prov = _load_checked(config_path, allow_dirty)
    phase3 = load_verified_csv(cfg.root, manifest["outputs"]["phase3"])
    mcq = {paper: load_verified_csv(cfg.root, manifest["outputs"][f"mcq_part1_{paper}"]) for paper in "AB"}

    pop, flow = phase3_population(phase3, cfg.freeze_date)
    flow["duplicates_removed_at_ingest"] = manifest["inputs"]["phase3"]["n_duplicates_dropped"]
    flow["rows_without_contact_email"] = manifest["inputs"]["phase3"]["n_without_contact_email"]
    items = item_long(pop, cfg.a4_offered_from)
    wide = participant_scores(items, pop)
    clean = wide[~wide["contaminated"]]

    headline = crossover_ttest(wide, "pct_a", "pct_b", "Headline: crossover t")
    lmm_label = "Pre-specified mixed model (Wald z; anti-conservative at this n)"
    lmm = attempt(lmm_label, PP, lambda: fit_lmm(wide, "pct_a", "pct_b", lmm_label))
    specs: list[tuple[str, str, Callable[[str], Estimate]]] = [
        (WELCH_LABEL, PP,
         lambda label: crossover_welch(wide, "pct_a", "pct_b", label)),
        ("S1 Excluding re-reading, AI use or discussion", PP,
         lambda label: crossover_ttest(clean, "pct_a", "pct_b", label)),
        (PERMUTATION_LABEL, PP,
         lambda label: permutation_test(wide, "pct_a", "pct_b", label, seed=cfg.permutation_seed)),
        ("S3 Item-level logistic GEE (odds ratio > 1 favours Bloomer)", "odds ratio",
         lambda label: fit_gee_items(items, label)),
        ("S4 Unanswered items treated as missing", PP,
         lambda label: crossover_ttest(wide, "pct_answered_a", "pct_answered_b", label)),
        ("S5 Methods-as-written raw item count (A4 included)", "items correct",
         lambda label: crossover_ttest(wide, "points5_a", "points5_b", label, unit="items correct")),
    ]
    # SAP v3.0: the primary analysis with the assignment-email group where the study team recorded one
    assigned = (assigned_groups(load_verified_csv(cfg.root, manifest["outputs"]["links_registration"]))
                if "links_registration" in manifest["outputs"] else {})
    if assigned:
        pop_assigned = pop.assign(group=pop["pid"].map(assigned).fillna(pop["group"]))
        wide_assigned = participant_scores(item_long(pop_assigned, cfg.a4_offered_from), pop_assigned)
        specs.append((ASSIGNED_GROUP_LABEL, PP,
                      lambda label: crossover_ttest(wide_assigned, "pct_a", "pct_b", label)))
    sensitivity = [attempt(label, unit, lambda f=fit, lb=label: f(lb)) for label, unit, fit in specs]

    results = build_results(
        freeze_date=cfg.freeze_date,
        a4_offered_from=cfg.a4_offered_from,
        flow=flow,
        part1=[part1_mcq_summary(mcq[paper], paper, cfg.study_start, cfg.freeze_date, cfg.a4_offered_from)
               for paper in "AB"],
        headline=headline,
        lmm=lmm,
        sensitivity=sensitivity,
        descriptives=cell_descriptives(wide),
        items=item_summary(items),
        perceived=perceived_retention(pop),
        prov=prov,
        status=cfg.status,
    )
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    write_json(results, cfg.outputs_dir / "results.json")
    (cfg.outputs_dir / "report.md").write_text(render_report(results), encoding="utf-8")
    plot_retention(wide, [headline, lmm, *sensitivity], cfg.outputs_dir / "fig_retention")
    return results


def run_survey3(config_path: str | Path, allow_dirty: bool = False) -> dict | None:
    """SAP Part B. Returns None when the manifest has no Survey 3 output (the input is not configured)."""
    cfg, manifest, prov = _load_checked(config_path, allow_dirty)
    if "survey3" not in manifest["outputs"]:
        return None
    survey = load_verified_csv(cfg.root, manifest["outputs"]["survey3"])
    mcq = {paper: load_verified_csv(cfg.root, manifest["outputs"][f"mcq_part1_{paper}"]) for paper in "AB"}
    pop, flow = survey3_population(survey, cfg.study_start, cfg.freeze_date)
    ingest_stats = manifest["inputs"]["survey3"]
    flow["duplicates_removed_at_ingest"] = ingest_stats["n_duplicates_dropped"]
    flow["rows_without_contact_email"] = ingest_stats["n_without_contact_email"]
    flow["other_recoded"] = ingest_stats["n_other_recoded"]
    feedback = (feedback_themes(load_verified_csv(cfg.root, manifest["outputs"]["feedback_codes"]), pop["pid"])
                if "feedback_codes" in manifest["outputs"] else None)
    results = build_survey3_results(
        freeze_date=cfg.freeze_date,
        flow=flow,
        adoption=choice_outcome(pop, "preference", PREFERENCE_BLOOMER, PREFERENCE_QUIZ),
        comprehension=choice_outcome(pop, "best_comprehension", COMPREHENSION_BLOOMER, COMPREHENSION_QUIZ),
        difficulty=difficulty(pop),
        usage=usage(pop),
        quiz_elapsed=quiz_elapsed(mcq, cfg.study_start, cfg.freeze_date),
        table1=table1(pop),
        subgroups=subgroups(pop),
        prior_knowledge=prior_knowledge_context(pop, mcq, cfg.study_start, cfg.freeze_date),
        feedback=feedback,
        prov=prov,
        status=cfg.status,
    )
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    write_json(results, cfg.outputs_dir / "survey3_results.json")
    (cfg.outputs_dir / "survey3_report.md").write_text(render_survey3_report(results), encoding="utf-8")
    plot_survey3(pop, cfg.outputs_dir / "fig_survey3")
    return results


PARTC_OUTPUT_KEYS = ("start", "links_part1", "links_phase3")


def run_partc(config_path: str | Path, allow_dirty: bool = False) -> dict | None:
    """SAP Part C. Returns None unless the manifest has the Start form and both link candidate files (ingest writes
    the link files only when start and survey3 are both configured)."""
    cfg, manifest, prov = _load_checked(config_path, allow_dirty)
    if not all(key in manifest["outputs"] for key in PARTC_OUTPUT_KEYS):
        return None
    if cfg.linkage_seed is None or cfg.linkage_draws is None:
        raise ValueError("Part C needs [study] linkage_seed and linkage_draws in the config")
    if cfg.linkage_draws < 1:
        raise ValueError(f"Part C [study] linkage_draws must be at least 1 (got {cfg.linkage_draws})")

    def load(key: str) -> pd.DataFrame:
        return load_verified_csv(cfg.root, manifest["outputs"][key])

    phase3_pop, _ = phase3_population(load("phase3"), cfg.freeze_date)
    wide = participant_scores(item_long(phase3_pop, cfg.a4_offered_from), phase3_pop)
    survey_pop, _ = survey3_population(load("survey3"), cfg.study_start, cfg.freeze_date)
    scores = {paper: mcq_scores(load(f"mcq_part1_{paper}"), paper, cfg.study_start, cfg.freeze_date,
                                cfg.a4_offered_from) for paper in "AB"}
    linked = linked_analyses(load("links_part1"), load("links_phase3"), pd.concat(scores.values(), ignore_index=True),
                             survey_pop, phase3_pop, wide, draws=cfg.linkage_draws, seed=cfg.linkage_seed)
    # SAP Part F (version 2.7): counts over Part A's analysed Phase 3 population, when the link file exists
    registration = (registration_link_summary(load("links_registration"), phase3_pop, load("start"))
                    if "links_registration" in manifest["outputs"] else None)
    results = build_partc_results(
        freeze_date=cfg.freeze_date,
        flow=flow_and_returns(load("start"), scores, survey_pop, phase3_pop, cfg.study_start, cfg.freeze_date),
        tipping=tipping_point(wide),
        forgetting=forgetting_unlinked(scores, wide),
        forgetting_pooled=forgetting_pooled(scores, wide),
        linked=linked,
        prov=prov,
        registration_link=registration,
        status=cfg.status,
    )
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    write_json(results, cfg.outputs_dir / "partc_results.json")
    (cfg.outputs_dir / "partc_report.md").write_text(render_partc_report(results), encoding="utf-8")
    plot_partc(results, linked["per_draw"], cfg.outputs_dir / "fig_partc")
    return results


def run_partd(config_path: str | Path, allow_dirty: bool = False) -> dict | None:
    """SAP Part D. Returns None unless the manifest lists the roster link file (ingest writes it only when
    part2_roster and survey3 are both configured)."""
    cfg, manifest, prov = _load_checked(config_path, allow_dirty)
    if "links_roster" not in manifest["outputs"]:
        return None

    def load(key: str) -> pd.DataFrame:
        return load_verified_csv(cfg.root, manifest["outputs"][key])

    phase3_pop, _ = phase3_population(load("phase3"), cfg.freeze_date)
    wide = participant_scores(item_long(phase3_pop, cfg.a4_offered_from), phase3_pop)
    survey_pop, _ = survey3_population(load("survey3"), cfg.study_start, cfg.freeze_date)
    scores = pd.concat([mcq_scores(load(f"mcq_part1_{paper}"), paper, cfg.study_start, cfg.freeze_date,
                                   cfg.a4_offered_from) for paper in "AB"], ignore_index=True)
    links, alternatives = load("links_roster"), load("links_roster_alternatives")
    # the chain to Part 1 needs Part C's Part 1 link candidates; without them D4 has no MCQ-side ratings
    pairs = (part1_certain_pairs(load("links_part1"), scores, survey_pop)
             if "links_part1" in manifest["outputs"] else {})
    pop, flow = partd_population(links, wide, phase3_pop, survey_pop)
    contrasts = subgroup_contrasts(pop)
    results = build_partd_results(
        freeze_date=cfg.freeze_date,
        flow=flow,
        link_quality=link_quality(links, manifest["inputs"]["part2_roster"], pop, pairs),
        equal_weight=equal_weight_benefit(pop),
        benefit=benefit_summary(pop),
        contrasts=contrasts,
        adjusted=adjusted_benefit(pop, scores, pairs),
        preference=preference_vs_benefit(pop),
        usage=usage_vs_benefit(pop),
        interval=retention_interval(pop),
        sensitivity=alternatives_sensitivity(alternatives, links, wide, phase3_pop, survey_pop, scores,
                                             pairs),
        prov=prov,
        status=cfg.status,
    )
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    write_json(results, cfg.outputs_dir / "partd_results.json")
    (cfg.outputs_dir / "partd_report.md").write_text(render_partd_report(results), encoding="utf-8")
    plot_partd(pop, contrasts, cfg.outputs_dir / "fig_partd")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/study.toml")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="write outputs even when code/config/SAP have uncommitted changes (stamped +dirty)")
    args = parser.parse_args(argv)
    try:
        results = run_analysis(args.config, allow_dirty=args.allow_dirty)
    except UncommittedChangesError as err:
        print(err, file=sys.stderr)
        raise SystemExit(2) from None
    head = results["primary"]["headline"]
    print(f"{results['status']}: analysed n={head['n_a'] + head['n_b']} "
          f"(group A {head['n_a']}, group B {head['n_b']}). Outputs: {load_config(args.config).outputs_dir}")
    try:  # the retention outputs above are already written and stay valid if Survey 3 fails
        survey = run_survey3(args.config, allow_dirty=args.allow_dirty)
    except Exception as err:  # noqa: BLE001 - any Survey 3 failure exits 3 (SAP B8); retention outputs stay
        print(f"Survey 3 analysis failed; retention outputs were written: {type(err).__name__}: {err}",
              file=sys.stderr)
        raise SystemExit(3) from None
    if survey is not None:
        print(f"Survey 3: analysed n={survey['flow']['analysed']}. Outputs: survey3_report.md, survey3_results.json")
    try:  # Part A and B outputs above are already written and stay valid if Part C fails
        partc = run_partc(args.config, allow_dirty=args.allow_dirty)
    except Exception as err:  # noqa: BLE001 - any Part C failure exits 4 (SAP C8); Part A and B outputs stay
        print(f"Part C analysis failed; Part A and B outputs were written: {type(err).__name__}: {err}",
              file=sys.stderr)
        raise SystemExit(4) from None
    if partc is not None:
        print(f"Part C: {partc['linked']['draws']} draws per family (exploratory). "
              "Outputs: partc_report.md, partc_results.json")
    try:  # Part A, B and C outputs above are already written and stay valid if Part D fails
        partd = run_partd(args.config, allow_dirty=args.allow_dirty)
    except Exception as err:  # noqa: BLE001 - any Part D failure exits 5 (SAP D8); A, B and C outputs stay
        print(f"Part D analysis failed; Part A, B and C outputs were written: {type(err).__name__}: {err}",
              file=sys.stderr)
        raise SystemExit(5) from None
    if partd is not None:
        print(f"Part D: {partd['flow']['analysed']} roster-linked people (exploratory). "
              "Outputs: partd_report.md, partd_results.json")
