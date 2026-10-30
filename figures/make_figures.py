#!/usr/bin/env python3
"""Manuscript Figures 1 and 2, drawn from the analysis outputs.

Every number printed on a figure is read from the reporting bundle's
manuscript_numbers.json. Per-participant retention scores come from the analysis
package's own scoring functions over the committed de-identified data, so nothing
is recomputed here. Run with the analysis environment:

    ~/.venvs/bloomer-retention/bin/python figures/make_figures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# The analysis repository sits beside this script's folder (public repository) or one level higher (study folder).
ANALYSIS = next(p / "analysis" for p in Path(__file__).resolve().parents[1:3] if (p / "analysis" / "src").is_dir())
BUNDLE = ANALYSIS / "outputs" / "manuscript"
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ANALYSIS / "src"))

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#9CA3AF",
    "axes.linewidth": 0.8,
    "xtick.color": "#2B2B2B",
    "ytick.color": "#2B2B2B",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

# One meaning per color, everywhere: blue = quiz, orange = Bloomer, greys = neutral.
QUIZ = "#00468B"
BLOOMER = "#D97848"
QUIZ_FILL = "#E3EDF7"
BLOOMER_FILL = "#FFF1E8"
INK = "#2B2B2B"
MUTED = "#6B7280"
LINE = "#C7CDD6"
PANEL = "#FAFBFD"
BORDER = "#B5BDC8"
REF = "#9CA3AF"

N = json.loads((BUNDLE / "manuscript_numbers.json").read_text())


def f(key: str) -> str:
    """Formatted value exactly as the bundle prints it."""
    return str(N[key]["formatted"])


def v(key: str) -> float:
    return float(N[key]["value"])


def paired_scores():
    """(quiz-studied %, Bloomer-studied %) per retention participant, from the analysis package."""
    from bloomer_retention.config import load_config
    from bloomer_retention.run import load_verified_csv
    from bloomer_retention.scoring import item_long, participant_scores, phase3_population

    cfg = load_config(ANALYSIS / "config" / "study.toml")
    manifest = json.loads(cfg.manifest.read_text(encoding="utf-8"))
    pop, _ = phase3_population(load_verified_csv(cfg.root, manifest["outputs"]["phase3"]), cfg.freeze_date)
    wide = participant_scores(item_long(pop, cfg.a4_offered_from), pop)
    pairs = []
    for _, row in wide.iterrows():
        # group A took the quiz on one article and Bloomer on the other; group B the reverse
        quiz, bloomer = (row.pct_a, row.pct_b) if row.group == "A" else (row.pct_b, row.pct_a)
        pairs.append((float(quiz), float(bloomer)))
    return pairs


def spread(values: list[float], width: float = 0.07) -> list[float]:
    """Deterministic side-by-side offsets for tied values, so no marker hides another."""
    offsets, seen = [], {}
    counts = {x: values.count(x) for x in values}
    for x in values:
        k = seen.get(x, 0)
        seen[x] = k + 1
        offsets.append((k - (counts[x] - 1) / 2) * width)
    return offsets


def panel_label(ax, letter: str, x: float = -0.16, y: float = 1.06) -> None:
    ax.text(x, y, letter.upper(), transform=ax.transAxes, fontsize=12, fontweight="bold", color=INK, va="bottom")


def save(fig, stem: str) -> None:
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=600, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


# ------------------------------------------------------------------------------------------ Figure 1

def box(ax, x, y, w, h, fill, edge, lw=0.9, r=0.018):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fill, ec=edge, lw=lw, zorder=1))


def arrow(ax, x0, y0, x1, y1, color=MUTED, lw=1.0):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=8,
                                 color=color, lw=lw, zorder=3, shrinkA=0, shrinkB=0))


def block_header(ax, x, y, number: str, title: str):
    ax.add_patch(plt.Circle((x + 0.022, y), 0.016, fc=INK, ec="none", zorder=4))
    ax.text(x + 0.022, y, number, color="white", fontsize=7.5, fontweight="bold", ha="center", va="center",
            zorder=5)
    ax.text(x + 0.05, y, title, fontsize=9.5, fontweight="bold", color=INK, va="center")


def not_linked(ax, x, y) -> None:
    """The caveat every count in Figure 1 carries, set so it cannot be read past."""
    ax.text(x, y, "Counts are forms, not people: not linked across steps", fontsize=7.5, fontweight="bold",
            color=INK, va="center", bbox=dict(boxstyle="round,pad=0.35", fc="#FDF3D8", ec="#E3C77A", lw=0.6))


def figure1() -> None:
    fig = plt.figure(figsize=(7.4, 5.3))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    L, R, W = 0.02, 0.51, 0.47
    TOP_Y, TOP_H = 0.53, 0.45
    BOT_Y, BOT_H = 0.02, 0.47
    for x, y, h in [(L, TOP_Y, TOP_H), (R, TOP_Y, TOP_H), (L, BOT_Y, BOT_H), (R, BOT_Y, BOT_H)]:
        box(ax, x, y, W, h, PANEL, BORDER)

    # (1) Participants
    block_header(ax, L + 0.01, 0.945, "1", "Participants and form counts")
    ax.text(L + 0.03, 0.87, "US neurologists and neurology trainees", fontsize=8.5, color=INK, va="center")
    ax.text(L + 0.03, 0.83, "NPI-verified, recruited nationally from May 2026", fontsize=8, color=MUTED,
            va="center")
    # two separate counts, no connector: no study identifier was assigned and responses were not linked
    for i, (num, what) in enumerate([(f("flow.signup.analysed"), "sign-ups"),
                                     (f("flow.part1.total"), "Part 1 quiz forms (quiz, then Bloomer)")]):
        ax.text(L + 0.03, 0.765 - i * 0.055, num, fontsize=15, fontweight="bold", color=INK, va="center")
        ax.text(L + 0.085, 0.765 - i * 0.055, what, fontsize=8.5, color=INK, va="center")
    not_linked(ax, L + 0.03, 0.66)
    ax.text(L + 0.03, 0.595, "Two review articles, counterbalanced across groups;\nparticipants were assigned both "
            "activities,\neach with a different article", fontsize=8, color=MUTED, va="center", linespacing=1.35)

    # (2) Crossover assessment
    block_header(ax, R + 0.01, 0.945, "2", "Article-counterbalanced assessment")
    rows = [("Group A", f("flow.part1.group_a"), "Article 1", "Article 2"),
            ("Group B", f("flow.part1.group_b"), "Article 2", "Article 1")]
    for i, (grp, n, quiz_art, bloom_art) in enumerate(rows):
        y = 0.87 - i * 0.085
        ax.text(R + 0.03, y, f"{grp}\n({n} forms)", fontsize=8, color=INK, va="center", linespacing=1.2)
        box(ax, R + 0.13, y - 0.028, 0.135, 0.056, QUIZ_FILL, QUIZ, lw=0.8, r=0.012)
        ax.text(R + 0.1975, y, f"5-item quiz\n{quiz_art}", fontsize=7.5, color=QUIZ, ha="center", va="center",
                linespacing=1.15)
        arrow(ax, R + 0.268, y, R + 0.3, y)
        box(ax, R + 0.303, y - 0.028, 0.155, 0.056, BLOOMER_FILL, BLOOMER, lw=0.8, r=0.012)
        ax.text(R + 0.3805, y, f"Bloomer\n{bloom_art}", fontsize=7.5, color=BLOOMER, ha="center", va="center",
                linespacing=1.15)
    ax.text(R + 0.03, 0.735, "Fixed order in both groups: quiz first, then Bloomer", fontsize=7, color=MUTED,
            va="center", style="italic")
    # the Bloomer loop
    ly = 0.635
    ax.text(R + 0.03, ly + 0.055, "Bloomer", fontsize=8, fontweight="bold", color=BLOOMER, va="center")
    steps = ["Write 3 questions:\nkey idea, clinical\ncase, limitation", "LLM grades against\nBloom's taxonomy",
             "Pass (level 3+)\nunlocks the\nnext question"]
    xs = [R + 0.03, R + 0.175, R + 0.32]
    for x, s in zip(xs, steps):
        box(ax, x, ly - 0.045, 0.13, 0.075, "white", BLOOMER, lw=0.7, r=0.01)
        ax.text(x + 0.065, ly - 0.0075, s, fontsize=6.8, color=INK, ha="center", va="center", linespacing=1.15)
    arrow(ax, xs[0] + 0.13, ly - 0.0075, xs[1], ly - 0.0075, color=BLOOMER)
    arrow(ax, xs[1] + 0.13, ly - 0.0075, xs[2], ly - 0.0075, color=BLOOMER)
    ax.annotate("", xy=(xs[0] + 0.065, ly - 0.047), xytext=(xs[2] + 0.065, ly - 0.047),
                arrowprops=dict(arrowstyle="-|>", color=BLOOMER, lw=0.7, mutation_scale=7,
                                connectionstyle="arc3,rad=-0.12"))
    ax.text(R + 0.24, ly - 0.072, "revise", fontsize=6.8, color=BLOOMER, ha="center", va="center",
            style="italic", zorder=6, bbox=dict(fc=PANEL, ec="none", pad=0.8))

    # (3) Outcomes
    block_header(ax, L + 0.01, 0.455, "3", "Outcomes")
    items = [("End of Part 1", "Survey after Bloomer", f"{f('demographics.n.overall')} forms",
              "Would rather prove competency with; best for\nchecking comprehension; difficulty; time"),
             ("About 1 month later", "Quiz on both articles, 5 items each",
              f"{f('flow.phase3.analysed')} forms ({f('flow.phase3.group_a')} group A, "
              f"{f('flow.phase3.group_b')} group B)",
              "Bloomer-studied minus quiz-studied article,\nwithin each respondent")]
    for i, (when, what, n, detail) in enumerate(items):
        y = 0.38 - i * 0.165
        ax.text(L + 0.03, y + 0.03, when, fontsize=7.5, color=MUTED, va="center")
        ax.text(L + 0.03, y, what, fontsize=8.5, fontweight="bold", color=INK, va="center")
        ax.text(L + 0.03, y - 0.03, n, fontsize=8, color=INK, va="center")
        ax.text(L + 0.03, y - 0.075, detail, fontsize=7.5, color=MUTED, va="center", linespacing=1.3)
    not_linked(ax, L + 0.03, 0.06)

    # (4) What we found
    block_header(ax, R + 0.01, 0.455, "4", "What we found")
    # retention: estimate and 95% CI on a small axis
    sub = fig.add_axes([R + 0.05, 0.305, W - 0.09, 0.07])
    lo, hi, th = v("primary.ci_low"), v("primary.ci_high"), v("primary.theta")
    sub.axvline(0, color=REF, lw=0.7, ls="--", zorder=0)
    sub.plot([lo, hi], [0, 0], color=INK, lw=1.2, solid_capstyle="butt")
    sub.plot([th], [0], "o", ms=5.5, mfc=INK, mec="white", mew=0.8)
    sub.set_xlim(-40, 40)
    sub.set_ylim(-0.6, 0.6)
    sub.set_yticks([])
    sub.spines["left"].set_visible(False)
    sub.set_xticks([-40, -20, 0, 20, 40])
    sub.tick_params(labelsize=6.5, length=2)
    sub.set_xlabel("Bloomer minus quiz, percentage points", fontsize=6.5, color=MUTED, labelpad=2)
    sub.patch.set_alpha(0)
    ax.text(R + 0.03, 0.405, f"Quiz score at 1 month: {f('primary.theta').replace('-', '−')} points "
            f"(95% CI, {f('primary.ci_low').replace('-', '−')} to {f('primary.ci_high')})",
            fontsize=8, color=INK, va="center")
    # three proportions as bars
    # preference over all respondents only; the decided-respondent share is reported in eMethods 4
    bars = [("Best for checking\ncomprehension: Bloomer", v("comprehension.all.pct"),
             f("comprehension.all.pct"), BLOOMER, None),
            ("Would rather prove\ncompetency with: Bloomer", v("adoption.all.pct"),
             f("adoption.all.pct"), BLOOMER, None),
            ("Rated Bloomer difficult", v("difficulty.bloomer.pct_difficult") / 100,
             f("difficulty.bloomer.pct_difficult"), BLOOMER, None),
            ("Rated quiz difficult", v("difficulty.quiz.pct_difficult") / 100,
             f("difficulty.quiz.pct_difficult"), QUIZ, None)]
    x0, bw = R + 0.215, 0.19
    for i, (label, frac, txt, color, note) in enumerate(bars):
        y = 0.215 - i * 0.047
        ax.text(x0 - 0.01, y, label, fontsize=6.8, color=INK, ha="right", va="center", linespacing=1.1)
        ax.add_patch(plt.Rectangle((x0, y - 0.011), bw, 0.022, fc="#EEF1F5", ec="none", zorder=1))
        ax.add_patch(plt.Rectangle((x0, y - 0.011), bw * frac, 0.022, fc=color, ec="none", zorder=2))
        ax.text(x0 + bw + 0.008, y, txt, fontsize=7, color=INK, va="center")
        if note:
            ax.text(x0, y - 0.019, note, fontsize=6, color=MUTED, va="center")
    ax.text(R + 0.03, 0.035, f"Preference: of all {f('demographics.n.overall')} respondents. Difficulty, paired: "
            f"{f('difficulty.paired.p_value')}.", fontsize=6.5, color=MUTED, va="center")
    save(fig, "Figure1")


# ------------------------------------------------------------------------------------------ Figure 2

def figure2() -> None:
    pairs = paired_scores()
    assert len(pairs) == int(v("flow.phase3.analysed")), "retention n differs from the bundle"
    fig = plt.figure(figsize=(7.4, 6.4))
    gs = fig.add_gridspec(2, 2, width_ratios=[0.85, 1.35], height_ratios=[0.82, 1], wspace=0.28, hspace=0.75)

    # a: each respondent's own difference, Bloomer-studied minus quiz-studied article (one strip, not split by
    # sequence group, which would also split by article)
    ax = fig.add_subplot(gs[1, 0])
    diffs = [b - q for q, b in pairs]
    # points closer than 8 percentage points share a row of offsets, so no marker hides another
    order = sorted(range(len(diffs)), key=lambda i: diffs[i])
    cluster, c = {}, 0
    for prev, i in zip([None] + order[:-1], order):
        if prev is not None and diffs[i] - diffs[prev] >= 8:
            c += 1
        cluster[i] = c
    offs = spread([cluster[i] for i in range(len(diffs))], width=0.09)
    colors = [BLOOMER if d > 0 else QUIZ if d < 0 else REF for d in diffs]
    ax.axhline(0, color=REF, lw=0.8, ls="--", zorder=0)
    ax.scatter(offs, diffs, s=34, c=colors, edgecolors="white", linewidths=0.7, zorder=3)
    ax.set_xlim(-0.6, 0.6)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_ylim(-105, 105)
    ax.set_yticks([-100, -50, 0, 50, 100])
    ax.set_ylabel("Bloomer minus quiz, percentage points")
    ax.yaxis.grid(True, color="#F3F4F6", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.text(0.58, 100, "Favors Bloomer", fontsize=7.5, color=BLOOMER, ha="right", va="top")
    ax.text(0.58, -100, "Favors quiz", fontsize=7.5, color=QUIZ, ha="right", va="bottom")
    ax.text(0.5, 1.0, f"n = {f('flow.phase3.analysed')} retention responses, one point each", transform=ax.transAxes,
            fontsize=7.5, color=MUTED, ha="center", va="bottom")
    panel_label(ax, "c", x=-0.3)

    # b: retention difference, primary and sensitivity analyses
    ax = fig.add_subplot(gs[1, 1])
    # the mixed model's Wald interval is anti-conservative at n = 17, so it is not shown (eTable 2)
    rows = [("Primary analysis (within-participant t)", "primary", INK),
            ("Welch t test", "sensitivity.welch", MUTED),
            ("Excluding re-reading, AI use,\nor discussion", "sensitivity.s1", MUTED)]
    for i, (label, key, color) in enumerate(rows):
        y = len(rows) - 1 - i
        th, lo, hi = v(f"{key}.theta"), v(f"{key}.ci_low"), v(f"{key}.ci_high")
        ax.text(-31.5, y + 0.3, label.replace("\n", " "), fontsize=8, color=color, va="center",
                fontweight="bold" if i == 0 else "normal", zorder=4,
                bbox=dict(fc="white", ec="none", pad=0.6))
        ax.plot([lo, hi], [y, y], color=color, lw=1.3, solid_capstyle="butt", zorder=2)
        ax.plot([th], [y], "o" if i == 0 else "s", ms=6 if i == 0 else 4.8, mfc=color, mec="white", mew=0.8,
                zorder=3)
        ax.text(33, y - 0.02, f"{f(key + '.theta').replace('-', '−')} ({f(key + '.ci_low').replace('-', '−')} to "
                f"{f(key + '.ci_high')})", fontsize=7.5, color=color, va="center")
    for y in range(len(rows)):
        ax.plot([0, 0], [y - 0.22, y + 0.14], color=REF, lw=0.7, ls="--", zorder=0)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlim(-32, 32)
    ax.set_ylim(-0.5, len(rows) - 0.3)
    ax.set_xticks([-30, -15, 0, 15, 30])
    ax.set_xlabel("Bloomer minus quiz, percentage points (95% CI)")
    ax.text(0.0, -0.24, "Favors quiz", fontsize=7.5, color=QUIZ, ha="left", va="top",
            transform=ax.transAxes)
    ax.text(1.0, -0.24, "Favors Bloomer", fontsize=7.5, color=BLOOMER, ha="right", va="top",
            transform=ax.transAxes)
    panel_label(ax, "d", x=-0.06)

    # a: which method respondents chose, for two purposes (all respondents); comprehension on top
    ax = fig.add_subplot(gs[0, 0:1])
    s3 = json.loads((ANALYSIS / "outputs" / "survey3_results.json").read_text())
    adopt, comp = s3["adoption"]["counts"], s3["comprehension"]["counts"]
    assert sum(adopt.values()) == sum(comp.values()) == int(v("demographics.n.overall"))
    cats = [
        ("Quiz", QUIZ, adopt["A 5-question quiz"], comp["The 5-question quiz"]),
        ("Bloomer", BLOOMER, adopt["Bloomer-AI"], comp["Bloomer"]),
        ("About the same", "#C9CFD8", 0, comp["They were about the same"]),
        ("Unsure, neither, or no opinion", "#E5E8ED", adopt["Unsure"] + adopt["No opinon"],
         comp["Neither were very good"] + comp["No opinon"]),
    ]
    ylab = ["Would rather prove\ncompetency with", "Best for checking\ncomprehension"]
    for j in range(2):
        left = 0
        y = j  # j = 1 (comprehension) is drawn on top
        for name, color, a_n, c_n in cats:
            n = a_n if j == 0 else c_n
            if n == 0:
                continue
            ax.barh(y, n, left=left, height=0.55, color=color, edgecolor="white", linewidth=0.8)
            if n >= 2:
                ax.text(left + n / 2, y, str(n), ha="center", va="center", fontsize=7.5,
                        color="white" if color in (QUIZ, BLOOMER) else INK)
            left += n
    ax.set_yticks([0, 1])  # ylab[0] (competency) at y = 0, ylab[1] (comprehension) at y = 1
    ax.set_yticklabels(ylab, fontsize=8)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, int(v("demographics.n.overall")))
    ax.set_xlabel(f"Respondents (n = {f('demographics.n.overall')})")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c, _, _ in cats]
    ax.legend(handles, [c[0] for c in cats], loc="upper center", bbox_to_anchor=(0.45, -0.38), ncol=2,
              frameon=False, fontsize=7, handlelength=1.0, columnspacing=1.0, handletextpad=0.4)
    panel_label(ax, "a", x=-0.3)

    # d: perceived difficulty
    ax = fig.add_subplot(gs[0, 1])
    vals = [("Quiz", v("difficulty.quiz.pct_difficult"), f("difficulty.quiz.pct_difficult"), QUIZ),
            ("Bloomer", v("difficulty.bloomer.pct_difficult"), f("difficulty.bloomer.pct_difficult"), BLOOMER)]
    for i, (name, pct, txt, color) in enumerate(vals):
        y = 1 - i
        ax.barh(y, 100, height=0.5, color="#EEF1F5", zorder=1)
        ax.barh(y, pct, height=0.5, color=color, zorder=2)
        ax.text(pct + 2, y, txt, va="center", fontsize=8, color=INK, zorder=3)
    ax.set_yticks([1, 0])
    ax.set_yticklabels([n for n, *_ in vals], fontsize=8)
    for tick, color in zip(ax.get_yticklabels(), [QUIZ, BLOOMER]):
        tick.set_color(color)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Rated a little or very difficult, % of respondents")
    ax.text(1.0, 1.02, f"Paired ratings, {f('difficulty.paired.p_value')}", fontsize=7.5, color=MUTED,
            ha="right", va="bottom", transform=ax.transAxes)
    panel_label(ax, "b", x=-0.2)

    save(fig, "Figure4")


# ------------------------------------------------------------------------------------------ Figure 3

def usage_values():
    """Per-respondent parsed attempts and minutes per Bloomer question, over the Survey 3 analysis population."""
    from bloomer_retention.config import load_config
    from bloomer_retention.run import load_verified_csv
    from bloomer_retention.survey3 import survey3_population

    cfg = load_config(ANALYSIS / "config" / "study.toml")
    manifest = json.loads(cfg.manifest.read_text(encoding="utf-8"))
    pop, _ = survey3_population(load_verified_csv(cfg.root, manifest["outputs"]["survey3"]), cfg.study_start,
                                cfg.freeze_date)
    out = {}
    for q in ("q1", "q2", "q3"):
        att = pop.loc[pop[f"{q}_attempts_status"] == "ok", f"{q}_attempts"].astype(float).tolist()
        mins = pop.loc[pop[f"{q}_time_status"] == "ok", f"{q}_minutes"].astype(float).tolist()
        out[q] = (att, mins)
    return out


def figure3() -> None:
    data = usage_values()
    labels = {"q1": "Key idea", "q2": "Clinical\ncase", "q3": "Limitation"}
    for q in data:  # every point plotted is one the bundle's summary counted
        assert len(data[q][0]) == int(v(f"usage.{q}.attempts.n")), q
        assert len(data[q][1]) == int(v(f"usage.{q}.minutes.n")), q
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.3), gridspec_kw={"wspace": 0.35})
    for ax, (idx, what, ylabel, letter) in zip(axes, [(0, "attempts", "Self-reported attempts", "A"),
                                                      (1, "minutes", "Self-reported minutes", "B")]):
        for i, q in enumerate(("q1", "q2", "q3")):
            vals = sorted(data[q][idx])
            most = max(vals.count(x) for x in vals)
            offs = spread(vals, width=min(0.045, 0.42 / most))
            ax.scatter([i + o for o in offs], vals, s=14, c=BLOOMER, alpha=0.75, edgecolors="white",
                       linewidths=0.5, zorder=3)
            med, lo, hi = (v(f"usage.{q}.{what}.{k}") for k in ("median", "q1", "q3"))
            ax.plot([i + 0.3, i + 0.3], [lo, hi], color=INK, lw=1.4, solid_capstyle="butt", zorder=4)
            ax.plot([i + 0.3], [med], "o", ms=5, mfc="white", mec=INK, mew=1.3, zorder=5)
        ax.set_xticks(range(3))
        ax.set_xticklabels([labels[q] for q in ("q1", "q2", "q3")])
        ax.set_xlim(-0.5, 2.6)
        ax.set_ylabel(ylabel)
        if what == "minutes":
            ax.set_yscale("log")
            ax.set_yticks([1, 2, 5, 10, 20, 50, 100, 200])
            ax.set_yticklabels(["1", "2", "5", "10", "20", "50", "100", "200"])
            ax.minorticks_off()
        ax.yaxis.grid(True, color="#F3F4F6", lw=0.6, zorder=0)
        ax.set_axisbelow(True)
        panel_label(ax, letter, x=-0.2)
    top = axes[0].get_ylim()[1]
    for i, q in enumerate(("q1", "q2", "q3")):
        axes[0].text(i + 0.1, top * 1.02, f(f'usage.{q}.attempts.pct_more_than_one'),
                     fontsize=7.5, color=MUTED, ha="center", va="bottom")
    axes[0].set_ylim(0, top * 1.1)
    axes[0].text(0.0, 1.02, "Needed more than 1 attempt:", transform=axes[0].transAxes, fontsize=7.5,
                 color=MUTED, ha="left", va="bottom")
    axes[1].text(1.0, 1.02, f"All 3 questions: median {f('usage.total_minutes.median')} min "
                 f"(IQR, {f('usage.total_minutes.q1')}-{f('usage.total_minutes.q3')})", transform=axes[1].transAxes,
                 fontsize=7.5, color=MUTED, ha="right", va="bottom")
    save(fig, "Figure3")


# ------------------------------------------------------------------------------------------ eFigures

def efigure1() -> None:
    """Forms received at each step, as four separate count boxes. No study identifier was assigned and responses were not linked,
    so no arrow or connector joins one step to the next."""
    fig = plt.figure(figsize=(7.2, 4.6))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.5, 0.955, "Forms received at each step (unlinked)", fontsize=11, fontweight="bold", color=INK,
            ha="center", va="center")
    steps = [
        ("Sign-ups", f"n = {f('flow.signup.analysed')}",
         f"Excluded: pilot test {f('flow.signup.excluded_pilot')}; not verified by NPI lookup "
         f"{f('flow.signup.excluded_npi_unmatched')}"),
        ("Part 1 quiz forms", f"n = {f('flow.part1.total')}; group A {f('flow.part1.group_a')}, "
         f"group B {f('flow.part1.group_b')}\ndated \u226528 days before the close: {f('flow.eligible.total')} "
         f"(group A {f('flow.eligible.A')}, group B {f('flow.eligible.B')})",
         # the misdirected retention entry (analysis config [exclude_ids]) is dropped before ingest; it has no bundle
         # key, so it is named in eTable 1 and its note, not here
         f"Excluded: pilot tests, group A {f('flow.part1.excluded_pilot_a')}, "
         f"group B {f('flow.part1.excluded_pilot_b')}; see eTable 1"),
        ("Survey forms after Bloomer", f"n = {f('flow.survey3.analysed')}; group A {f('flow.survey3.group_a')}, "
         f"group B {f('flow.survey3.group_b')}",
         f"Excluded: pilot test {f('flow.survey3.excluded_pilot')}, blank {f('flow.survey3.excluded_blank')}"),
        ("1-month retention quiz forms\n(analyzed for retention)",
         f"n = {f('flow.phase3.analysed')}; group A {f('flow.phase3.group_a')}, group B {f('flow.phase3.group_b')}",
         f"Excluded: repeat submission {f('flow.phase3.duplicates_removed')}"),
    ]
    ys = [0.82, 0.60, 0.38, 0.16]
    bw, bh = 0.84, 0.18
    x0 = 0.08
    for (title, n, excl), y in zip(steps, ys):
        box(ax, x0, y - bh / 2, bw, bh, "white", INK, lw=1.0)
        ax.text(x0 + 0.03, y + 0.04 if "\n" not in title else y + 0.025, title, fontsize=9, fontweight="bold", color=INK, ha="left",
                va="center", linespacing=1.2)
        ax.text(x0 + 0.03, y - 0.045, n, fontsize=8.5, color=INK, ha="left", va="center", linespacing=1.3)
        ax.text(x0 + bw - 0.03, y, excl, fontsize=7.8, color=MUTED, ha="right", va="center")
    ax.text(0.5, 0.035, "Each count is one form or response. No study identifier was assigned and responses were not linked, "
            "so the counts do not follow people from one step to the next.", fontsize=7.5, color=MUTED, ha="center",
            va="center")
    save(fig, "eFigure1")


def efigure2() -> None:
    """A: later forms as a ratio of Part 1 quiz forms, by sequence group (form counts, not linked; the retention
    bars use the Part 1 forms dated at least 28 days before the close). B: quiz-studied items, 1 month minus immediate
    (different respondents)."""
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.2), gridspec_kw={"width_ratios": [0.9, 1.3], "wspace": 0.45})
    ax = axes[0]
    grp = [("Group A", "#3B4556"), ("Group B", "#9CA3AF")]
    bars = {  # (forms returned, denominator forms, percent) per step and group, all from the bundle
        "survey3": [(f(f"flow.return.survey3.group_{g}.n_returned"), f(f"flow.return.survey3.group_{g}.n_part1"),
                     v(f"flow.return.survey3.group_{g}.pct")) for g in "ab"],
        "phase3": [(f(f"flow.eligible_returns.{g}_n_returned"), f(f"flow.eligible.{g}"),
                    v(f"flow.eligible_returns.{g}_pct")) for g in "AB"],
    }
    for j, step in enumerate(("survey3", "phase3")):
        for i, (g, color) in enumerate(grp):
            n_ret, n_den, pct = bars[step][i]
            pct = pct * 100 if pct <= 1 else pct
            x = j + (i - 0.5) * 0.36
            ax.bar(x, pct, width=0.34, color=color)
            ax.text(x, pct + 2, f"{n_ret}/{n_den}", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Survey after Bloomer\n(all Part 1 forms)", "Retention quiz\n(Part 1 forms \u226528 d\nbefore close)"],
                       fontsize=7.5)
    ax.set_ylim(0, 118)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_ylabel("Later forms per Part 1 quiz form, %")
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=c) for _, c in grp], [g for g, _ in grp], frameon=False,
              fontsize=7.5, loc="upper center", ncol=2, handlelength=1.0, columnspacing=1.0)
    ax.text(1, -0.34, "Form counts, not linked. Retention quiz: descriptive",
            transform=ax.transAxes, fontsize=7, color=MUTED, ha="right")
    panel_label(ax, "A", x=-0.28)

    ax = axes[1]
    rows = [("Article 1 (group A)", "forgetting.group_a", MUTED, "s"),
            ("Article 2 (group B)", "forgetting.group_b", MUTED, "s"),
            ("Both articles, equal weight", "forgetting.pooled", QUIZ, "o")]
    for i, (label, key, color, marker) in enumerate(rows):
        y = len(rows) - 1 - i
        th, lo, hi = v(f"{key}.difference"), v(f"{key}.ci_low"), v(f"{key}.ci_high")
        ax.plot([lo, hi], [y, y], color=color, lw=1.3, solid_capstyle="butt")
        ax.plot([th], [y], marker, ms=6 if marker == "o" else 4.8, mfc=color, mec="white", mew=0.8)
        ax.text(-68, y + 0.3, label, fontsize=8, color=INK if marker == "o" else MUTED, va="center",
                fontweight="bold" if marker == "o" else "normal")
        ax.text(26, y, f"{f(key + '.difference').replace('-', '−')} ({f(key + '.ci_low').replace('-', '−')} "
                f"to {f(key + '.ci_high').replace('-', '−')})", fontsize=7.5, color=color, va="center")
    for y in range(len(rows)):
        ax.plot([0, 0], [y - 0.22, y + 0.14], color=REF, lw=0.7, ls="--")
    ax.set_xlim(-68, 25)
    ax.set_ylim(-0.5, len(rows) - 0.3)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("1 month minus immediate, percentage points (95% CI)")
    panel_label(ax, "B", x=-0.05)
    save(fig, "eFigure2")


if __name__ == "__main__":
    figure1()
    figure2()
    figure3()
    efigure1()
    efigure2()
    print("wrote", *sorted(p.name for p in OUT.glob("*Figure*.*")))
