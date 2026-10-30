"""The manuscript tables: the eight of SAP E2 (design section 4), Table 9 (SAP Part G) and Table 10 (SAP v3.3).

Every cell is fetched through `get`, so a table that asks for a number the analysis layer never wrote fails with
that path and its file rather than printing a blank cell. Nothing here computes: where the spec asked for a number
no results JSON holds, the cell is `-` and a footnote names the gap.
"""
from __future__ import annotations

from bloomer_retention.bundle.format import (
    COUNT,
    MISSING,
    PERCENT,
    PP,
    Cell,
    Num,
    Table,
    cell,
    count_num,
    df_num,
    estimate_cell,
    joined,
    mean_sd_cell,
    median_iqr_cell,
    of_cell,
    p_num,
    pct_num,
    pp_num,
    render_markdown,
    share_num,
    slug,
    status_num,
    text_at,
    text_num,
    value_num,
)
from bloomer_retention.bundle.load import BundleError, MissingResultError, Results, get, join_path
from bloomer_retention.labels import NPI_UNMATCHED_LABEL, PERMUTATION_LABEL, WELCH_LABEL, display_label, is_final

GROUPS = ("A", "B")
REGISTRATION_LINK = "registration_link"  # partc_results key written from SAP v2.7 (Part F)
# The rule `format.fmt_p` implements, which is `report.fmt_p`'s rule; the two extra bands are the ones a reader
# would otherwise be surprised by (a P of .992 prints as .99, and a P below .05 never prints as .05).
P_CONVENTION = ("P values follow the JAMA convention: P < .001 below .001; three decimals below .0095; P = .01 "
                "from .0095 to .01; two decimals from .01, except three decimals from .045 to .05, so a value "
                "below .05 never prints as .05; and P > .99 from .995 up.")
NO_ESTIMATOR = "Estimator: none. The cells are descriptive counts and summaries as the analysis layer wrote them."
# Display-only corrections of the form's own typos, exactly as the analysis reports make them.
DISPLAY = {"No opinon": "No opinion", "Tradtional MCQ": "Traditional MCQ"}
TABLE1_LABELS = {"gender": "Gender", "region": "US region", "role": "Role", "subspecialty": "Subspecialty",
                 "setting": "Practice setting", "ai_use": "Prior AI use", "cme_hours": "CME hours per week",
                 "cme_format": "Most common CME format"}
DIRECTION_LABELS = {"B_to_A": "Group B relabelled as A", "A_to_B": "Group A relabelled as B"}
GROUP_KEY = {"overall": "overall", "A": "group_a", "B": "group_b"}
METHOD_KEY = {"Bloomer": "bloomer", "MCQ": "mcq"}
# The index name of a sensitivity row's P value, where it is not `p_value`: the v2.6 keys are named in the
# pre-submission revision plan, which the manuscript repository reads (`sensitivity.welch.p`).
SENSITIVITY_P_KEY = {"sensitivity.welch": "p"}
# Table 4's SAP v2.6 footnote, one sentence per v2.6 row, printed only for the rows the results hold.
SENSITIVITY_V26_NOTES = {
    WELCH_LABEL: ("Welch crossover t: the headline estimate with the standard error from the unpooled group "
                  "variances of d and a Welch-Satterthwaite df, so it does not assume equal variances in the two "
                  "sequence groups."),
    PERMUTATION_LABEL: ("S2 Permutation test (exchangeability): relabelled in SAP v2.6 from the re-randomisation "
                        "test, because allocation alternated in order of enrollment rather than using a random "
                        "mechanism; the computation is unchanged."),
}


def display(label: str) -> str:
    return DISPLAY.get(label, label)


def entry_index(results: Results, base: str, **fields: object) -> int:
    """Position of the list entry matching every field; a loud failure when the analysis wrote no such entry.

    Looking an entry up by what it says it is, rather than by position, keeps the tables correct if the analysis
    layer ever reorders a list.
    """
    for rank, entry in enumerate(get(results, base)):
        if isinstance(entry, dict) and all(entry.get(field) == wanted for field, wanted in fields.items()):
            return rank
    wanted = ", ".join(f"{field}={value!r}" for field, value in fields.items())
    raise MissingResultError(f"{base}[{wanted}]", results.file(base.split(".")[0]),
                             f"no entry with {wanted}")


# --------------------------------------------------------------------------------------------- Table 1: flow

# Printed above Table 1, not among its footnotes. All four results files stamp this status, and it appeared
# nowhere in the bundle: a team pasting these counts into a manuscript had nothing in front of them saying the
# retention sample is still accruing, and the date the four "after the freeze date" rows are counted against was
# never stated either. Interim numbers become final by omission.
STANDING_STATUS = (
    "The rows this table excludes as \"after the freeze date\" are those dated after the freeze date above. The "
    "retention sample is still accruing, so these counts are not final."
)
# SAP v3.0: a final run's status line names the close date, and the counts are final
STANDING_STATUS_FINAL = (
    "The rows this table excludes as \"after the freeze date\" are those dated after the close date above. Data "
    "collection is closed, so these counts are final."
)
FLOW_BEGINS_AT_SIGNUP = (
    "The flow begins at signup. No step in the study data records a verification between signing up and Part 1, "
    "so the table has no verified row."
)
# SAP v3.2: the signup count leaves out the signups the NPI lookup could not match, which the study data now record;
# the footnote above would then say the opposite, so results carrying that count get this one instead.
FLOW_BEGINS_AT_SIGNUP_NPI = (
    "The flow begins at signup. The signup count leaves out the signups that the study team could not match to a "
    "neurologist or neurology trainee by National Provider Identifier (NPI) lookup; they were never sent study "
    "links. No step in the study data records which of the other signups were verified, so the table has no "
    "verified row."
)
NPI_KEY = "excluded_npi_unmatched"  # partc_results.flow.start key written from SAP v3.2


def has_npi_exclusion(results: Results) -> bool:
    """SAP v3.2: results written before it carry no NPI exclusion count, and the flow renders as it did then."""
    return NPI_KEY in get(results, "partc_results.flow.start")


# Two results files count the same population by different routes. The bundle adds nothing up, so it cannot
# reconcile them; if they ever disagree it refuses to render rather than print one of the two.
CROSS_CHECKS = (
    ("partc_results.flow.counts_by_group.survey3.total", "survey3_results.flow.analysed",
     "the Survey 3 population"),
    ("partc_results.flow.counts_by_group.phase3.total", "results.flow.analysed", "the Phase 3 population"),
    ("partc_results.flow.survey3_without_group", "survey3_results.flow.analysed_without_bloomer_paper",
     "Survey 3 responses without a group"),
)


def _must_agree(results: Results, left: str, right: str, what: str) -> None:
    if get(results, left) != get(results, right):
        raise BundleError(
            f"the results files disagree about {what}: {left} is {get(results, left)} and {right} is "
            f"{get(results, right)}. The bundle computes nothing, so it cannot reconcile them; re-run the "
            "analysis so both come from one run."
        )


def mcq_arm(results: Results, group: str) -> int:
    """The `descriptives` entry for the article this group studied with the MCQ, found by what it says it is."""
    base = f"partc_results.forgetting_unlinked.{group}"
    return entry_index(results, "results.descriptives", group=text_at(results, f"{base}.group"),
                       paper=text_at(results, f"{base}.paper"), method="MCQ")


def check_cross_file_counts(results: Results) -> None:
    for left, right, what in CROSS_CHECKS:
        _must_agree(results, left, right, what)
    # Figure 4 annotates the Part 1 immediate mean from Part C's `forgetting_unlinked`; Table 8 prints it from
    # Part A's `part1_context`. Two files, two keys, one quantity: an export where the two count it over
    # different frames would publish a figure and a table that disagree.
    for group in GROUPS:
        base = f"partc_results.forgetting_unlinked.{group}"
        paper = text_at(results, f"{base}.paper")
        rank = entry_index(results, "results.part1_context", paper=paper)
        _must_agree(results, f"{base}.mean_immediate", f"results.part1_context.{rank}.pct_correct_mean",
                    f"the Part 1 immediate mean for Paper {paper} (Figure 4 draws the first, Table 8 the second)")
        arm = f"results.descriptives.{mcq_arm(results, group)}"
        _must_agree(results, f"{base}.mean_one_month", f"{arm}.mean",
                    f"the 1-month MCQ-arm mean for group {group} (Table 8 prints the first beside the second's SD)")


def known_bias_about(results: Results, part: str, needle: str) -> str:
    """The one `known_biases` entry mentioning `needle`, quoted verbatim.

    A table travels alone. Table 5 reports the adoption co-primary, and the disclosure that makes it readable -
    pooled Q25 counts were seen before the denominator was chosen - lives in the supplement's S2, which a reader
    of the table may never see. Selecting the entry by a phrase the analysis layer wrote fails loudly if it is
    ever reworded, rather than quietly dropping the caveat.
    """
    found = [str(entry) for entry in get(results, f"{part}.known_biases") if needle in str(entry)]
    if len(found) != 1:
        raise BundleError(
            f"{part}.known_biases holds {len(found)} entries mentioning {needle!r}, not one. The table that "
            "reports this outcome must carry its disclosure with it, so the bundle refuses to render rather "
            "than print the outcome without it."
        )
    return found[0]


def _return_cells(results: Results, key: str, group: str) -> Cell:
    base = f"partc_results.flow.returns.{key}.by_group.{group}"
    prefix = f"flow.return.{key}.{GROUP_KEY[group]}"
    return cell(of_cell(results, f"{base}.n_returned", f"{base}.n_part1", prefix,
                        part_key="n_returned", whole_key="n_part1"),
                " (", pct_num(results, f"{base}.pct", f"{prefix}.pct"), ")")


def registration_footnote(results: Results) -> Cell:
    """SAP Part F: retention to sign-up link counts, interval and eligibility. Counts only."""
    base = f"partc_results.{REGISTRATION_LINK}"
    interval = f"{base}.interval_days"

    def days(field: str) -> Num:
        return value_num(results, f"{interval}.{field}", f"regl.interval.{field}", unit="days")

    def option_counts(field: str) -> list:
        # the options are the keys the analysis layer wrote, in its order; a blank answer is counted as "missing"
        options = [option for option in get(results, f"{base}.{field}") if option != "missing"]
        parts: list = []
        for rank, option in enumerate(options):
            parts += [", " if rank else "", option, " ",
                      count_num(results, join_path(*base.split("."), field, option), f"regl.{field}.{slug(option)}",
                                unit="people")]
        return parts

    return cell(
        "Retention to sign-up link (SAP Part F): the Part 1 quiz forms are anonymous, so analysed "
        "retention responses can be linked only to the sign-up (Start form); ",
        count_num(results, f"{base}.n_linked", "regl.n_linked", unit="people"), " were linked, ",
        count_num(results, f"{base}.n_by_basis.record", "regl.n_record", unit="people"),
        " from records (sign-up email or a name) and ",
        count_num(results, f"{base}.n_by_basis.timing", "regl.n_timing", unit="people"),
        " decided by the study team on timing. Sign-up to retention, an upper bound on the Part 1 to retention "
        "interval: median ", days("median"), " days (IQR ", days("q1"), " to ", days("q3"), "; range ", days("min"),
        " to ", days("max"), "). Among the linked, US-based: ", *option_counts("us_based"),
        "; role: ", *option_counts("role"),
        *(followup_sentences(results) if "followup" in get(results, base) else
          [". Counts only; no group comparison is made."]))


def followup_sentences(results: Results) -> list:
    """SAP F4: assignment-email agreement and the two record-based intervals, as cell parts."""
    base = f"partc_results.{REGISTRATION_LINK}.followup"

    def interval(field: str, key: str) -> list:
        path = f"{base}.{field}"

        def num(name: str) -> Num:
            return value_num(results, f"{path}.{name}", f"regl.{key}.{name}", unit="days")

        return ["median ", num("median"), " days (IQR ", num("q1"), " to ", num("q3"), "; range ", num("min"),
                " to ", num("max"), "; n = ", count_num(results, f"{path}.n", f"regl.{key}.n", unit="people"), ")"]

    return [
        ". Study-team follow-up records (SAP F4): the assignment email was recorded for ",
        count_num(results, f"{base}.assignment.n_recorded", "regl.assign.recorded", unit="people"), " of ",
        count_num(results, f"{base}.assignment.n_population", "regl.assign.population", unit="people"),
        " analysed retention responses, and the self-reported group agreed for ",
        count_num(results, f"{base}.assignment.n_agree", "regl.assign.agree", unit="people"), " and differed for ",
        count_num(results, f"{base}.assignment.n_disagree", "regl.assign.disagree", unit="people"),
        ". Part 1 (Bloomer summary received) to retention: ", *interval("part1_to_retention_days", "part1"),
        ". Retention link sent to retention: ", *interval("link_to_retention_days", "link"), ". Counts only.",
    ]


def table1_flow(results: Results) -> Table:
    check_cross_file_counts(results)
    paper_a = entry_index(results, "results.part1_context", paper="A")
    paper_b = entry_index(results, "results.part1_context", paper="B")
    rows: list[tuple[Cell, ...]] = [
        (
            cell("Signed up (Start form)"), cell(MISSING), cell(MISSING),
            cell(count_num(results, "partc_results.flow.start.analysed", "flow.signup.analysed", unit="people")),
            joined([
                cell("de-identified ", count_num(results, "partc_results.flow.start.deidentified",
                                                 "flow.signup.deidentified", unit="people")),
                cell("pilot rows excluded ", count_num(results, "partc_results.flow.start.excluded_pilot",
                                                       "flow.signup.excluded_pilot", unit="people")),
                cell("signed up after the freeze date ",
                     count_num(results, "partc_results.flow.start.excluded_after_freeze",
                               "flow.signup.excluded_after_freeze", unit="people")),
                *([cell(f"{NPI_UNMATCHED_LABEL} ",
                        count_num(results, f"partc_results.flow.start.{NPI_KEY}",
                                  "flow.signup.excluded_npi_unmatched", unit="people"))]
                  if has_npi_exclusion(results) else []),
            ]),
        ),
        (
            cell("Completed Part 1 (MCQ form)"),
            cell(count_num(results, "partc_results.flow.counts_by_group.part1_mcq.A", "flow.part1.group_a",
                           unit="forms")),
            cell(count_num(results, "partc_results.flow.counts_by_group.part1_mcq.B", "flow.part1.group_b",
                           unit="forms")),
            cell(count_num(results, "partc_results.flow.counts_by_group.part1_mcq.total", "flow.part1.total",
                           unit="forms")),
            joined([
                cell("pilot rows excluded, Paper A ",
                     count_num(results, f"results.part1_context.{paper_a}.n_pilot_excluded",
                               "flow.part1.excluded_pilot_a", unit="forms"),
                     ", Paper B ", count_num(results, f"results.part1_context.{paper_b}.n_pilot_excluded",
                                             "flow.part1.excluded_pilot_b", unit="forms")),
                cell("started after the freeze date, Paper A ",
                     count_num(results, f"results.part1_context.{paper_a}.n_after_freeze_excluded",
                               "flow.part1.excluded_after_freeze_a", unit="forms"),
                     ", Paper B ", count_num(results, f"results.part1_context.{paper_b}.n_after_freeze_excluded",
                                             "flow.part1.excluded_after_freeze_b", unit="forms")),
            ]),
        ),
        (
            cell("Completed Survey 3"),
            cell(count_num(results, "survey3_results.flow.analysed_group_A", "flow.survey3.group_a", unit="people")),
            cell(count_num(results, "survey3_results.flow.analysed_group_B", "flow.survey3.group_b", unit="people")),
            cell(count_num(results, "survey3_results.flow.analysed", "flow.survey3.analysed", unit="people")),
            joined([
                cell("de-identified ", count_num(results, "survey3_results.flow.survey3_deidentified",
                                                 "flow.survey3.deidentified", unit="people")),
                cell("pilot rows excluded ", count_num(results, "survey3_results.flow.excluded_pilot",
                                                       "flow.survey3.excluded_pilot", unit="people")),
                cell("blank submissions excluded ", count_num(results, "survey3_results.flow.excluded_blank",
                                                              "flow.survey3.excluded_blank", unit="people")),
                cell("completed after the freeze date ",
                     count_num(results, "survey3_results.flow.excluded_after_freeze",
                               "flow.survey3.excluded_after_freeze", unit="people")),
                cell("duplicates removed at ingest ",
                     count_num(results, "survey3_results.flow.duplicates_removed_at_ingest",
                               "flow.survey3.duplicates_removed", unit="people")),
                cell("without a Bloomer paper ",
                     count_num(results, "survey3_results.flow.analysed_without_bloomer_paper",
                               "flow.survey3.without_group", unit="people")),
            ]),
        ),
        (
            cell("Completed 1 month (Phase 3)"),
            cell(count_num(results, "results.flow.analysed_group_A", "flow.phase3.group_a", unit="people")),
            cell(count_num(results, "results.flow.analysed_group_B", "flow.phase3.group_b", unit="people")),
            cell(count_num(results, "results.flow.analysed", "flow.phase3.analysed", unit="people")),
            joined([
                cell("de-identified ", count_num(results, "results.flow.phase3_deidentified",
                                                 "flow.phase3.deidentified", unit="people")),
                cell("duplicates removed at ingest ", count_num(results, "results.flow.duplicates_removed_at_ingest",
                                                                "flow.phase3.duplicates_removed", unit="people")),
                cell("completed after the freeze date ", count_num(results, "results.flow.excluded_after_freeze",
                                                                   "flow.phase3.excluded_after_freeze",
                                                                   unit="people")),
                cell("without a group ", count_num(results, "results.flow.excluded_missing_group",
                                                   "flow.phase3.excluded_missing_group", unit="people")),
            ]),
        ),
    ]
    for label, key in (("Return: Part 1 to Survey 3", "survey3"), ("Return: Part 1 to Phase 3", "phase3")):
        rows.append((
            cell(label), _return_cells(results, key, "A"), _return_cells(results, key, "B"), cell(MISSING),
            cell(text_at(results, f"partc_results.flow.returns.{key}.test"), ": ",
                 p_num(results, f"partc_results.flow.returns.{key}.p_value", f"flow.return.{key}.p_value")),
        ))
    eligible, eligible_returns = "partc_results.flow.returns_eligible", "partc_results.flow.returns_eligible.phase3"
    cutoff = text_num(results, f"{eligible}.cutoff", "flow.eligible.cutoff", unit="date")
    rows.append((
        cell("Return: Part 1 to Phase 3, follow-up-eligible forms"),
        *[cell(count_num(results, f"{eligible_returns}.by_group.{group}.n_returned",
                         f"flow.eligible_returns.{group}_n_returned", unit="people"),
               " of ", count_num(results, f"{eligible}.part1_eligible.{group}", f"flow.eligible.{group}",
                                 unit="forms"),
               " (", pct_num(results, f"{eligible_returns}.by_group.{group}.pct", f"flow.eligible_returns.{group}_pct"),
               ")")
          for group in GROUPS],
        cell(count_num(results, f"{eligible}.part1_eligible.total", "flow.eligible.total", unit="forms")),
        cell(text_at(results, f"{eligible_returns}.test"), ": ",
             p_num(results, f"{eligible_returns}.p_value", "flow.eligible_returns.p"),
             "; eligible forms dated on or before ", cutoff),
    ))
    dates = "partc_results.flow.date_ranges"
    footnotes = [
        cell("n: ", count_num(results, "partc_results.flow.start.analysed", "flow.signup.analysed", unit="people"),
             " signups, ", count_num(results, "partc_results.flow.counts_by_group.part1_mcq.A", "flow.part1.group_a",
                                     unit="forms"),
             " and ", count_num(results, "partc_results.flow.counts_by_group.part1_mcq.B", "flow.part1.group_b",
                                unit="forms"),
             " Part 1 MCQ forms (groups A and B), ", count_num(results, "survey3_results.flow.analysed",
                                                               "flow.survey3.analysed", unit="people"),
             " Survey 3 responses and ", count_num(results, "results.flow.analysed", "flow.phase3.analysed",
                                                   unit="people"), " Phase 3 responses analysed."),
        cell("Estimator: none for the counts. Return rates are compared between groups with ",
             text_at(results, "partc_results.flow.returns.survey3.test"), " (Part 1 to Survey 3) and ",
             text_at(results, "partc_results.flow.returns.phase3.test"), " (Part 1 to Phase 3)."),
        cell(P_CONVENTION),
        cell("Counts are of forms, not of followed people: return rates compare counts of unlinked forms."),
        cell("The Start form carries no group, so signups are not split by group. Analysed signups answering No to "
             "US-based: ", count_num(results, "partc_results.flow.start.analysed_not_us_based",
                                     "flow.signup.not_us_based", unit="people"), " (they stay in every count)."),
        cell("The duplicate check covers only rows that gave a contact email; Phase 3 rows without one: ",
             count_num(results, "results.flow.rows_without_contact_email", "flow.phase3.rows_without_contact_email",
                       unit="people"), "; Survey 3 rows without one: ",
             count_num(results, "survey3_results.flow.rows_without_contact_email",
                       "flow.survey3.rows_without_contact_email", unit="people"), "."),
        cell(FLOW_BEGINS_AT_SIGNUP_NPI if has_npi_exclusion(results) else FLOW_BEGINS_AT_SIGNUP),
        cell("No total in this table is added up by the bundle: each is the count the analysis layer wrote over "
             "that step's own population. For Survey 3 and Phase 3 that can differ from group A plus group B, "
             "because a Survey 3 response without a Bloomer paper belongs to no group but is still analysed (",
             count_num(results, "survey3_results.flow.analysed_without_bloomer_paper", "flow.survey3.without_group",
                       unit="people"),
             " here). The Part 1 total counts the two MCQ form files, one per paper, and there is no group-less "
             "Part 1 form, so for that row it is group A plus group B."),
        cell("Follow-up-eligible forms (SAP C1): the Part 1 to Phase 3 return rate recomputed over the "
             "Part 1 MCQ forms dated on or before ", cutoff, ", the freeze date minus 28 days, when a respondent "
             "had had the full 1-month window. The numerator is every analysed retention (Phase 3) response in "
             "that group, as in the row above, because the forms are unlinked and a response cannot be traced to "
             "an eligible form. Part 1 MCQ forms are dated ",
             text_num(results, f"{dates}.part1.0", "flow.dates.part1_min", unit="date"), " to ",
             text_num(results, f"{dates}.part1.1", "flow.dates.part1_max", unit="date"),
             " and Phase 3 responses ",
             text_num(results, f"{dates}.phase3.0", "flow.dates.phase3_min", unit="date"), " to ",
             text_num(results, f"{dates}.phase3.1", "flow.dates.phase3_max", unit="date"), "."),
    ]
    if REGISTRATION_LINK in results["partc_results"]:  # SAP v2.7 Part F; absent before v2.7, so optional here
        footnotes.append(registration_footnote(results))
    return Table(1, "Participant flow", ("Step", "Group A", "Group B", "Total", "Exclusions and notes"),
                 tuple(rows), tuple(footnotes), standing=cell("**", status_num(results), ".** ",
                                           STANDING_STATUS_FINAL if is_final(text_at(results, "results.status"))
                                           else STANDING_STATUS))


# ------------------------------------------------------------------------------------ Table 2: characteristics

TABLE2_PERCENT_NOTE = (
    "Cells are n (%). Both the percentage and the denominator it uses are written by the analysis layer "
    "(`survey3_results.table1.categorical_pct.<variable>.<group>`) and are never computed here. The denominator "
    "is every respondent in that column, blanks included, so a variable's levels sum to 100%."
)


def check_denominators(results: Results) -> None:
    """Every Table 1 percentage must have been taken over the respondents the same table counts."""
    for variable, by_group in get(results, "survey3_results.table1.categorical_pct").items():
        for group in by_group:
            recorded = get(results, f"survey3_results.table1.categorical_pct.{variable}.{group}.denominator")
            respondents = get(results, f"survey3_results.table1.n.{group}")
            if recorded != respondents:
                raise BundleError(
                    f"survey3_results.table1.categorical_pct.{variable}.{group}.denominator is {recorded} but "
                    f"survey3_results.table1.n.{group} is {respondents}: the percentages in Table 2 would not be "
                    "over the respondents the same table reports"
                )


def _numeric_row(results: Results, key: str, label: str, *, digits: int = 1, unit: str = PP) -> tuple[Cell, ...]:
    return (cell(label), *[median_iqr_cell(results, f"survey3_results.table1.numeric.{key}.{group}",
                                           f"demographics.{key}.{GROUP_KEY[group]}", digits=digits, unit=unit)
                           for group in ("overall", *GROUPS)])


def table2_characteristics(results: Results) -> Table:
    check_denominators(results)
    rows: list[tuple[Cell, ...]] = [
        (cell("Respondents, n"),
         *[cell(count_num(results, f"survey3_results.table1.n.{group}", f"demographics.n.{GROUP_KEY[group]}",
                          unit="people")) for group in ("overall", *GROUPS)]),
        _numeric_row(results, "age", "Age, median (IQR) [n]", unit="years"),
    ]
    categorical = get(results, "survey3_results.table1.categorical")
    for variable in categorical:  # the analysis writes these JSON objects sorted, so the order is deterministic
        label = TABLE1_LABELS.get(variable, variable)
        for option in categorical[variable]["overall"]:
            prefix = f"demographics.{variable}.{slug(option)}"
            counts = [count_num(results,
                                join_path("survey3_results", "table1", "categorical", variable, group, option),
                                f"{prefix}.{GROUP_KEY[group]}.n", unit="people")
                      for group in ("overall", *GROUPS)]
            if not any(count.value for count in counts):
                continue  # an option nobody chose in any group is left out, as in the analysis's own Table 1
            shares = [pct_num(results, join_path("survey3_results", "table1", "categorical_pct", variable, group,
                                                 "levels", option), f"{prefix}.{GROUP_KEY[group]}.pct")
                      for group in ("overall", *GROUPS)]
            rows.append((cell(f"{label}: {display(option)}"),
                         *[cell(count, " (", share, ")") for count, share in zip(counts, shares)]))
    rows += [
        _numeric_row(results, "years_attending", "Years in practice, attendings, median (IQR) [n]", unit="years"),
        _numeric_row(results, "years_trainee", "PGY year, trainees, median (IQR) [n]", unit="years"),
        _numeric_row(results, "prior_knowledge", "Prior knowledge of the Bloomer article (1-10), median (IQR) [n]",
                     unit="rating points (1-10)"),
    ]
    footnotes = [
        cell("n: ", count_num(results, "survey3_results.table1.n.overall", "demographics.n.overall", unit="people"),
             " Survey 3 respondents (group A ",
             count_num(results, "survey3_results.table1.n.A", "demographics.n.group_a", unit="people"), ", group B ",
             count_num(results, "survey3_results.table1.n.B", "demographics.n.group_b", unit="people"),
             "). These are the Survey 3 respondents, not the Phase 3 retention sample."),
        cell(NO_ESTIMATOR),
        cell(P_CONVENTION + " No P value is reported in this table."),
        cell("blank counts respondents who left the item empty; an option nobody chose in any group is not listed."),
        cell("Adoption choice is not broken down by subspecialty here. At this n the smallest subspecialties "
             "hold one respondent, and crossing one respondent with their Q25 answer, beside the group this "
             "table already gives, identifies that person's preference. Subspecialty counts are in the table "
             "above; the adoption subgroups the analysis plan specifies are in supplement S3."),
        cell(TABLE2_PERCENT_NOTE),
    ]
    return Table(2, "Participant characteristics (Survey 3 respondents)",
                 ("Characteristic", "Overall", "Group A", "Group B"), tuple(rows), tuple(footnotes))


# ---------------------------------------------------------------------------------- Table 3: primary outcome

def _descriptive_row(results: Results, group: str, paper: str) -> tuple[Cell, ...]:
    rank = entry_index(results, "results.descriptives", group=group, paper=paper)
    base, prefix = f"results.descriptives.{rank}", f"descriptives.group_{group.lower()}.paper_{paper.lower()}"
    method = text_at(results, f"{base}.method")
    return (
        cell(f"Group {group}, Paper {paper} ({method}-studied)"),
        cell(count_num(results, f"{base}.n", f"{prefix}.n", unit="people")),
        mean_sd_cell(results, f"{base}.mean", f"{base}.sd", prefix, unit=PERCENT),
        median_iqr_cell(results, base, prefix, unit=PERCENT),
        cell(MISSING), cell(MISSING),
    )


def _estimate_row(results: Results, base: str, prefix: str, label: str) -> tuple[Cell, ...]:
    # the unit comes from the row, as it does in Table 4: a row the analysis layer writes in another unit must
    # not be relabelled as percentage points and re-rounded to one decimal by the manuscript
    unit = text_at(results, f"{base}.unit")
    return (
        cell(label),
        cell(count_num(results, f"{base}.n_a", f"{prefix}.n_a", unit="people"), "/",
             count_num(results, f"{base}.n_b", f"{prefix}.n_b", unit="people")),
        cell(MISSING), cell(MISSING),
        estimate_cell(results, base, prefix, digits=1 if unit == PP else 2, unit=unit),
        cell(p_num(results, f"{base}.p_value", f"{prefix}.p_value")),
    )


def table3_primary(results: Results) -> Table:
    head, lmm = "results.primary.headline", "results.primary.prespecified_model"
    rows = [_descriptive_row(results, group, paper) for group in GROUPS for paper in GROUPS]
    rows.append(_estimate_row(results, head, "primary", text_at(results, f"{head}.label")))
    rows.append(_estimate_row(results, lmm, "primary.lmm", text_at(results, f"{lmm}.label")))
    footnotes = [
        cell("n: ", count_num(results, f"{head}.n_a", "primary.n_a", unit="people"), " group A and ",
             count_num(results, f"{head}.n_b", "primary.n_b", unit="people"),
             " group B participants contribute both articles."),
        cell("Estimator: ", text_at(results, f"{head}.estimator"), " for the headline (df ",
             count_num(results, f"{head}.df", "primary.df", unit=COUNT), ", SE ",
             value_num(results, f"{head}.se", "primary.se"), "); ", text_at(results, f"{lmm}.estimator"),
             " for the pre-specified model (SE ", value_num(results, f"{lmm}.se", "primary.lmm.se"),
             "). The mixed model is reported alongside the headline, not as a second primary result."),
        cell(P_CONVENTION),
        cell("The outcome is the percent of valid items correct at 1 month; the estimate is the Bloomer-studied "
             "article minus the MCQ-studied article in ", PP, ", averaged over the two sequence groups."),
    ]
    notes = get(results, f"{lmm}.notes")
    if notes:
        footnotes.append(cell("Model notes: " + "; ".join(str(note) for note in notes) + "."))
    return Table(3, "Primary outcome: 1-month retention",
                 ("Row", "n", "Mean (SD), %", "Median (IQR), %",
                  "Bloomer minus MCQ, percentage points (95% CI)", "P"),
                 tuple(rows), tuple(footnotes))


# ------------------------------------------------------------------------------------- Table 4: sensitivity

def sensitivity_prefix(results: Results, rank: int) -> str:
    """`sensitivity.s1` from the analysis's own row label, so the keys survive a reordered list."""
    return f"sensitivity.{slug(text_at(results, f'results.sensitivity.{rank}.label').split()[0])}"


def _sensitivity_rows(results: Results) -> list[tuple[Cell, ...]]:
    rows = []
    for rank in range(len(get(results, "results.sensitivity"))):
        base = f"results.sensitivity.{rank}"
        label = text_at(results, f"{base}.label")
        prefix = sensitivity_prefix(results, rank)
        unit = text_at(results, f"{base}.unit")
        digits = 1 if unit == PP else 2
        p_key = SENSITIVITY_P_KEY.get(prefix, "p_value")
        rows.append((
            cell(display_label(label)),
            cell(text_at(results, f"{base}.estimator")),
            cell(count_num(results, f"{base}.n_a", f"{prefix}.n_a", unit="people"), "/",
                 count_num(results, f"{base}.n_b", f"{prefix}.n_b", unit="people")),
            estimate_cell(results, base, prefix, digits=digits, unit=unit),
            cell(unit),
            cell(p_num(results, f"{base}.p_value", f"{prefix}.{p_key}")),
        ))
    return rows


def _tipping_rows(results: Results) -> list[tuple[Cell, ...]]:
    rows = []
    for direction in get(results, "partc_results.tipping_point.directions"):
        base = f"partc_results.tipping_point.directions.{direction}"
        prefix = f"tipping.{direction.lower()}"
        smallest = get(results, f"{base}.smallest_k_ci_excludes_zero")
        if smallest is None:
            smallest_cell = cell("none of the subsets tried")
        else:
            # without the denominator the cell reads as "relabel k responses and the result turns significant",
            # when it is the worst case over every subset of that size and most of them do nothing
            at_k = f"{base}.by_k.{entry_index(results, f'{base}.by_k', k=smallest)}"
            smallest_cell = cell(
                "smallest k whose 95% CI excludes 0: ",
                count_num(results, f"{base}.smallest_k_ci_excludes_zero", f"{prefix}.smallest_k",
                          unit="responses"),
                "; at that k ",
                share_num(results, f"{at_k}.share_ci_excludes_zero", f"{prefix}.share_at_smallest_k"),
                " of ", count_num(results, f"{at_k}.n_subsets", f"{prefix}.n_subsets_at_smallest_k",
                                  unit="subsets"),
                " subsets, ", count_num(results, f"{at_k}.n_ci_above_zero", f"{prefix}.n_above_at_smallest_k",
                                        unit="subsets"),
                " with the interval above and ",
                count_num(results, f"{at_k}.n_ci_below_zero", f"{prefix}.n_below_at_smallest_k", unit="subsets"),
                " below")
        rows.append((
            cell(f"S6 Group-mislabelling tipping point: {DIRECTION_LABELS.get(direction, direction)}"),
            cell("relabelling, worst case over subsets"),
            cell(count_num(results, f"{base}.n_source", f"{prefix}.n_source", unit="people")),
            smallest_cell,
            cell("responses relabelled"),
            cell(MISSING),
        ))
    return rows


def table4_sensitivity(results: Results) -> Table:
    rows = _sensitivity_rows(results) + _tipping_rows(results)
    largest = []
    for direction in get(results, "partc_results.tipping_point.directions"):
        base = f"partc_results.tipping_point.directions.{direction}.by_k.-1"
        prefix = f"tipping.{direction.lower()}"
        largest.append(cell(DIRECTION_LABELS.get(direction, direction), " at k = ",
                            count_num(results, f"{base}.k", f"{prefix}.max_k", unit="responses"), ": theta ",
                            value_num(results, f"{base}.theta_min", f"{prefix}.theta_min"), " to ",
                            value_num(results, f"{base}.theta_max", f"{prefix}.theta_max"), " over ",
                            count_num(results, f"{base}.n_subsets", f"{prefix}.n_subsets", unit="subsets"),
                            " subsets"))
    footnotes = [
        cell("n: ", count_num(results, "results.primary.headline.n_a", "primary.n_a", unit="people"),
             " group A and ", count_num(results, "results.primary.headline.n_b", "primary.n_b", unit="people"),
             " group B participants, except S1, which drops participants who re-read, used AI or discussed the "
             "articles."),
        cell("Estimator: named per row. The tipping-point rows are not estimates: they relabel every subset of k "
             "Phase 3 responses from one group to the other and recompute the headline, so the smallest k is a "
             "worst case across all subsets of that size."),
        cell(P_CONVENTION),
        cell("Headline without relabelling: ",
             estimate_cell(results, "partc_results.tipping_point.observed", "tipping.observed"), " ", PP, "; ",
             p_num(results, "partc_results.tipping_point.observed.p_value", "tipping.observed.p_value"), "."),
        cell("Theta range at the largest k tried: ", joined(largest), "."),
        cell("Degrees of freedom, where the estimator uses them: headline ",
             count_num(results, "results.primary.headline.df", "primary.df", unit=COUNT), "; ",
             joined([cell(text_at(results, f"results.sensitivity.{rank}.label").split()[0], " ",
                          df_num(results, f"results.sensitivity.{rank}.df",
                                f"{sensitivity_prefix(results, rank)}.df", unit=COUNT))
                     for rank, entry in enumerate(get(results, "results.sensitivity"))
                     if entry.get("df") is not None], ", "), "."),
    ]
    notes = [f"{text_at(results, f'results.sensitivity.{rank}.label').split()[0]}: {note}"
             for rank, entry in enumerate(get(results, "results.sensitivity")) for note in entry.get("notes", [])]
    if notes:
        footnotes.append(cell("Analysis notes: " + "; ".join(notes) + "."))
    v26 = [SENSITIVITY_V26_NOTES[entry["label"]] for entry in get(results, "results.sensitivity")
           if entry.get("label") in SENSITIVITY_V26_NOTES]
    if v26:
        footnotes.append(cell(" ".join(v26)))
    return Table(4, "Sensitivity analyses and the group-mislabelling tipping point",
                 ("Analysis", "Estimator", "n (A/B)", "Estimate (95% CI)", "Unit", "P"),
                 tuple(rows), tuple(footnotes))


# ------------------------------------------------------------------------- Table 5: adoption and satisfaction

def _choice_rows(results: Results, key: str, prefix: str, question: str) -> list[tuple[Cell, ...]]:
    decided, everyone = f"survey3_results.{key}.decided", f"survey3_results.{key}.all_respondents"
    return [
        (
            cell(f"{question}, respondents who chose one or the other"),
            of_cell(results, f"{decided}.n_bloomer", f"{decided}.n_decided", f"{prefix}.decided",
                    part_key="n_bloomer", whole_key="n_decided"),
            cell(share_num(results, f"{decided}.proportion", f"{prefix}.decided.pct")),
            cell(share_num(results, f"{decided}.ci_low", f"{prefix}.decided.ci_low"), " to ",
                 share_num(results, f"{decided}.ci_high", f"{prefix}.decided.ci_high")),
            cell(p_num(results, f"{decided}.p_value", f"{prefix}.decided.p_value")),
        ),
        (
            cell(f"{question}, all respondents who answered"),
            of_cell(results, f"{everyone}.n_bloomer", f"{everyone}.n_answered", f"{prefix}.all",
                    part_key="n_bloomer", whole_key="n_answered"),
            cell(share_num(results, f"{everyone}.proportion", f"{prefix}.all.pct")),
            cell(share_num(results, f"{everyone}.ci_low", f"{prefix}.all.ci_low"), " to ",
                 share_num(results, f"{everyone}.ci_high", f"{prefix}.all.ci_high")),
            cell(MISSING),
        ),
    ]


def _difficulty_row(results: Results, key: str, label: str) -> tuple[Cell, ...]:
    base, prefix = f"survey3_results.difficulty.{key}", f"difficulty.{key}"
    return (
        cell(label),
        cell(count_num(results, f"{base}.n", f"{prefix}.n", unit="people")),
        cell(median_iqr_cell(results, base, prefix, unit="rating points (1-5)"), "; ",
             pct_num(results, f"{base}.pct_difficult", f"{prefix}.pct_difficult"),
             " rated it a little or very difficult"),
        cell(MISSING), cell(MISSING),
    )


def table5_adoption(results: Results) -> Table:
    rows = _choice_rows(results, "adoption", "adoption", "Chose Bloomer to prove CME competency (Q25)")
    rows += _choice_rows(results, "comprehension", "comprehension",
                         "Chose Bloomer as best for checking comprehension (Q22)")
    rows.append(_difficulty_row(results, "quiz", "Difficulty of the traditional 5-question quiz (Q23)"))
    rows.append(_difficulty_row(results, "bloomer", "Difficulty of Bloomer (Q24)"))
    paired = "survey3_results.difficulty.paired"
    rows.append((
        cell("Difficulty, Bloomer minus quiz (paired)"),
        cell(count_num(results, f"{paired}.n_pairs", "difficulty.paired.n_pairs", unit="people"), " pairs (",
             count_num(results, f"{paired}.n_nonzero", "difficulty.paired.n_nonzero", unit="people"), " non-zero)"),
        cell("median difference ", value_num(results, f"{paired}.median_difference",
                                             "difficulty.paired.median_difference",
                                             unit="rating points (1-5)")),
        cell(MISSING),
        cell(p_num(results, f"{paired}.p_value", "difficulty.paired.p_value")),
    ))
    counts = [cell(display(option), " ",
                   count_num(results, join_path("survey3_results", "adoption", "counts", option),
                             f"adoption.counts.{slug(option)}", unit="people"))
              for option in get(results, "survey3_results.adoption.counts")]
    footnotes = [
        cell("n: ", count_num(results, "survey3_results.adoption.all_respondents.n_answered", "adoption.all.n_answered",
                              unit="people"), " Survey 3 respondents answered Q25 and ",
             count_num(results, "survey3_results.comprehension.all_respondents.n_answered",
                       "comprehension.all.n_answered", unit="people"), " answered Q22; ",
             count_num(results, "survey3_results.difficulty.quiz.n", "difficulty.quiz.n", unit="people"),
             " rated the quiz item and ",
             count_num(results, f"{paired}.n_pairs", "difficulty.paired.n_pairs", unit="people"),
             " rated both difficulty items."),
        cell("Estimator: exact binomial test against 50% for the adoption and comprehension proportions with exact "
             "95% CIs; ", text_at(results, f"{paired}.test"), " for the paired difficulty difference, which "
             "resolved to ", text_at(results, f"{paired}.method"), "."),
        cell(P_CONVENTION),
        cell("Q25 is not a forced choice, so the co-primary proportion uses respondents who chose Bloomer or the "
             "quiz; all-respondent results are reported alongside. Q25 answers: ", joined(counts), "."),
        cell("Difference from 50% among decided respondents (Q25): ",
             pp_num(results, "survey3_results.adoption.decided.effect_vs_half", "adoption.decided.effect_vs_half"),
             " ", PP, "."),
        cell("Proportions are shown as percentages; that conversion is display only, not a computed statistic."),
        cell("Both difficulty items are rated on a 1 to 5 scale; the medians, the IQRs and the paired difference "
             "are in rating points on that scale."),
        cell("Disclosure: ", known_bias_about(results, "survey3_results", "Q25")),
    ]
    return Table(5, "Adoption and satisfaction (Survey 3)",
                 ("Outcome", "n", "Estimate", "95% CI", "P"), tuple(rows), tuple(footnotes))


# ---------------------------------------------------------------------------------- Table 6: Bloomer usage

def table6_usage(results: Results) -> Table:
    rows = []
    for question in get(results, "survey3_results.usage.per_question"):
        base, prefix = f"survey3_results.usage.per_question.{question}", f"usage.{question}"
        rows.append((
            cell(text_at(results, f"{base}.label")),
            median_iqr_cell(results, f"{base}.attempts", f"{prefix}.attempts", unit="attempts"),
            cell(pct_num(results, f"{base}.attempts.pct_more_than_one", f"{prefix}.attempts.pct_more_than_one")),
            median_iqr_cell(results, f"{base}.minutes", f"{prefix}.minutes", unit="minutes"),
            cell(count_num(results, f"{base}.time_status.unparsed", f"{prefix}.time_unparsed", unit="people"), " / ",
                 count_num(results, f"{base}.time_status.blank", f"{prefix}.time_blank", unit="people")),
            cell(count_num(results, f"{base}.attempts_status.unparsed", f"{prefix}.attempts_unparsed",
                           unit="people"), " / ",
                 count_num(results, f"{base}.attempts_status.blank", f"{prefix}.attempts_blank", unit="people")),
        ))
    rows.append((
        cell("All three questions, per person"),
        median_iqr_cell(results, "survey3_results.usage.total_attempts", "usage.total_attempts", unit="attempts"),
        cell(MISSING),
        median_iqr_cell(results, "survey3_results.usage.total_minutes", "usage.total_minutes", unit="minutes"),
        cell(MISSING), cell(MISSING),
    ))
    proxy = "survey3_results.usage.completion_proxy"
    excl = "survey3_results.usage.total_minutes_excl_over_60"
    footnotes = [
        cell("n: ", count_num(results, f"{proxy}.n", "usage.completion_proxy.n", unit="people"),
             " Survey 3 respondents; per-question and per-person counts differ because a free-text time or attempt "
             "that matches no parsing rule is missing."),
        cell(NO_ESTIMATOR),
        cell(P_CONVENTION + " No P value is reported in this table."),
        cell("Completion proxy: ", count_num(results, f"{proxy}.n_complete", "usage.completion_proxy.n_complete",
                                             unit="people"), " of ",
             count_num(results, f"{proxy}.n", "usage.completion_proxy.n", unit="people"), " (",
             pct_num(results, f"{proxy}.pct", "usage.completion_proxy.pct"), "), defined as ",
             text_at(results, f"{proxy}.definition"),
             ". This is not the mastery rate, which the form does not record."),
        cell("Extreme usage (SAP B5): respondents reporting more than 60 minutes on at least one "
             "question, ", count_num(results, "survey3_results.usage.n_any_question_over_60", "usage.over60.n",
                                    unit="people"),
             "; excluding them, the per-person total is ",
             value_num(results, f"{excl}.median", "usage.over60.median_excl", unit="minutes"), " (",
             value_num(results, f"{excl}.q1", "usage.over60.q1_excl", unit="minutes"), " to ",
             value_num(results, f"{excl}.q3", "usage.over60.q3_excl", unit="minutes"), ") minutes."),
    ]
    return Table(6, "Bloomer usage (Survey 3 self-report)",
                 ("Question", "Attempts, median (IQR) [n]", "More than 1 attempt", "Minutes, median (IQR) [n]",
                  "Time not parsed / blank", "Attempts not parsed / blank"),
                 tuple(rows), tuple(footnotes))


# -------------------------------------------------------------------------- Table 7: item-level performance

def table7_items(results: Results) -> Table:
    limited = get(results, "results.date_limited_items")
    rows = []
    for rank in range(len(get(results, "results.items"))):
        base = f"results.items.{rank}"
        item_id, method = text_at(results, f"{base}.item_id"), text_at(results, f"{base}.method")
        prefix = f"items.{item_id.lower()}.{METHOD_KEY.get(method, slug(method))}"
        rows.append((
            cell(item_id),
            cell(f"{method}-studied"),
            cell("date-limited" if item_id in limited else "yes"),
            cell(count_num(results, f"{base}.n", f"{prefix}.n", unit="people")),
            cell(count_num(results, f"{base}.n_correct", f"{prefix}.n_correct", unit="people")),
            cell(pct_num(results, f"{base}.pct_correct", f"{prefix}.pct_correct", digits=0)),
            cell(count_num(results, f"{base}.n_not_scored", f"{prefix}.n_not_scored", unit="people")),
        ))
    rules = [cell("Item ", item_id, " is scored only for responses dated on or after ",
                  text_at(results, f"results.date_limited_items.{item_id}.scored_from"), ", because ",
                  text_at(results, f"results.date_limited_items.{item_id}.reason"),
                  "; analysed Phase 3 responses with it scored: ",
                  count_num(results, f"results.date_limited_items.{item_id}.n_phase3_scored",
                            f"items.date_limited.{item_id.lower()}.n_scored", unit="people"), ", not scored: ",
                  count_num(results, f"results.date_limited_items.{item_id}.n_phase3_not_scored",
                            f"items.date_limited.{item_id.lower()}.n_not_scored", unit="people"))
             for item_id in limited]
    footnotes = [
        cell("n: ", count_num(results, "results.flow.analysed", "flow.phase3.analysed", unit="people"),
             " analysed Phase 3 responses; each item is answered by the group that was given its paper, so the n "
             "of a row is the size of that arm for that item."),
        cell(NO_ESTIMATOR + " Percent correct is over scored responses only."),
        cell(P_CONVENTION + " No P value is reported in this table; the item-level test is S3 in Table 4."),
        cell("Date-limited items: ", joined(rules) if rules else cell("none"), "."),
    ]
    return Table(7, "Item-level percent correct at 1 month",
                 ("Item", "Studied with", "Scored", "n", "Correct, n", "% correct", "Not scored, n"),
                 tuple(rows), tuple(footnotes))


# ----------------------------------------------------------------- Table 8: immediate scores and forgetting

def table8_forgetting(results: Results) -> Table:
    rows = []
    for group in GROUPS:
        rank = entry_index(results, "results.part1_context", paper=group)
        part1, prefix1 = f"results.part1_context.{rank}", f"part1.paper_{group.lower()}"
        base, prefix = f"partc_results.forgetting_unlinked.{group}", f"forgetting.group_{group.lower()}"
        rows.append((
            # each entry names its own paper and group; the loop letter is only how the analysis layer keys them
            cell(f"Paper {text_at(results, f'{base}.paper')} (group {text_at(results, f'{base}.group')})"),
            cell(count_num(results, f"{base}.n_immediate", f"{prefix}.n_immediate", unit="forms"), "; ",
                 mean_sd_cell(results, f"{part1}.pct_correct_mean", f"{part1}.pct_correct_sd", prefix1,
                              unit=PERCENT)),
            cell(count_num(results, f"{base}.n_one_month", f"{prefix}.n_one_month", unit="people"), "; ",
                 value_num(results, f"{base}.mean_one_month", f"{prefix}.mean_one_month", unit=PERCENT), " (",
                 value_num(results, f"results.descriptives.{mcq_arm(results, group)}.sd",
                           f"descriptives.group_{group.lower()}.paper_{group.lower()}.sd", unit=PERCENT), ")"),
            estimate_cell(results, base, prefix, theta_key="difference"),
        ))
    pooled, pooled_prefix = "partc_results.forgetting_pooled", "forgetting.pooled"
    elapsed = "survey3_results.quiz_elapsed"
    rows.append((
        cell("Both articles, equal weight"),
        cell(count_num(results, f"{pooled}.n_immediate", f"{pooled_prefix}.n_immediate", unit="forms")),
        cell(count_num(results, f"{pooled}.n_one_month", f"{pooled_prefix}.n_one_month", unit="people")),
        estimate_cell(results, pooled, pooled_prefix, theta_key="difference"),
    ))
    footnotes = [
        cell("n: Part 1 MCQ forms ",
             count_num(results, "partc_results.forgetting_unlinked.A.n_immediate", "forgetting.group_a.n_immediate",
                       unit="forms"), " (Paper A) and ",
             count_num(results, "partc_results.forgetting_unlinked.B.n_immediate", "forgetting.group_b.n_immediate",
                       unit="forms"), " (Paper B); Phase 3 responses ",
             count_num(results, "partc_results.forgetting_unlinked.A.n_one_month", "forgetting.group_a.n_one_month",
                       unit="people"), " and ",
             count_num(results, "partc_results.forgetting_unlinked.B.n_one_month", "forgetting.group_b.n_one_month",
                       unit="people"), "."),
        cell("Estimator: Welch t on the two independent groups of forms, 1 month minus immediate; df ",
             value_num(results, "partc_results.forgetting_unlinked.A.df", "forgetting.group_a.df", unit=COUNT),
             " and ", value_num(results, "partc_results.forgetting_unlinked.B.df", "forgetting.group_b.df",
                                unit=COUNT), "."),
        cell("Both articles, equal weight: the mean of the two article differences, each article weighted equally "
             "as in the primary estimand, with a Welch-Satterthwaite df of ",
             value_num(results, f"{pooled}.df", f"{pooled_prefix}.df", unit=COUNT),
             " over the four groups of forms."),
        cell(P_CONVENTION + " No P value is reported in this table; the 95% CIs carry the inference."),
        cell("Different respondents: this compares groups of forms, not people. The immediate score is the Part 1 "
             "MCQ form and the 1-month score is the MCQ-studied article in Phase 3."),
        cell("Median prior knowledge of the article (1-10) at Part 1: Paper A ",
             value_num(results, f"results.part1_context.{entry_index(results, 'results.part1_context', paper='A')}"
                                ".prior_knowledge_median", "part1.paper_a.prior_knowledge_median",
                       unit="rating points (1-10)"), ", Paper B ",
             value_num(results, f"results.part1_context.{entry_index(results, 'results.part1_context', paper='B')}"
                                ".prior_knowledge_median", "part1.paper_b.prior_knowledge_median",
                       unit="rating points (1-10)"), "."),
        cell("Part 1 MCQ form elapsed time (SAP B5): Microsoft Forms start to completion, which includes "
             "any time spent reading, median ",
             value_num(results, f"{elapsed}.minutes.median", "quiz_elapsed.median", unit="minutes"), " minutes (IQR ",
             value_num(results, f"{elapsed}.minutes.q1", "quiz_elapsed.q1", unit="minutes"), " to ",
             value_num(results, f"{elapsed}.minutes.q3", "quiz_elapsed.q3", unit="minutes"), ") over ",
             count_num(results, f"{elapsed}.n_forms", "quiz_elapsed.n_forms", unit="forms"), " analysed forms; ",
             count_num(results, f"{elapsed}.n_implausible", "quiz_elapsed.n_implausible", unit="forms"),
             " implausible times (completion before start or over 24 hours) are set missing."),
    ]
    return Table(8, "Immediate Part 1 scores and forgetting in the MCQ arm (unlinked)",
                 ("Article (group)", "Part 1 immediate: n; mean (SD), %", "1 month: n; mean (SD), %",
                  "1 month minus immediate, percentage points (95% CI)"),
                 tuple(rows), tuple(footnotes))


BUILDERS = (table1_flow, table2_characteristics, table3_primary, table4_sensitivity, table5_adoption,
            table6_usage, table7_items, table8_forgetting)


FEEDBACK_THEME_LABELS = {
    "engagement": "Engaged more deeply with the article",
    "prefers_writing": "Preferred writing questions to a quiz, or felt it tested understanding better",
    "teaching": "Would use it with trainees or in teaching",
    "unclear_expectations": "Expectations unclear; asked for examples or a tutorial",
    "grader_feedback": "Grader too strict or feedback too vague to act on",
    "effort_time": "More effort or time than a quiz",
    "task_design": "Proposed a change to the task",
}


def table9_feedback(results: Results) -> Table:
    base = "survey3_results.feedback"
    rows = [(cell(label), cell(count_num(results, f"{base}.themes.{key}", f"fb.theme.{key}", unit="people")))
            for key, label in FEEDBACK_THEME_LABELS.items()]
    rows.append((cell("Any positive theme"),
                 cell(count_num(results, f"{base}.n_any_positive", "fb.positive", unit="people"))))
    rows.append((cell("Any barrier or suggestion"),
                 cell(count_num(results, f"{base}.n_any_barrier", "fb.barrier", unit="people"))))
    footnotes = [cell("SAP Part G: ",
                      count_num(results, f"{base}.n_substantive", "fb.n_substantive", unit="people"), " of ",
                      count_num(results, f"{base}.n_population", "fb.n_population", unit="people"),
                      " analysed Survey 3 respondents left a substantive comment; a comment can carry more than "
                      "one theme. Counts only; no comment text is read.")]
    return Table(9, "Free-text comment themes", ("Theme", "Respondents"), tuple(rows), tuple(footnotes),
                 standing=cell("**", status_num(results), ".** ",
                               STANDING_STATUS_FINAL if is_final(text_at(results, "results.status"))
                               else STANDING_STATUS))


# ------------------------------------------------------- Table 10: perceived retention and usefulness (SAP v3.3)

# Part A's report labels for the three Phase 3 perception items (SAP section 9, D3), copied because the bundle may
# not import `report` (E1); a test pins the copy to the original.
PERCEIVED_LABELS = {
    "perceived_better": "Which format helped you retain the material better after one month",
    "useful_bloomer": "Usefulness rating, Bloomer",
    "useful_mcq": "Usefulness rating, traditional MCQ",
}
PERCEIVED_KEY = {"perceived_better": "better", "useful_bloomer": "useful_bloomer", "useful_mcq": "useful_mcq"}
# The form's own answer order for each item, copied from `answer_key.ALLOWED_VALUES` (a test pins the copy). The
# results files are written with sorted keys, so the order `scoring.perceived_retention` built does not survive the
# file; putting the rows back in the form's order is sorting, which E1 allows.
USEFULNESS_SCALE = ("Not useful at all", "Slightly useful", "Moderately useful", "Useful", "Very useful")
PERCEIVED_ORDER = {
    "perceived_better": ("Bloomer", "Tradtional MCQ", "Both equally", "Neither / not sure"),  # sic: the form's own
    "useful_bloomer": USEFULNESS_SCALE,
    "useful_mcq": USEFULNESS_SCALE,
}
NO_ANSWER = "No answer"


def perceived_answers(results: Results, item: str) -> list[str]:
    """The answers the analysis wrote for one item, in the form's order, as `scoring.perceived_retention` orders
    them: the form's answers, then any other answer alphabetically, then "No answer"."""
    order = PERCEIVED_ORDER[item]
    return sorted(get(results, f"results.perceived_retention.{item}"),
                  key=lambda answer: (answer == NO_ANSWER, order.index(answer) if answer in order else len(order),
                                      answer))


def table10_perceived(results: Results) -> Table:
    """D3 counts as Part A wrote them, one row per answer in the form's order. An answer nobody chose has no count
    in the results, so it has no row here either."""
    rows = [
        (cell(f"{label}: {display(answer)}"),
         cell(count_num(results, join_path("results", "perceived_retention", item, answer),
                        f"perceived.{PERCEIVED_KEY[item]}.{slug(display(answer))}", unit="people")))
        for item, label in PERCEIVED_LABELS.items() for answer in perceived_answers(results, item)
    ]
    footnotes = [
        cell("n: ", count_num(results, "results.flow.analysed", "flow.phase3.analysed", unit="people"),
             " analysed Phase 3 (1-month) responses. Each item is counted over all of them, a blank answer as No "
             "answer."),
        cell(NO_ESTIMATOR),
        cell(P_CONVENTION + " No P value is reported in this table."),
        cell("Self-reported answers on the Phase 3 (1-month) form (SAP section 9, D3). An answer no respondent "
             "chose is not listed. Counts only; no group comparison is made."),
    ]
    return Table(10, "Perceived retention and usefulness at 1 month (Phase 3 self-report)",
                 ("Item and answer", "Respondents"), tuple(rows), tuple(footnotes),
                 standing=cell("**", status_num(results), ".** ",
                               STANDING_STATUS_FINAL if is_final(text_at(results, "results.status"))
                               else STANDING_STATUS))


def has_feedback(results: Results) -> bool:
    """SAP v3.1 Part G: the comment-theme counts exist only when the private coding worksheet was configured."""
    return "feedback" in get(results, "survey3_results")


def always(results: Results) -> bool:
    return True


# The tables after the eight of SAP E2, in print order, as (number, builder, whether these results hold it). The
# change report rebuilds a previous tag's numbers from this same list, so a table added here is compared too.
LATER_TABLES = ((9, table9_feedback, has_feedback), (10, table10_perceived, always))


def build_tables(results: Results) -> list[Table]:
    tables = [build(results) for build in BUILDERS]
    tables += [build(results) for _, build, present in LATER_TABLES if present(results)]
    return tables


def render_all_markdown(tables: list[Table]) -> str:
    return "# Manuscript tables\n\n" + "\n".join(render_markdown(table) + "\n" for table in tables).rstrip("\n") + "\n"
