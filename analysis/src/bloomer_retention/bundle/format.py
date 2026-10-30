"""Formatting and the cell machinery every manuscript table is built from (SAP E2).

The helpers are behavioural copies of `report.fmt_p`, `report.fmt_estimate`, `report._num`, `report._row`,
`survey3_report._median_iqr`, `survey3_report._pct` and `survey3_report._percent`. They are copied rather than
imported because those modules import the analysis modules, which the purity rule forbids (design section 2).
`tests/test_bundle_format.py` pins every one of them against its original, the composed `estimate_cell` and
`median_iqr_cell` included, so a change to the analysis's formatting fails the suite rather than leaving the
manuscript's CI column silently disagreeing with the report it reproduces. One difference is deliberate and
tested: every helper here treats NaN as missing, where `survey3_report._percent` checks only None.

A table cell is a tuple of fragments: literal label text, and `Num`s. A `Num` carries the raw value the analysis
layer wrote, its manuscript string, the dotted source path and its unit, so `manuscript_numbers.json` is collected
from the very cells the tables render - one code path, not two.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

from bloomer_retention.bundle.load import MissingResultError, Results, get

PP = "percentage points"
COUNT = "count"
PERCENT = "percent"
PROBABILITY = "probability"
STATUS = "status"
MISSING = "-"


def missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_p(p: float | None) -> str:
    """JAMA style, identical to `report.fmt_p`: P < .001; 3 decimals below .0095; P = .01 from .0095 to .01;
    2 decimals from .01, except 3 decimals from .045 to .05 so a value below .05 never prints as .05; P > .99."""
    if missing(p):
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
        text = "0.049" if text == "0.050" else text
    else:
        text = f"{p:.2f}"
    return "P = " + text.lstrip("0")


def fmt_num(value: float | None, digits: int = 1) -> str:
    return MISSING if missing(value) else f"{value:.{digits}f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    """A value the analysis already wrote in percent."""
    return MISSING if missing(value) else f"{value:.{digits}f}%"


def fmt_share(value: float | None, digits: int = 1) -> str:
    """A proportion written as a percentage. Display only: 0.2857 and 28.6% are the same number in two units."""
    return MISSING if missing(value) else f"{100 * value:.{digits}f}%"


def row(cells: list[object]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


@dataclass(frozen=True)
class Num:
    """One reported number: the value the analysis wrote, its manuscript string, its source path and its unit."""

    key: str
    value: float | int | None
    formatted: str
    source: str
    unit: str


Fragment = str | Num
Cell = tuple[Fragment, ...]


def cell(*fragments: Fragment | Cell) -> Cell:
    """Flatten literal text and `Num`s (and nested cells) into one cell."""
    out: list[Fragment] = []
    for fragment in fragments:
        if isinstance(fragment, tuple):
            out.extend(fragment)
        else:
            out.append(fragment)
    return tuple(out)


def joined(cells: list[Cell], separator: str = "; ") -> Cell:
    out: list[Fragment] = []
    for rank, item in enumerate(cells):
        if rank:
            out.append(separator)
        out.extend(item)
    return tuple(out)


def text(value: Cell | Fragment) -> str:
    if isinstance(value, Num):
        return value.formatted
    if isinstance(value, str):
        return value
    return "".join(f.formatted if isinstance(f, Num) else f for f in value)


def numbers_in(value: Cell | Fragment) -> list[Num]:
    if isinstance(value, Num):
        return [value]
    if isinstance(value, str):
        return []
    return [f for f in value if isinstance(f, Num)]


@dataclass(frozen=True)
class Table:
    """One manuscript table: its number, title, column headers, rows of cells, footnotes and a standing line.

    The standing line prints above the header row rather than among the footnotes, because it says what the
    whole table is - the run's interim status - and a reader who pastes the table into a manuscript must see it
    before the numbers, not after them.
    """

    number: int
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    footnotes: tuple[Cell, ...]
    standing: Cell = ()

    @property
    def label(self) -> str:
        return f"Table {self.number}. {self.title}"

    def cells(self) -> list[Cell]:
        return [c for r in self.rows for c in r]

    def numbers(self) -> list[Num]:
        found = [n for c in self.cells() for n in numbers_in(c)]
        return (numbers_in(self.standing) + found
                + [n for note in self.footnotes for n in numbers_in(note)])


def render_markdown(table: Table) -> str:
    lines = [f"## {table.label}", ""]
    if table.standing:
        lines += [text(table.standing), ""]
    lines += [row(list(table.headers)), row([MISSING * 3] * len(table.headers))]
    lines += [row([text(c) for c in r]) for r in table.rows]
    if table.footnotes:
        lines += ["", *[f"- {text(note)}" for note in table.footnotes]]
    return "\n".join(lines) + "\n"


def render_csv(table: Table) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if table.standing:
        writer.writerow([f"Note: {text(table.standing)}"])
    writer.writerow(list(table.headers))
    for r in table.rows:
        writer.writerow([text(c) for c in r])
    for note in table.footnotes:
        writer.writerow([f"Note: {text(note)}"])
    return buffer.getvalue()


def write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


# --- number builders: every one fetches through `get`, so a spec gap fails loudly with its path and file ---

def value_num(results: Results, path: str, key: str, *, digits: int = 1, unit: str = PP) -> Num:
    raw = get(results, path)
    return Num(key, raw, fmt_num(raw, digits), path, unit)


def count_num(results: Results, path: str, key: str, *, unit: str = COUNT) -> Num:
    raw = get(results, path)
    if missing(raw):
        return Num(key, raw, MISSING, path, unit)
    if not isinstance(raw, int) or isinstance(raw, bool):
        # `f"{raw:d}"` on a float df raises a bare ValueError, which names neither the path nor the file
        raise MissingResultError(path, results.file(path.split(".")[0]),
                                 f"a count must be a whole number; the analysis layer wrote {raw!r}")
    return Num(key, raw, f"{raw:d}", path, unit)


def df_num(results: Results, path: str, key: str, *, unit: str = COUNT) -> Num:
    """Degrees of freedom: a whole number (pooled, GEE) prints as `count_num` would; a Welch-Satterthwaite df
    (`crossover_welch`, SAP v2.6 S6) is a float and prints to one decimal instead of failing `count_num`'s
    whole-number guard, which exists for true counts (n_a, n_b, ...), not this field."""
    raw = get(results, path)
    if missing(raw):
        return Num(key, raw, MISSING, path, unit)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return Num(key, raw, f"{raw:d}", path, unit)
    if isinstance(raw, float):
        return Num(key, raw, f"{raw:.1f}", path, unit)
    raise MissingResultError(path, results.file(path.split(".")[0]),
                             f"a degrees-of-freedom value must be a number; the analysis layer wrote {raw!r}")


def pct_num(results: Results, path: str, key: str, *, digits: int = 1) -> Num:
    raw = get(results, path)
    return Num(key, raw, fmt_pct(raw, digits), path, PERCENT)


def share_num(results: Results, path: str, key: str, *, digits: int = 1) -> Num:
    raw = get(results, path)
    return Num(key, raw, fmt_share(raw, digits), path, PERCENT)


def pp_num(results: Results, path: str, key: str, *, digits: int = 1) -> Num:
    """A proportion reported in percentage points, as `report` writes a difference from 50%. Display only."""
    raw = get(results, path)
    return Num(key, raw, MISSING if missing(raw) else f"{100 * raw:.{digits}f}", path, PP)


def p_num(results: Results, path: str, key: str) -> Num:
    raw = get(results, path)
    return Num(key, raw, fmt_p(raw), path, PROBABILITY)


def text_num(results: Results, path: str, key: str, *, unit: str) -> Num:
    """A string the analysis layer wrote, carried in the index the way a number is.

    The run status uses this: it belongs in the index because the change report is what tells the study team
    what moved, and a changed freeze date changes the frame of every count beneath it. So do the dates Table 1
    quotes under SAP v2.6 (the follow-up-eligibility cutoff and the Part 1 and Phase 3 date ranges), for the
    same reason: a moved date re-cuts the population a count is over.
    """
    raw = get(results, path)
    return Num(key, raw, MISSING if raw is None else str(raw), path, unit)


def status_num(results: Results) -> Num:
    """The run's own status line, copied verbatim: `INTERIM analysis, data freeze YYYY-MM-DD`."""
    return text_num(results, "results.status", "status.run", unit=STATUS)


def text_at(results: Results, path: str) -> str:
    """A label the analysis layer wrote (an estimator, a question label, a note). Quoted, never rewritten."""
    raw = get(results, path)
    return MISSING if raw is None else str(raw)


# --- cell builders ---

def estimate_cell(results: Results, base: str, prefix: str, *, digits: int = 1, unit: str = PP,
                  theta_key: str = "theta") -> Cell:
    """`3.3 (95% CI, -20.7 to 27.3)`, or the bare estimate when the analysis wrote no interval."""
    theta = value_num(results, f"{base}.{theta_key}", f"{prefix}.{theta_key}", digits=digits, unit=unit)
    low = value_num(results, f"{base}.ci_low", f"{prefix}.ci_low", digits=digits, unit=unit)
    high = value_num(results, f"{base}.ci_high", f"{prefix}.ci_high", digits=digits, unit=unit)
    if missing(theta.value):
        return cell("not estimable")
    if missing(low.value) or missing(high.value):
        return cell(theta)
    return cell(theta, " (95% CI, ", low, " to ", high, ")")


def median_iqr_cell(results: Results, base: str, prefix: str, *, digits: int = 1, unit: str = PP) -> Cell:
    """`4.0 (2.0 to 4.0) [n = 29]`, identical in shape to `survey3_report._median_iqr`."""
    n = count_num(results, f"{base}.n", f"{prefix}.n", unit="people")
    if not n.value:
        return cell(MISSING, " [n = ", n, "]")
    return cell(value_num(results, f"{base}.median", f"{prefix}.median", digits=digits, unit=unit),
                " (", value_num(results, f"{base}.q1", f"{prefix}.q1", digits=digits, unit=unit),
                " to ", value_num(results, f"{base}.q3", f"{prefix}.q3", digits=digits, unit=unit),
                ") [n = ", n, "]")


def mean_sd_cell(results: Results, mean_path: str, sd_path: str, prefix: str, *, digits: int = 1,
                 unit: str = PP) -> Cell:
    return cell(value_num(results, mean_path, f"{prefix}.mean", digits=digits, unit=unit),
                " (", value_num(results, sd_path, f"{prefix}.sd", digits=digits, unit=unit), ")")


def of_cell(results: Results, part_path: str, whole_path: str, prefix: str, *, part_key: str = "n",
            whole_key: str = "n_total") -> Cell:
    return cell(count_num(results, part_path, f"{prefix}.{part_key}", unit="people"), " of ",
                count_num(results, whole_path, f"{prefix}.{whole_key}", unit="people"))


def slug(label: str) -> str:
    """A stable key segment for a form option or level label."""
    out = [c.lower() if c.isalnum() else "_" for c in label]
    return "".join(out).strip("_").replace("__", "_").replace("__", "_")
