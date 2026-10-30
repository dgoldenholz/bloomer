"""Start form ("Bloomer-Start", enrollment) definition: allowlisted columns and offered options (SAP Part C, C6).

The form has no group and no scores. Its "Email" column is the anonymous placeholder, and the name and follow-up
email columns hold contact details: ingest never selects any of them.
"""
from __future__ import annotations

ColumnSpec = dict[str, tuple[str, str]]

START_SPEC: ColumnSpec = {
    "start_time": ("exact", "Start time"),
    "completion_time": ("exact", "Completion time"),
    "adult": ("prefix", "Are you 18 years or older?"),
    "us_based": ("prefix", "Are you currently US-based?"),
    "role": ("prefix", "Which best describes you?"),
}
# Documentation only: contact columns of the Start export that are never read (no spec entry selects them).
START_CONTACT_COLUMNS = ("Email", "Name", "follow-up email")

START_OPTIONS: dict[str, tuple[str, ...]] = {
    "adult": ("Yes", "No"),
    "us_based": ("Yes", "No"),
    "role": ("Neurology resident", "ABPN-certified neurologist", "Neurology fellow", "Other"),
}
# npi_unmatched (SAP v3.2): True for a sign-up the study team's NPI lookup could not match to a neurologist or
# neurology trainee, set from the config's Start form IDs after the pids are assigned
START_COLUMNS = ["pid", "signup_date", "adult", "us_based", "role", "npi_unmatched"]
