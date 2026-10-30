"""Part D outputs: partd_results.json, partd_report.md and fig_partd.{pdf,png} (SAP Part D, D8).

No name, date, time, pid or raw pair list is written. Not aggregates only, though: fig_partd carries one mark per
linked person (panel a one bar, panel c one point), so the Part D outputs are restricted like survey3_report.md.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.lines as mlines  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bloomer_retention.partd import (  # noqa: E402
    CONTRAST_LABELS,
    EQUAL_WEIGHT_LABEL,
    MIN_PEOPLE,
    MIN_PER_LEVEL,
)
from bloomer_retention.report import (  # noqa: E402
    BLOOMER_COLOR,
    LABEL_COLOR,
    MCQ_COLOR,
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
from bloomer_retention.roster_link import _plural  # noqa: E402
from bloomer_retention.survey3_report import _median_iqr  # noqa: E402
from bloomer_retention.labels import run_status  # noqa: E402

NAME_METHOD_LABELS = {
    "name_exact": "Exact normalised name",
    "name_tokens": "Two or more shared name tokens",
    "name_single_token": "Single-token name carried by one row (weaker)",
    "name_fuzzy": "Spelling variant within the fuzzy ratio (weaker)",
}
SURVEY3_METHOD_LABELS = {"date_unique": "One Survey 3 response on the Part 2 date",
                         "date_time": "Resolved by the Part 2 clock time", "group_resolved": "Resolved by group",
                         "enumerated": "Enumerated (tie on the Part 2 date)"}
DEVIATIONS = (
    "Part D links people through a study-team roster of names and Part 2 dates, so its population is a subset of "
    "Part A's: only people whose roster entry resolves to exactly one Survey 3 response and one Phase 3 response "
    "are analysed.",
    "Part D was written after the Part A, Part B and Part C interim results were seen, so every Part D analysis "
    "is exploratory (D9).",
    "Part D supersedes Part C's probabilistic Phase 3 link for the linked people; Part C's C5 estimates are kept "
    "unchanged beside it.",
)
BIASES = (
    "The Part D population is very small, so every estimate is imprecise and every subgroup contrast is "
    "exploratory, unadjusted and not corrected for multiplicity.",
    "Name matching can err: {exact} entries matched a Phase 3 row on the exact normalised name, {tokens} on shared "
    "name tokens, {single} on a single token and {fuzzy} on a spelling variant, and {unmatched_entries} matched no "
    "row. A wrong name match attaches the wrong Survey 3 answers and the wrong retention interval to a person. "
    "The last two steps are weaker, so the {weak_links} certain link(s) they produced are kept out of the headline "
    "population and enter only the D8 variant that includes them.",
    "Ties on a Part 2 date are resolved by the Part 2 clock time and by group agreement where possible and "
    "enumerated otherwise; the ambiguous links are excluded from the headline and varied in D8.",
    "The testing effect and the order effect of Part A still apply: MCQ-studied items were answered once in Part "
    "1 while Bloomer-studied items were first seen at 1 month, which biases the benefit toward MCQ.",
    "The roster holds {roster} entries, of which {matched} matched a Phase 3 response, and {unclaimed} claimed by "
    "no roster entry, so linked people may differ from unlinked ones.",
    "D4 uses the chained Part 1 MCQ form from Part C's probabilistic Part 1 link, restricted to certain pairs, so "
    "it inherits that link's error rate.",
    "Part A, Part B and Part C interim results were seen before Part D was written, and a count-only feasibility "
    "check of the roster was run before Part D was specified (D9).",
)
FIGURE_NOTE = "a: retention benefit per person, sorted; b: subgroup contrasts; c: benefit against the interval."


def build_partd_results(*, freeze_date: date, flow: dict, link_quality: dict, equal_weight: dict, benefit: dict,
                        contrasts: list[dict], adjusted: dict, preference: dict, usage: dict, interval: dict,
                        sensitivity: dict, prov: dict, status: str = "interim") -> dict:
    return _clean({
        "status": run_status(status, freeze_date),
        "sap": f"{SAP_VERSION} (Part D)",
        "flow": flow,
        "link_quality": link_quality,
        "equal_weight_benefit": equal_weight,
        "benefit": benefit,
        "subgroup_contrasts": contrasts,
        "adjusted_benefit": adjusted,
        "preference_vs_benefit": preference,
        "usage_vs_benefit": usage,
        "retention_interval": interval,
        "sensitivity": sensitivity,
        "deviations": DEVIATIONS,
        "known_biases": known_biases(link_quality),
        "provenance": prov,
    })


def known_biases(quality: dict) -> tuple[str, ...]:
    """SAP D8, with the actual name-match counts in the name-matching line."""
    by_name = quality.get("n_by_name_method", {})
    roster = quality.get("n_roster_rows", 0)
    unmatched_entries = quality.get("n_unmatched_roster_phase3", 0)  # roster entries that found no Phase 3 row
    unclaimed = quality.get("n_unmatched_phase3", 0)  # Phase 3 responses that no roster entry claims
    return tuple(bias.format(exact=by_name.get("name_exact", 0), tokens=by_name.get("name_tokens", 0),
                             single=by_name.get("name_single_token", 0), fuzzy=by_name.get("name_fuzzy", 0),
                             weak_links=quality.get("n_weak_name_links", 0),
                             unmatched_entries=unmatched_entries,
                             # coverage needs both counts: entries that found a Phase 3 row, and Phase 3
                             # responses no entry claims. The roster's own size is neither.
                             matched=roster - unmatched_entries,
                             unclaimed=f"{_plural(unclaimed, 'Phase 3 response')} "
                                       f"{'is' if unclaimed == 1 else 'are'}",
                             roster=roster) for bias in BIASES)


def _reason(entry: dict) -> str:
    return f"not estimable ({entry['reason']})" if entry.get("reason") else "not estimable"


def _correlation(entry: dict, digits: int = 2) -> str:
    if not entry.get("estimable"):
        return _reason(entry)
    return f"{entry['rho']:.{digits}f} (n = {entry['n']}); {fmt_p(entry['p_value'])}"


def _flow_lines(flow: dict, quality: dict) -> list[str]:
    lines = [
        f"Part A analysed {flow['phase3_analysed']} Phase 3 responses and Part B {flow['survey3_analysed']} Survey "
        f"3 responses. The roster holds {quality.get('n_roster_rows', 0)} entries and produced "
        f"{flow['roster_links']} links, of which {flow['certain_links']} are certain and "
        f"{flow['ambiguous_links']} ambiguous. Excluded from the certain links: "
        f"{flow['excluded_not_in_phase3_population']} outside the Phase 3 analysis population, "
        f"{flow['excluded_not_in_survey3_population']} outside the Survey 3 analysis population and "
        f"{flow['excluded_without_both_scores']} without both article scores, and "
        f"{flow['excluded_weak_name_match']} matched only through a weaker name step. Part D analyses "
        f"{flow['analysed']} people (group A {flow['analysed_group_A']}, group B {flow['analysed_group_B']}); "
        f"{quality['n_with_mcq_form']} of them have a chained Part 1 MCQ form.",
        "",
        _row(["Roster to Phase 3, by method", "n"]), _row(["---"] * 2),
    ]
    for method, label in NAME_METHOD_LABELS.items():
        lines.append(_row([label, quality.get("n_by_name_method", {}).get(method, 0)]))
    lines.append(_row(["No match, or more than one", quality.get("n_unmatched_roster_phase3", 0)]))
    lines += ["", "The headline population uses the first two steps only; the two weaker steps are reported and "
              "enter the D8 sensitivity analysis. Certain links from a weaker step: "
              f"{quality.get('n_weak_name_links', 0)}."]
    lines += ["", _row(["Roster to Survey 3, by method", "n"]), _row(["---"] * 2)]
    for method, label in SURVEY3_METHOD_LABELS.items():
        lines.append(_row([label, quality.get("n_by_method", {}).get(method, 0)]))
    # Covers two populations: no response on the date at all, and a demoted entry that no consistent assignment
    # could seat - for the latter a response did exist, it just could not be uniquely that entry's.
    lines.append(_row(["No Survey 3 response the entry could claim on the Part 2 date",
                       quality.get("n_unmatched_roster_survey3", 0)]))
    sizes = quality.get("ambiguous_group_sizes") or []
    lines += [
        "",
        f"Certain links: {quality.get('n_certain', 0)} of {quality.get('n_links', 0)}. Ambiguous date groups: "
        f"{quality.get('n_ambiguous_groups', 0)}"
        + (f" (sizes {', '.join(str(size) for size in sizes)})" if sizes else "")
        + f"; {quality.get('n_assignments', 0)} consistent whole-roster assignments were enumerated"
        + (" (capped, so D8 covers only the first assignments)" if quality.get("assignments_truncated") else "")
        + f". Phase 3 responses that no roster entry claims: {quality.get('n_unmatched_phase3', 0)}. Entries "
          "demoted from certain because two of them resolved to one response: "
        + f"{quality.get('n_certain_collisions_demoted', 0)}.",
    ]
    return lines


def _benefit_lines(equal_weight: dict, benefit: dict) -> list[str]:
    # Two different quantities, and the definition and caveats belong in every branch (SAP D2).
    lines = [
        "Retention benefit = the 1-month percent correct on the Bloomer-studied article minus the MCQ-studied "
        "article, from Part A's per-participant scores. Two quantities follow and they are not the same number. "
        "Part A's estimand weights the two sequence groups equally, which is what removes the article (paper) "
        "effect (SAP section 6); the mean per-person benefit weights people equally, so whenever the two groups "
        "differ in size it keeps that effect and is a description of the linked people rather than Part A's "
        "estimand. Neither is a new primary result.",
        "",
    ]
    if equal_weight.get("estimable"):
        lines.append(
            f"- **{EQUAL_WEIGHT_LABEL}:** "
            f"{fmt_estimate(equal_weight['theta'], equal_weight['ci_low'], equal_weight['ci_high'])} percentage "
            f"points; {fmt_p(equal_weight['p_value'])}; n = {equal_weight['n']} (group A {equal_weight['n_a']}, "
            f"group B {equal_weight['n_b']}); {equal_weight['estimator']}. This is Part A's estimand restricted "
            "to the linked people.")
    else:
        lines.append(f"- {EQUAL_WEIGHT_LABEL} (Part A's estimand restricted to the linked people): "
                     f"{_reason(equal_weight)}.")
    if not benefit.get("estimable"):
        return [*lines, f"- Mean per-person benefit among the linked people: {_reason(benefit)}."]
    return [
        *lines,
        f"- Mean per-person benefit among the linked people: "
        f"{fmt_estimate(benefit['mean'], benefit['ci_low'], benefit['ci_high'])} percentage points; "
        f"{fmt_p(benefit['p_value'])}; n = {benefit['n']}; one-sample t against 0. Person-weighted, so it is not "
        "Part A's estimand.",
        f"- Mean (SD): {_num(benefit['mean'])} ({_num(benefit['sd'])}). Median (IQR): {_median_iqr(benefit)}.",
    ]


def _contrast_lines(contrasts: list[dict]) -> list[str]:
    lines = [_row(["Contrast", "First level, n; mean", "Second level, n; mean",
                   "Difference, percentage points (Welch 95% CI)", "P"]), _row(["---"] * 5)]
    for entry in contrasts:
        levels = entry["levels"]
        cells = [f"{level['level']}: {level['n']}; {_num(level['mean'])}" for level in levels]
        if entry.get("estimable"):
            estimate = fmt_estimate(entry["difference"], entry["ci_low"], entry["ci_high"])
            p_value = fmt_p(entry["p_value"])
        else:
            estimate, p_value = _reason(entry), "-"
        lines.append(_row([entry["label"], *cells, estimate, p_value]))
    return lines


def _adjusted_lines(adjusted: dict) -> list[str]:
    # The pointer to Part C's C5.1 is added only when there is an estimate to compare: C5.1's value lives in
    # another file, so sending the reader there for a comparison that cannot be made is worse than silence.
    definition = ("OLS of the retention benefit on the group code (+0.5 group A, -0.5 group B) and the "
                  "prior-knowledge difference (Bloomer article from Survey 3 minus MCQ article from the chained "
                  "Part 1 form). The intercept is the benefit at equal prior knowledge with equal group weights")
    if not adjusted.get("estimable"):
        return [f"{definition}.", "",
                f"- Adjusted retention benefit: {_reason(adjusted)}; people with a chained Part 1 MCQ form: "
                f"{adjusted.get('n_with_mcq_form', 0)}."]
    lines = [f"{definition}; compare it with Part C's C5.1, which averages the same quantity over probabilistic "
             "matchings.", ""]
    return [*lines, f"- **Adjusted retention benefit:** "
                    f"{fmt_estimate(adjusted['estimate'], adjusted['ci_low'], adjusted['ci_high'])} percentage "
                    f"points; {fmt_p(adjusted['p_value'])}; n = {adjusted['n']} of "
                    f"{adjusted['n_with_mcq_form']} people with a chained Part 1 MCQ form."]


def _preference_lines(preference: dict) -> list[str]:
    counts = preference["counts"]
    table = preference["table"]
    lines = [f"Decided respondents (Q25): preferred Bloomer {counts['preferred Bloomer']}, preferred the quiz "
             f"{counts['preferred the quiz']}.", ""]
    if preference.get("estimable"):
        lines.append(f"- **Point-biserial correlation of the benefit with preferring Bloomer:** "
                     f"{preference['point_biserial']:.2f} (n = {preference['n']}); "
                     f"{fmt_p(preference['p_value'])}.")
        # a x d / (b x c): only a zero in b or c is non-finite, so name those two cells rather than "a cell is 0".
        odds = ("not finite (nobody preferred Bloomer with a benefit of 0 or below, or nobody preferred the quiz "
                "with a benefit above 0)" if preference["odds_ratio"] is None
                else _num(preference["odds_ratio"], 2))
        lines.append(f"- 2x2 of preference against a benefit above 0: Fisher's exact test, odds ratio "
                     f"{odds}; {fmt_p(preference['fisher_p_value'])}.")
    else:
        lines.append(f"- Preference against measured benefit: {_reason(preference)}.")
    lines += ["", _row(["", "Benefit above 0", "Benefit 0 or below"]), _row(["---"] * 3),
              _row(["Preferred Bloomer", table[0][0], table[0][1]]),
              _row(["Preferred the quiz", table[1][0], table[1][1]])]
    return lines


def _sensitivity_lines(sensitivity: dict) -> list[str]:
    if not sensitivity["n_assignments"]:
        return ["No consistent assignment was enumerated, so there is nothing to vary."]
    people = sensitivity["n_people"]
    weaker = sensitivity.get("with_weaker_names") or {}
    lines = [
        f"Every D2-D7 estimate is recomputed over each of the {sensitivity['n_assignments']} enumerated "
        "assignments. Each assignment holds the certain links plus one consistent choice for every ambiguous date "
        "group, so each is a \"with ambiguous links\" variant; assignment 0 is the primary one and is the column "
        f"below. People per assignment: {people['min']} to {people['max']}. The last column is a separate variant, "
        "not a superset of assignment 0: it repeats D2-D7 over the certain links of every name method, so it adds "
        "the weaker name matches and leaves out the ambiguous links that assignment 0 includes"
        + (f" ({weaker['n']} people)." if "n" in weaker else "."),
        "",
        _row(["Estimate", "Assignment 0 (with ambiguous links)", "Range across assignments",
              "Including weaker name matches", "Assignments estimable"]),
        _row(["---"] * 5),
    ]
    primary = sensitivity.get("with_ambiguous") or {}
    for key, entry in sensitivity["ranges"].items():
        digits = 2 if "rho" in key or "biserial" in key else 1
        span = ("-" if entry["min"] is None
                else f"{entry['min']:.{digits}f} to {entry['max']:.{digits}f}")
        lines.append(_row([entry["label"], _num(primary.get(key), digits), span, _num(weaker.get(key), digits),
                           f"{entry['n_estimable']} of {sensitivity['n_assignments']}"]))
    return lines


def render_partd_report(results: dict) -> str:
    flow, prov, quality = results["flow"], results["provenance"], results["link_quality"]
    usage, interval = results["usage_vs_benefit"], results["retention_interval"]
    lines = [
        "# Bloomer vs MCQ: roster-linked person-level analyses (Part D)",
        "",
        f"**{results['status']}.** Specified in `{results['sap']}` after the Part A, Part B and Part C interim "
        f"results were seen: every analysis below is exploratory. Code version `{prov['code_commit']}`.",
        "",
        "Part D replaces Part C's probabilistic Phase 3 link for the linked people with a deterministic link "
        "built at ingest from a "
        f"study-team roster of names and Part 2 dates. At least {MIN_PEOPLE} people, and at least {MIN_PER_LEVEL} "
        "per level, are needed for an estimate; otherwise the analysis is reported as not estimable with its "
        "reason. Percentage points are Bloomer-studied minus MCQ-studied at 1 month.",
        "",
        "## D1. Link quality and population", "", *_flow_lines(flow, quality),
        "", "## D2. Retention benefit per person", "",
        *_benefit_lines(results["equal_weight_benefit"], results["benefit"]),
        "", "## D3. Retention benefit by subgroup (exploratory, unadjusted)", "",
        "All six contrasts are exploratory, unadjusted and not corrected for multiplicity (SAP D3).", "",
        *_contrast_lines(results["subgroup_contrasts"]),
        "", "## D4. Retention benefit adjusted for prior knowledge", "", *_adjusted_lines(results["adjusted_benefit"]),
        "", "## D5. Preference against measured benefit", "", *_preference_lines(results["preference_vs_benefit"]),
        "", "## D6. Usage against retention benefit", "",
        f"- Total Bloomer attempts vs benefit, Spearman rho: {_correlation(usage['attempts'])}.",
        f"- Total Bloomer minutes vs benefit, Spearman rho: {_correlation(usage['minutes'])}.",
        "", "## D7. Retention interval", "",
        "Days from the Survey 3 completion date to the Phase 3 completion date, per person.",
        "",
        f"- Median (IQR): {_median_iqr(interval) if interval.get('estimable') else _reason(interval)}.",
        f"- Interval vs benefit, Spearman rho: {_correlation(interval['vs_benefit'])}.",
        f"- Interval vs the Bloomer-studied score, Spearman rho: {_correlation(interval['vs_bloomer_score'])}.",
        "", "## D8. Sensitivity to the ambiguous links and weaker name matches", "", *_sensitivity_lines(results["sensitivity"]),
        "", "## Method notes", "", *[f"- {d}" for d in results["deviations"]],
        "", "## Known biases", "", *[f"- {b}" for b in results["known_biases"]],
        "", "## Reproducibility", "",
        f"- Python {prov['python']}; " + ", ".join(f"{k} {v}" for k, v in prov["packages"].items()),
        f"- Config `{prov['config']}`; figure `fig_partd.pdf` / `.png` ({FIGURE_NOTE})",
    ]
    for key in ("part2_roster", "survey3", "phase3", "mcq_part1_A", "mcq_part1_B"):
        if key in prov["inputs"]:
            lines.append(input_line(key, prov["inputs"][key]))
    for key in ("links_roster", "links_roster_alternatives"):
        if key in prov["deidentified"]:
            entry = prov["deidentified"][key]
            lines.append(f"- Roster link `{entry['file']}`: sha256 `{entry['sha256'][:12]}`, {entry['n_rows']} rows")
    return "\n".join(lines) + "\n"


def _style() -> None:
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": REF_COLOR,
        "axes.linewidth": 0.8, "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def _empty(ax, message: str = "Not estimable") -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, color=MUTED_COLOR)


def plot_partd(pop: pd.DataFrame, contrasts: list[dict], out_stem: Path) -> list[Path]:
    """a: retention benefit per person, sorted, with a zero line; b: subgroup contrasts; c: benefit vs interval."""
    _style()
    fig, (ax_a, ax_b, ax_c) = plt.subplots(1, 3, figsize=(11.0, 3.9), gridspec_kw={"width_ratios": [1, 1.5, 1]})

    if len(pop):
        ordered = pop.sort_values("benefit", kind="stable").reset_index(drop=True)
        benefit = ordered["benefit"].to_numpy(dtype=float)
        # A benefit of exactly 0 is a tie, not "MCQ higher": percent scores make ties plausible.
        colors = [BLOOMER_COLOR if value > 0 else MUTED_COLOR if value == 0 else MCQ_COLOR for value in benefit]
        ax_a.bar(np.arange(len(benefit)), benefit, color=colors, width=0.72)
        ax_a.set_xticks(range(len(benefit)), [""] * len(benefit))
        ax_a.tick_params(axis="x", length=0)
        ax_a.set_xlabel("Linked people, sorted", labelpad=2)
        ax_a.legend(handles=[mlines.Line2D([], [], marker="s", linestyle="", color=BLOOMER_COLOR,
                                           label="Bloomer higher"),
                             mlines.Line2D([], [], marker="s", linestyle="", color=MCQ_COLOR, label="MCQ higher"),
                             mlines.Line2D([], [], marker="s", linestyle="", color=MUTED_COLOR, label="Equal (0)")],
                    loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3, frameon=False, fontsize=7.5)
    else:
        _empty(ax_a, "No linked people")
    ax_a.axhline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_a.set_ylabel("Bloomer minus MCQ at 1 month (pp)")

    shown = [entry for entry in contrasts if entry.get("estimable")]
    if shown:
        for rank, entry in enumerate(shown):
            y = len(shown) - 1 - rank
            ax_b.errorbar(entry["difference"], y,
                          xerr=[[entry["difference"] - entry["ci_low"]], [entry["ci_high"] - entry["difference"]]],
                          fmt="o", color=LABEL_COLOR, ecolor=MUTED_COLOR, elinewidth=1.2, capsize=2.5, markersize=5)
        ax_b.set_yticks(range(len(shown)), [CONTRAST_LABELS[e["factor"]].replace("Retention benefit by ", "")
                                            for e in reversed(shown)], fontsize=8)
        ax_b.set_ylim(-0.6, len(shown) - 0.4)  # keep the rows evenly spaced when only a few are estimable
    else:
        _empty(ax_b)
        ax_b.set_yticks([])
    ax_b.axvline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_b.spines["left"].set_visible(False)
    ax_b.tick_params(axis="y", length=0)
    ax_b.set_xlabel("Difference in benefit, percentage points (95% CI)")

    complete = pop.dropna(subset=["benefit", "interval_days"]) if len(pop) else pop
    if len(complete):
        for group, marker in (("A", "o"), ("B", "s")):
            rows = complete[complete["group"] == group]
            ax_c.scatter(rows["interval_days"].astype(float), rows["benefit"].astype(float), s=42, marker=marker,
                         color=BLOOMER_COLOR, edgecolors="white", linewidths=0.8, label=f"Group {group}")
        ax_c.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False, fontsize=7.5)
    else:
        _empty(ax_c, "No interval data")
    ax_c.axhline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_c.set_xlabel("Survey 3 to Phase 3 interval (days)", labelpad=2)
    ax_c.set_ylabel("Bloomer minus MCQ at 1 month (pp)")

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
