"""Loading, dotted-path lookup and the provenance guard for the manuscript bundle (SAP E1).

Every value the bundle reports is fetched with `get()`, whose first path segment names the results file, so each
reported number carries the source path that produced it and a typo becomes a loud failure instead of a blank cell.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# part name -> results file; the part name is the first segment of every dotted path, so `results.primary.theta`
# reads outputs/results.json and `partd_results.flow.analysed` reads outputs/partd_results.json (spec section 4).
PART_FILES: dict[str, str] = {
    "results": "results.json",
    "survey3_results": "survey3_results.json",
    "partc_results": "partc_results.json",
    "partd_results": "partd_results.json",
}
SAP_VERSION = re.compile(r"\bv(\d+(?:\.\d+)*)\b")


class BundleError(RuntimeError):
    """Any failure that makes the bundle unsafe to write; the runner exits 6 having written nothing."""


class MissingResultError(BundleError, KeyError):
    """A dotted path that no results JSON holds: the spec asked for a number the analysis layer never wrote."""

    def __init__(self, path: str, file: str, detail: str) -> None:
        super().__init__(f"{path}: {detail} (looked in {file})")
        self.path, self.file = path, file

    def __str__(self) -> str:  # KeyError would repr the message and add quotes
        return str(self.args[0])


class ProvenanceMismatchError(BundleError):
    """The results files come from different runs, so they must never be assembled into one manuscript."""


@dataclass(frozen=True)
class Results:
    """The four results JSONs, with the code commit and SAP version every one of them agrees on."""

    parts: dict[str, dict]
    files: dict[str, str]
    sap_version: str
    code_commit: str

    def __getitem__(self, part: str) -> dict:
        if part not in self.parts:
            raise MissingResultError(part, "the bundle", f"unknown results file; known: {', '.join(self.parts)}")
        return self.parts[part]

    def __contains__(self, part: str) -> bool:
        return part in self.parts

    def file(self, part: str) -> str:
        return self.files.get(part, "the bundle")


def _sap_version(text: str, file: str) -> str:
    """The version inside a `sap` string such as 'SAP.md v2.1 (Part B)'; the part suffix is not part of it."""
    found = SAP_VERSION.search(text)
    if found is None:
        raise ProvenanceMismatchError(f"{file}: 'sap' string {text!r} carries no vN.N version")
    return found.group(1)


def check_provenance(parts: dict[str, dict], files: dict[str, str]) -> tuple[str, str]:
    """Every results file must carry the same code commit and the same SAP version (spec section 3)."""
    commits, versions = {}, {}
    for part, data in parts.items():
        if part not in files:
            raise BundleError(f"no file recorded for {part!r}: the bundle was handed a partial results map, so it "
                              "cannot say which file a number came from")
        file = files[part]
        for key in ("provenance", "sap"):
            if key not in data:
                raise ProvenanceMismatchError(f"{file}: no {key!r} key")
        if "code_commit" not in data["provenance"]:
            raise ProvenanceMismatchError(f"{file}: no 'provenance.code_commit' key")
        commits[file] = data["provenance"]["code_commit"]
        versions[file] = _sap_version(data["sap"], file)
    for label, found in (("code_commit", commits), ("SAP version", versions)):
        if len(set(found.values())) > 1:
            listed = "; ".join(f"{file} {value}" for file, value in sorted(found.items()))
            raise ProvenanceMismatchError(
                f"results files disagree on {label} ({listed}): they come from different runs, so they must not be "
                "assembled into one manuscript; re-run the analysis and commit all four outputs together"
            )
    return next(iter(commits.values())), next(iter(versions.values()))


def results_from(parts: dict[str, dict], files: dict[str, str] | None = None) -> Results:
    """Build a checked `Results` from already-parsed JSON (the tests plant dicts; `load_results` reads files)."""
    named = files or {part: f"{part}.json" for part in parts}
    commit, version = check_provenance(parts, named)
    return Results(parts=dict(parts), files=dict(named), sap_version=version, code_commit=commit)


def load_results(outputs_dir: str | Path) -> Results:
    """Read the four committed results JSONs. Nothing under data/ is read: the bundle never touches row-level data."""
    directory = Path(outputs_dir)
    parts, files = {}, {}
    for part, name in PART_FILES.items():
        path = directory / name
        if not path.is_file():
            raise BundleError(f"{path}: no such results file; run `make analyze` before `make report`")
        try:
            parts[part] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise BundleError(f"{path}: not valid JSON ({err})") from None
        files[part] = path.as_posix()
    return results_from(parts, files)


ESCAPE = "\\"


def escape_segment(segment: str) -> str:
    return str(segment).replace(ESCAPE, ESCAPE * 2).replace(".", ESCAPE + ".")


def join_path(*segments: str) -> str:
    """A dotted path whose segments may themselves contain dots, such as a form option written as a JSON key."""
    return ".".join(escape_segment(segment) for segment in segments)


def child(path: str, *segments: str) -> str:
    """Extend an already-built path with literal segments that may contain dots."""
    return ".".join([path, *(escape_segment(segment) for segment in segments)])


def split_path(path: str) -> list[str]:
    """Split on unescaped dots; `a.b\\.c` is two segments, `a` and `b.c`."""
    segments, current, escaping = [], [], False
    for character in path:
        if escaping:
            current.append(character)
            escaping = False
        elif character == ESCAPE:
            escaping = True
        elif character == ".":
            segments.append("".join(current))
            current = []
        else:
            current.append(character)
    segments.append("".join(current))
    return [s for s in segments if s != ""]


def list_index(segment: str) -> int | None:
    """A path segment read as a list index, or None when it is not one: `label`, `--1` and `1_0` are not."""
    if not segment.lstrip("-").isdigit():
        return None
    try:
        return int(segment)
    except ValueError:  # `--1` survives the digit check above but is not an integer
        return None


def get(results: Results, path: str):
    """Value at a dotted path such as `results.primary.headline.theta`; a digit segment indexes a list.

    A segment that contains a dot (a form option used as a JSON key) is escaped by `join_path`.
    Raises `MissingResultError` (a `KeyError`) naming the full path and the file it was looked for in.
    """
    segments = split_path(path)
    part = segments[0] if segments else ""
    if part not in results:
        raise MissingResultError(path, "the bundle",
                                 f"unknown results file {part!r}; known: {', '.join(results.parts)}")
    node = results[part]
    walked = part
    for segment in segments[1:]:
        file = results.file(part)
        if isinstance(node, dict):
            if segment not in node:
                raise MissingResultError(path, file, f"no key {segment!r} under {walked!r}")
            node = node[segment]
        elif isinstance(node, list):
            index = list_index(segment)
            if index is None:
                raise MissingResultError(path, file, f"{walked!r} is a list; {segment!r} is not an index")
            if not -len(node) <= index < len(node):
                raise MissingResultError(path, file, f"{walked!r} has {len(node)} entries; no index {segment}")
            node = node[index]
        else:
            raise MissingResultError(path, file, f"{walked!r} is {type(node).__name__}, not a dict or list")
        walked = f"{walked}.{segment}"
    return node
