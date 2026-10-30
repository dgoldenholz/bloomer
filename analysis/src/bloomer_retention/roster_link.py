"""Deterministic Survey 3 <-> Phase 3 link from a study-team roster of names and Part 2 dates (SAP Part D, D1).

Private: the roster's `name` column and the raw Phase 3 name columns are read here, in memory, and never written
or printed. The two output frames carry pseudonymous pids, a method label and a flag only - no name, date or time.
Errors name counts only, never a name, a date or a time.

Roster to Phase 3 is by normalised name: an exact key, then a unique two-token overlap, then the two weaker
fallbacks of a unique row carrying a single-token key and a unique row within the fuzzy ratio. Roster to Survey 3
is by the Part 2 date, narrowed by an optional clock time and by group agreement; ties that survive are
enumerated, and every consistent assignment of a date's roster entries to that date's responses is written to the
alternatives frame (assignment 0 is the primary one, which reproduces the links frame).
"""
from __future__ import annotations

import difflib
import itertools
import unicodedata
from collections.abc import Iterable

import pandas as pd

from bloomer_retention.answer_key import normalize_text
from bloomer_retention.survey3_forms import GROUP_BY_BLOOMER_PAPER

ROSTER_COLUMNS = ("name", "part2_date", "part2_time", "note")
# The two Phase 3 headers that can hold a name (the Forms respondent name and the gift-card identity question),
# each matched as the whole leading token of the normalised header - see `_header_matches`. Neither leaves here.
PHASE3_NAME_COLUMNS = ("Name", "Full Name-as on government ID")
TIME_TOLERANCE_HOURS = 6  # a clock time breaks a same-date tie only within this many hours
MIN_SHARED_TOKENS = 2  # tokens two names must share for the fallback match
FUZZY_RATIO = 0.85  # difflib.SequenceMatcher ratio between normalised keys for the weakest fallback
MAX_ASSIGNMENTS = 256  # cap on enumerated whole-roster assignments; the excess is flagged, never silently dropped
DEGREE_TOKENS = frozenset(("md", "do", "ms", "mph", "phd", "faan", "faes", "facns", "rn", "np", "dr"))
# In order of strength. The last two are weaker and are kept out of the Part D headline population (SAP D1).
NAME_METHODS = ("name_exact", "name_tokens", "name_single_token", "name_fuzzy")
SURVEY3_METHODS = ("date_unique", "date_time", "group_resolved", "enumerated")
LINK_COLUMNS = ["s3_pid", "p3_pid", "name_method", "method", "certain"]
ALTERNATIVE_COLUMNS = ["assignment_id", "s3_pid", "p3_pid"]
DATE_FORMAT = "ISO8601"


def normalize_name(value: object) -> str:
    """Comparison key: lower case, no accents, no bracketed text, no degree tokens, alphabetic tokens sorted.

    "Rivera, Ana M., MD", "Ana M. Rivera" and "RIVERA Ana M (Annie)" all give "ana m rivera".
    Blank, missing and degree-only values give "", which never matches anything.
    """
    text = normalize_text(value)
    if text is None:
        return ""
    depth, kept = 0, []
    for character in text:  # drop bracketed text (nicknames, "(retired)") without a regex over nested brackets
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            kept.append(character)
    stripped = unicodedata.normalize("NFKD", "".join(kept))
    folded = "".join(c for c in stripped if not unicodedata.combining(c)).casefold()
    tokens = []
    for token in "".join(c if c.isalpha() else " " for c in folded).split():
        if token not in DEGREE_TOKENS:
            tokens.append(token)
    return " ".join(sorted(tokens))


def _header_matches(header: str, target: str) -> bool:
    """True when `target` is the whole of `header`'s leading token, allowing a same-token export suffix.

    The rule is the target being a whole prefix *token* of the header, not a bare "starts with": an alphabetic
    continuation makes a different word ("Names", "Nameplate of the practice"), and whitespace starts a further
    word, so the header is a longer question ("Name of your institution"). Only punctuation or a digit may follow,
    which keeps the Forms duplicate-question suffix ("Name2") and the gift-card header's own "-as on government
    ID" working. A header that is merely a longer question contributes free text to the row's name keys, where it
    can produce a spurious exact match (the wrong person linked), a spurious two-token overlap, or a spurious
    "claimed by more than one roster entry" abort.
    """
    if not header.startswith(target):
        return False
    rest = header[len(target):]
    return not rest or not (rest[0].isalpha() or rest[0].isspace())


def name_columns(columns: Iterable[object]) -> list[object]:
    """The Phase 3 name columns present in a raw export, matched on the target as a whole leading token."""
    targets = [normalize_text(text) for text in PHASE3_NAME_COLUMNS]
    return [column for column in columns
            if any(_header_matches(normalize_text(column) or "", target) for target in targets)]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _check_frames(roster: pd.DataFrame, phase3_raw: pd.DataFrame, phase3_public: pd.DataFrame) -> None:
    missing = [column for column in ROSTER_COLUMNS if column not in roster.columns]
    if missing:
        raise ValueError("part2_roster is missing columns: " + ", ".join(missing))
    if len(phase3_raw) != len(phase3_public):
        raise ValueError(f"part2_roster linkage needs aligned Phase 3 frames: "
                         f"{_plural(len(phase3_raw), 'raw Phase 3 row')} for "
                         f"{_plural(len(phase3_public), 'de-identified row')}")


def _roster_keys(roster: pd.DataFrame) -> list[str]:
    keys = [normalize_name(value) for value in roster["name"]]
    seen: dict[str, int] = {}
    for key in keys:
        if key:
            seen[key] = seen.get(key, 0) + 1
    duplicates = sum(1 for count in seen.values() if count > 1)
    if duplicates:
        raise ValueError(f"part2_roster has {_plural(duplicates, 'duplicate normalised name')}")
    return keys


def _roster_dates(roster: pd.DataFrame) -> pd.Series:
    text = roster["part2_date"].astype("string")
    parsed = pd.to_datetime(text, errors="coerce", format=DATE_FORMAT)
    unparseable = int((text.notna() & parsed.isna()).sum() + text.isna().sum())
    if unparseable:
        raise ValueError(f"part2_roster has {unparseable} unparseable part2_date "
                         f"{'value' if unparseable == 1 else 'values'}")
    return parsed.dt.normalize()


def _roster_times(roster: pd.DataFrame, dates: pd.Series) -> tuple[list[pd.Timestamp | None], int]:
    """Part 2 clock times as timestamps on their Part 2 date; an unreadable or blank time is treated as absent."""
    text = roster["part2_time"].astype("string")
    combined = pd.Series([None if pd.isna(value) else f"{day.date().isoformat()} {value}"
                          for value, day in zip(text, dates)], index=text.index, dtype="string")
    parsed = pd.to_datetime(combined, errors="coerce", format=DATE_FORMAT)
    unparsed = int((text.notna() & parsed.isna()).sum())  # both carry the roster's index, as in _roster_dates
    return [None if pd.isna(stamp) else stamp for stamp in parsed], unparsed


def _phase3_keys(phase3_raw: pd.DataFrame) -> list[set[str]]:
    columns = name_columns(phase3_raw.columns)
    keys = []
    for _, row in phase3_raw.reset_index(drop=True).iterrows():
        keys.append({key for key in (normalize_name(row[column]) for column in columns) if key})
    return keys


def _fuzzy_rows(key: str, phase3_keys: list[set[str]]) -> list[int]:
    """Every Phase 3 row within FUZZY_RATIO of the roster key.

    There is no "best ratio": a step that finds more than one candidate leaves the entry unmatched (spec section 3
    step 5), so two rows above the threshold reject the match rather than letting the closer one win. Names that
    differ by one letter score well above 0.85 on this normalisation and are plausibly two different people, and a
    wrong link is undetectable downstream, so rejecting is the only safe resolution.
    """
    return [row for row, keys in enumerate(phase3_keys)
            if any(difflib.SequenceMatcher(None, key, other).ratio() >= FUZZY_RATIO for other in keys)]


def _name_match(key: str, phase3_keys: list[set[str]]) -> tuple[int | None, str | None]:
    """The Phase 3 row a roster key names, and the step that found it.

    Steps, in order: the exact normalised key; a unique two-token overlap; a unique row carrying a single-token
    key as one of its own tokens; a unique row within FUZZY_RATIO. A step that finds more than one candidate does
    not fall through to a weaker step: the entry is left unmatched.
    """
    tokens = set(key.split())
    steps = [
        ("name_exact", [row for row, keys in enumerate(phase3_keys) if key in keys]),
        ("name_tokens", [row for row, keys in enumerate(phase3_keys)
                         if any(len(tokens & set(other.split())) >= MIN_SHARED_TOKENS for other in keys)]),
        ("name_single_token", [row for row, keys in enumerate(phase3_keys)
                               if any(key in set(other.split()) for other in keys)] if len(tokens) == 1 else []),
        ("name_fuzzy", _fuzzy_rows(key, phase3_keys)),
    ]
    for method, rows in steps:
        if len(rows) == 1:
            return rows[0], method
        if rows:
            return None, None  # more than one candidate at this step: unmatched and counted
    return None, None


def _match_phase3(roster_keys: list[str], phase3_keys: list[set[str]]) -> tuple[dict[int, int], dict[int, str]]:
    """Roster row -> Phase 3 row and the step that found it (_name_match).

    A roster entry with no match, or with more than one at a step, is left unmatched. Raises when one Phase 3 row
    is claimed by two roster entries (counts only).
    """
    matched: dict[int, int] = {}
    methods: dict[int, str] = {}
    for entry, key in enumerate(roster_keys):
        if not key:
            continue
        row, method = _name_match(key, phase3_keys)
        if row is not None:
            matched[entry], methods[entry] = row, method
    claimed: dict[int, int] = {}
    for row in matched.values():
        claimed[row] = claimed.get(row, 0) + 1
    contested = sum(1 for count in claimed.values() if count > 1)
    if contested:
        raise ValueError(f"{_plural(contested, 'Phase 3 row')} "
                         f"{'is' if contested == 1 else 'are'} claimed by more than one roster entry")
    return matched, methods


def _survey3_candidates(entry_date: pd.Timestamp, entry_time: pd.Timestamp | None, p3_group: object,
                        by_date: dict[str, list[str]], completion: dict[str, pd.Timestamp],
                        s3_groups: dict[str, object]) -> tuple[list[str], str]:
    """Same-date Survey 3 responses, narrowed by the clock time and then by group agreement."""
    candidates = list(by_date.get(entry_date.date().isoformat(), []))
    method = "date_unique"
    if len(candidates) > 1 and entry_time is not None:
        gaps = {pid: abs((completion[pid] - entry_time).total_seconds()) / 3600 for pid in candidates}
        nearest = min(candidates, key=lambda pid: (gaps[pid], pid))
        if gaps[nearest] <= TIME_TOLERANCE_HOURS:
            candidates, method = [nearest], "date_time"
    if len(candidates) > 1 and isinstance(p3_group, str):
        agreeing = [pid for pid in candidates
                    if not isinstance(s3_groups.get(pid), str) or s3_groups[pid] == p3_group]
        if agreeing and len(agreeing) < len(candidates):
            candidates = agreeing
            if len(candidates) == 1:
                method = "group_resolved"
    return candidates, method


def _assignments(entries: list[int], options: dict[int, list[str]], taken: set[str]) -> list[list[tuple[str, int]]]:
    """Every injective assignment of a date's pending entries to that date's free responses, in candidate order."""
    found: list[list[tuple[str, int]]] = []

    def walk(position: int, used: set[str], chosen: list[tuple[str, int]]) -> None:
        if position == len(entries):
            found.append(list(chosen))
            return
        entry = entries[position]
        for pid in options[entry]:
            if pid in used:
                continue
            chosen.append((pid, entry))
            walk(position + 1, used | {pid}, chosen)
            chosen.pop()

    walk(0, set(taken), [])
    return found


def build_roster_links(roster: pd.DataFrame, phase3_raw: pd.DataFrame, phase3_public: pd.DataFrame,
                       survey3_public: pd.DataFrame, survey3_times: pd.DataFrame,
                       ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Roster -> (links, alternatives, stats), implementing SAP Part D section D1.

    `phase3_raw` holds the kept raw Phase 3 rows in the order of `phase3_public` (ingest passes `raw.loc[rows]`);
    only its name columns are read. `survey3_times` supplies the private Survey 3 completion times used for the
    clock-time tie-break; no time is written.

    links: [s3_pid, p3_pid, name_method, method, certain]. `name_method` names the step that found the Phase 3
    row and `method` the step that resolved the Survey 3 response.
    alternatives: [assignment_id, s3_pid, p3_pid], every consistent whole-roster assignment, 0 being the primary.
    stats: counts only, for the manifest and the Part D link-quality section.
    """
    _check_frames(roster, phase3_raw, phase3_public)
    roster_keys = _roster_keys(roster)
    dates = _roster_dates(roster)
    times, n_time_unparsed = _roster_times(roster, dates)
    matched, name_methods = _match_phase3(roster_keys, _phase3_keys(phase3_raw))

    p3_pids = list(phase3_public["pid"])
    p3_groups = list(phase3_public["group"])
    by_date: dict[str, list[str]] = {}
    for pid, day in zip(survey3_public["pid"], survey3_public["completion_date"]):
        by_date.setdefault(str(day), []).append(pid)
    completion = dict(zip(survey3_times["pid"], pd.to_datetime(survey3_times["completion_time"])))
    s3_groups = {pid: GROUP_BY_BLOOMER_PAPER.get(paper) for pid, paper in
                 zip(survey3_public["pid"], survey3_public["bloomer_paper"])}

    certain: list[tuple[str, int, str]] = []  # (s3 pid, phase3 row, method)
    resolved: list[tuple[int, str, str]] = []  # (roster entry, its only candidate, method) before collision checks
    pending_options: dict[int, list[str]] = {}
    pending_by_date: dict[str, list[int]] = {}
    n_unmatched_survey3 = 0
    for entry in sorted(matched):
        row = matched[entry]
        candidates, method = _survey3_candidates(dates.iloc[entry], times[entry], p3_groups[row], by_date,
                                                 completion, s3_groups)
        if not candidates:
            n_unmatched_survey3 += 1
        elif len(candidates) == 1:
            resolved.append((entry, candidates[0], method))
        else:
            pending_options[entry] = sorted(candidates)
            pending_by_date.setdefault(dates.iloc[entry].date().isoformat(), []).append(entry)

    # Entries are narrowed independently, so two of them can be left holding the same Survey 3 response - one
    # response cannot be two people. Rather than letting both claim it (which would attribute one person's data to
    # another), every claimant of a contested response is demoted into the enumeration path over that date's
    # responses (spec section 3 step 4); a date that cannot seat them all injectively yields no assignment, and
    # they are left unmatched.
    claims: dict[str, list[int]] = {}
    for entry, pid, _ in resolved:
        claims.setdefault(pid, []).append(entry)
    contested = {entry for entries in claims.values() if len(entries) > 1 for entry in entries}
    for entry, pid, method in resolved:
        if entry not in contested:
            certain.append((pid, matched[entry], method))
            continue
        day = dates.iloc[entry].date().isoformat()
        pending_options[entry] = sorted(by_date.get(day, []))
        pending_by_date.setdefault(day, []).append(entry)
    for entries in pending_by_date.values():
        entries.sort()  # demoted entries join their date group in roster order, so enumeration stays deterministic

    taken = {pid for pid, _, _ in certain}
    groups: list[list[list[tuple[str, int]]]] = []
    ambiguous_sizes: list[int] = []
    for day in sorted(pending_by_date):
        entries = pending_by_date[day]
        options = _assignments(entries, pending_options, taken)
        if not options:
            n_unmatched_survey3 += len(entries)
            continue
        groups.append(options)
        if len(options) > 1:
            ambiguous_sizes.append(len(entries))

    by_row = {row: name_methods[entry] for entry, row in matched.items()}  # one entry per row (claims are checked)
    primary = [(pid, row, "enumerated", len(options) == 1) for options in groups for pid, row in options[0]]
    rows = [{"s3_pid": pid, "p3_pid": p3_pids[row], "name_method": by_row[row], "method": method, "certain": True}
            for pid, row, method in certain]
    rows += [{"s3_pid": pid, "p3_pid": p3_pids[row], "name_method": by_row[row], "method": method, "certain": sure}
             for pid, row, method, sure in primary]
    links = pd.DataFrame(rows, columns=LINK_COLUMNS)
    links["certain"] = links["certain"].astype(bool)
    links = links.sort_values(["s3_pid", "p3_pid"], kind="stable").reset_index(drop=True)

    base = [(pid, p3_pids[row]) for pid, row, _ in certain]
    total = 1
    for options in groups:
        total *= len(options)
    alternative_rows = []
    for assignment_id, combination in enumerate(itertools.product(*groups)):
        if assignment_id >= MAX_ASSIGNMENTS:
            break
        pairs = base + [(pid, p3_pids[row]) for chosen in combination for pid, row in chosen]
        alternative_rows += [{"assignment_id": assignment_id, "s3_pid": pid, "p3_pid": p3}
                             for pid, p3 in sorted(pairs)]
    alternatives = pd.DataFrame(alternative_rows, columns=ALTERNATIVE_COLUMNS)

    stats = {
        "n_roster_rows": int(len(roster)),
        "n_by_name_method": {method: sum(1 for value in name_methods.values() if value == method)
                             for method in NAME_METHODS},
        "n_by_method": {method: int((links["method"] == method).sum()) for method in SURVEY3_METHODS},
        "n_links_by_name_method": {method: int((links["name_method"] == method).sum()) for method in NAME_METHODS},
        "n_links": int(len(links)),
        "n_certain": int(links["certain"].sum()),
        "n_certain_collisions_demoted": len(contested),
        "n_ambiguous_groups": len(ambiguous_sizes),
        "ambiguous_group_sizes": ambiguous_sizes,
        "n_assignments": min(total, MAX_ASSIGNMENTS),
        "assignments_truncated": total > MAX_ASSIGNMENTS,
        "n_unmatched_roster_phase3": int(len(roster) - len(matched)),
        "n_unmatched_roster_survey3": n_unmatched_survey3,
        "n_unmatched_roster": int(len(roster) - len(links)),
        "n_unmatched_phase3": int(len(phase3_public) - links["p3_pid"].nunique()),
        "n_part2_time_unparsed": n_time_unparsed,
    }
    return links, alternatives, stats
