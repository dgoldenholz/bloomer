"""Stage 3: `make report` / `bloomer-report` (SAP E1).

Reads only the committed, de-identified `outputs/*.json` (plus `SAP.md` for the Part E prose and its version
line, and the analysed figures it copies). Writes everything under `outputs/manuscript/`. Any failure exits 6
having written nothing: the bundle is built in a temporary directory beside the target and moved into place only
once every file exists.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from contextlib import suppress
from pathlib import Path

from bloomer_retention.bundle import EXIT_CODE
from bloomer_retention.bundle.changes import compare, render_changes, tag_index, tag_results
from bloomer_retention.bundle.figures import build_figures, captions, render_captions
from bloomer_retention.bundle.format import Num, numbers_in, render_csv, render_markdown, write_json
from bloomer_retention.bundle.load import BundleError, MissingResultError, Results, load_results
from bloomer_retention.bundle.numbers import build_index, index_file
from bloomer_retention.bundle.supplement import (
    PUBLIC_HEAD,
    RESTRICTED_HEAD,
    RESTRICTED_SUPPLEMENT,
    Section,
    build_supplement,
    read_sap,
    render_supplement,
    section_builders,
    split_sections,
)
from bloomer_retention.bundle.tables import BUILDERS, LATER_TABLES, Table, build_tables, render_all_markdown

MANUSCRIPT_DIR = "manuscript"
STAGING_DIR = ".manuscript.staging"
PREVIOUS_DIR = ".manuscript.previous"
SAP_FILE = "SAP.md"


def _ignore_vanished(function, path, exc_info) -> None:
    """Swallow an entry that has already gone; re-raise anything else.

    `shutil.rmtree` is given this as its `onerror` hook (the 3.11 spelling; this project pins Python 3.11).
    A file that is no longer there is the outcome the caller wanted, not a failure to retry.
    """
    error = exc_info[1]
    if not isinstance(error, FileNotFoundError):
        raise error


def remove_tree(path: Path) -> None:
    """Delete a directory, tolerating the exFAT drive's AppleDouble sidecars.

    This repository lives on an exFAT volume, where macOS writes an AppleDouble `._x` sidecar beside every file
    `x`, and deleting `x` removes `._x` with it. `rmtree` lists a directory's entries before it deletes any of
    them, so it always reaches a sidecar that its own previous delete has already taken away. Retrying whole
    passes cleared about one file per pass and then raised - on a 29-file bundle that meant a `FileNotFoundError`
    out of `publish()`, after the swap, so the run published a bundle and reported writing nothing. Skipping the
    vanished entry and carrying on inside one pass is the fix; anything else still raises.
    """
    if not path.exists():
        return
    shutil.rmtree(path, onerror=_ignore_vanished)


def config_root(config_path: str | Path) -> Path | None:
    """The analysis root the config lives in, as `config.load_config` resolves it: `<root>/config/study.toml`."""
    path = Path(config_path).resolve()
    return path.parent.parent if path.is_file() else None


def outputs_from_config(config_path: str | Path) -> Path | None:
    """`[paths] outputs_dir` from the study config, resolved against the analysis root as `config.load_config` does.

    Only this one key is read; the bundle needs no input path, no seed and no date.
    """
    root = config_root(config_path)
    if root is None:
        return None
    path = Path(config_path).resolve()
    outputs = tomllib.loads(path.read_text(encoding="utf-8")).get("paths", {}).get("outputs_dir")
    if not outputs:
        return None
    found = Path(outputs)
    return found if found.is_absolute() else root / found


def sap_from_config(config_path: str | Path) -> Path:
    """`SAP.md` beside the analysis root the config lives in.

    The default has to resolve the way `outputs_dir` does. Defaulting to `SAP.md` relative to the working
    directory meant `bloomer-report --config /abs/.../config/study.toml`, run from anywhere else, found the
    outputs and not the SAP.
    """
    root = config_root(config_path)
    return (root / SAP_FILE) if root is not None else Path(SAP_FILE)


def publish(staging: Path, manuscript: Path, previous: Path) -> None:
    """Swap the new bundle into place, with no moment in which neither bundle exists.

    Deleting `manuscript/` and then renaming staging into it leaves nothing behind if the rename fails - and the
    caller reports "nothing written" while the delivered bundle is gone. The old bundle is renamed aside instead,
    the new one renamed in, and only then is the old one deleted; any failure puts the old one back.
    """
    remove_tree(previous)
    moved = manuscript.exists()
    if moved:
        manuscript.rename(previous)
    try:
        staging.rename(manuscript)
    except BaseException:
        if moved:
            previous.rename(manuscript)
        raise
    # The bundle is published from here. Removing the copy it replaced is housekeeping, and failing at it cannot
    # unpublish what is already in place, so it must not turn a successful run into "nothing written". What is
    # left behind is visible in `outputs/` and the caller reports it.
    with suppress(OSError):
        remove_tree(previous)


def caption_numbers(results: Results) -> list[Num]:
    return [number for _, caption in captions(results) for number in numbers_in(caption)]


def collect_index(results: Results, tables: list[Table], sections: list[Section]) -> dict[str, dict]:
    return build_index([number for table in tables for number in table.numbers()],
                       caption_numbers(results),
                       [number for section in sections for number in section.numbers()])


def index_units(sap_text: str) -> list[tuple[str, object]]:
    """Every block that contributes keys, labelled, so the change report can build them one at a time."""
    units: list[tuple[str, object]] = [(f"Table {rank + 1}", (lambda r, build=build: build(r).numbers()))
                                       for rank, build in enumerate(BUILDERS)]
    # A later table the tag's results do not hold contributes nothing, so its keys are reported as added; one they
    # do hold is rebuilt like any other, or its keys would be listed as added against every tag that reported them.
    units += [(f"Table {number}", (lambda r, build=build, present=present: build(r).numbers() if present(r) else []))
              for number, build, present in LATER_TABLES]
    units.append(("Figure captions", caption_numbers))
    units += [(f"Supplement {key}", (lambda r, build=build: build(r).numbers()))
              for key, build in section_builders(sap_text)]
    return units


def index_by_block(results: Results, units: list[tuple[str, object]], *,
                   lenient: bool = False) -> tuple[dict[str, list[Num]], dict[str, str]]:
    """Each block's numbers, keyed by block label. When lenient, a block that cannot be built is reported, not raised.

    A key the older analysis layer never wrote is not an error for a previous tag - it is what "key added" means -
    but the keys of a block that could not be rebuilt are not evidence of anything, so the caller leaves them out
    of the comparison entirely rather than listing a whole block as added.
    """
    groups, problems = {}, {}
    for label, unit in units:
        try:
            groups[label] = unit(results)
        except MissingResultError as err:
            if not lenient:
                raise
            problems[label] = str(err)
    return groups, problems


def write_bundle(results: Results, *, outputs_dir: Path, target: Path, tables: list[Table],
                 sections: list[Section]) -> None:
    for table in tables:
        (target / f"table{table.number}.md").write_text(render_markdown(table), encoding="utf-8")
        (target / f"table{table.number}.csv").write_text(render_csv(table), encoding="utf-8")
    (target / "tables.md").write_text(render_all_markdown(tables), encoding="utf-8")
    (target / "figures.md").write_text(render_captions(results), encoding="utf-8")
    publishable, restricted = split_sections(sections)
    (target / "supplement.md").write_text(render_supplement(publishable, preamble=PUBLIC_HEAD), encoding="utf-8")
    if restricted:
        (target / RESTRICTED_SUPPLEMENT).write_text(
            render_supplement(restricted, title="Supplementary information: Part D (restricted)",
                              preamble=RESTRICTED_HEAD), encoding="utf-8")
    write_json(index_file(collect_index(results, tables, sections)), target / "manuscript_numbers.json")
    build_figures(results, outputs_dir, target)


def write_change_report(results: Results, *, root: Path, outputs_dir: Path, target: Path, tag: str,
                        sap_path: Path, new_index: dict[str, dict]) -> None:
    old_results = tag_results(root, tag, outputs_dir.name)
    units = index_units(read_sap(sap_path))
    old_groups, problems = index_by_block(old_results, units, lenient=True)
    new_groups, _ = index_by_block(results, units)
    old_index = build_index(*old_groups.values())
    # Keys are shared: every figure-caption key is also a table key, and more are shared between tables. A block
    # that could not be rebuilt says nothing about a key the tag genuinely holds and another block rebuilt, so
    # only the keys the old index really lacks are left out - suppressing spurious additions is all this needs.
    skipped = {number.key for label in problems for number in new_groups.get(label, [])} - set(old_index)
    changes = compare(old_index, new_index, ignore=skipped)
    report = render_changes(tag=tag, old_results=old_results, new_results=results, old_index=old_index,
                            new_index=new_index, changes=changes,
                            problems=[f"{label}: {problem}" for label, problem in problems.items()],
                            n_skipped=len(skipped),
                            reported_old=tag_index(root, tag, outputs_dir.name))
    (target / f"changes_since_{tag}.md").write_text(report, encoding="utf-8")


def run_report(*, outputs_dir: str | Path = "outputs", sap_path: str | Path = "SAP.md",
               tag: str | None = None, root: str | Path | None = None) -> Path:
    """Build the whole bundle in a staging directory, then move it into `outputs/manuscript/` in one step."""
    outputs = Path(outputs_dir)
    repo_root = Path(root) if root is not None else outputs.parent
    results = load_results(outputs)
    manuscript, staging = outputs / MANUSCRIPT_DIR, outputs / STAGING_DIR
    previous = outputs / PREVIOUS_DIR
    remove_tree(staging)
    staging.mkdir(parents=True)
    try:
        tables = build_tables(results)
        sections = build_supplement(results, sap_path=sap_path)
        write_bundle(results, outputs_dir=outputs, target=staging, tables=tables, sections=sections)
        if tag:
            write_change_report(results, root=repo_root, outputs_dir=outputs, target=staging, tag=tag,
                                sap_path=Path(sap_path),
                                new_index=collect_index(results, tables, sections))
        publish(staging, manuscript, previous)
    except BaseException:
        # a cleanup that raises here would replace the failure that brought us here, and that failure is the
        # one the operator needs to read
        with suppress(OSError):
            remove_tree(staging)
        raise
    return manuscript


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/study.toml",
                        help="study config; only [paths] outputs_dir is read from it")
    parser.add_argument("--outputs", default=None, help="outputs directory (overrides the config)")
    parser.add_argument("--sap", default=None,
                        help=f"SAP file the supplement's Part E prose is read from "
                             f"(default: {SAP_FILE} in the analysis root the config lives in)")
    parser.add_argument("--tag", default=None, help="previous tag to compare the manuscript numbers against")
    args = parser.parse_args(argv)
    outputs = Path(args.outputs) if args.outputs else (outputs_from_config(args.config) or Path("outputs"))
    sap = Path(args.sap) if args.sap else sap_from_config(args.config)
    try:
        manuscript = run_report(outputs_dir=outputs, sap_path=sap, tag=args.tag)
    except Exception as err:  # noqa: BLE001 - every bundle failure exits 6 with nothing written (SAP E1)
        print(f"manuscript bundle failed, nothing written: {type(err).__name__}: {err}", file=sys.stderr)
        raise SystemExit(EXIT_CODE) from None
    # ._* are the exFAT drive's AppleDouble metadata files, not bundle outputs (they are git-ignored).
    written = sorted(path.name for path in manuscript.iterdir() if not path.name.startswith("._"))
    print(f"Manuscript bundle: {len(written)} files in {manuscript}")
    print("  " + ", ".join(written))
    leftover = manuscript.parent / PREVIOUS_DIR
    if leftover.exists():
        print(f"note: the bundle this run replaced could not be removed and is left at {leftover}. The new "
              "bundle above is in place; delete that directory when convenient.", file=sys.stderr)
