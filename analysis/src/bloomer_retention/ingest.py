"""Stage 1 (private): raw Microsoft Forms exports -> de-identified CSVs + data/manifest.json.

Only allowlisted columns leave this module. Contact emails (Phase 3, Survey 3) are read in memory to drop
duplicate submissions and are never written or printed. Survey 3 free-text numbers are parsed here, so only
numbers and parse statuses are written. The Start form's contact columns are never read. Row values are never
printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from bloomer_retention.answer_key import (
    ALLOWED_VALUES,
    ITEM_IDS,
    ITEM_STEMS,
    normalize_text,
    unrecognized_responses,
)
from bloomer_retention.config import load_config
from bloomer_retention.feedback import read_feedback_codes
from bloomer_retention.linkage import part1_links, phase3_links
from bloomer_retention.registration_link import (FOLLOWUP_WORKSHEET_COLUMNS, WORKSHEET_COLUMNS,
                                                 build_registration_links)
from bloomer_retention.roster_link import _plural, build_roster_links
from bloomer_retention.start_form import START_COLUMNS, START_OPTIONS, START_SPEC
from bloomer_retention.survey3_forms import (
    OPTIONS as SURVEY3_OPTIONS,
    OTHER_OPTION,
    QUESTIONS,
    SURVEY3_COLUMNS,
    SURVEY3_CONTACT_EMAIL,
    SURVEY3_SPEC,
)
from bloomer_retention.survey3_parse import (
    parse_age,
    parse_attempts,
    parse_minutes,
    parse_prior_knowledge,
    parse_years,
)

ColumnSpec = dict[str, tuple[str, str]]  # short name -> (match mode, header text)

PHASE3_SPEC: ColumnSpec = {
    "completion_time": ("exact", "Completion time"),
    "group": ("exact", "I am from Group:"),
    "reread_a": ("prefix", "Have you re-read Paper A"),
    "reread_b": ("prefix", "Have you re-read Paper B"),
    "used_ai": ("prefix", "Did you use Bloomer or any other AI tool"),
    "discussed": ("prefix", "Did you discuss either article"),
    **{item_id: ("prefix", ITEM_STEMS[item_id]) for item_id in ITEM_IDS},
    "useful_bloomer": ("exact", "Bloomer"),
    "useful_mcq": ("exact", "Tradtional MCQ"),  # sic: the form's own spelling
    "perceived_better": ("prefix", "Overall, which format do you feel helped you retain"),
}
PHASE3_CONTACT_EMAIL = ("exact", "Email-if chose email")
PHASE3_COLUMNS = [
    "pid", "completion_date", "group", "reread_a", "reread_b", "used_ai", "discussed",
    *ITEM_IDS, "useful_bloomer", "useful_mcq", "perceived_better",
]

MCQ_BASE_SPEC: ColumnSpec = {
    "start_time": ("exact", "Start time"),
    "prior_knowledge": ("prefix", "For the paper you read what would you rate your prior knowledge"),
}

DATE_COLUMNS = {"completion_date", "start_date"}
ROSTER_OUTPUT_KEYS = ("links_roster", "links_roster_alternatives")  # SAP Part D link files
REGISTRATION_OUTPUT_KEY = "links_registration"  # SAP Part F link file
FEEDBACK_OUTPUT_KEY = "feedback_codes"  # SAP Part G (v3.1): pid + 0/1 theme codes
PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "ssn_or_tin": re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b"),
    "phone": re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    "date_of_birth": re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_column(columns: Iterable[object], mode: str, text: str) -> object:
    """Return the single column whose normalised header equals (exact) or starts with (prefix) text."""
    target = normalize_text(text)
    hits = []
    for column in columns:
        header = normalize_text(column) or ""
        if (mode == "exact" and header == target) or (mode == "prefix" and header.startswith(target)):
            hits.append(column)
    if len(hits) != 1:
        raise ValueError(f"expected exactly one column matching {mode} {text!r}; found {len(hits)}")
    return hits[0]


def select_columns(raw: pd.DataFrame, spec: ColumnSpec) -> pd.DataFrame:
    return pd.DataFrame({name: raw[find_column(raw.columns, mode, text)] for name, (mode, text) in spec.items()})


def find_pii(df: pd.DataFrame) -> list[str]:
    """'column:pattern' for every non-date column holding a value shaped like PII."""
    hits = []
    for column in df.columns:
        if column in DATE_COLUMNS:
            continue
        values = df[column].dropna().astype(str)
        for name, pattern in PII_PATTERNS.items():
            if values.str.contains(pattern).any():
                hits.append(f"{column}:{name}")
    return hits


def _dedupe_by_contact(raw: pd.DataFrame, out: pd.DataFrame, completion: pd.Series,
                      contact_spec: tuple[str, str]) -> tuple[pd.DataFrame, pd.Series, dict]:
    """Order by completion time and keep the earliest response per normalised contact email (held in memory)."""
    email = raw[find_column(raw.columns, *contact_spec)]
    contact = email.map(lambda v: normalize_text(v).casefold() if normalize_text(v) else None)
    order = completion.sort_values(kind="stable").index
    out, completion, contact = out.loc[order], completion.loc[order], contact.loc[order]
    duplicate = contact.notna() & contact.duplicated(keep="first")
    # rows without a contact email are counted before dedupe: they cannot be checked for duplicates
    stats = {"n_duplicates_dropped": int(duplicate.sum()), "n_without_contact_email": int(contact.isna().sum())}
    return out[~duplicate], completion[~duplicate], stats


def private_times(raw: pd.DataFrame, rows: pd.Index, pids: pd.Series) -> pd.DataFrame:
    """[pid, start_time, completion_time] for the raw rows behind each output pid (SAP Part C, C6).

    Private: held in memory to build the link candidate files and never written or printed.
    """
    def column(header: str) -> object:
        return pd.to_datetime(raw.loc[rows, find_column(raw.columns, "exact", header)]).to_numpy()

    return pd.DataFrame({"pid": pids.to_numpy(), "start_time": column("Start time"),
                         "completion_time": column("Completion time")})


def _deidentify_phase3(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.Index]:
    out = select_columns(raw, PHASE3_SPEC)
    completion = pd.to_datetime(out.pop("completion_time"))
    out, completion, dedupe = _dedupe_by_contact(raw, out, completion, PHASE3_CONTACT_EMAIL)
    rows = out.index

    out = out.map(normalize_text)
    out.insert(0, "completion_date", completion.dt.strftime("%Y-%m-%d"))
    out.insert(0, "pid", [f"R{i:02d}" for i in range(1, len(out) + 1)])
    stats = {"n_rows_raw": int(len(raw)), **dedupe}
    return out.reset_index(drop=True)[PHASE3_COLUMNS], stats, rows


def deidentify_phase3(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df, stats, _ = _deidentify_phase3(raw)
    return df, stats


def deidentify_phase3_with_times(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """deidentify_phase3 plus the private start and completion times of the kept rows (after dedupe and reorder)."""
    df, stats, rows = _deidentify_phase3(raw)
    return df, stats, private_times(raw, rows, df["pid"])


def deidentify_phase3_with_times_and_rows(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame,
                                                                     pd.DataFrame]:
    """deidentify_phase3_with_times plus the kept raw rows in output order (SAP Part D, D1).

    Private: those rows hold the respondents' names. They are held in memory by ingest to build the roster link
    and are never written or printed.
    """
    df, stats, rows = _deidentify_phase3(raw)
    return df, stats, private_times(raw, rows, df["pid"]), raw.loc[rows].reset_index(drop=True)


def _deidentify_mcq(raw: pd.DataFrame, paper: str) -> tuple[pd.DataFrame, dict, pd.Index]:
    items = [i for i in ITEM_IDS if i[0] == paper]
    out = select_columns(raw, {**MCQ_BASE_SPEC, **{i: ("prefix", ITEM_STEMS[i]) for i in items}})
    start = pd.to_datetime(out.pop("start_time"))
    end = pd.to_datetime(raw.loc[out.index, find_column(raw.columns, "exact", "Completion time")])
    # SAP v2.6, B: Forms start to completion, in minutes; completion before start or over 24 h is implausible
    # and set missing here (never written as a raw timestamp - elapsed_min carries no identifier).
    elapsed = ((end - start).dt.total_seconds() / 60).round(1)
    elapsed = elapsed.where((elapsed >= 0) & (elapsed <= 24 * 60))
    order = start.sort_values(kind="stable").index
    out, start, elapsed = out.loc[order], start.loc[order], elapsed.loc[order]

    prior = pd.to_numeric(out.pop("prior_knowledge"), errors="coerce").astype("Int64")
    out = out.map(normalize_text)
    out.insert(0, "prior_knowledge", prior)
    out.insert(0, "elapsed_min", elapsed)
    out.insert(0, "start_date", start.dt.strftime("%Y-%m-%d"))
    out.insert(0, "pid", [f"M{paper}{i:02d}" for i in range(1, len(out) + 1)])
    df = out.reset_index(drop=True)[["pid", "start_date", "elapsed_min", "prior_knowledge", *items]]
    return df, {"n_rows_raw": int(len(raw))}, order


def deidentify_mcq(raw: pd.DataFrame, paper: str) -> tuple[pd.DataFrame, dict]:
    df, stats, _ = _deidentify_mcq(raw, paper)
    return df, stats


def deidentify_mcq_with_times(raw: pd.DataFrame, paper: str) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """deidentify_mcq plus the private start and completion times, aligned with the output pids."""
    df, stats, rows = _deidentify_mcq(raw, paper)
    return df, stats, private_times(raw, rows, df["pid"])


def check_allowed_values(df: pd.DataFrame, allowed_values: dict[str, tuple[str, ...]] = ALLOWED_VALUES) -> None:
    """Refuse item responses outside the offered options and text outside allowed_values (blanks allowed).

    The error names columns and row counts only, never the values, which could be free text from a respondent.
    """
    counts = {}
    for column in df.columns:
        if column in ITEM_IDS:
            n_bad = sum(bool(unrecognized_responses(column, [value])) for value in df[column])
        elif column in allowed_values:
            allowed = set(allowed_values[column])
            n_bad = sum(text not in allowed for text in map(normalize_text, df[column]) if text is not None)
        else:
            continue
        if n_bad:
            counts[column] = int(n_bad)
    if counts:
        raise ValueError("unexpected values (form edited?): " + "; ".join(f"{c}: {n}" for c, n in counts.items()))


def _deidentify_survey3(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.Index]:
    """Survey 3: allowlisted columns, parsed numbers instead of free text, "Other" recoding, duplicate removal."""
    selected = select_columns(raw, SURVEY3_SPEC)
    completion = pd.to_datetime(selected["completion_time"])
    selected, completion, stats = _dedupe_by_contact(raw, selected, completion, SURVEY3_CONTACT_EMAIL)

    out = pd.DataFrame(index=selected.index)
    out["start_date"] = pd.to_datetime(selected["start_time"]).dt.strftime("%Y-%m-%d")
    out["completion_date"] = completion.dt.strftime("%Y-%m-%d")
    out["age"] = selected["age"].map(parse_age).astype("Int64")
    out["years"] = selected["years"].map(parse_years).astype("Int64")
    out["prior_knowledge"] = selected["prior_knowledge"].map(parse_prior_knowledge).astype("Int64")
    recoded = {}
    for column, options in SURVEY3_OPTIONS.items():
        text = selected[column].map(normalize_text)
        if column in OTHER_OPTION:
            unrecognised = text.notna() & ~text.isin(options)
            text = text.mask(unrecognised, OTHER_OPTION[column])
            recoded[column] = int(unrecognised.sum())
        out[column] = text
    for q in QUESTIONS:
        minutes = selected[f"{q}_time"].map(parse_minutes)
        attempts = selected[f"{q}_attempts"].map(parse_attempts)
        out[f"{q}_minutes"] = minutes.map(lambda parsed: parsed[0]).astype("Float64")
        out[f"{q}_time_status"] = minutes.map(lambda parsed: parsed[1])
        out[f"{q}_attempts"] = attempts.map(lambda parsed: parsed[0]).astype("Float64")
        out[f"{q}_attempts_status"] = attempts.map(lambda parsed: parsed[1])
    out.insert(0, "pid", [f"S{i:02d}" for i in range(1, len(out) + 1)])
    stats = {"n_rows_raw": int(len(raw)), **stats, "n_other_recoded": recoded}
    return out.reset_index(drop=True)[SURVEY3_COLUMNS], stats, selected.index


def deidentify_survey3(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Survey 3: allowlisted columns, parsed numbers instead of free text, "Other" recoding, duplicate removal."""
    df, stats, _ = _deidentify_survey3(raw)
    return df, stats


def deidentify_survey3_with_times(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """deidentify_survey3 plus the private start and completion times of the kept rows (after dedupe and reorder)."""
    df, stats, rows = _deidentify_survey3(raw)
    return df, stats, private_times(raw, rows, df["pid"])


def _npi_unmatched(raw: pd.DataFrame, ids: Iterable[int]) -> pd.Series:
    """True for the raw rows whose Forms ID is listed (SAP v3.2). An ID the export lacks stops ingest (a count only)."""
    listed = set(ids)
    if not listed:
        return pd.Series(False, index=raw.index)
    forms_id = pd.to_numeric(raw[find_column(raw.columns, "exact", "ID")], errors="coerce")
    missing = len(listed - set(forms_id.dropna().astype(int)))
    if missing:
        raise ValueError(f"start: {missing} NPI-unmatched sign-up ID{'' if missing == 1 else 's'} not in the export")
    return forms_id.isin(listed)


def _deidentify_start(raw: pd.DataFrame, npi_unmatched_ids: Iterable[int] = ()
                      ) -> tuple[pd.DataFrame, dict, pd.Index]:
    selected = select_columns(raw, START_SPEC)
    completion = pd.to_datetime(selected["completion_time"])
    order = completion.sort_values(kind="stable").index
    selected, completion = selected.loc[order], completion.loc[order]
    out = pd.DataFrame(index=selected.index)
    out["signup_date"] = completion.dt.strftime("%Y-%m-%d")
    for column in START_OPTIONS:
        out[column] = selected[column].map(normalize_text)
    out.insert(0, "pid", [f"N{i:02d}" for i in range(1, len(out) + 1)])
    # SAP v3.2: flagged after the pids are assigned, so no pid moves (the Part F link file names Start pids)
    out["npi_unmatched"] = _npi_unmatched(raw, npi_unmatched_ids).loc[order].astype(bool)
    stats = {"n_rows_raw": int(len(raw))}
    if out["npi_unmatched"].any():
        stats["n_npi_unmatched"] = int(out["npi_unmatched"].sum())
    return out.reset_index(drop=True)[START_COLUMNS], stats, order


def deidentify_start(raw: pd.DataFrame, npi_unmatched_ids: Iterable[int] = ()) -> tuple[pd.DataFrame, dict]:
    """Start form: allowlisted closed questions; pid N01... by completion time (stable); signup_date = completion date.

    No contact column is read, so there is no duplicate check. `npi_unmatched` is True for the rows whose Forms ID
    is in `npi_unmatched_ids` (SAP v3.2); every row is kept, with the pid it has without the flag.
    """
    df, stats, _ = _deidentify_start(raw, npi_unmatched_ids)
    return df, stats


EXPORT_TIME_COLUMNS = ("Start time", "Completion time", "Last modified time")


def read_export(cfg, key: str) -> tuple[pd.DataFrame, dict]:
    """Read one raw export with the config's exclusions and time shift applied (SAP v3.0).

    Excluded rows (by Forms ID) are dropped first, and the index is then renumbered, so a worksheet's 1-based
    row numbers still count rows of the export as read. The shift moves every Forms timestamp by a whole number
    of hours, for an export downloaded in another time zone. Stats are counts only.
    """
    raw = pd.read_excel(cfg.inputs[key])
    excluded = set(cfg.exclude_ids.get(key, ()))
    if excluded:
        ids = pd.to_numeric(raw[find_column(raw.columns, "exact", "ID")], errors="coerce")
        missing = excluded - set(ids.dropna().astype(int))
        if missing:
            raise ValueError(f"{key}: {len(missing)} configured exclusion ID(s) not in the export")
        raw = raw[~ids.isin(excluded)].reset_index(drop=True)
    hours = cfg.time_shift_hours.get(key, 0.0)
    if hours:
        for column in EXPORT_TIME_COLUMNS:
            if column in raw.columns:
                raw[column] = pd.to_datetime(raw[column]) + pd.Timedelta(hours=hours)
    stats = {}
    if excluded:
        stats["n_excluded_by_config"] = len(excluded)
    if hours:
        stats["time_shift_hours"] = hours
    return raw, stats


def kept_positions(raw: pd.DataFrame, rows: pd.Index) -> list[int]:
    """0-based positions in the raw export of the kept rows, in output (pid) order. Private: never written."""
    positions = raw.index.get_indexer(rows)
    if (positions < 0).any():
        raise ValueError("kept rows are not all in the raw export")
    return [int(position) for position in positions]


def registration_links(cfg) -> tuple[pd.DataFrame, dict, tuple[pd.DataFrame, pd.DataFrame]]:
    """SAP Part F: the worksheet's raw row numbers -> pids, through the private kept-rows index of each export.

    The Phase 3 and Start exports are de-identified again here only to recover which raw row became which pid;
    the frames are returned so the caller can check they equal the ones it writes. Only the worksheet's two
    row-number columns and match_method are read; nothing from the worksheet is written or printed.
    """
    (phase3_raw, _), (start_raw, _) = read_export(cfg, "phase3"), read_export(cfg, "start")
    phase3_df, _, phase3_rows = _deidentify_phase3(phase3_raw)
    start_df, _, start_rows = _deidentify_start(start_raw, cfg.npi_unmatched_start_ids)
    readable = {*WORKSHEET_COLUMNS, *FOLLOWUP_WORKSHEET_COLUMNS}  # names, emails and notes are never read
    worksheet = pd.read_excel(cfg.inputs["phase3_registration_links"], usecols=lambda column: column in readable)
    links, stats = build_registration_links(
        worksheet, phase3_positions=kept_positions(phase3_raw, phase3_rows), phase3_pids=list(phase3_df["pid"]),
        n_phase3_raw=len(phase3_raw), start_positions=kept_positions(start_raw, start_rows),
        start_pids=list(start_df["pid"]), n_start_raw=len(start_raw),
        phase3_completion=list(phase3_df["completion_date"]))
    return links, stats, (phase3_df, start_df)


def write_csv(df: pd.DataFrame, path: Path) -> str:
    hits = find_pii(df)
    if hits:
        raise ValueError(f"refusing to write {path.name}: PII-shaped values in {hits}")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return sha256_file(path)


def run_ingest(config_path: str | Path) -> dict:
    cfg = load_config(config_path)
    link = "start" in cfg.inputs and "survey3" in cfg.inputs  # SAP Part C: link candidates need both
    roster = "part2_roster" in cfg.inputs and "survey3" in cfg.inputs  # SAP Part D: the roster link needs Survey 3
    registration = "phase3_registration_links" in cfg.inputs and "start" in cfg.inputs  # SAP Part F
    times_needed = link or roster
    phase3_reader = (deidentify_phase3_with_times_and_rows if roster else
                     deidentify_phase3_with_times if times_needed else deidentify_phase3)
    readers = {  # with linking, readers also return the private times (never written)
        "phase3": phase3_reader,
        "mcq_part1_A": lambda raw: (deidentify_mcq_with_times if link else deidentify_mcq)(raw, "A"),
        "mcq_part1_B": lambda raw: (deidentify_mcq_with_times if link else deidentify_mcq)(raw, "B"),
    }
    allowed = {key: ALLOWED_VALUES for key in readers}
    if "survey3" in cfg.inputs:  # optional input (SAP Part B)
        readers["survey3"] = deidentify_survey3_with_times if times_needed else deidentify_survey3
        allowed["survey3"] = SURVEY3_OPTIONS
    if "start" in cfg.inputs:  # optional input (SAP Part C)
        readers["start"] = lambda raw: deidentify_start(raw, cfg.npi_unmatched_start_ids)
        allowed["start"] = START_OPTIONS
    frames, times, phase3_rows = {}, {}, None
    for key, reader in readers.items():
        raw, read_stats = read_export(cfg, key)
        df, stats, *private = reader(raw)
        stats = {**stats, **read_stats}
        check_allowed_values(df, allowed[key])  # every input is validated before any file is written
        frames[key] = (df, stats)
        if private:
            times[key] = private[0]
        if len(private) > 1:  # the kept raw Phase 3 rows, held in memory for the roster link only
            phase3_rows = private[1]
    derived, roster_stats = {}, None
    if link:  # derived from other inputs, so these outputs have no manifest "inputs" entry
        mcq_times = {"A": times["mcq_part1_A"], "B": times["mcq_part1_B"]}
        derived["links_part1"] = part1_links(mcq_times, frames["survey3"][0], times["survey3"])
        derived["links_phase3"] = phase3_links(mcq_times, frames["phase3"][0], times["phase3"])
    if roster:  # SAP Part D: names are read here and never written or printed
        derived["links_roster"], derived["links_roster_alternatives"], roster_stats = build_roster_links(
            pd.read_csv(cfg.inputs["part2_roster"]), phase3_rows, frames["phase3"][0], frames["survey3"][0],
            times["survey3"])
    del times, phase3_rows
    registration_stats = None
    if registration:  # SAP Part F: the worksheet's names and emails are never read (usecols), written or printed
        derived[REGISTRATION_OUTPUT_KEY], registration_stats, (phase3_df, start_df) = registration_links(cfg)
        if not (phase3_df.equals(frames["phase3"][0]) and start_df.equals(frames["start"][0])):
            raise ValueError("sign-up link: re-derived Phase 3 or Start frame differs from the one written")
    feedback_stats = None
    if "survey3_feedback_codes" in cfg.inputs and "survey3" in cfg.inputs:  # SAP Part G: pid + 0/1 codes only
        raw_s3, s3_read = read_export(cfg, "survey3")  # re-derive which export row became which pid (private)
        _, _, s3_rows = _deidentify_survey3(raw_s3)
        if s3_read.get("n_excluded_by_config", 0) or kept_positions(raw_s3, s3_rows) != list(range(len(raw_s3))):
            raise ValueError("feedback codes are keyed by export row, but Survey 3 pids do not follow export rows "
                             "(a row was dropped, excluded or reordered)")
        derived[FEEDBACK_OUTPUT_KEY] = read_feedback_codes(cfg.inputs["survey3_feedback_codes"],
                                                           frames["survey3"][0]["pid"])
        feedback_stats = {"n_worksheet_rows": int(len(derived[FEEDBACK_OUTPUT_KEY])),
                          "n_substantive": int(derived[FEEDBACK_OUTPUT_KEY]["substantive"].sum())}

    manifest: dict = {"inputs": {}, "outputs": {}}
    for key, (df, stats) in frames.items():
        source = cfg.inputs[key]
        manifest["inputs"][key] = {"file": source.name, "sha256": sha256_file(source), **stats}
    if roster_stats is not None:
        source = cfg.inputs["part2_roster"]
        manifest["inputs"]["part2_roster"] = {"file": source.name, "sha256": sha256_file(source), **roster_stats}
    if registration_stats is not None:
        source = cfg.inputs["phase3_registration_links"]
        manifest["inputs"]["phase3_registration_links"] = {"file": source.name, "sha256": sha256_file(source),
                                                           **registration_stats}
    if feedback_stats is not None:
        source = cfg.inputs["survey3_feedback_codes"]
        manifest["inputs"]["survey3_feedback_codes"] = {"file": source.name, "sha256": sha256_file(source),
                                                        **feedback_stats}
    for key, df in {**{key: df for key, (df, _) in frames.items()}, **derived}.items():
        target = cfg.deidentified_dir / f"{key}.csv"
        manifest["outputs"][key] = {
            "file": target.relative_to(cfg.root).as_posix(),
            "sha256": write_csv(df, target),
            "n_rows": int(len(df)),
        }
    cfg.manifest.parent.mkdir(parents=True, exist_ok=True)
    cfg.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/study.toml")
    args = parser.parse_args(argv)
    manifest = run_ingest(args.config)
    for key, output in manifest["outputs"].items():
        if key in (*ROSTER_OUTPUT_KEYS, REGISTRATION_OUTPUT_KEY, FEEDBACK_OUTPUT_KEY):  # Part D and Part F link files: counts only
            print(f"{key}: {output['n_rows']} rows -> {output['file']}")
            continue
        if key not in manifest["inputs"]:  # link candidate files (SAP Part C): counts only
            print(f"{key}: {output['n_rows']} candidate pairs -> {output['file']}")
            continue
        stats = manifest["inputs"][key]
        dropped = stats.get("n_duplicates_dropped", 0)
        unchecked = (f"; {stats['n_without_contact_email']} without a contact email, not checked"
                     if "n_without_contact_email" in stats else "")
        if stats.get("n_npi_unmatched"):  # SAP v3.2: kept with their pids, left out of the sign-up count
            unchecked += f"; flagged NPI-unmatched {stats['n_npi_unmatched']}"
        if stats.get("n_other_recoded"):
            unchecked += "; recoded to Other: " + ", ".join(f"{c} {n}" for c, n in stats["n_other_recoded"].items())
        print(f"{key}: {stats['n_rows_raw']} raw rows -> {output['n_rows']} de-identified rows "
              f"({dropped} duplicates dropped{unchecked}) -> {output['file']}")
    if "phase3_registration_links" in manifest["inputs"]:  # SAP Part F: counts only
        stats = manifest["inputs"]["phase3_registration_links"]
        print(f"phase3_registration_links: {stats['n_worksheet_rows']} worksheet rows -> {stats['n_links']} links "
              f"({stats['n_by_basis']['record']} from records, {stats['n_by_basis']['timing']} by timing)")
    if "part2_roster" in manifest["inputs"]:  # SAP Part D: counts only, never a name, date or time
        stats = manifest["inputs"]["part2_roster"]
        demoted = stats["n_certain_collisions_demoted"]  # named only when it happens, as the ordinary case is 0
        collisions = f"; {demoted} demoted for claiming one response" if demoted else ""
        print(f"part2_roster: {stats['n_roster_rows']} roster rows -> {stats['n_links']} links "
              f"({stats['n_certain']} certain; {_plural(stats['n_ambiguous_groups'], 'ambiguous date group')} over "
              f"{_plural(stats['n_assignments'], 'assignment')}{collisions}); "
              f"{stats['n_unmatched_roster']} roster entries and "
              f"{stats['n_unmatched_phase3']} Phase 3 rows unmatched")
