"""Survey 3 outputs: survey3_results.json, survey3_report.md and fig_survey3.{pdf,png} (SAP Part B, B8)."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from bloomer_retention.report import (  # noqa: E402
    BLOOMER_COLOR,
    LABEL_COLOR,
    MCQ_COLOR,
    REF_COLOR,
    SAP_VERSION,
    _clean,
    _num,
    _row,
    fmt_p,
    input_line,
)
from bloomer_retention.survey3_forms import OPTIONS, QUESTIONS  # noqa: E402
from bloomer_retention.labels import run_status  # noqa: E402

DISPLAY = {"No opinon": "No opinion", "no opinon": "no opinion"}  # the form's typo, corrected in the report only
TABLE1_LABELS = {"gender": "Gender", "region": "US region", "role": "Role", "subspecialty": "Subspecialty",
                 "setting": "Practice setting", "ai_use": "Prior AI use", "cme_hours": "CME hours per week",
                 "cme_format": "Most common CME format"}
FACTOR_LABELS = {"role": "Role", "ai_use": "Prior AI use", "cme_hours": "CME hours per week", "group": "Group"}
DEVIATIONS = (
    "Adoption: the form's Q25 is not a forced choice (it also offers Unsure and No opinion), so the co-primary "
    "proportion uses respondents who chose Bloomer or the quiz; all-respondent results are reported alongside.",
    "Mastery rate: the form does not record whether the 'Article Mastery Complete' screen was reached, so a "
    "completion proxy (time and attempts entered for all three questions) is reported instead.",
    "Years in practice mixes post-training years (attendings) with PGY year (trainees), so it is summarised "
    "separately by role.",
    "Survey 3 carries no participant identifier, so it cannot be linked to the Part 1 MCQ scores or to 1-month "
    "retention; subgroup analyses of retention are not possible.",
)
BIASES = (
    "The MCQ always preceded Bloomer, so preference and difficulty ratings may partly reflect order or recency.",
    "All outcomes are self-reported; time and attempts were typed from memory or the Bloomer summary screen.",
    "About {n} respondents: proportions and subgroup comparisons are imprecise, and subgroups are exploratory and "
    "unadjusted.",
    "Pooled answer counts for several Survey 3 questions, including Q25, were seen at the 2026-09-14 review before "
    "the analysis plan was agreed, so the adoption result was effectively known when its denominator (decided "
    "respondents) was chosen; one development run of this analysis on the real export was also viewed before SAP "
    "Part B was committed (SAP section B9).",
    "Free-text times and attempts that match no parsing rule are missing (counts reported), and a two-decimal time "
    "typed as text, such as 1.30, is read as minutes:seconds.",
    "Survey 3 respondents are the Part 1 participants who returned the survey, so non-response may bias every "
    "estimate.",
    "Group is taken from the self-reported Bloomer paper.",
    "Duplicate submissions can be checked only for responses that gave an invite email; the others are counted, "
    "not checked (see Population).",
)
DIFFICULTY_COLORS = ("#00468B", "#7A9CC6", "#D1D5DB", "#F0B48C", "#D97848")  # not at all ... very difficult
CHOICE_COLORS = {"Bloomer-AI": BLOOMER_COLOR, "Bloomer": BLOOMER_COLOR, "A 5-question quiz": MCQ_COLOR,
                 "The 5-question quiz": MCQ_COLOR, "Unsure": "#9CA3AF", "They were about the same": "#9CA3AF",
                 "Neither were very good": "#6B7280", "No opinon": "#D1D5DB"}


def build_survey3_results(*, freeze_date: date, flow: dict, adoption: dict, comprehension: dict, difficulty: dict,
                          usage: dict, quiz_elapsed: dict, table1: dict, subgroups: dict, prior_knowledge: dict,
                          prov: dict, status: str = "interim", feedback: dict | None = None) -> dict:
    return _clean({
        "status": run_status(status, freeze_date),
        "sap": f"{SAP_VERSION} (Part B)",
        "flow": flow,
        "adoption": adoption,
        "comprehension": comprehension,
        "difficulty": difficulty,
        "usage": usage,
        "quiz_elapsed": quiz_elapsed,
        "table1": table1,
        "subgroups": subgroups,
        "prior_knowledge_context": prior_knowledge,
        **({"feedback": feedback} if feedback is not None else {}),
        "deviations": DEVIATIONS,
        "known_biases": tuple(b.format(n=flow["analysed"]) for b in BIASES),
        "provenance": prov,
    })


def _pct(part: float | None, digits: int = 1) -> str:
    return "-" if part is None else f"{100 * part:.{digits}f}%"


def _percent(value: float | None, digits: int = 1) -> str:
    """A value the analysis already wrote in percent (Table 1 cells read `table1.categorical_pct`)."""
    return "-" if value is None else f"{value:.{digits}f}%"


def _median_iqr(summary: dict, digits: int = 1) -> str:
    if not summary["n"]:
        return "- [n = 0]"
    return (f"{_num(summary['median'], digits)} ({_num(summary['q1'], digits)} to {_num(summary['q3'], digits)}) "
            f"[n = {summary['n']}]")


def _choice_lines(outcome: dict, question: str) -> list[str]:
    decided, everyone = outcome["decided"], outcome["all_respondents"]
    counts = "; ".join(f"{DISPLAY.get(k, k)} {v}" for k, v in outcome["counts"].items())
    lines = [question, ""]
    if decided["n_decided"]:
        lines.append(
            f"- **Chose Bloomer, among respondents who chose Bloomer or the quiz:** {_pct(decided['proportion'])} "
            f"({decided['n_bloomer']} of {decided['n_decided']}; 95% CI, {_pct(decided['ci_low'])} to "
            f"{_pct(decided['ci_high'])}); exact binomial test against 50%, {fmt_p(decided['p_value'])}; "
            f"difference from 50%: {100 * decided['effect_vs_half']:.1f} percentage points."
        )
    else:
        lines.append("- **Chose Bloomer, among respondents who chose Bloomer or the quiz:** no decided respondents.")
    lines.append(f"- Answers: {counts}.")
    if everyone["n_answered"]:
        lines.append(f"- Sensitivity, all respondents who answered: {_pct(everyone['proportion'])} ({everyone['n_bloomer']} of "
                     f"{everyone['n_answered']}; 95% CI, {_pct(everyone['ci_low'])} to {_pct(everyone['ci_high'])}).")
    for group, group_counts in outcome["by_group"].items():
        lines.append(f"- Group {group}: " + "; ".join(f"{DISPLAY.get(k, k)} {v}" for k, v in group_counts.items()) + ".")
    return lines


def render_survey3_report(results: dict) -> str:
    flow, prov = results["flow"], results["provenance"]
    lines = [
        "# Bloomer vs MCQ: Survey 3 (adoption, satisfaction, usage)",
        "",
        f"**{results['status']}.** Pre-specified in `{results['sap']}`. Code version `{prov['code_commit']}`.",
        "",
        "## Co-primary: adoption",
        "",
        *_choice_lines(results["adoption"], "For CME competency with articles, would you rather prove competency "
                                            "with Bloomer or a 5-question quiz? (Q25)"),
        "",
        "## Secondary: best for checking comprehension",
        "",
        *_choice_lines(results["comprehension"], "Which was best for checking your comprehension for CME? (Q22)"),
        "",
        "## Secondary: difficulty",
        "",
        "Scored 1 = not at all difficult to 5 = very difficult; no opinion is missing.",
        "",
        _row(["Item", "Median (IQR) [n]", "A little or very difficult", "No opinion"]), _row(["---"] * 4),
    ]
    diff = results["difficulty"]
    for label, key in (("Traditional 5-question quiz (Q23)", "quiz"), ("Bloomer (Q24)", "bloomer")):
        item = diff[key]
        pct = "-" if item["pct_difficult"] is None else f"{item['pct_difficult']:.1f}%"
        lines.append(_row([label, _median_iqr(item), pct, "not offered" if key == "bloomer" else item["n_no_opinion"]]))
    paired = diff["paired"]
    median_difference = _num(paired["median_difference"])
    lines += ["", f"Paired comparison: {paired['n_pairs']} respondents rated both ({paired['n_nonzero']} with a "
                  f"non-zero difference); median difference, Bloomer minus quiz, {median_difference} points; "
                  f"Wilcoxon signed-rank {fmt_p(paired['p_value'])}"
                  + (f" ({paired['method']})." if paired.get("method") else ".")]

    use = results["usage"]
    lines += ["", "## Bloomer usage", "",
              _row(["Question", "Attempts, median (IQR) [n]", "More than 1 attempt", "Minutes, median (IQR) [n]",
                    "Time not parsed / blank", "Attempts not parsed / blank"]),
              _row(["---"] * 6)]
    for q in QUESTIONS:
        entry = use["per_question"][q]
        more = entry["attempts"]["pct_more_than_one"]
        lines.append(_row([entry["label"], _median_iqr(entry["attempts"]), "-" if more is None else f"{more:.1f}%",
                           _median_iqr(entry["minutes"]),
                           f"{entry['time_status']['unparsed']} / {entry['time_status']['blank']}",
                           f"{entry['attempts_status']['unparsed']} / {entry['attempts_status']['blank']}"]))
    proxy = use["completion_proxy"]
    lines += [
        "",
        f"Per person, over respondents with all three values parsed: total attempts {_median_iqr(use['total_attempts'])}; "
        f"total minutes {_median_iqr(use['total_minutes'])}.",
        "",
        f"Completion proxy: {proxy['n_complete']} of {proxy['n']} ({_num(proxy['pct'])}%) entered time and attempts "
        "for all three questions. This is not the mastery rate, which the form does not record.",
    ]

    lines += [
        "", "## Population", "",
        f"Survey 3 flow: de-identified responses {flow['survey3_deidentified']}; pilot rows excluded "
        f"{flow['excluded_pilot']}; blank submissions excluded {flow['excluded_blank']}; completed after the freeze "
        f"date {flow['excluded_after_freeze']}; analysed {flow['analysed']} (group A {flow['analysed_group_A']}, "
        f"group B {flow['analysed_group_B']}, without a Bloomer paper {flow['analysed_without_bloomer_paper']}). "
        f"Duplicate submissions removed at ingest {flow['duplicates_removed_at_ingest']}; the duplicate check covers "
        f"only rows with an invite email, and {flow['rows_without_contact_email']} rows without one were not "
        "checked. Free-text answers recoded to Other at ingest: "
        + ", ".join(f"{column} {n}" for column, n in flow["other_recoded"].items()) + ".",
        "Group A did the MCQ on Paper A and Bloomer on Paper B; group B the reverse.",
    ]

    t1 = results["table1"]
    groups = ("overall", "A", "B")
    lines += ["", "## Table 1", "", "Survey 3 respondents (not the Phase 3 retention sample).", "",
              _row(["Characteristic", "Overall", "Group A", "Group B"]), _row(["---"] * 4),
              _row(["Respondents", *[t1["n"][g] for g in groups]]),
              _row(["Age, median (IQR) [n]", *[_median_iqr(t1["numeric"]["age"][g]) for g in groups]])]
    for column, label in TABLE1_LABELS.items():
        for option in (*OPTIONS[column], "blank"):
            counts, shares = t1["categorical"][column], t1["categorical_pct"][column]
            if not any(counts[g][option] for g in groups):
                continue
            # the percentage and its denominator come from the analysis layer, so this report and the manuscript
            # bundle cannot arrive at different numbers for the same cell (SAP B6)
            cells = [f"{counts[g][option]} ({_percent(shares[g]['levels'][option])})" for g in groups]
            lines.append(_row([f"{label}: {DISPLAY.get(option, option)}", *cells]))
    for key, label in (("years_attending", "Years in practice, attendings, median (IQR) [n]"),
                       ("years_trainee", "PGY year, trainees, median (IQR) [n]"),
                       ("prior_knowledge", "Prior knowledge of the Bloomer article (1-10), median (IQR) [n]")):
        lines.append(_row([label, *[_median_iqr(t1["numeric"][key][g]) for g in groups]]))

    sub = results["subgroups"]
    lines += ["", "## Exploratory subgroups: adoption among decided respondents", "",
              "Fisher's exact test on each 2x2 table; unadjusted for multiple comparisons.", "",
              _row(["Factor", "Level", "Bloomer", "Quiz", "% Bloomer", "Odds ratio", "P"]), _row(["---"] * 7)]
    for factor in sub["factors"]:
        for rank, level in enumerate(factor["levels"]):
            pct = "-" if level["pct_bloomer"] is None else f"{level['pct_bloomer']:.1f}%"
            odds = _num(factor["odds_ratio"], 2) if rank == 0 else ""
            p_text = fmt_p(factor["p_value"]) if rank == 0 else ""
            lines.append(_row([FACTOR_LABELS.get(factor["factor"], factor["factor"]) if rank == 0 else "",
                               level["level"], level["n_bloomer"],
                               level["n_quiz"], pct, odds, p_text]))
    shown = [f"{option} (Bloomer {c['n_bloomer']}, quiz {c['n_quiz']})" for option, c in sub["subspecialty"].items()
             if c["n_bloomer"] or c["n_quiz"]]
    lines += ["", "Subspecialty, counts only: " + ("; ".join(shown) if shown else "none") + ".",
              "An odds ratio shown as - could not be estimated (a zero cell or an empty level)."]

    lines += ["", "## Prior-knowledge context (unlinked; descriptive)", "",
              _row(["Paper", "Bloomer-article rating (Survey 3)", "MCQ-article rating (Part 1 MCQ forms)"]),
              _row(["---"] * 3)]
    for paper, entry in results["prior_knowledge_context"].items():
        lines.append(_row([paper, _median_iqr(entry["bloomer_article_rating"]),
                           _median_iqr(entry["mcq_article_rating"])]))

    if "feedback" in results:  # SAP v3.1 Part G: counts only
        fb = results["feedback"]
        lines += ["", "### Participant comments (SAP Part G)", "",
                  f"{fb['n_substantive']} of {fb['n_population']} analysed respondents left a substantive comment; "
                  "a comment can carry more than one theme. Counts only; comment text is never read.", "",
                  *[f"- {theme}: {n}" for theme, n in fb["themes"].items()],
                  f"- any positive theme: {fb['n_any_positive']}", f"- any barrier or suggestion: {fb['n_any_barrier']}"]
    lines += ["", "## Method notes", "", *[f"- {d}" for d in results["deviations"]],
              "", "## Known biases", "", *[f"- {b}" for b in results["known_biases"]],
              "", "## Reproducibility", "",
              f"- Python {prov['python']}; " + ", ".join(f"{k} {v}" for k, v in prov["packages"].items()),
              f"- Config `{prov['config']}`; figure `fig_survey3.pdf` / `.png`"]
    if "survey3" in prov["inputs"]:
        lines.append(input_line("survey3", prov["inputs"]["survey3"]))
    return "\n".join(lines) + "\n"


def _stacked_row(ax, y: float, counts: dict[str, int], colors: dict[str, str]) -> None:
    total = sum(counts.values())
    left = 0.0
    for option, n in counts.items():
        if not n:
            continue
        width = 100 * n / total
        ax.barh(y, width, left=left, color=colors[option], edgecolor="white", linewidth=0.8, height=0.55)
        if width >= 8:
            text_color = "white" if colors[option] in (MCQ_COLOR, BLOOMER_COLOR, "#6B7280") else LABEL_COLOR
            ax.text(left + width / 2, y, str(n), ha="center", va="center", fontsize=8, color=text_color)
        left += width


def plot_survey3(pop: pd.DataFrame, out_stem: Path) -> list[Path]:
    """a: answer distributions for Q25 (preference) and Q22 (comprehension); b: diverging difficulty ratings."""
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": REF_COLOR,
        "axes.linewidth": 0.8, "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.5, 3.6))

    rows = (("preference", "Prove competency with (Q25)"), ("best_comprehension", "Best for comprehension (Q22)"))
    for y, (column, _) in zip((1, 0), rows):
        _stacked_row(ax_a, y, {o: int((pop[column] == o).sum()) for o in OPTIONS[column]}, CHOICE_COLORS)
    ax_a.set_yticks([1, 0], [label for _, label in rows])
    ax_a.set_xlim(0, 100)
    ax_a.set_xlabel("Respondents who answered (%)")
    ax_a.tick_params(axis="y", length=0)
    ax_a.spines["left"].set_visible(False)
    ax_a.legend(handles=[mpatches.Patch(color=BLOOMER_COLOR, label="Bloomer"),
                         mpatches.Patch(color=MCQ_COLOR, label="Quiz"),
                         mpatches.Patch(color="#9CA3AF", label="Unsure / about the same"),
                         mpatches.Patch(color="#6B7280", label="Neither good"),
                         mpatches.Patch(color="#D1D5DB", label="No opinion")],
                loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, frameon=False, fontsize=8)

    scale = OPTIONS["bloomer_difficulty"]  # not at all ... very difficult
    for y, column in ((1, "quiz_difficulty"), (0, "bloomer_difficulty")):
        counts = [int((pop[column] == option).sum()) for option in scale]
        total = sum(counts)
        if not total:
            continue
        shares = [100 * c / total for c in counts]
        left = -(shares[0] + shares[1] + shares[2] / 2)  # centre the neutral category on zero
        for share, color in zip(shares, DIFFICULTY_COLORS):
            if share:
                ax_b.barh(y, share, left=left, color=color, edgecolor="white", linewidth=0.8, height=0.55)
            left += share
    ax_b.axvline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_b.set_yticks([1, 0], ["Traditional quiz (Q23)", "Bloomer (Q24)"])
    ax_b.set_xlim(-100, 100)
    ax_b.set_xticks([-100, -50, 0, 50, 100], ["100", "50", "0", "50", "100"])
    ax_b.set_xlabel("Respondents (%): easier  |  harder")
    ax_b.tick_params(axis="y", length=0)
    ax_b.spines["left"].set_visible(False)
    ax_b.legend(handles=[mpatches.Patch(color=c, label=label) for c, label in
                         zip(DIFFICULTY_COLORS, ("Not at all", "Not very", "Neutral", "A little", "Very difficult"))],
                loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, frameon=False, fontsize=8)

    for ax, letter in ((ax_a, "a"), (ax_b, "b")):
        ax.text(-0.12, 1.05, letter, transform=ax.transAxes, fontsize=14, fontweight="bold", color=LABEL_COLOR)
    fig.tight_layout()
    paths = []
    for suffix in (".pdf", ".png"):
        path = out_stem.with_suffix(suffix)
        fig.savefig(path, dpi=600, bbox_inches="tight", pad_inches=0.15,
                    metadata={"CreationDate": None} if suffix == ".pdf" else None)
        paths.append(path)
    plt.close(fig)
    return paths
