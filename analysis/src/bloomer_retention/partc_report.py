"""Part C outputs: partc_results.json, partc_report.md and fig_partc.{pdf,png} (SAP Part C, C8).

Aggregates only: no pid, pair or timestamp is written.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from bloomer_retention.crossover import PP  # noqa: E402
from bloomer_retention.partc import GROUPS, ROLE_OPTIONS  # noqa: E402
from bloomer_retention.labels import NPI_UNMATCHED_LABEL, run_status  # noqa: E402
from bloomer_retention.report import (  # noqa: E402
    BLOOMER_COLOR,
    LABEL_COLOR,
    MUTED_COLOR,
    REF_COLOR,
    SAP_VERSION,
    _clean,
    _num,
    _row,
    fmt_estimate,
    fmt_p,
    input_line,
)

GROUP_COLORS = {"A": "#374151", "B": "#9CA3AF"}
DEVIATIONS = (
    "No form carries a participant identifier, so every person-level result rests on probabilistic links by "
    "timestamp and group, summarised across many sampled matchings beside a random-matching reference.",
    "Part C was written after the Part A and Part B interim results were seen, so every Part C analysis is "
    "exploratory.",
)
BIASES = (
    "Link errors dilute associations toward what random matching gives, so linked estimates are pulled toward the "
    "random reference; agreement with the reference does not show that no association exists.",
    "C4.1 and C5.2 are means over (nearly) all linked forms, so they barely depend on who is paired with whom: they "
    "restate unlinked group comparisons (C5.2 is close to the C3 comparison weighted by Phase 3 group sizes) and add "
    "no person-level evidence, even when their 95% CI excludes 0.",
    "Attrition: people who returned Survey 3 or Phase 3 may differ from those who did not, and return rates compare "
    "counts of unlinked forms, not followed people.",
    "Group is self-reported on the Phase 3 form and taken from the Bloomer paper on Survey 3.",
    "Subgroups are very small: many draws can be not estimable, and pooled estimates rest on the estimable draws "
    "only (share reported).",
    "The gap weights, windows, clear-pair margins and the 90% stability threshold are assumptions, not estimated.",
    "Rubin's rules treat the sampled matchings like imputations, but the sampler is not a posterior distribution "
    "over matchings, so the pooled intervals are approximate.",
    "Part A and Part B interim results, and aggregate counts from a timestamp spike on the real exports, were seen "
    "before Part C was written (SAP C9).",
)
DIRECTION_LABELS = {"B_to_A": "Group B relabelled as A", "A_to_B": "Group A relabelled as B"}
RETURN_FOLLOW_UP_CAVEAT = (
    "Phase 3 invitations go out about a month after each Part 1, so MCQ forms completed shortly before the freeze "
    "could not yet have returned a Phase 3 form, and the Part 1 to Phase 3 rates are approximate.")
SMALLEST_K_CAVEAT = (
    "The smallest k below is a worst case across all subsets of that size, not an estimate: it asks whether any "
    "single subset's 95% CI excludes 0.")
VERDICTS = {False: "no (inside the random-matching range)", True: "yes (outside the random-matching range)"}
TABLE_NOTES = (
    "Date-based intervals are normal-quantile 95% CIs (Rubin's rules) over the estimable draws. The random reference "
    "column is the spread of estimates across random matchings, not a confidence interval.",
    "Differs from random matching? Compares the date-based estimate with estimates from random matchings. A "
    "difference needs both informative links and a real association, so \"no\" does not show that the links are "
    "uninformative or that no association exists. \"Yes\" means the date-based estimate lies outside the 2.5th to "
    "97.5th percentile range of the reference draws.",
)
GROUP_CHECK_LIMITATION = (
    "When the date-based and random 2.5th to 97.5th percentile ranges coincide or overlap heavily, this check cannot "
    "detect mislabelling, and the shares are not estimates of a mislabelling rate.")
LINK_LABELS = {"part1": ("Part 1 link (Survey 3 to MCQ form)", "h"), "phase3": ("Phase 3 link (Phase 3 to MCQ form)",
                                                                                 "days")}


def build_partc_results(*, freeze_date: date, flow: dict, tipping: dict, forgetting: dict, forgetting_pooled: dict,
                        linked: dict, prov: dict, registration_link: dict | None = None,
                        status: str = "interim") -> dict:
    return _clean({
        "status": run_status(status, freeze_date),
        "sap": f"{SAP_VERSION} (Part C)",
        "flow": flow,
        "tipping_point": tipping,
        "forgetting_unlinked": forgetting,
        "forgetting_pooled": forgetting_pooled,
        "linked": {key: value for key, value in linked.items() if key != "per_draw"},
        **({"registration_link": registration_link} if registration_link is not None else {}),
        "deviations": DEVIATIONS,
        "known_biases": BIASES,
        "provenance": prov,
    })


def _registration_lines(entry: dict) -> list[str]:
    """SAP Part F: counts and the interval only; no group comparison."""
    interval = entry["interval_days"]

    def days(key: str) -> str:
        return "-" if interval[key] is None else f"{interval[key]:.1f}"

    def counts(by: dict) -> str:
        return ", ".join(f"{option} {n}" for option, n in by.items())

    return [
        "", "## Part F. Retention to sign-up link (SAP Part F)", "",
        f"{entry['n_linked']} of {entry['n_population']} analysed retention responses are linked to a sign-up "
        f"(Start form) row: {entry['n_by_basis']['record']} from records (sign-up email or tracker name) and "
        f"{entry['n_by_basis']['timing']} decided by the study team on timing. The Part 1 quiz forms are anonymous, "
        "so no Part 1 link is possible.",
        "",
        f"Sign-up to retention, days (an upper bound on the Part 1 to retention interval): median "
        f"{days('median')} (IQR {days('q1')} to {days('q3')}; range {days('min')} to {days('max')}; n = "
        f"{interval['n']}).",
        "",
        f"Among the linked: US-based {counts(entry['us_based'])}; role {counts(entry['role'])}. "
        + ("Counts only; no group or assignment comparison is made (deferred by the author)."
           if "followup" not in entry else "Counts only."),
        *_followup_lines(entry.get("followup")),
    ]


def _followup_lines(followup: dict | None) -> list[str]:
    """SAP version 3.0: assignment-email agreement and the two record-based intervals, as counts and summaries."""
    if followup is None:
        return []
    agree = followup["assignment"]

    def summary(interval: dict) -> str:
        if interval["n"] == 0:
            return "no records"
        return (f"median {interval['median']:.1f} (IQR {interval['q1']:.1f} to {interval['q3']:.1f}; range "
                f"{interval['min']:.1f} to {interval['max']:.1f}; n = {interval['n']})")

    return [
        "", "### Study-team follow-up records (SAP F4)", "",
        f"Assignment email recorded for {agree['n_recorded']} of {agree['n_population']} analysed retention "
        f"responses; the self-reported group agrees for {agree['n_agree']} and differs for {agree['n_disagree']}.",
        "",
        f"Part 1 (Bloomer summary received) to retention, days: {summary(followup['part1_to_retention_days'])}.",
        "",
        f"Retention link sent to retention, days: {summary(followup['link_to_retention_days'])}.",
    ]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def _digits(unit: str) -> int:
    return 2 if unit == "rho" else 1


def _flow_lines(flow: dict) -> list[str]:
    start, counts = flow["start"], flow["counts_by_group"]
    lines = [
        f"Start form signups analysed: {start['analysed']} (de-identified {start['deidentified']}; pilot rows excluded "
        f"{start['excluded_pilot']}; signed up after the freeze date {start['excluded_after_freeze']}; "
        f"{NPI_UNMATCHED_LABEL} {start['excluded_npi_unmatched']}). By role: "
        + "; ".join(f"{role} {n}" for role, n in start["by_role"].items()) + ". Analysed signups answering No to "
        f"US-based: {start['analysed_not_us_based']} (they stay in every count, SAP C6).",
        "",
        _row(["Form", "Group A", "Group B", "Total"]), _row(["---"] * 4),
    ]
    for label, key in (("Part 1 MCQ forms (Paper A form = group A)", "part1_mcq"), ("Survey 3 analysed", "survey3"),
                       ("Phase 3 analysed", "phase3")):
        # the total counts the population, so it can exceed A + B when a form carries no group (C1)
        lines.append(_row([label, counts[key]["A"], counts[key]["B"], counts[key]["total"]]))
    lines += ["", f"Survey 3 respondents without a Bloomer paper (no group): {flow['survey3_without_group']}.", "",
              "Return rates compare counts of unlinked forms, not followed people.", "",
              _row(["Return", "Group A", "Group B", "Fisher's exact P"]), _row(["---"] * 4)]
    for label, key in (("Part 1 to Survey 3", "survey3"), ("Part 1 to Phase 3", "phase3")):
        entry = flow["returns"][key]
        cells = [f"{entry['by_group'][g]['n_returned']} of {entry['by_group'][g]['n_part1']} "
                 f"({_pct(entry['by_group'][g]['pct'])})" for g in GROUPS]
        lines.append(_row([label, *cells, fmt_p(entry["p_value"]) if entry["p_value"] is not None else "not run"]))
    notes = [f"- {label}: {flow['returns'][key]['note']}." for label, key in
             (("Part 1 to Survey 3", "survey3"), ("Part 1 to Phase 3", "phase3")) if flow["returns"][key]["note"]]
    lines += ["", *notes] if notes else []
    lines += ["", RETURN_FOLLOW_UP_CAVEAT]
    lines += ["", _row(["Role", "Signups, n (%)", "Survey 3, n (%)"]), _row(["---"] * 3)]
    for role in (*ROLE_OPTIONS, "blank"):
        signup, survey = flow["role_mix"]["signup"][role], flow["role_mix"]["survey3"][role]
        lines.append(_row(["Blank" if role == "blank" else role, f"{signup['n']} ({_pct(signup['pct'])})",
                           f"{survey['n']} ({_pct(survey['pct'])})"]))
    return lines


def _tipping_lines(tipping: dict) -> list[str]:
    observed = tipping["observed"]
    head = ("not estimable" if observed is None else
            f"{fmt_estimate(observed['theta'], observed['ci_low'], observed['ci_high'])} percentage points")
    lines = [f"Headline crossover t without relabelling: {head}. Each row relabels every subset of k Phase 3 "
             "responses from one group to the other and recomputes the headline.", "",
             _row(["Direction", "k", "Subsets", "Not estimable", "Theta range, percentage points",
                   "Subsets with 95% CI excluding 0", "Subsets with 95% CI above 0 / below 0"]), _row(["---"] * 7)]
    for key, direction in tipping["directions"].items():
        for row in direction["by_k"]:
            theta_range = ("-" if row["theta_min"] is None
                           else f"{row['theta_min']:.1f} to {row['theta_max']:.1f}")
            share = "-" if row["share_ci_excludes_zero"] is None else f"{100 * row['share_ci_excludes_zero']:.1f}%"
            sides = ("-" if row["share_ci_excludes_zero"] is None
                     else f"{row['n_ci_above_zero']} / {row['n_ci_below_zero']}")
            lines.append(_row([DIRECTION_LABELS[key], row["k"], row["n_subsets"], row["n_not_estimable"], theta_range,
                               share, sides]))
    lines.append("")
    if tipping["observed_ci_excludes_zero"]:
        lines += ["The headline 95% CI already excludes 0 without relabelling, so the smallest k below does not mark "
                  "a tipping point; the theta ranges show how far relabelling can move the estimate.", ""]
    lines += [SMALLEST_K_CAVEAT, ""]
    for key, direction in tipping["directions"].items():
        smallest = direction["smallest_k_ci_excludes_zero"]
        lines.append(f"- {DIRECTION_LABELS[key]} ({direction['n_source']} responses in the source group): smallest k "
                     f"at which any subset's CI excludes 0: {'none' if smallest is None else smallest}.")
    return lines


def _forgetting_lines(forgetting: dict, pooled: dict) -> list[str]:
    lines = ["Different respondents: Part 1 immediate scores (percent of valid items, D4 rule) against the 1-month "
             "score on the MCQ-studied article from Phase 3. This compares groups of forms, not people.", "",
             _row(["Article (group)", "Part 1 immediate, n; mean %", "1 month, n; mean %",
                   "1 month minus immediate, percentage points (Welch 95% CI)"]), _row(["---"] * 4)]
    for paper in GROUPS:
        row = forgetting[paper]
        lines.append(_row([f"Paper {paper} (group {paper})", f"{row['n_immediate']}; {_num(row['mean_immediate'])}",
                           f"{row['n_one_month']}; {_num(row['mean_one_month'])}",
                           fmt_estimate(row["difference"], row["ci_low"], row["ci_high"])]))
    lines.append(_row(["Both articles, equal weight", str(pooled["n_immediate"]), str(pooled["n_one_month"]),
                       fmt_estimate(pooled["difference"], pooled["ci_low"], pooled["ci_high"])]))
    lines += ["", "Both articles, equal weight: the mean of the two article differences, each article weighted "
              "equally as in the primary estimand (Welch-Satterthwaite df over the four groups of forms)."]
    return lines


def _link_quality_lines(linked: dict) -> list[str]:
    quality = linked["link_quality"]
    labels = [LINK_LABELS[key][0] for key in ("part1", "phase3")]
    lines = [_row(["", *labels]), _row(["---"] * 3)]

    def cells(fn) -> list[str]:
        return [fn(quality[key], LINK_LABELS[key][1]) for key in ("part1", "phase3")]

    def best(q: dict, unit: str) -> str:
        b = q["best_matching"]
        if not b["n_pairs"]:
            return "0"
        return f"{b['n_pairs']}; {b['gap_median']:.1f} {unit} ({b['gap_q1']:.1f} to {b['gap_q3']:.1f})"

    def per_draw(summary: dict) -> str:
        return "-" if summary["median"] is None else f"{summary['median']:.1f} ({summary['min']} to {summary['max']})"

    lines += [
        _row(["MCQ forms in the population", *cells(lambda q, _: q["n_left_in_population"])]),
        _row(["Forms to link in the population", *cells(lambda q, _: q["n_right_in_population"])]),
        _row(["Candidate pairs (population, any group) / with positive same-group weight",
              *cells(lambda q, _: f"{q['n_candidate_edges']} / {q['n_positive_weight_edges']}")]),
        _row(["Forms to link with at least one weighted candidate", *cells(lambda q, _: q["n_right_with_candidate"])]),
        _row(["Best matching: pairs; gap median (IQR)", *cells(best)]),
        _row(["Clear pairs (no rival candidate within the margin)",
              *cells(lambda q, unit: f"{q['clear_pairs']} (margin {q['clear_margin']:g} {unit})")]),
        _row(["Pairs in at least 90% of date-based draws", *cells(lambda q, _: q["stable_pairs"])]),
        _row(["Matched per date-based draw, median (range)", *cells(lambda q, _: per_draw(q["matched_per_draw"]))]),
        "",
        "Phase 3 people whose MCQ form is also linked to a Survey 3 in the same draw, median (range): "
        f"{per_draw(quality['phase3']['matched_with_survey3_per_draw'])}.",
    ]
    return lines


def _estimate_rows(linked: dict, sections: tuple[str, ...]) -> list[str]:
    lines = [_row(["Analysis", "Date-based, pooled (normal-quantile 95% CI, Rubin's rules)",
                   "Date-based draws estimable", "Reference draws estimable",
                   "Random reference, median (2.5th to 97.5th percentile)", "Percentile among reference draws",
                   "Differs from random matching?"]),
             _row(["---"] * 7)]
    for key, entry in linked["estimates"].items():
        if entry["section"] not in sections:
            continue
        date_based, reference = entry["date"], entry["reference"]
        digits = _digits(entry["unit"])
        unit = "" if entry["unit"] in (PP, "rho") else f" {entry['unit']}"
        estimate = fmt_estimate(date_based["estimate"], date_based["ci_low"], date_based["ci_high"], digits) + unit
        ref = ("not estimable" if reference["median"] is None else
               f"{reference['median']:.{digits}f} ({reference['p2_5']:.{digits}f} to {reference['p97_5']:.{digits}f})")
        flag = entry["differs_from_random_matching"]
        verdict = "-" if flag is None else VERDICTS[flag]
        percentile = "-" if entry["reference_percentile"] is None else f"{entry['reference_percentile']:.1f}"
        lines.append(_row([f"{entry['section']} {entry['label']}", estimate,
                           f"{date_based['n_estimable']} of {date_based['n_draws']}",
                           f"{reference['n_estimable']} of {reference['n_draws']}", ref, percentile, verdict]))
    return lines


def _table_notes(linked: dict, sections: tuple[str, ...], extra: tuple[str, ...] = ()) -> list[str]:
    """Notes under a C4 or C5 table: interval labels, the verdict definition, then per-analysis notes (SAP C7)."""
    notes = [*TABLE_NOTES]
    notes += [f"{entry['section']}: {entry['note']}" for entry in linked["estimates"].values()
              if entry["section"] in sections and entry["note"]]
    return ["", *[f"- {note}" for note in (*notes, *extra)]]


def render_partc_report(results: dict) -> str:
    flow, prov, linked = results["flow"], results["provenance"], results["linked"]
    lines = [
        "# Bloomer vs MCQ: cross-phase analyses without identifiers (Part C)",
        "",
        f"**{results['status']}.** Specified in `{results['sap']}` after the Part A and Part B interim results were "
        f"seen: every analysis below is exploratory. Code version `{prov['code_commit']}`.",
        "",
        "Percentage points are Bloomer minus MCQ unless stated. Person-level results (C4, C5) rest on probabilistic "
        f"links by timestamp and group: each is recomputed in {linked['draws']} sampled matchings, pooled with "
        "Rubin's rules over the draws in which it is estimable, and set beside the same analysis on random matchings.",
        "",
        "## C1. Flow and return rates", "", *_flow_lines(flow),
        "", "## C2. Group-mislabeling tipping point", "", *_tipping_lines(results["tipping_point"]),
        "", "## C3. Forgetting in the MCQ arm (unlinked)", "", *_forgetting_lines(results["forgetting_unlinked"], results["forgetting_pooled"]),
        "", "## Link quality", "", *_link_quality_lines(linked),
        "", "## C4. Part 1 person-level analyses (Survey 3 to MCQ form link)", "",
        *_estimate_rows(linked, ("C4.1", "C4.2", "C4.3")),
        *_table_notes(linked, ("C4.1", "C4.2", "C4.3"), ("C4.3 is pooled on Fisher's z and shown as Spearman rho.",)),
        "", "## C5. Phase 3 person-level analyses (Phase 3 to MCQ form link; sensitivity analysis)", "",
        *_estimate_rows(linked, ("C5.1", "C5.2", "C5.3")),
        *_table_notes(linked, ("C5.1", "C5.2", "C5.3")),
        "",
    ]
    check = linked["group_label_check"]

    def share(summary: dict) -> str:
        if summary["median"] is None:
            return f"not estimable (estimable in {summary['n_estimable']} of {summary['n_draws']} draws)"
        return (f"median {100 * summary['median']:.1f}% (2.5th to 97.5th percentile, {100 * summary['p2_5']:.1f}% to "
                f"{100 * summary['p97_5']:.1f}%; estimable in {summary['n_estimable']} of {summary['n_draws']} draws)")

    lines += [
        "C5.4 Group-label check (group ignored when matching): share of matched Phase 3 people whose MCQ form group "
        f"differs from their self-reported group. With dates: {share(check['with_dates'])}. Random matching without "
        f"dates: {share(check['without_dates'])}. {GROUP_CHECK_LIMITATION}",
        *(_registration_lines(results["registration_link"]) if "registration_link" in results else []),
        "", "## Method notes", "", *[f"- {d}" for d in results["deviations"]],
        "", "## Known biases", "", *[f"- {b}" for b in results["known_biases"]],
        "", "## Reproducibility", "",
        f"- Python {prov['python']}; " + ", ".join(f"{k} {v}" for k, v in prov["packages"].items()),
        f"- Config `{prov['config']}`; figure `fig_partc.pdf` / `.png`",
        f"- Linkage: seed {linked['seeds']['date_part1']}, {linked['draws']} draws per family; seeds by family: "
        + ", ".join(f"{name} {seed}" for name, seed in linked["seeds"].items()),
    ]
    for key in ("start", "survey3", "phase3", "mcq_part1_A", "mcq_part1_B"):
        if key in prov["inputs"]:
            lines.append(input_line(key, prov["inputs"][key]))
    for key in ("links_part1", "links_phase3"):
        if key in prov["deidentified"]:
            entry = prov["deidentified"][key]
            lines.append(f"- Link candidates `{entry['file']}`: sha256 `{entry['sha256'][:12]}`, {entry['n_rows']} rows")
    return "\n".join(lines) + "\n"


def plot_partc(results: dict, per_draw: dict, out_stem: Path) -> list[Path]:
    """a: forms by group; b: tipping-point theta ranges by k; c: per-draw adjusted theta, date-based vs random."""
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": REF_COLOR,
        "axes.linewidth": 0.8, "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fig, (ax_a, ax_b, ax_c) = plt.subplots(1, 3, figsize=(10.5, 3.9))
    below = {"loc": "upper center", "bbox_to_anchor": (0.5, -0.2), "frameon": False, "fontsize": 7.5}

    counts = results["flow"]["counts_by_group"]
    stages = (("part1_mcq", "Part 1\nMCQ form"), ("survey3", "Survey 3"), ("phase3", "Phase 3"))
    for offset, group in ((-0.18, "A"), (0.18, "B")):
        heights = [counts[key][group] for key, _ in stages]
        bars = ax_a.bar(np.arange(len(stages)) + offset, heights, width=0.34, color=GROUP_COLORS[group],
                        label=f"Group {group}")
        for bar, height in zip(bars, heights):
            ax_a.text(bar.get_x() + bar.get_width() / 2, height, str(height), ha="center", va="bottom", fontsize=8,
                      color=LABEL_COLOR)
    ax_a.set_xticks(range(len(stages)), [label for _, label in stages])
    ax_a.set_ylabel("Forms analysed")
    ax_a.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax_a.legend(ncol=2, **below)

    tipping = results["tipping_point"]
    for offset, key, marker in ((-0.12, "B_to_A", "o"), (0.12, "A_to_B", "s")):
        for row in tipping["directions"][key]["by_k"]:
            if row["theta_min"] is None:
                continue
            ax_b.plot([row["k"] + offset] * 2, [row["theta_min"], row["theta_max"]], color=MUTED_COLOR, linewidth=1.4)
            ax_b.scatter([row["k"] + offset] * 2, [row["theta_min"], row["theta_max"]], marker=marker, s=14,
                         color=MUTED_COLOR, zorder=2)
    if tipping["observed"] is not None:
        ax_b.axhline(tipping["observed"]["theta"], color=BLOOMER_COLOR, linewidth=0.9, label="Observed theta")
    ax_b.axhline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_b.set_xlabel("Responses relabelled (k)", labelpad=2)
    ax_b.set_ylabel("Theta range, percentage points")
    ax_b.legend(handles=[plt.Line2D([], [], marker="o", color=MUTED_COLOR, label="B relabelled as A"),
                         plt.Line2D([], [], marker="s", color=MUTED_COLOR, label="A relabelled as B"),
                         plt.Line2D([], [], color=BLOOMER_COLOR, label="Observed theta")], ncol=2, **below)

    dated = np.asarray(per_draw["adjusted_theta"]["date"], dtype=float)
    reference = np.asarray(per_draw["adjusted_theta"]["reference"], dtype=float)
    if len(dated) or len(reference):
        values = np.concatenate([dated, reference])
        bins = np.histogram_bin_edges(values, bins=30) if np.ptp(values) > 0 else 10
        if len(reference):
            ax_c.hist(reference, bins=bins, color=REF_COLOR, alpha=0.7, label="Random reference")
        if len(dated):
            ax_c.hist(dated, bins=bins, histtype="step", color=LABEL_COLOR, linewidth=1.2, label="Date-based")
        pooled = results["linked"]["estimates"]["adjusted_theta"]["date"]["estimate"]
        if pooled is not None:
            ax_c.axvline(pooled, color=BLOOMER_COLOR, linewidth=1.0)
        ax_c.legend(handles=[mpatches.Patch(color=REF_COLOR, label="Random reference"),
                             plt.Line2D([], [], color=LABEL_COLOR, label="Date-based"),
                             plt.Line2D([], [], color=BLOOMER_COLOR, label="Date-based pooled")], ncol=2, **below)
    else:
        ax_c.text(0.5, 0.5, "Not estimable in any draw", ha="center", va="center", transform=ax_c.transAxes,
                  color=MUTED_COLOR)
    ax_c.set_xlabel("Adjusted theta per draw, percentage points")
    ax_c.set_ylabel("Draws")

    for ax, letter in ((ax_a, "a"), (ax_b, "b"), (ax_c, "c")):
        ax.text(-0.14, 1.05, letter, transform=ax.transAxes, fontsize=14, fontweight="bold", color=LABEL_COLOR)
    fig.tight_layout()
    paths = []
    for suffix in (".pdf", ".png"):
        path = out_stem.with_suffix(suffix)
        fig.savefig(path, dpi=600, bbox_inches="tight", pad_inches=0.15,
                    metadata={"CreationDate": None} if suffix == ".pdf" else None)
        paths.append(path)
    plt.close(fig)
    return paths
