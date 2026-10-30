"""The four manuscript figures (SAP E3, design section 3).

Figures 2 and 3 are the analysed figures, copied byte for byte: the functions that drew them live in `report.py`
and `survey3_report.py`, which import the analysis modules, so re-rendering them here would breach the purity rule
and risk a manuscript figure that disagrees with the one the analysis published. Figures 1 and 4 are new and are
drawn from the results JSONs alone, with the project's colours and 600 dpi.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from bloomer_retention.bundle.format import (  # noqa: E402
    Cell,
    Num,
    cell,
    count_num,
    fmt_pct,
    pct_num,
    share_num,
    status_num,
    text,
    value_num,
)
from bloomer_retention.bundle.load import BundleError, Results, get  # noqa: E402
from bloomer_retention.bundle.tables import NPI_KEY, entry_index, has_npi_exclusion  # noqa: E402
from bloomer_retention.labels import WELCH_LABEL, display_label  # noqa: E402

# The project's figure palette, copied from `report.py` for the same reason the formatting helpers are.
MCQ_COLOR, BLOOMER_COLOR = "#00468B", "#D97848"
LABEL_COLOR, MUTED_COLOR, REF_COLOR = "#2B2B2B", "#6B7280", "#9CA3AF"
GROUP_COLORS = {"A": "#374151", "B": "#9CA3AF"}
DPI = 600
COPIED = {"fig2_retention": "fig_retention", "fig3_adoption": "fig_survey3"}
SUFFIXES = (".pdf", ".png")
STYLE = {
    "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": REF_COLOR,
    "axes.linewidth": 0.8, "pdf.fonttype": 42, "ps.fonttype": 42,
}
# The Start form and the Part 1 MCQ forms carry no shared identifier and are not linked, so the study cannot say
# how many signups failed to complete Part 1. Subtracting the two counts would assert a followed-people number
# the data does not support, so the figure states the gap instead of filling it (SAP C1, C6).
UNLINKED_NOTE = ("The signup and Part 1 counts come from unlinked forms, so the number of\n"
                 "signups that did not go on to complete Part 1 cannot be determined.")
# The same caveat for the arrows below: only the first was marked, so the later ones still read as a cohort
# flowing down the page. No two steps are linked, so no arrow here is a followed-people transition.
UNLINKED_LATER = ("Survey 3 and Phase 3 responses are not linked to each other either; the rates\n"
                  "above are counts of Part 1 forms that returned a later form, not of people.")


# SAP v3.2: the signup stage's NPI exclusion, broken to fit the exclusion box
NPI_LINE = "Not matched to a neurologist or neurology\ntrainee by NPI lookup"


@contextmanager
def styled():
    """The project's figure style, scoped to the drawing: `rcParams` is process-global, and a reporting stage
    that leaves it changed for whatever draws next is a reporting stage with a side effect."""
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # silence subsetting chatter for system Helvetica
    with plt.rc_context(STYLE):
        yield


def save(fig, out_stem: Path) -> list[Path]:
    paths = []
    for suffix in SUFFIXES:
        path = out_stem.with_suffix(suffix)
        fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15,
                    metadata={"CreationDate": None} if suffix == ".pdf" else None)
        paths.append(path)
    plt.close(fig)
    return paths


def copy_figure(outputs_dir: Path, source_stem: str, out_stem: Path) -> list[Path]:
    """Copy the analysed figure under its manuscript name, byte for byte (design section 2)."""
    paths = []
    for suffix in SUFFIXES:
        source = Path(outputs_dir) / f"{source_stem}{suffix}"
        if not source.is_file():
            raise BundleError(f"{source}: no such figure; run `make analyze` before `make report`")
        target = out_stem.with_suffix(suffix)
        target.write_bytes(source.read_bytes())
        paths.append(target)
    return paths


def _box(ax, y: float, x: float, width: float, height: float, lines: list[str], *, color: str = LABEL_COLOR,
         face: str = "white", size: float = 8.0) -> None:
    ax.add_patch(mpatches.FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.006,rounding_size=0.02",
                                         linewidth=0.9, edgecolor=color, facecolor=face))
    ax.text(x + width / 2, y + height / 2, "\n".join(lines), ha="center", va="center", fontsize=size,
            color=LABEL_COLOR)


def _arrow(ax, x: float, top: float, bottom: float) -> None:
    ax.annotate("", xy=(x, bottom), xytext=(x, top),
                arrowprops={"arrowstyle": "-|>", "color": MUTED_COLOR, "linewidth": 0.9})


def _return_note(results: Results, key: str, label: str) -> str:
    base = f"partc_results.flow.returns.{key}.by_group"
    return (f"Returned, {label}: group A {fmt_pct(get(results, f'{base}.A.pct'))}, "
            f"group B {fmt_pct(get(results, f'{base}.B.pct'))}")


def fig1_flow(results: Results, out_stem: Path) -> list[Path]:
    """CONSORT-style flow: the four stages down the left, what was excluded at each stage on the right.

    The third element of a stage is what is written in the gap **below** its box, which is the arrow leaving it:
    in CONSORT grammar an annotation beside an arrow describes that transition. Both return rates have the Part 1
    MCQ forms as their denominator, so both belong on the arrow out of Part 1; drawn above the Phase 3 box, the
    Part 1 to Phase 3 rate invites a reader to apply it to the Survey 3 count just above it.
    """
    paper_a = entry_index(results, "results.part1_context", paper="A")
    paper_b = entry_index(results, "results.part1_context", paper="B")
    stages = [
        (["Signed up (Start form)", f"n = {get(results, 'partc_results.flow.start.analysed')}"],
         [f"De-identified responses {get(results, 'partc_results.flow.start.deidentified')}",
          f"Pilot rows excluded {get(results, 'partc_results.flow.start.excluded_pilot')}",
          "Signed up after the freeze date "
          f"{get(results, 'partc_results.flow.start.excluded_after_freeze')}",
          *([f"{NPI_LINE} {get(results, f'partc_results.flow.start.{NPI_KEY}')}"]
            if has_npi_exclusion(results) else [])],
         [UNLINKED_NOTE]),
        (["Completed Part 1 (MCQ form)",
          f"n = {get(results, 'partc_results.flow.counts_by_group.part1_mcq.total')} "
          f"(A {get(results, 'partc_results.flow.counts_by_group.part1_mcq.A')}, "
          f"B {get(results, 'partc_results.flow.counts_by_group.part1_mcq.B')})"],
         [f"Pilot rows excluded, Paper A {get(results, f'results.part1_context.{paper_a}.n_pilot_excluded')}, "
          f"Paper B {get(results, f'results.part1_context.{paper_b}.n_pilot_excluded')}",
          "Started after the freeze date, Paper A "
          f"{get(results, f'results.part1_context.{paper_a}.n_after_freeze_excluded')}, Paper B "
          f"{get(results, f'results.part1_context.{paper_b}.n_after_freeze_excluded')}"],
         [_return_note(results, "survey3", "Part 1 to Survey 3"),
          _return_note(results, "phase3", "Part 1 to Phase 3")]),
        (["Completed Survey 3",
          f"n = {get(results, 'survey3_results.flow.analysed')} "
          f"(A {get(results, 'survey3_results.flow.analysed_group_A')}, "
          f"B {get(results, 'survey3_results.flow.analysed_group_B')})"],
         [f"De-identified responses {get(results, 'survey3_results.flow.survey3_deidentified')}",
          f"Pilot rows excluded {get(results, 'survey3_results.flow.excluded_pilot')}",
          f"Blank submissions excluded {get(results, 'survey3_results.flow.excluded_blank')}",
          f"Completed after the freeze date {get(results, 'survey3_results.flow.excluded_after_freeze')}",
          f"Duplicates removed at ingest {get(results, 'survey3_results.flow.duplicates_removed_at_ingest')}",
          "Without a Bloomer paper "
          f"{get(results, 'survey3_results.flow.analysed_without_bloomer_paper')}"],
         [UNLINKED_LATER]),
        (["Completed 1 month (Phase 3), analysed",
          f"n = {get(results, 'results.flow.analysed')} "
          f"(A {get(results, 'results.flow.analysed_group_A')}, "
          f"B {get(results, 'results.flow.analysed_group_B')})"],
         [f"De-identified responses {get(results, 'results.flow.phase3_deidentified')}",
          f"Duplicates removed at ingest {get(results, 'results.flow.duplicates_removed_at_ingest')}",
          f"Completed after the freeze date {get(results, 'results.flow.excluded_after_freeze')}",
          f"Without a group {get(results, 'results.flow.excluded_missing_group')}"],
         []),
    ]
    with styled():
        fig, ax = plt.subplots(figsize=(7.2, 6.4))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        height, gap = 0.15, 0.095
        top = 0.98
        for rank, (main, excluded, notes) in enumerate(stages):
            y = top - rank * (height + gap) - height
            _box(ax, y, 0.02, 0.48, height, main)
            _box(ax, y + 0.015, 0.56, 0.42, height - 0.03, excluded, color=REF_COLOR, face="#F6F6F6", size=6.8)
            ax.annotate("", xy=(0.56, y + height / 2), xytext=(0.50, y + height / 2),
                        arrowprops={"arrowstyle": "-|>", "color": REF_COLOR, "linewidth": 0.8})
            if rank:
                _arrow(ax, 0.26, y + height + gap, y + height)
            for note_rank, note in enumerate(notes):
                ax.text(0.28, y - gap * (note_rank + 1) / (len(notes) + 1), note,
                        ha="left", va="center", fontsize=6.8, color=MUTED_COLOR)
        return save(fig, out_stem)


def immediate_mean(results: Results, paper: str) -> Num:
    """The Part 1 immediate mean panel b annotates, keyed like every other number the manuscript prints.

    Table 8 prints the same quantity from Part A's `part1_context`; `tables.check_cross_file_counts` refuses to
    render if the two files disagree about it.
    """
    return pct_num(results, f"partc_results.forgetting_unlinked.{paper}.mean_immediate",
                   f"forgetting.group_{paper.lower()}.mean_immediate")


def fig4_crossphase(results: Results, out_stem: Path) -> list[Path]:
    """a: return rates by group; b: unlinked forgetting in the MCQ arm, 1 month minus immediate with 95% CI."""
    with styled():
        fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.5, 3.6), gridspec_kw={"width_ratios": [1, 1.2]})

        stages = (("survey3", "Part 1 to\nSurvey 3"), ("phase3", "Part 1 to\nPhase 3"))
        for offset, group in ((-0.18, "A"), (0.18, "B")):
            heights, labels = [], []
            for key, _ in stages:
                base = f"partc_results.flow.returns.{key}.by_group.{group}"
                heights.append(float(get(results, f"{base}.pct")))
                labels.append(f"{get(results, f'{base}.n_returned')}/{get(results, f'{base}.n_part1')}")
            positions = [rank + offset for rank in range(len(stages))]
            bars = ax_a.bar(positions, heights, width=0.34, color=GROUP_COLORS[group], label=f"Group {group}")
            for bar, height, label in zip(bars, heights, labels):
                ax_a.text(bar.get_x() + bar.get_width() / 2, height, label, ha="center", va="bottom", fontsize=7.5,
                          color=LABEL_COLOR)
        ax_a.set_xticks(range(len(stages)), [label for _, label in stages])
        ax_a.set_ylim(0, 105)
        ax_a.set_ylabel("Forms returned (%)")
        ax_a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False, fontsize=8)

        papers, tick_labels = ("A", "B"), []
        for rank, paper in enumerate(papers):
            base = f"partc_results.forgetting_unlinked.{paper}"
            # each entry names its own paper and group; reading them off the loop letter would keep the label
            # right only for as long as the analysis layer keys this block by group
            tick_labels.append(f"Paper {get(results, f'{base}.paper')} (group {get(results, f'{base}.group')})")
            difference = float(get(results, f"{base}.difference"))
            low, high = float(get(results, f"{base}.ci_low")), float(get(results, f"{base}.ci_high"))
            y = len(papers) - 1 - rank
            ax_b.errorbar(difference, y, xerr=[[difference - low], [high - difference]], fmt="o", color=MCQ_COLOR,
                          ecolor=MUTED_COLOR, elinewidth=1.2, capsize=2.5, markersize=5)
            ax_b.text(difference, y + 0.18,
                      f"immediate {immediate_mean(results, paper).formatted} "
                      f"(n = {get(results, f'{base}.n_immediate')})  ->  "
                      f"1 month {fmt_pct(get(results, f'{base}.mean_one_month'))} "
                      f"(n = {get(results, f'{base}.n_one_month')})",
                      ha="center", va="bottom", fontsize=7.0, color=MUTED_COLOR)
        ax_b.axvline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
        ax_b.set_yticks(range(len(papers)), list(reversed(tick_labels)))
        ax_b.set_ylim(-0.6, len(papers) - 0.2)
        ax_b.spines["left"].set_visible(False)
        ax_b.tick_params(axis="y", length=0)
        ax_b.set_xlabel("1 month minus immediate, percentage points (95% CI)")

        for ax, letter in ((ax_a, "a"), (ax_b, "b")):
            ax.text(-0.14, 1.05, letter, transform=ax.transAxes, fontsize=14, fontweight="bold", color=LABEL_COLOR)
        fig.tight_layout()
        return save(fig, out_stem)


# --- captions: the numbers in them are keyed like the table cells, so the index covers them too ---

def captions(results: Results) -> list[tuple[str, Cell]]:
    head = "results.primary.headline"
    # Every caption carries the run's status: a figure travels further from its supplement than a table does,
    # and nothing else on the page says the retention sample is still accruing.
    status = cell(" Status: ", status_num(results), ".")
    # panel b plots every sensitivity row; the Welch row (SAP v2.6) is explained only when it is there
    welch_note = (cell(f" Panel b's {display_label(WELCH_LABEL)} row does not assume equal variances in the two "
                       "sequence groups.")
                  if any(entry.get("label") == WELCH_LABEL for entry in get(results, "results.sensitivity")) else ())
    return [
        ("fig1_flow", cell(
            "Figure 1. Participant flow. ",
            count_num(results, "partc_results.flow.start.analysed", "flow.signup.analysed", unit="people"),
            " signups; ", count_num(results, "partc_results.flow.counts_by_group.part1_mcq.A", "flow.part1.group_a",
                                    unit="forms"),
            " and ", count_num(results, "partc_results.flow.counts_by_group.part1_mcq.B", "flow.part1.group_b",
                               unit="forms"),
            " Part 1 MCQ forms in groups A and B; ",
            count_num(results, "survey3_results.flow.analysed", "flow.survey3.analysed", unit="people"),
            " Survey 3 responses; ", count_num(results, "results.flow.analysed", "flow.phase3.analysed",
                                               unit="people"),
            " Phase 3 responses analysed at 1 month. Every count is one row per form or response. The steps are "
            "not linked to each other, so no count here follows the same people from one step to the next, and "
            "duplicate submissions could be checked only for the rows that gave a contact email.",
            " NPI, National Provider Identifier." if has_npi_exclusion(results) else "", status)),
        ("fig2_retention", cell(
            "Figure 2. Retention at 1 month, n = ",
            count_num(results, "results.flow.analysed", "flow.phase3.analysed", unit="people"),
            ". a, paired 1-month scores per participant; b, the headline estimate "
            "and the percentage-point sensitivity estimates with 95% CIs. Headline ",
            value_num(results, f"{head}.theta", "primary.theta"), " (95% CI, ",
            value_num(results, f"{head}.ci_low", "primary.ci_low"), " to ",
            value_num(results, f"{head}.ci_high", "primary.ci_high"),
            ") percentage points. Copied byte for byte from the analysed figure `fig_retention`.",
            *welch_note, status)),
        ("fig3_adoption", cell(
            "Figure 3. Adoption and satisfaction (Survey 3), n = ",
            count_num(results, "survey3_results.flow.analysed", "flow.survey3.analysed", unit="people"),
            ". a, answer distributions for Q25 (prove competency) "
            "and Q22 (best for comprehension); b, diverging difficulty ratings for Q23 and Q24. Among decided "
            "respondents, ",
            share_num(results, "survey3_results.adoption.decided.proportion", "adoption.decided.pct"),
            " chose Bloomer. Copied byte for byte from the analysed figure `fig_survey3`.", status)),
        ("fig4_crossphase", cell(
            "Figure 4. Cross-phase return rates and unlinked forgetting. a, the share of Part 1 MCQ forms that "
            "returned Survey 3 and Phase 3, by group; b, the 1-month score on the MCQ-studied article minus the "
            "immediate Part 1 score, with Welch 95% CIs. Paper A ",
            value_num(results, "partc_results.forgetting_unlinked.A.difference", "forgetting.group_a.difference"),
            " and Paper B ",
            value_num(results, "partc_results.forgetting_unlinked.B.difference", "forgetting.group_b.difference"),
            " percentage points. Immediate Part 1 means ", immediate_mean(results, "A"), " (Paper A) and ",
            immediate_mean(results, "B"), " (Paper B). Different respondents: this compares groups of forms, "
            "not people.", status)),
    ]


def render_captions(results: Results) -> str:
    lines = ["# Manuscript figure captions", ""]
    for _, caption in captions(results):
        lines += [text(caption), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def build_figures(results: Results, outputs_dir: Path, manuscript_dir: Path) -> list[Path]:
    """Every figure, in manuscript order: two drawn here and two copied from the analysed outputs."""
    written = fig1_flow(results, manuscript_dir / "fig1_flow")
    for name, source in COPIED.items():
        written += copy_figure(outputs_dir, source, manuscript_dir / name)
    written += fig4_crossphase(results, manuscript_dir / "fig4_crossphase")
    return written
