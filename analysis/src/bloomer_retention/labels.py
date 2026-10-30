"""Display labels shared by the Part A report, the retention figure and the manuscript bundle (SAP v2.6).

This module imports nothing, so the bundle may use it without breaking its purity rule (SAP E1). The analysis
labels are what `results.json` stores and what the bundle's index keys are built from (`sensitivity.s2.*`), so
they are never renamed; only what a reader sees changes.
"""
from __future__ import annotations

WELCH_LABEL = "Welch crossover t"
PERMUTATION_LABEL = "S2 Re-randomisation test"
# SAP v3.0: the primary analysis with each sequence group taken from the study team's assignment email
# where one was recorded, and the self-reported group otherwise.
ASSIGNED_GROUP_LABEL = "S7 Sequence group from the assignment email where recorded"
RUN_STATUSES = ("interim", "final")
# SAP v3.2: the sign-up count's NPI exclusion, worded the same in the Part C report and the manuscript bundle
NPI_UNMATCHED_LABEL = "not matched to a neurologist or neurology trainee by NPI lookup"
# The sensitivity rows that SAP v2.6 added or relabelled. Each must have a display label below.
V26_SENSITIVITY_LABELS = (WELCH_LABEL, PERMUTATION_LABEL)
SENSITIVITY_DISPLAY = {
    WELCH_LABEL: "Welch crossover t (unequal variances)",
    PERMUTATION_LABEL: "S2 Permutation test (exchangeability)",
}


def display_label(label: str) -> str:
    """The label a reader sees for a sensitivity row; the analysis label itself when no mapping exists."""
    return SENSITIVITY_DISPLAY.get(label, label)


def run_status(status: str, freeze_date) -> str:
    """The status line every results file stamps: interim (data freeze) or final (data collection closed)."""
    if status not in RUN_STATUSES:
        raise ValueError(f"run status must be one of {RUN_STATUSES}, not {status!r}")
    if status == "final":
        return f"FINAL analysis, data collection closed {freeze_date.isoformat()}"
    return f"INTERIM analysis, data freeze {freeze_date.isoformat()}"


def is_final(status_line: str) -> bool:
    """True for a status line `run_status` wrote for a final run."""
    return str(status_line).startswith("FINAL analysis")
