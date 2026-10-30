"""Load config/study.toml and resolve its paths against the analysis root."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bloomer_retention.labels import RUN_STATUSES

INPUT_KEYS = ("phase3", "mcq_part1_A", "mcq_part1_B")
# survey3: SAP Part B; start (with survey3): SAP Part C; part2_roster (with survey3): SAP Part D;
# phase3_registration_links (with start): SAP Part F
OPTIONAL_INPUT_KEYS = ("survey3", "start", "part2_roster", "phase3_registration_links", "survey3_feedback_codes")


@dataclass(frozen=True)
class StudyConfig:
    root: Path
    freeze_date: date
    study_start: date
    a4_offered_from: date  # first response date on which item A4 is scored (SAP section 5.3)
    permutation_seed: int
    inputs: dict[str, Path]
    deidentified_dir: Path
    manifest: Path
    outputs_dir: Path
    linkage_seed: int | None = None  # SAP Part C matching sampler; optional [study] key
    linkage_draws: int | None = None  # SAP Part C number of sampled matchings; optional [study] key
    status: str = "interim"  # SAP v3.0: "final" once data collection is closed; freeze_date is then the close date
    # SAP v3.0: hours added to an export's Start/Completion/Last modified times, so exports downloaded in a
    # different time zone line up with the earlier ones (verified on every overlapping row)
    time_shift_hours: dict[str, float] = field(default_factory=dict)
    # SAP v3.0: Forms IDs dropped from an export before anything else, each with a reason in the config and the SAP
    exclude_ids: dict[str, tuple[int, ...]] = field(default_factory=dict)
    # SAP v3.2: Start form IDs of the sign-ups the study team's NPI lookup could not match to a neurologist or
    # neurology trainee. Flagged at ingest after the pids are assigned, and left out of the sign-up count (C1, C6)
    npi_unmatched_start_ids: tuple[int, ...] = ()


def load_config(config_path: str | Path) -> StudyConfig:
    config_path = Path(config_path).resolve()
    root = config_path.parent.parent
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    missing = [key for key in INPUT_KEYS if key not in raw["inputs"]]
    if missing:
        raise ValueError(f"config [inputs] is missing: {', '.join(missing)}")

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    return StudyConfig(
        root=root,
        freeze_date=date.fromisoformat(raw["study"]["freeze_date"]),
        study_start=date.fromisoformat(raw["study"]["study_start"]),
        a4_offered_from=date.fromisoformat(raw["study"]["a4_offered_from"]),
        permutation_seed=int(raw["study"]["permutation_seed"]),
        inputs={key: resolve(raw["inputs"][key]) for key in (*INPUT_KEYS, *OPTIONAL_INPUT_KEYS) if key in raw["inputs"]},
        deidentified_dir=resolve(raw["paths"]["deidentified_dir"]),
        manifest=resolve(raw["paths"]["manifest"]),
        outputs_dir=resolve(raw["paths"]["outputs_dir"]),
        linkage_seed=_optional_int(raw["study"], "linkage_seed"),
        linkage_draws=_optional_int(raw["study"], "linkage_draws"),
        status=_status(raw["study"]),
        time_shift_hours=_per_input(raw, "input_time_shift_hours", float),
        exclude_ids=_per_input(raw, "exclude_ids", lambda ids: tuple(int(i) for i in ids)),
        npi_unmatched_start_ids=_npi_unmatched_start_ids(raw),
    )


def _npi_unmatched_start_ids(raw: dict) -> tuple[int, ...]:
    """`[study] npi_unmatched_start_ids` (SAP v3.2): whole Start form IDs, each listed once; needs the Start form."""
    ids = tuple(int(i) for i in raw["study"].get("npi_unmatched_start_ids", ()))
    if ids and "start" not in raw["inputs"]:
        raise ValueError("config [study] npi_unmatched_start_ids needs [inputs] start")
    repeated = len(ids) - len(set(ids))
    if repeated:
        raise ValueError(f"config [study] npi_unmatched_start_ids lists {repeated} repeated ID"
                         f"{'' if repeated == 1 else 's'}")
    return ids


def _status(section: dict) -> str:
    status = str(section.get("status", "interim"))
    if status not in RUN_STATUSES:
        raise ValueError(f"config [study] status must be one of {RUN_STATUSES}, not {status!r}")
    return status


def _per_input(raw: dict, table: str, convert) -> dict:
    """An optional table keyed by input name; every key must name a configured input."""
    entries = raw.get(table, {})
    unknown = sorted(set(entries) - set(raw["inputs"]))
    if unknown:
        raise ValueError(f"config [{table}] names inputs that are not configured: {', '.join(unknown)}")
    return {key: convert(value) for key, value in entries.items()}


def _optional_int(section: dict, key: str) -> int | None:
    return int(section[key]) if key in section else None
