"""The manuscript supplement, sections S1-S7 (SAP E4, design section 5).

Assembled from what the pipeline already writes: the SAP's Part E prose, every method note
and known bias from the four results files, the subgroup and link-quality blocks, Part D's D2-D8, and provenance.
S6's prose is the one part that lives nowhere else, so it is written into `SAP.md` Part E and read from there; if
the SAP does not carry it yet, the section renders a clearly marked seam instead of inventing text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bloomer_retention.bundle.format import (
    COUNT,
    MISSING,
    PP,
    Cell,
    Num,
    cell,
    count_num,
    estimate_cell,
    joined,
    median_iqr_cell,
    numbers_in,
    p_num,
    pct_num,
    row,
    status_num,
    text,
    text_at,
    value_num,
)
from bloomer_retention.bundle.load import BundleError, Results, child, get

PART_LABELS = {"results": "Part A", "survey3_results": "Part B", "partc_results": "Part C",
               "partd_results": "Part D"}
FACTOR_LABELS = {"role": "Role", "ai_use": "Prior AI use", "cme_hours": "CME hours per week", "group": "Group"}
NAME_METHOD_LABELS = {"name_exact": "Exact normalised name", "name_tokens": "Two or more shared name tokens",
                      "name_single_token": "Single-token name carried by one row (weaker)",
                      "name_fuzzy": "Spelling variant within the fuzzy ratio (weaker)"}
SURVEY3_METHOD_LABELS = {"date_unique": "One Survey 3 response on the Part 2 date",
                         "date_time": "Resolved by the Part 2 clock time", "group_resolved": "Resolved by group",
                         "enumerated": "Enumerated (tie on the Part 2 date)"}
S4_HEADING = "### E4.1 Linkage method note (supplement S4)"
S6_HEADING = "### E4.2 Codebook and de-identification (supplement S6)"
SEAM = ("<!-- SEAM: `SAP.md` does not yet carry `{heading}`. The bundle writes no prose of its own, so this "
        "section stays empty until the SAP does (SAP E4). -->")
SAP_FILE_VERSION = re.compile(r"^Version (\d+(?:\.\d+)*)\.", re.MULTILINE)
SEED_NOTE = ("Part C's per-family linkage seeds are derived from the configured base seed and are written out in "
             "full above; Part A's re-randomisation seed is stamped into every results file's provenance.")
# S7 recorded a `git describe` of the repository root until version 2.2. It could not reproduce: this bundle is
# committed into the repository it described and the release tag is applied to that same commit, so the `-dirty`
# suffix cleared and the nearest tag changed after the value was written, and a clean clone rebuilt a different
# supplement. The code commit is path-scoped to the analysis sources, so committing outputs cannot move it.
TAG_NOTE = ("- No git tag is recorded here. The release tag is applied in git to the commit that records these "
            "outputs, whose parent is the code version above, `{commit}`; `git tag --contains {commit}` names "
            "it. A tag written while this bundle was being generated could not be that tag, because the bundle "
            "is committed into the repository and tagged afterwards.")
# S6 states this restriction, two sections below, and S6 is not what gets excerpted: S5 is the section a reader
# lifts out on its own. It is repeated at S5's head so the marking travels with the cells it is about
# (SAP D8, E4.2; README).
RESTRICTED_SUPPLEMENT = "supplement_partd_restricted.md"
RESTRICTED_SECTIONS = ("S5",)
# S5 shipped in the same file as six publishable sections, so attaching "the supplement" to a submission
# attached the restricted section with it. Splitting the file makes the ordinary act safe (SAP E4.2).
PUBLIC_HEAD = (
    "These are the publishable supplement sections. Supplement section S5, the Part D person-level results, is "
    "restricted to the study team and is not in this file: it is in `" + RESTRICTED_SUPPLEMENT + "`. This file "
    "may be attached to a submission as it stands."
)
RESTRICTED_HEAD = (
    "**Restricted to the study team. Do not attach this file to a submission, and do not circulate it to "
    "participants as a results summary.** It holds supplement section S5 alone; the publishable sections are in "
    "`supplement.md`."
)
S5_RESTRICTED = (
    "**Restricted to the study team.** This section reports person-level results over about nine linked people. "
    "The D3 and D5 tables below print two-person and single-person cells, so a participant who knows their own "
    "answers can recover another person's score from them. It is restricted on the same terms as "
    "`survey3_report.md` and `partd_report.md` (SAP B2 and D8), and it must not be circulated to participants as "
    "a results summary."
)


@dataclass(frozen=True)
class Section:
    """One supplement section: its S-number, its title and its lines, each line a cell of text and numbers."""

    key: str
    title: str
    lines: tuple[Cell, ...]

    def numbers(self) -> list[Num]:
        return [n for line in self.lines for n in numbers_in(line)]


def row_cell(cells: list[Cell]) -> Cell:
    """One Markdown table row whose cells keep their numbers."""
    return cell("| ", joined(cells, " | "), " |")


def divider(columns: int) -> Cell:
    return cell(row([MISSING * 3] * columns))


def read_sap(sap_path: str | Path) -> str:
    """The SAP text. A path that is not a file stops the bundle rather than rendering an empty supplement.

    Returning `""` here used to be survivable: S4's method note and the whole of S6 - the codebook and the
    restricted-outputs guidance - collapsed to `<!-- SEAM: ... -->` comments, which are
    invisible in rendered Markdown or PDF, and the run still exited 0. A supplement with no de-identification
    section is not a successful run. The seam stays for the case it was written for: a SAP that exists but does
    not yet carry a heading (SAP E4).
    """
    path = Path(sap_path)
    if not path.is_file():
        raise BundleError(f"{path}: no such file. The supplement reads its linkage method note (S4) and its "
                          "codebook and de-identification section (S6) from the SAP, so the supplement would lose "
                          "both and say nothing about it.")
    return path.read_text(encoding="utf-8")


def sap_block(sap_text: str, heading: str) -> list[str]:
    """The lines under `heading`, up to the next heading of the same or a higher level. Empty when absent."""
    level = len(heading) - len(heading.lstrip("#"))
    lines, collecting, block = sap_text.splitlines(), False, []
    for line in lines:
        if line.strip() == heading:
            collecting = True
            continue
        if collecting:
            stripped = line.lstrip("#")
            found = len(line) - len(stripped)
            if line.startswith("#") and found <= level and stripped.startswith(" "):
                break
            block.append(line)
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    return block


def sap_lines(sap_text: str, heading: str) -> list[Cell]:
    block = sap_block(sap_text, heading)
    return [cell(line) for line in block] if block else [cell(SEAM.format(heading=heading))]


def sap_file_version(sap_text: str) -> str | None:
    """The version this SAP file declares, which can be ahead of the version stamped on the outputs."""
    found = SAP_FILE_VERSION.search(sap_text)
    return found.group(1) if found else None


def attributed(results: Results, field: str) -> list[tuple[str, list[str]]]:
    """Every entry of `field` across the four results files, de-duplicated, each with the parts that carry it."""
    found: dict[str, list[str]] = {}
    for part in PART_LABELS:
        for entry in get(results, f"{part}.{field}"):
            found.setdefault(str(entry), []).append(PART_LABELS[part])
    return list(found.items())


def _attributed_lines(results: Results, field: str) -> list[Cell]:
    return [cell(f"- ({'; '.join(parts)}) {entry}") for entry, parts in attributed(results, field)]


# ------------------------------------------------------------------------------------------------- sections

def s1_analysis_plan(results: Results, sap_text: str) -> Section:
    lines = [
        cell(f"Every number in this manuscript comes from one analysis run: SAP version {results.sap_version}, "
             f"code version `{results.code_commit}`. The four results files agree on both; the bundle refuses to "
             "assemble them otherwise."),
    ]
    file_version = sap_file_version(sap_text)
    if file_version and file_version != results.sap_version:
        lines.append(cell(
            f"`SAP.md` is at version {file_version}, ahead of the version {results.sap_version} stamped on these "
            "outputs; the outputs will carry the later version at the next analysis run."))
    lines += [
        cell(""),
        cell("### Method notes"),
        cell(""),
        *_attributed_lines(results, "deviations"),
    ]
    return Section("S1", "Analysis plan", tuple(lines))


def s2_known_biases(results: Results) -> Section:
    return Section("S2", "Known biases", tuple(_attributed_lines(results, "known_biases")))


def s3_subgroups(results: Results) -> Section:
    lines = [
        cell("Adoption (Q25) among decided respondents, by factor. Fisher's exact test on each 2x2 table, "
             "unadjusted for multiple comparisons; every subgroup is exploratory."),
        cell(""),
        cell(row(["Factor", "Level", "Bloomer", "Quiz", "% Bloomer", "Odds ratio", "P"])),
        divider(7),
    ]
    for rank in range(len(get(results, "survey3_results.subgroups.factors"))):
        base = f"survey3_results.subgroups.factors.{rank}"
        name = text_at(results, f"{base}.factor")
        prefix = f"subgroups.{name}"
        for level_rank in range(len(get(results, f"{base}.levels"))):
            level_base = f"{base}.levels.{level_rank}"
            level = text_at(results, f"{level_base}.level")
            level_prefix = f"{prefix}.level_{level_rank}"
            first = level_rank == 0
            lines.append(row_cell([
                cell(FACTOR_LABELS.get(name, name) if first else ""),
                cell(level),
                cell(count_num(results, f"{level_base}.n_bloomer", f"{level_prefix}.n_bloomer", unit="people")),
                cell(count_num(results, f"{level_base}.n_quiz", f"{level_prefix}.n_quiz", unit="people")),
                cell(pct_num(results, f"{level_base}.pct_bloomer", f"{level_prefix}.pct_bloomer")),
                cell(value_num(results, f"{base}.odds_ratio", f"{prefix}.odds_ratio", digits=2, unit="odds ratio")
                     if first else ""),
                cell(p_num(results, f"{base}.p_value", f"{prefix}.p_value") if first else ""),
            ]))
    lines += [cell(""), cell("An odds ratio shown as `-` could not be estimated (a zero cell or an empty level).")]
    return Section("S3", "Exploratory subgroups: adoption among decided respondents", tuple(lines))


def _partc_link_rows(results: Results) -> list[Cell]:
    base = "partc_results.linked.link_quality"
    families = (("part1", "Part 1 link (Survey 3 to MCQ form)", "h"),
                ("phase3", "Phase 3 link (Phase 3 to MCQ form)", "days"))
    rows = [cell(row(["", *[label for _, label, _ in families]])), divider(3)]

    def counts(field: str, label: str, unit: str = COUNT) -> Cell:
        return row_cell([cell(label), *[cell(count_num(results, f"{base}.{key}.{field}",
                                                       f"linkage.partc.{key}.{field}", unit=unit))
                                        for key, _, _ in families]])

    rows += [
        counts("n_left_in_population", "MCQ forms in the population", "forms"),
        counts("n_right_in_population", "Forms to link in the population", "forms"),
        counts("n_candidate_edges", "Candidate pairs (population, any group)", "pairs"),
        counts("n_positive_weight_edges", "Candidate pairs with positive same-group weight", "pairs"),
        counts("n_right_with_candidate", "Forms to link with at least one weighted candidate", "forms"),
        counts("clear_pairs", "Clear pairs (no rival candidate within the margin)", "pairs"),
        counts("stable_pairs", "Pairs in at least 90% of date-based draws", "pairs"),
        row_cell([cell("Best matching: pairs; gap median (IQR)"),
                  *[cell(count_num(results, f"{base}.{key}.best_matching.n_pairs",
                                   f"linkage.partc.{key}.best_pairs", unit="pairs"), "; ",
                         value_num(results, f"{base}.{key}.best_matching.gap_median",
                                   f"linkage.partc.{key}.gap_median", unit=unit), f" {unit} (",
                         value_num(results, f"{base}.{key}.best_matching.gap_q1", f"linkage.partc.{key}.gap_q1",
                                   unit=unit), " to ",
                         value_num(results, f"{base}.{key}.best_matching.gap_q3", f"linkage.partc.{key}.gap_q3",
                                   unit=unit), ")")
                    for key, _, unit in families]]),
        row_cell([cell("Matched per date-based draw, median (range)"),
                  *[cell(value_num(results, f"{base}.{key}.matched_per_draw.median",
                                   f"linkage.partc.{key}.matched_median", unit="forms"), " (",
                         count_num(results, f"{base}.{key}.matched_per_draw.min",
                                   f"linkage.partc.{key}.matched_min", unit="forms"), " to ",
                         count_num(results, f"{base}.{key}.matched_per_draw.max",
                                   f"linkage.partc.{key}.matched_max", unit="forms"), ")")
                    for key, _, _ in families]]),
    ]
    return rows


def labelled_methods(results: Results, path: str, labels: dict[str, str]) -> list[tuple[str, str]]:
    """Every method the analysis wrote, in the order it wrote them, each with its supplement label.

    Iterating the label dictionary instead would drop a method added to the analysis out of a table that reads as
    a complete accounting of how each roster entry was matched. An unlabelled method stops the bundle.
    """
    found = get(results, path)
    unknown = [method for method in found if method not in labels]
    if unknown:
        raise BundleError(
            f"{path}: no supplement label for {', '.join(repr(method) for method in sorted(unknown))}. The "
            "analysis layer writes a link method the supplement cannot name; add it to the label table in "
            "bundle/supplement.py rather than letting it vanish from S4."
        )
    return [(method, labels[method]) for method in found]


def _partd_link_rows(results: Results) -> list[Cell]:
    base = "partd_results.link_quality"
    rows = [cell(row(["Roster to Phase 3, by name method", "n"])), divider(2)]
    for method, label in labelled_methods(results, f"{base}.n_by_name_method", NAME_METHOD_LABELS):
        rows.append(row_cell([cell(label), cell(count_num(results, f"{base}.n_by_name_method.{method}",
                                                          f"linkage.partd.name_{method}", unit="entries"))]))
    rows += [cell(""), cell(row(["Roster to Survey 3, by method", "n"])), divider(2)]
    for method, label in labelled_methods(results, f"{base}.n_by_method", SURVEY3_METHOD_LABELS):
        rows.append(row_cell([cell(label), cell(count_num(results, f"{base}.n_by_method.{method}",
                                                          f"linkage.partd.method_{method}", unit="entries"))]))
    rows += [
        cell(""),
        cell("Roster entries ", count_num(results, f"{base}.n_roster_rows", "linkage.partd.n_roster_rows",
                                          unit="entries"),
             "; links ", count_num(results, f"{base}.n_links", "linkage.partd.n_links", unit="links"),
             ", of which certain ", count_num(results, f"{base}.n_certain", "linkage.partd.n_certain",
                                              unit="links"),
             " and ambiguous ", count_num(results, f"{base}.n_ambiguous_links", "linkage.partd.n_ambiguous",
                                          unit="links"),
             ". Ambiguous date groups ", count_num(results, f"{base}.n_ambiguous_groups",
                                                   "linkage.partd.n_ambiguous_groups", unit="groups"),
             "; consistent whole-roster assignments enumerated ",
             count_num(results, f"{base}.n_assignments", "linkage.partd.n_assignments", unit="assignments"),
             ". Phase 3 responses no roster entry claims ",
             count_num(results, f"{base}.n_unmatched_phase3", "linkage.partd.n_unmatched_phase3", unit="people"),
             "; people in the Part D population ",
             count_num(results, f"{base}.n_partd_population", "linkage.partd.n_population", unit="people"),
             ", of whom ", count_num(results, f"{base}.n_with_mcq_form", "linkage.partd.n_with_mcq_form",
                                     unit="people"), " have a chained Part 1 MCQ form."),
    ]
    return rows


def s4_linkage(results: Results, sap_text: str) -> Section:
    lines = [
        *sap_lines(sap_text, S4_HEADING),
        cell(""),
        cell("### Part C: probabilistic timestamp links"),
        cell(""),
        *_partc_link_rows(results),
        cell(""),
        cell("Draws per family: ", count_num(results, "partc_results.linked.draws", "linkage.partc.draws",
                                             unit="draws"), "."),
        cell(""),
        cell("### Part D: deterministic roster link"),
        cell(""),
        *_partd_link_rows(results),
    ]
    return Section("S4", "Linkage and its limits", tuple(lines))


def _partd_flow_line(results: Results) -> Cell:
    base = "partd_results.flow"
    return cell(
        "Part A analysed ", count_num(results, f"{base}.phase3_analysed", "partd.flow.phase3_analysed",
                                      unit="people"),
        " Phase 3 responses and Part B ", count_num(results, f"{base}.survey3_analysed",
                                                    "partd.flow.survey3_analysed", unit="people"),
        " Survey 3 responses. The roster produced ", count_num(results, f"{base}.roster_links",
                                                               "partd.flow.roster_links", unit="links"),
        " links, of which ", count_num(results, f"{base}.certain_links", "partd.flow.certain_links", unit="links"),
        " are certain and ", count_num(results, f"{base}.ambiguous_links", "partd.flow.ambiguous_links",
                                       unit="links"),
        " ambiguous. Excluded from the certain links: ",
        count_num(results, f"{base}.excluded_not_in_phase3_population", "partd.flow.excluded_not_in_phase3",
                  unit="links"), " outside the Phase 3 population, ",
        count_num(results, f"{base}.excluded_not_in_survey3_population", "partd.flow.excluded_not_in_survey3",
                  unit="links"), " outside the Survey 3 population, ",
        count_num(results, f"{base}.excluded_without_both_scores", "partd.flow.excluded_without_both_scores",
                  unit="links"), " without both article scores and ",
        count_num(results, f"{base}.excluded_weak_name_match", "partd.flow.excluded_weak_name_match", unit="links"),
        " matched only through a weaker name step. Part D analyses ",
        count_num(results, f"{base}.analysed", "partd.n_analysed", unit="people"), " people (group A ",
        count_num(results, f"{base}.analysed_group_A", "partd.n_analysed_group_a", unit="people"), ", group B ",
        count_num(results, f"{base}.analysed_group_B", "partd.n_analysed_group_b", unit="people"), ").")


def _reason(results: Results, base: str) -> Cell:
    reason = get(results, base).get("reason")
    return cell(f"not estimable ({reason})" if reason else "not estimable")


def _d2_lines(results: Results) -> list[Cell]:
    equal, benefit = "partd_results.equal_weight_benefit", "partd_results.benefit"
    lines = []
    if get(results, f"{equal}.estimable"):
        lines.append(cell("- **", text_at(results, f"{equal}.label"), ":** ",
                          estimate_cell(results, equal, "partd.equal_weight"), " ", PP, "; ",
                          p_num(results, f"{equal}.p_value", "partd.equal_weight.p_value"), "; n = ",
                          count_num(results, f"{equal}.n", "partd.equal_weight.n", unit="people"), " (group A ",
                          count_num(results, f"{equal}.n_a", "partd.equal_weight.n_a", unit="people"), ", group B ",
                          count_num(results, f"{equal}.n_b", "partd.equal_weight.n_b", unit="people"), "); ",
                          text_at(results, f"{equal}.estimator"),
                          ". This is Part A's estimand restricted to the linked people."))
    else:
        lines.append(cell("- Retention benefit, equal group weights: ", _reason(results, equal), "."))
    if get(results, f"{benefit}.estimable"):
        lines.append(cell("- Mean per-person benefit among the linked people: ",
                          estimate_cell(results, benefit, "partd.benefit", theta_key="mean"), " ", PP, "; ",
                          p_num(results, f"{benefit}.p_value", "partd.benefit.p_value"), "; n = ",
                          count_num(results, f"{benefit}.n", "partd.benefit.n", unit="people"),
                          "; ", text_at(results, f"{benefit}.test"),
                          ". Person-weighted, so it is not Part A's estimand."))
        lines.append(cell("- Median (IQR): ", median_iqr_cell(results, benefit, "partd.benefit"), "; SD ",
                          value_num(results, f"{benefit}.sd", "partd.benefit.sd"), "."))
    else:
        lines.append(cell("- Mean per-person benefit: ", _reason(results, benefit), "."))
    return lines


def _d3_lines(results: Results) -> list[Cell]:
    lines = [cell(row(["Contrast", "First level, n; mean", "Second level, n; mean",
                       "Difference, percentage points (Welch 95% CI)", "P"])), divider(5)]
    for rank in range(len(get(results, "partd_results.subgroup_contrasts"))):
        base = f"partd_results.subgroup_contrasts.{rank}"
        prefix = f"partd.contrast.{text_at(results, f'{base}.factor')}"
        levels = []
        for level_rank in range(len(get(results, f"{base}.levels"))):
            level_base = f"{base}.levels.{level_rank}"
            levels.append(cell(text_at(results, f"{level_base}.level"), ": ",
                               count_num(results, f"{level_base}.n", f"{prefix}.level_{level_rank}.n",
                                         unit="people"), "; ",
                               value_num(results, f"{level_base}.mean", f"{prefix}.level_{level_rank}.mean")))
        if get(results, f"{base}.estimable"):
            # a Welch interval on 1.3 df spans hundreds of points on a 0-100 scale; without the df beside it the
            # width reads as a measurement rather than as two people against seven
            estimate = cell(estimate_cell(results, base, prefix, theta_key="difference"), "; Welch df ",
                            value_num(results, f"{base}.df", f"{prefix}.df", digits=2, unit=COUNT))
            p_value = cell(p_num(results, f"{base}.p_value", f"{prefix}.p_value"))
        else:
            estimate, p_value = _reason(results, base), cell(MISSING)
        lines.append(row_cell([cell(text_at(results, f"{base}.label")), *levels, estimate, p_value]))
    lines += [cell(""), cell("All contrasts are exploratory, unadjusted and not corrected for multiplicity.")]
    return lines


def _correlation_line(results: Results, base: str, prefix: str, label: str) -> Cell:
    if not get(results, f"{base}.estimable"):
        return cell(f"- {label}: ", _reason(results, base), ".")
    return cell(f"- {label}: Spearman rho ", value_num(results, f"{base}.rho", f"{prefix}.rho", digits=2, unit="rho"),
                " (n = ", count_num(results, f"{base}.n", f"{prefix}.n", unit="people"), "); ",
                p_num(results, f"{base}.p_value", f"{prefix}.p_value"), ".")


def _d5_lines(results: Results) -> list[Cell]:
    base = "partd_results.preference_vs_benefit"
    lines = [cell("Decided respondents (Q25): preferred Bloomer ",
                  count_num(results, child(base, "counts", "preferred Bloomer"),
                            "partd.preference.n_preferred_bloomer", unit="people"), ", preferred the quiz ",
                  count_num(results, child(base, "counts", "preferred the quiz"),
                            "partd.preference.n_preferred_quiz", unit="people"), ".")]
    if get(results, f"{base}.estimable"):
        lines.append(cell("- Point-biserial correlation of the benefit with preferring Bloomer: ",
                          value_num(results, f"{base}.point_biserial", "partd.preference.point_biserial", digits=2,
                                    unit="correlation"), " (n = ",
                          count_num(results, f"{base}.n", "partd.preference.n", unit="people"), "); ",
                          p_num(results, f"{base}.p_value", "partd.preference.p_value"), "."))
        lines.append(cell("- 2x2 of preference against a benefit above 0: odds ratio ",
                          value_num(results, f"{base}.odds_ratio", "partd.preference.odds_ratio", digits=2,
                                    unit="odds ratio"), "; ",
                          p_num(results, f"{base}.fisher_p_value", "partd.preference.fisher_p_value"),
                          " (Fisher's exact test)."))
    else:
        lines.append(cell("- Preference against measured benefit: ", _reason(results, base), "."))
    lines += [cell(""), cell(row(["", "Benefit above 0", "Benefit 0 or below"])), divider(3)]
    for rank, label in ((0, "Preferred Bloomer"), (1, "Preferred the quiz")):
        lines.append(row_cell([cell(label),
                               cell(count_num(results, f"{base}.table.{rank}.0", f"partd.preference.cell_{rank}0",
                                              unit="people")),
                               cell(count_num(results, f"{base}.table.{rank}.1", f"partd.preference.cell_{rank}1",
                                              unit="people"))]))
    return lines


def _d8_lines(results: Results) -> list[Cell]:
    base = "partd_results.sensitivity"
    if not get(results, f"{base}.n_assignments"):
        return [cell("No consistent assignment was enumerated, so there is nothing to vary.")]
    lines = [
        cell("Every D2-D7 estimate is recomputed over each of the ",
             count_num(results, f"{base}.n_assignments", "partd.sensitivity.n_assignments", unit="assignments"),
             " enumerated assignments; people per assignment ",
             count_num(results, f"{base}.n_people.min", "partd.sensitivity.n_people_min", unit="people"), " to ",
             count_num(results, f"{base}.n_people.max", "partd.sensitivity.n_people_max", unit="people"),
             ". The last column is a separate variant, not a superset: it repeats D2-D7 over the certain links of "
             "every name method, over ",
             count_num(results, f"{base}.with_weaker_names.n", "partd.sensitivity.n_with_weaker_names",
                       unit="people"), " people. Every column here is a different population from the D2 to D7 "
             "estimates above, which are computed over the ",
             count_num(results, "partd_results.flow.analysed", "partd.n_analysed", unit="people"),
             " people of D1: a range across assignments is not an interval around the headline."),
        cell(""),
        cell(row(["Estimate", "Assignment 0 (with ambiguous links)", "Range across assignments",
                  "Including weaker name matches", "Assignments estimable"])),
        divider(5),
    ]
    for key in get(results, f"{base}.ranges"):
        entry = f"{base}.ranges.{key}"
        prefix = f"partd.sensitivity.{key}"
        digits = 2 if "rho" in key or "biserial" in key else 1
        span = (cell(MISSING) if get(results, f"{entry}.min") is None
                else cell(value_num(results, f"{entry}.min", f"{prefix}.min", digits=digits), " to ",
                          value_num(results, f"{entry}.max", f"{prefix}.max", digits=digits)))
        lines.append(row_cell([
            cell(text_at(results, f"{entry}.label")),
            cell(value_num(results, f"{base}.with_ambiguous.{key}", f"{prefix}.with_ambiguous", digits=digits)),
            span,
            cell(value_num(results, f"{base}.with_weaker_names.{key}", f"{prefix}.with_weaker_names",
                           digits=digits)),
            cell(count_num(results, f"{entry}.n_estimable", f"{prefix}.n_estimable", unit="assignments"), " of ",
                 count_num(results, f"{base}.n_assignments", "partd.sensitivity.n_assignments",
                           unit="assignments")),
        ]))
    return lines


def s5_partd(results: Results) -> Section:
    adjusted, interval = "partd_results.adjusted_benefit", "partd_results.retention_interval"
    lines = [
        cell(S5_RESTRICTED),
        cell(""),
        cell("Exploratory throughout: Part D was written after the Part A, Part B and Part C interim "
             "results were seen, and its population is a small subset of Part A's."),
        cell(""),
        cell("### D1. Population and flow"),
        cell(""),
        _partd_flow_line(results),
        cell(""),
        cell("### D2. Retention benefit per person"),
        cell(""),
        *_d2_lines(results),
        cell(""),
        cell("### D3. Retention benefit by subgroup"),
        cell(""),
        *_d3_lines(results),
        cell(""),
        cell("### D4. Retention benefit adjusted for prior knowledge"),
        cell(""),
    ]
    if get(results, f"{adjusted}.estimable"):
        lines.append(cell("- Adjusted retention benefit: ", estimate_cell(results, adjusted, "partd.adjusted",
                                                                          theta_key="estimate"), " ", PP, "; ",
                          p_num(results, f"{adjusted}.p_value", "partd.adjusted.p_value"), "; n = ",
                          count_num(results, f"{adjusted}.n", "partd.adjusted.n", unit="people"), " of ",
                          count_num(results, f"{adjusted}.n_with_mcq_form", "partd.adjusted.n_with_mcq_form",
                                    unit="people"), " people with a chained Part 1 MCQ form."))
    else:
        lines.append(cell("- Adjusted retention benefit: ", _reason(results, adjusted),
                          "; people with a chained Part 1 MCQ form: ",
                          count_num(results, f"{adjusted}.n_with_mcq_form", "partd.adjusted.n_with_mcq_form",
                                    unit="people"), "."))
    lines += [
        cell(""),
        cell("### D5. Preference against measured benefit"),
        cell(""),
        *_d5_lines(results),
        cell(""),
        cell("### D6. Usage against retention benefit"),
        cell(""),
        _correlation_line(results, "partd_results.usage_vs_benefit.attempts", "partd.usage.attempts",
                          "Total Bloomer attempts vs benefit"),
        _correlation_line(results, "partd_results.usage_vs_benefit.minutes", "partd.usage.minutes",
                          "Total Bloomer minutes vs benefit"),
        cell(""),
        cell("### D7. Retention interval"),
        cell(""),
        cell("- Days from the Survey 3 completion date to the Phase 3 completion date, median (IQR): ",
             median_iqr_cell(results, interval, "partd.interval", unit="days")
             if get(results, f"{interval}.estimable") else _reason(results, interval), "."),
        _correlation_line(results, f"{interval}.vs_benefit", "partd.interval.vs_benefit",
                          "Interval vs benefit"),
        _correlation_line(results, f"{interval}.vs_bloomer_score", "partd.interval.vs_bloomer_score",
                          "Interval vs the Bloomer-studied score"),
        cell(""),
        cell("### D8. Sensitivity to the ambiguous links and weaker name matches"),
        cell(""),
        *_d8_lines(results),
    ]
    return Section("S5", "Part D person-level results (exploratory)", tuple(lines))


def s6_codebook(sap_text: str) -> Section:
    return Section("S6", "Codebook and de-identification", tuple(sap_lines(sap_text, S6_HEADING)))


def s7_reproducibility(results: Results) -> Section:
    prov = "results.provenance"
    packages = get(results, f"{prov}.packages")
    lines = [
        cell("- Status: ", status_num(results), "."),
        cell(f"- Python {text_at(results, f'{prov}.python')}; "
             + ", ".join(f"{name} {version}" for name, version in packages.items())),
        cell(f"- Config `{text_at(results, f'{prov}.config')}`; code version `{results.code_commit}`; "
             f"SAP version {results.sap_version}."),
        cell(TAG_NOTE.format(commit=results.code_commit)),
        cell(""),
        cell("### Raw inputs"),
        cell(""),
    ]
    for key in get(results, f"{prov}.inputs"):
        base = f"{prov}.inputs.{key}"
        source = get(results, base)
        if "n_rows_raw" in source:
            size = cell(count_num(results, f"{base}.n_rows_raw", f"reproducibility.input.{key}.n_rows_raw",
                                  unit="rows"), " raw rows")
        elif "n_worksheet_rows" in source:  # the SAP v2.7 Part F sign-up worksheet
            size = cell(count_num(results, f"{base}.n_worksheet_rows",
                                  f"reproducibility.input.{key}.n_worksheet_rows", unit="rows"), " worksheet rows")
        else:
            size = cell(count_num(results, f"{base}.n_roster_rows", f"reproducibility.input.{key}.n_roster_rows",
                                  unit="entries"), " roster entries")
        lines.append(cell(f"- `{key}`: `{text_at(results, f'{base}.file')}`, sha256 "
                          f"`{text_at(results, f'{base}.sha256')[:12]}`, ", size))
    lines += [cell(""), cell("### De-identified inputs to stage 2"), cell("")]
    for key in get(results, f"{prov}.deidentified"):
        base = f"{prov}.deidentified.{key}"
        lines.append(cell(f"- `{text_at(results, f'{base}.file')}`: sha256 "
                          f"`{text_at(results, f'{base}.sha256')[:12]}`, ",
                          count_num(results, f"{base}.n_rows", f"reproducibility.deidentified.{key}.n_rows",
                                    unit="rows"), " rows"))
    lines += [cell(""), cell("### Seeds"), cell(""),
              # "S2" alone reads as supplement section S2 (Known biases); this is the Table 4 sensitivity row
              cell("- Part A permutation test (Table 4, row S2): ",
                   count_num(results, f"{prov}.seeds.permutation", "reproducibility.seed.permutation",
                             unit="seed"))]
    for name in get(results, "partc_results.linked.seeds"):
        lines.append(cell(f"- Part C linkage, {name}: ",
                          count_num(results, f"partc_results.linked.seeds.{name}",
                                    f"reproducibility.seed.{name}", unit="seed")))
    lines += [cell(""), cell(SEED_NOTE)]
    return Section("S7", "Reproducibility", tuple(lines))


def section_builders(sap_text: str):
    """One builder per section, so a caller can build them one at a time (the change report does).

    Every section is a function of the results and of `SAP.md` alone. Nothing here is a function of the
    repository the bundle is written into, which is what makes a clean clone rebuild it byte for byte.
    """
    return [
        ("S1", lambda results: s1_analysis_plan(results, sap_text)),
        ("S2", s2_known_biases),
        ("S3", s3_subgroups),
        ("S4", lambda results: s4_linkage(results, sap_text)),
        ("S5", s5_partd),
        ("S6", lambda results: s6_codebook(sap_text)),
        ("S7", s7_reproducibility),
    ]


def build_supplement(results: Results, *, sap_path: str | Path) -> list[Section]:
    sap_text = read_sap(sap_path)
    return [build(results) for _, build in section_builders(sap_text)]


def split_sections(sections: list[Section]) -> tuple[list[Section], list[Section]]:
    """The publishable sections and the restricted ones, in their delivered order."""
    return ([s for s in sections if s.key not in RESTRICTED_SECTIONS],
            [s for s in sections if s.key in RESTRICTED_SECTIONS])


def render_supplement(sections: list[Section], *, title: str = "Supplementary information",
                      preamble: str = "") -> str:
    lines = [f"# {title}", ""]
    if preamble:
        lines += [preamble, ""]
    for section in sections:
        lines += [f"## {section.key}. {section.title}", ""]
        lines += [text(line) for line in section.lines]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


