"""`changes_since_<tag>.md`: what moved between a previous tag and the current outputs (SAP E5, design section 7).

The previous tag's results are read out of git with `git show <tag>:outputs/...`, so nothing is checked out and the
working tree is untouched.

This is the one place in the bundle that does arithmetic: the old-to-new difference of a key. It is a property of
two runs, not a study statistic, and it never reaches a table, a figure, the supplement or the numbers index - the
change report is a reviewer's aid, not manuscript text (SAP E5).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bloomer_retention.bundle.format import MISSING, fmt_num, row
from bloomer_retention.bundle.load import PART_FILES, BundleError, Results, results_from
from bloomer_retention.bundle.numbers import sort_key


def git_show(root: str | Path, spec: str) -> str:
    """`git show <tag>:<path>` without checking anything out."""
    try:
        done = subprocess.run(["git", "-C", str(root), "show", spec], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise BundleError("git is not available, so the change report cannot read the comparison tag") from None
    except subprocess.CalledProcessError as err:
        raise BundleError(f"cannot read {spec} out of git: {err.stderr.strip() or 'no such tag or path'}") from None
    return done.stdout


MANUSCRIPT_INDEX = "manuscript/manuscript_numbers.json"


def tag_index(root: str | Path, tag: str, outputs_dir: str = "outputs") -> dict[str, dict] | None:
    """The numbers index the tag actually committed, or None when that release committed none.

    This is the only record of what a previous release really reported. The value comparison cannot see it: it
    rebuilds the tag's numbers with today's builders, so for a change that altered only what is reported -
    the old results files being untouched - every key today asks for is present in them and nothing shows.
    """
    spec = f"{tag}:{outputs_dir}/{MANUSCRIPT_INDEX}"
    try:
        payload = json.loads(git_show(root, spec))
    except BundleError:
        return None  # the tag exists (its results files were just read); this release published no index
    except json.JSONDecodeError as err:
        raise BundleError(f"{spec}: not valid JSON ({err})") from None
    # the file's own `_readme` note is not a reported number
    return {key: entry for key, entry in payload.items() if isinstance(entry, dict)}


def tag_results(root: str | Path, tag: str, outputs_dir: str = "outputs") -> Results:
    """The four results JSONs as the tag holds them, checked by the same provenance guard as the current ones."""
    parts, files = {}, {}
    for part, name in PART_FILES.items():
        spec = f"{tag}:{outputs_dir}/{name}"
        try:
            parts[part] = json.loads(git_show(root, spec))
        except json.JSONDecodeError as err:
            raise BundleError(f"{spec}: not valid JSON ({err})") from None
        files[part] = spec
    return results_from(parts, files)


@dataclass(frozen=True)
class Change:
    key: str
    old: dict
    new: dict

    @property
    def difference(self) -> float | None:
        old, new = self.old["value"], self.new["value"]
        if isinstance(old, bool) or isinstance(new, bool) or not isinstance(old, (int, float)) \
                or not isinstance(new, (int, float)):
            return None
        return new - old

    @property
    def relative(self) -> float | None:
        difference = self.difference
        if difference is None or not self.old["value"]:
            return None
        return difference / self.old["value"]


def compare(old: dict[str, dict], new: dict[str, dict], *, ignore: set[str] | frozenset[str] = frozenset()
            ) -> dict[str, list]:
    """Keys added, removed and changed. A key whose value is unchanged is not reported, even by zero.

    `ignore` holds the keys of blocks that could not be rebuilt from the previous tag: absent from the old index
    for a reason that says nothing about the numbers, so they are left out rather than reported as added.
    """
    added = [key for key in new if key not in old and key not in ignore]
    removed = [key for key in old if key not in new and key not in ignore]
    changed = [Change(key, old[key], new[key]) for key in new
               if key in old and key not in ignore and old[key]["value"] != new[key]["value"]]
    return {
        "added": sorted(added, key=sort_key),
        "removed": sorted(removed, key=sort_key),
        "changed": sorted(changed, key=lambda change: sort_key(change.key)),
    }


def _difference_text(difference: float) -> str:
    """Four decimals, trailing zeros trimmed - except that a real difference is never trimmed away to `0`.

    A row whose Difference column reads `0` beside a Relative column reading a real percentage reads as a bug in
    the report, and a reader who decides one column is broken stops trusting the other; too small to show at four
    decimals is shown in exponent form instead.
    """
    text = fmt_num(difference, 4).rstrip("0").rstrip(".") or "0"
    if difference and text.lstrip("-") == "0":
        return f"{difference:.1e}"
    return text


def _difference_cells(change: Change) -> tuple[str, str]:
    difference, relative = change.difference, change.relative
    absolute = MISSING if difference is None else _difference_text(difference)
    return absolute, MISSING if relative is None else f"{100 * relative:.1f}%"


def render_reported_set(*, tag: str, reported_old: dict[str, dict] | None,
                        new_index: dict[str, dict]) -> list[str]:
    """What the set of reported numbers gained and lost since the tag published one.

    A separate question from the one above it, and labelled so the two cannot be read as the same: that section
    asks whether a number moved, this one asks whether the numbers reported are the same numbers.

    Keys the bundle no longer reports are listed without their values; see the comment below for why that is not
    an oversight.
    """
    lines = ["", f"## Reported set since `{tag}`", ""]
    if reported_old is None:
        lines.append(f"Not comparable: `{tag}` committed no `outputs/{MANUSCRIPT_INDEX}`, so there is no record "
                     "of which numbers that release reported. Releases made before the manuscript bundle "
                     "existed have none.")
        return lines
    lines += ["The comparison above rebuilds this tag's numbers with today's builders, so it answers whether a "
              "number moved, and a change that altered only what is reported moves none. This compares "
              f"today's index against the one `{tag}` committed, which is what that release actually published, "
              "so it answers whether the set of reported numbers changed. A key the bundle no longer reports is "
              "listed by key and source only; its last published value is in that release's own committed "
              f"index, `{tag}:outputs/{MANUSCRIPT_INDEX}`, under whatever restriction that index carried.", ""]
    added = sorted((key for key in new_index if key not in reported_old), key=sort_key)
    removed = sorted((key for key in reported_old if key not in new_index), key=sort_key)
    # "No longer reported" prints no Value column, and must not be given one back. A key leaves the reported set
    # because the bundle stopped printing it, and one reason for that is disclosure: version 2.3 dropped Table
    # 2's subspecialty-by-adoption footnote because a single-respondent cell, beside the group the table already
    # printed, identified that respondent's Q25 answer. Listing those sixteen values here republished exactly
    # what had been removed, one file over. Nothing is lost by the omission - the value is in the previous
    # release's committed index, which carries that release's own restrictions. Note that neither S6's rules nor
    # the index's `restricted` flag would have caught it, because both key off the `partd.` prefix and these are
    # `demographics.` rows; widening that prefix is not the fix. The rule is that a value withdrawn for
    # disclosure reasons is not reprinted anywhere, whatever its key happens to begin with.
    for label, empty, keys, index, with_value in (
            ("Now reported", "No key is newly reported.", added, new_index, True),
            ("No longer reported", "No key stopped being reported.", removed, reported_old, False)):
        lines += [f"### {label} ({len(keys)})", ""]
        if keys:
            headers = ["Key", "Value", "Source"] if with_value else ["Key", "Source"]
            lines += [row(headers), row([MISSING * 3] * len(headers))]
            lines += [row([f"`{key}`", *([index[key]["formatted"]] if with_value else []),
                           f"`{index[key]['source']}`"]) for key in keys]
        else:
            lines.append(empty)
        lines.append("")
    return lines[:-1]


def render_changes(*, tag: str, old_results: Results, new_results: Results, old_index: dict[str, dict],
                   new_index: dict[str, dict], changes: dict[str, list], problems: list[str] | None = None,
                   n_skipped: int = 0, reported_old: dict[str, dict] | None = None) -> str:
    lines = [
        f"# Manuscript numbers changed since `{tag}`",
        "",
        row(["", f"`{tag}`", "Current outputs"]),
        row([MISSING * 3] * 3),
        row(["Code commit", f"`{old_results.code_commit}`", f"`{new_results.code_commit}`"]),
        row(["SAP version", old_results.sap_version, new_results.sap_version]),
        "",
        # "Changed (0)" at the top of a report that could not compare 40% of the index reads as "nothing moved"
        "Flow counts are listed first, then the primary outcome, then everything else: a changed n explains most "
        "changed estimates. A key whose value did not move is not listed."
        + (f" {n_skipped} of the {len(new_index)} keys in the current index could not be compared against "
           f"`{tag}` at all; they are listed under \"Not compared\" at the end." if n_skipped else ""),
        "",
        f"## Changed ({len(changes['changed'])})",
        "",
    ]
    if changes["changed"]:
        lines += [row(["Key", "Old", "New", "Difference", "Relative", "Source"]), row([MISSING * 3] * 6)]
        for change in changes["changed"]:
            absolute, relative = _difference_cells(change)
            lines.append(row([f"`{change.key}`", change.old["formatted"], change.new["formatted"], absolute,
                              relative, f"`{change.new['source']}`"]))
    else:
        lines.append("No reported number changed.")
    for label, keys, index in (("Added", changes["added"], new_index), ("Removed", changes["removed"], old_index)):
        lines += ["", f"## {label} ({len(keys)})", ""]
        if keys:
            lines += [row(["Key", "Value", "Source"]), row([MISSING * 3] * 3)]
            lines += [row([f"`{key}`", index[key]["formatted"], f"`{index[key]['source']}`"]) for key in keys]
        else:
            lines.append(f"No key was {label.lower()}.")
    if problems:
        lines += ["", f"## Not compared ({len(problems)})", "",
                  f"These blocks could not be rebuilt from `{tag}`, because the analysis layer did not write a key "
                  f"they need at that version. The {n_skipped} keys they carry are left out of the comparison "
                  "above rather than reported as added. A block lands here when a later SAP version added the keys "
                  "it reads, as a version adding reporting-support keys does.", ""]
        lines += [f"- {problem}" for problem in problems]
    lines += render_reported_set(tag=tag, reported_old=reported_old, new_index=new_index)
    return "\n".join(lines) + "\n"
