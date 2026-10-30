"""`manuscript_numbers.json`: every reported number under a stable key (SAP E5, design section 6).

The index is collected from the very cells the tables, figure captions and supplement render, so there is one code
path to each number. A key repeated in two places must carry the same value, formatted string, source path and
unit, or the bundle refuses to write: two readings of one key is the drift this design exists to prevent.
"""
from __future__ import annotations

from bloomer_retention.bundle.format import Num
from bloomer_retention.bundle.load import BundleError

# The change report lists flow counts first, then the primary outcome, then everything else: a changed n explains
# most changed estimates (SAP E5). `manuscript_numbers.json` itself is written sorted by key, like every other
# JSON this project writes, because it is a lookup table rather than something read top to bottom.
ORDER = ("flow.", "primary.")
# Part D person-level content rides inside a file that otherwise reads as public: 179 of the delivered entries
# begin `partd.`, among them the two-person D3 contrast cells and the D5 2x2. Attaching "the numbers file" to a
# submission would leak them, so every such entry is marked in band and the file says so at its head (SAP E4.2).
RESTRICTED_PREFIX = "partd."
NOTE_KEY = "_readme"
NOTE = (
    "Entries whose key begins `partd.` carry Part D person-level content and are restricted to the study team "
    "on the same terms as supplement section S5: at about nine linked people the D3 contrast cells and the D5 "
    "2x2 hold two-person and single-person counts, from which a participant who knows their own answers can "
    "recover another person's score. Each such entry is marked \"restricted\": true. Every other entry is "
    "publishable. This note sorts first and is not a reported number."
)


def collect(*groups: list[Num]) -> dict[str, Num]:
    """Every `Num`, keyed. A repeated key must agree with itself in every field."""
    index: dict[str, Num] = {}
    for group in groups:
        for number in group:
            seen = index.get(number.key)
            if seen is not None and seen != number:
                raise BundleError(
                    f"manuscript number {number.key!r} is written twice with different content: "
                    f"{seen.formatted!r} from {seen.source} and {number.formatted!r} from {number.source}"
                )
            index[number.key] = number
    return index


def sort_key(key: str) -> tuple[int, str]:
    for rank, prefix in enumerate(ORDER):
        if key.startswith(prefix):
            return rank, key
    return len(ORDER), key


def restricted(key: str) -> bool:
    return key.startswith(RESTRICTED_PREFIX)


def as_payload(index: dict[str, Num]) -> dict[str, dict]:
    return {number.key: {"value": number.value, "formatted": number.formatted, "source": number.source,
                         "unit": number.unit, **({"restricted": True} if restricted(number.key) else {})}
            for number in sorted(index.values(), key=lambda number: number.key)}


def index_file(index: dict[str, dict]) -> dict:
    """The index as it is written to disk: the note first, then every entry.

    The note is added here rather than in `build_index`, because the change report builds an index of a previous
    tag and compares the two entry by entry; a note among the entries would be compared as one.
    """
    return {NOTE_KEY: NOTE, **index}


def build_index(*groups: list[Num]) -> dict[str, dict]:
    return as_payload(collect(*groups))
