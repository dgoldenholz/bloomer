"""Stage 2c: results.json, report.md and the retention figure."""
from __future__ import annotations

import json
import logging
import math
import platform
import subprocess
from dataclasses import asdict
from datetime import date
from importlib import metadata
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.lines as mlines  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bloomer_retention.answer_key import DATE_LIMITED_ITEMS  # noqa: E402
from bloomer_retention.crossover import PP, Estimate  # noqa: E402
from bloomer_retention.labels import display_label, run_status  # noqa: E402

PACKAGES = ("numpy", "pandas", "scipy", "statsmodels", "matplotlib", "openpyxl")
SAP_VERSION = "SAP.md v3.3"
# Paths whose last commit identifies the code version; outputs/ and data/ commits do not change it.
TRACKED_PATHS = ("src", "tests", "config", "SAP.md", "pyproject.toml", "uv.lock", "Makefile")
PERCEIVED_LABELS = {
    "perceived_better": "Which format helped you retain the material better after one month",
    "useful_bloomer": "Usefulness rating, Bloomer",
    "useful_mcq": "Usefulness rating, traditional MCQ",
}
DISPLAY_OPTIONS = {"Tradtional MCQ": "Traditional MCQ"}  # the form's typo, corrected in the report only
DEVIATIONS = (
    "Prior-knowledge covariate omitted: ratings exist only in the anonymous Part 1 forms and cannot be linked to Phase 3.",
    "Item A4 is scored only for responses dated on or after {a4_offered_from}, because its keyed answer was not "
    "offered until the forms were corrected on 2026-09-14; scores are percent of each response's valid items "
    "(Paper A 5 items from that date and 4 before it, Paper B 5 items). S5 gives the Methods-as-written 5-point scale.",
    "Headline inference uses t with n - 2 df; the mixed model's Wald z interval is reported alongside.",
)
TESTING_EFFECT_BIAS = (
    "MCQ-studied items were answered once in Part 1; Bloomer-studied items were first seen at 1 month. "
    "This testing effect biases the contrast toward MCQ."
)
GROUP_BIAS = (
    "Phase 3 group sizes are unbalanced against similar Part 1 form counts (Part 1 MCQ forms: group A {part1_a}, "
    "group B {part1_b}; Phase 3 analysed: group A {phase3_a}, group B {phase3_b}), so either return rates differ "
    "by group or some participants misreported their group. A misreported group flips the sign of that "
    "participant's difference and pulls theta toward zero. Group cannot be verified against allocation records "
    "in this analysis."
)
OTHER_BIASES = (
    "Interim: Phase 3 is still accruing and estimates will change.",
    "The retention interval cannot be computed per participant (no link to Part 1 dates).",
)
# SAP v3.0: a final run closes data collection, and Part F supplies the follow-up records the interim lacked
FINAL_BIASES = (
    "Final: data collection is closed, and the retention sample is smaller than the 50 planned.",
    "The retention interval comes from the study team's records of Part 1 and of the retention link (SAP Part F, "
    "version 3.0), not from linked study forms.",
)
GROUP_RECORDS_FINAL = ("Group cannot be verified against allocation records in this analysis; Part F compares it "
                       "with the study team's assignment emails.")
MCQ_COLOR, BLOOMER_COLOR = "#00468B", "#D97848"
LABEL_COLOR, MUTED_COLOR, REF_COLOR = "#2B2B2B", "#6B7280", "#9CA3AF"


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _estimable(estimate: dict) -> bool:
    return estimate["estimator"] != "not estimable"


def fmt_p(p: float | None) -> str:
    """JAMA style: P < .001; 3 decimals below .0095; P = .01 from .0095 to .01; 2 decimals from .01, except
    3 decimals from .045 to .05 so a value below .05 never prints as .05; P > .99 at the top."""
    if _missing(p):
        return "P = NA"
    if p < 0.001:
        return "P < .001"
    if p >= 0.995:
        return "P > .99"
    if p < 0.0095:
        text = f"{p:.3f}"
    elif p < 0.01:
        text = "0.01"
    elif 0.045 <= p < 0.05:
        text = f"{p:.3f}"
        text = "0.049" if text == "0.050" else text  # 3-decimal rounding must not reach .05
    else:
        text = f"{p:.2f}"
    return "P = " + text.lstrip("0")


def fmt_estimate(theta: float | None, low: float | None, high: float | None, digits: int = 1) -> str:
    if _missing(theta):
        return "not estimable"
    if _missing(low) or _missing(high):
        return f"{theta:.{digits}f}"
    return f"{theta:.{digits}f} (95% CI, {low:.{digits}f} to {high:.{digits}f})"


def _num(value: float | None, digits: int = 1) -> str:
    return "-" if _missing(value) else f"{value:.{digits}f}"


def _phase3_rows(n: int) -> str:
    return f"{n} Phase 3 row" + ("" if n == 1 else "s")


def _row(cells: list[object]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _clean(obj: object) -> object:
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python, tuples -> lists, floats rounded to 10 places."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        return _clean(obj.item())
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 10)
    return obj


def input_line(key: str, source: dict) -> str:
    """Reproducibility line for one raw input; the Part 2 roster is counted in entries and the Part F worksheet in
    worksheet rows, not raw form rows."""
    if "n_rows_raw" in source:
        rows = f"{source['n_rows_raw']} raw rows"
    elif "n_worksheet_rows" in source:
        rows = f"{source['n_worksheet_rows']} worksheet rows"
    else:
        rows = f"{source['n_roster_rows']} roster entries"
    return f"- Input `{key}`: `{source['file']}`, sha256 `{source['sha256'][:12]}`, {rows}"


def provenance(root: Path, config_path: Path, manifest: dict, seeds: dict[str, int] | None = None) -> dict:
    """Reproducibility stamp for one stage 2 run, including the seeds it used (SAP section 14)."""
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return None
        return done.stdout.strip()

    commit = git("log", "-1", "--format=%h", "--", *TRACKED_PATHS)
    if commit is None:
        code = "not a git repository"
    else:
        code = (commit or "uncommitted") + ("+dirty" if git("status", "--porcelain", "--", *TRACKED_PATHS) else "")
    return {
        "code_commit": code,
        "python": platform.python_version(),
        "packages": {name: metadata.version(name) for name in PACKAGES},
        "config": config_path.relative_to(root).as_posix() if config_path.is_relative_to(root) else config_path.name,
        "seeds": dict(seeds or {}),
        "inputs": manifest["inputs"],
        "deidentified": manifest["outputs"],
    }


def known_biases(part1: list[dict], flow: dict, status: str = "interim") -> tuple[str, ...]:
    """SAP section 12, with the actual Part 1 and Phase 3 group counts in the group line."""
    counts = {entry["paper"]: entry["n"] for entry in part1}
    group_line = GROUP_BIAS.format(part1_a=counts["A"], part1_b=counts["B"],
                                   phase3_a=flow["analysed_group_A"], phase3_b=flow["analysed_group_B"])
    if status == "final":
        group_line = group_line.replace("Group cannot be verified against allocation records in this analysis.",
                                        GROUP_RECORDS_FINAL)
        return (TESTING_EFFECT_BIAS, group_line, *FINAL_BIASES)
    return (TESTING_EFFECT_BIAS, group_line, *OTHER_BIASES)


def date_limited_items(items: pd.DataFrame, a4_offered_from: date) -> dict:
    """Each date-limited item's cutoff and reason, with the analysed Phase 3 responses scored and not scored on it."""
    rules = {}
    for item_id, reason in DATE_LIMITED_ITEMS.items():
        rows = items[items["item_id"] == item_id]
        rules[item_id] = {"reason": reason, "scored_from": a4_offered_from.isoformat(),
                          "n_phase3_scored": int(rows["n"].sum()),
                          "n_phase3_not_scored": int(rows["n_not_scored"].sum())}
    return rules


def build_results(*, freeze_date: date, a4_offered_from: date, flow: dict, part1: list[dict], headline: Estimate,
                  lmm: Estimate, sensitivity: list[Estimate], descriptives: list[dict], items: pd.DataFrame,
                  perceived: dict, prov: dict, status: str = "interim") -> dict:
    return _clean({
        "status": run_status(status, freeze_date),
        "sap": SAP_VERSION,
        "flow": flow,
        "part1_context": part1,
        "date_limited_items": date_limited_items(items, a4_offered_from),
        "primary": {"headline": asdict(headline), "prespecified_model": asdict(lmm)},
        "sensitivity": [asdict(e) for e in sensitivity],
        "descriptives": descriptives,
        "items": items.to_dict("records"),
        "perceived_retention": perceived,
        "deviations": tuple(d.format(a4_offered_from=a4_offered_from.isoformat()) for d in DEVIATIONS),
        "known_biases": known_biases(part1, flow, status),
        "provenance": prov,
    })


def write_json(results: dict, path: Path) -> None:
    path.write_text(json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def mixed_model_paragraph(head: dict, lmm: dict) -> str:
    """Why the mixed model is not a second primary result, and why its interval is narrower when it is.

    The model is saturated, so its standard error equals the headline's unless REML puts the random-intercept
    variance on its zero boundary; only then is the smaller standard error part of the explanation.
    """
    text = "The mixed model is reported alongside the headline, not as a second primary result."
    if not _estimable(lmm) or lmm["ci_high"] - lmm["ci_low"] >= head["ci_high"] - head["ci_low"]:
        return text
    text += " Its interval is narrower because it uses a normal (z) reference instead of t"
    if lmm["se"] < head["se"] * (1 - 1e-3):
        text += (", and because its estimated between-participant (random-intercept) variance is near zero, which "
                 "makes its standard error smaller than the headline's")
    return text + "."


def render_report(results: dict) -> str:
    flow, prov = results["flow"], results["provenance"]
    head, lmm = results["primary"]["headline"], results["primary"]["prespecified_model"]
    part1 = {entry["paper"]: entry for entry in results["part1_context"]}
    lines = [
        "# Bloomer vs MCQ: 1-month retention",
        "",
        f"**{results['status']}.** Pre-specified in `{results['sap']}`. Code version `{prov['code_commit']}`.",
        "",
        "## Primary outcome",
        "",
        "Percent of valid items correct at 1 month, Bloomer-studied article minus MCQ-studied article, "
        "averaged over the two sequence groups.",
        "",
        f"- **{head['label']}.** {fmt_estimate(head['theta'], head['ci_low'], head['ci_high'])} "
        f"percentage points; {fmt_p(head['p_value'])}; n = {head['n_a'] + head['n_b']} "
        f"(group A {head['n_a']}, group B {head['n_b']}); {head['estimator']}.",
    ]
    if _estimable(lmm):
        lines.append(f"- **{lmm['label']}.** {fmt_estimate(lmm['theta'], lmm['ci_low'], lmm['ci_high'])} "
                     f"percentage points; {fmt_p(lmm['p_value'])}; {lmm['estimator']}.")
    else:
        lines.append(f"- **{lmm['label']}.** not estimable.")
    lines += [f"  - Model note: {note}" for note in lmm["notes"]]
    lines += ["", mixed_model_paragraph(head, lmm)]

    lines += ["", "## Sensitivity analyses", "",
              _row(["Analysis", "Estimator", "n (A/B)", "Estimate (95% CI)", "Unit", "P"]), _row(["---"] * 6)]
    for s in results["sensitivity"]:
        if not _estimable(s):
            lines.append(_row([display_label(s["label"]), "-", "-", "not estimable", "-", "-"]))
            continue
        digits = 1 if s["unit"] == PP else 2
        lines.append(_row([display_label(s["label"]), s["estimator"], f"{s['n_a']}/{s['n_b']}",
                           fmt_estimate(s["theta"], s["ci_low"], s["ci_high"], digits), s["unit"],
                           fmt_p(s["p_value"])]))
    notes = [f"- {display_label(s['label'])}: {note}" for s in results["sensitivity"] for note in s["notes"]]
    if notes:
        lines += ["", *notes]

    lines += [
        "", "## Population", "",
        _row(["", "Group A", "Group B", "Total"]), _row(["---"] * 4),
        _row(["Part 1 MCQ form responses (unlinked; pilot rows excluded)", part1["A"]["n"], part1["B"]["n"],
              part1["A"]["n"] + part1["B"]["n"]]),
        _row(["Phase 3 analysed", flow["analysed_group_A"], flow["analysed_group_B"], flow["analysed"]]),
        "",
        f"Phase 3 flow: de-identified responses {flow['phase3_deidentified']}; "
        f"duplicate submissions removed at ingest {flow['duplicates_removed_at_ingest']}; "
        f"completed after the freeze date {flow['excluded_after_freeze']}; "
        f"without a group {flow['excluded_missing_group']}. The duplicate check covers only rows with a contact "
        f"email; {_phase3_rows(flow['rows_without_contact_email'])} without a contact email "
        f"{'was' if flow['rows_without_contact_email'] == 1 else 'were'} not checked. "
        "The Paper A MCQ form was taken by group A and the Paper B form by group B.",
        "",
        *[f"Item {item_id} is scored only for responses dated on or after {rule['scored_from']} and is excluded "
          f"before that date; {rule['reason']}. Analysed Phase 3 responses with {item_id} scored: "
          f"{rule['n_phase3_scored']}; not scored: {rule['n_phase3_not_scored']}."
          for item_id, rule in results["date_limited_items"].items()],
        "", "## Retention by group and article", "",
        _row(["Group", "Article", "Part 1 method", "n", "Mean (SD), %", "Median (IQR), %"]), _row(["---"] * 6),
    ]
    for d in results["descriptives"]:
        lines.append(_row([d["group"], f"Paper {d['paper']}", d["method"], d["n"],
                           f"{_num(d['mean'])} ({_num(d['sd'])})",
                           f"{_num(d['median'])} ({_num(d['q1'])} to {_num(d['q3'])})"]))

    lines += ["", "## Item-level percent correct at 1 month", "",
              _row(["Item", "Scored", "MCQ-studied", "Bloomer-studied"]), _row(["---"] * 4)]
    limited = results["date_limited_items"]
    by_item: dict[str, dict[str, str]] = {}
    for r in results["items"]:  # counts cover scored rows only; no percent when the item was never scored
        cell = f"{r['pct_correct']:.0f}% ({r['n_correct']}/{r['n']})" if r["n"] else "not scored"
        by_item.setdefault(r["item_id"], {})[r["method"]] = cell
    for item_id in sorted(by_item):
        entry = by_item[item_id]
        scored = f"from {limited[item_id]['scored_from']}" if item_id in limited else "yes"
        lines.append(_row([item_id, scored, entry.get("MCQ", "-"), entry.get("Bloomer", "-")]))

    lines += ["", "## Perceived retention (Phase 3 self-report)", ""]
    for column, counts in results["perceived_retention"].items():
        lines.append(f"- {PERCEIVED_LABELS[column]}: "
                     + ", ".join(f"{DISPLAY_OPTIONS.get(k, k)} {v}" for k, v in counts.items()))

    lines += ["", "## Part 1 context (unlinked; different respondents from Phase 3)", "",
              _row(["Article", "n", "Pilot rows excluded", "Started after freeze excluded",
                    "Mean (SD) % of valid items correct", "Median prior knowledge (1-10)"]),
              _row(["---"] * 6)]
    for paper in ("A", "B"):
        c = part1[paper]
        lines.append(_row([f"Paper {paper}", c["n"], c["n_pilot_excluded"], c["n_after_freeze_excluded"],
                           f"{_num(c['pct_correct_mean'])} ({_num(c['pct_correct_sd'])})",
                           _num(c["prior_knowledge_median"])]))

    lines += ["", "## Method notes", "", *[f"- {d}" for d in results["deviations"]],
              "", "## Known biases", "", *[f"- {b}" for b in results["known_biases"]],
              "", "## Reproducibility", "",
              f"- Python {prov['python']}; " + ", ".join(f"{k} {v}" for k, v in prov["packages"].items()),
              f"- Config `{prov['config']}`; figure `fig_retention.pdf` / `.png`"]
    for key, source in prov["inputs"].items():
        lines.append(input_line(key, source))
    return "\n".join(lines) + "\n"


def _tick_label(label: str) -> str:
    """Long labels break before their parenthetical so panel b keeps its width."""
    return label.replace(" (", "\n(", 1) if len(label) > 45 else label


def plot_retention(wide: pd.DataFrame, estimates: list[Estimate], out_stem: Path) -> list[Path]:
    """a: paired 1-month scores per participant; b: headline and percentage-point estimates with 95% CI."""
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # silence subsetting chatter for system Helvetica
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": REF_COLOR,
        "axes.linewidth": 0.8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.5, 3.6), gridspec_kw={"width_ratios": [1, 1.5]})

    pairs = wide.dropna(subset=["pct_a", "pct_b"]).reset_index(drop=True)
    jitter = np.random.default_rng(0).uniform(-0.07, 0.07, size=len(pairs))
    for i, record in pairs.iterrows():
        mcq = record["pct_a"] if record["group"] == "A" else record["pct_b"]
        bloomer = record["pct_b"] if record["group"] == "A" else record["pct_a"]
        marker = "o" if record["group"] == "A" else "s"
        ax_a.plot([jitter[i], 1 + jitter[i]], [mcq, bloomer], color="#D1D5DB", linewidth=0.8, zorder=1)
        ax_a.scatter([jitter[i]], [mcq], s=42, marker=marker, color=MCQ_COLOR, edgecolors="white",
                     linewidths=0.8, zorder=2)
        ax_a.scatter([1 + jitter[i]], [bloomer], s=42, marker=marker, color=BLOOMER_COLOR, edgecolors="white",
                     linewidths=0.8, zorder=2)
    ax_a.set_xticks([0, 1], ["MCQ-studied\narticle", "Bloomer-studied\narticle"])
    ax_a.set_xlim(-0.45, 1.45)
    ax_a.set_ylim(-5, 105)
    ax_a.set_ylabel("Valid items correct at 1 month (%)")
    ax_a.legend(handles=[
        mlines.Line2D([], [], marker="o", linestyle="", color=MUTED_COLOR, label="Group A"),
        mlines.Line2D([], [], marker="s", linestyle="", color=MUTED_COLOR, label="Group B"),
    ], loc="lower center", bbox_to_anchor=(0.5, -0.36), ncol=2, frameon=False, fontsize=9)

    shown = [estimates[0]] + [e for e in estimates[1:] if e.unit == PP and not _missing(e.ci_low)]
    for rank, est in enumerate(shown):
        y = len(shown) - 1 - rank
        color = LABEL_COLOR if rank == 0 else MUTED_COLOR
        ax_b.errorbar(est.theta, y, xerr=[[est.theta - est.ci_low], [est.ci_high - est.theta]], fmt="o",
                      color=color, ecolor=color, elinewidth=1.2, capsize=2.5, markersize=5)
    ax_b.axvline(0, color=REF_COLOR, linestyle="--", linewidth=0.7, zorder=0)
    ax_b.set_yticks(range(len(shown)), [_tick_label(display_label(e.label)) for e in reversed(shown)], fontsize=8.5)
    ax_b.spines["left"].set_visible(False)
    ax_b.tick_params(axis="y", length=0)
    ax_b.set_xlabel("Bloomer minus MCQ, percentage points (95% CI)")

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
