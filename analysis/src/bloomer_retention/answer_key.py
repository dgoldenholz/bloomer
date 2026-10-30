"""Answer key, offered options and response normalisation for the 10 retention items (SAP section 5).

Key: bolded options in Q/Alex questions for paper 1.docx (Paper A) and Q/Q PAPER B.docx (Paper B).
Offered options: Forms/Bloomer MCQ Paper A.pdf (2026-04-06), Bloomer Phase 3.pdf (2026-06-29),
Q/Q PAPER B.docx, the option strings present in the exports, and Olanzapine for A4 (added to both forms 2026-09-14).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

import pandas as pd

PAPERS = ("A", "B")
ITEM_IDS = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5")

# Normalised header prefix that identifies each item's column in every export.
ITEM_STEMS = {
    "A1": "According to the article, what is the primary pathologic mechanism for the memory decline in Lewy Body Dementia",
    "A2": "An 80-year-old man with a past medical history of hypertension",
    "A3": "An 82-year-old woman presents to clinic for evaluation of dementia",
    "A4": "A 78-year-old patient presents to her PCP with confusion",
    "A5": "A 72 year old patient presents to your office for evaluation of dementia",
    "B1": "A 70-year-old woman presents to the Emergency Department",
    "B2": "According to the article's eligibility criteria",
    "B3": "According to the article, what was the reported effect of endovascular thrombectomy",
    "B4": "A 25-year-old man is admitted with a proximal right MCA stroke",
    "B5": "Based on the pooled analysis of the 3 randomized controlled trials",
}

ANSWER_KEY = {
    "A1": "Loss of acetylcholine-producing neurons",
    "A2": "Age",
    "A3": "All of the above",
    "A4": "Olanzapine",
    "A5": "Sleep study consistent with REM behavior disorder",
    "B1": "The procedure is associated with a numerically higher but not statistically significant risk of sICH compared to medical management.",
    "B2": "Infarct core volume > 50 mL or ASPECTS < 5",
    "B3": "EVT was associated with a nearly twofold higher probability of achieving independent ambulation (mRS 0–3) at 90 days.",
    "B4": "There was no significant difference in the rate of DC between the EVT and MM groups in the analysis.",
    "B5": "EVT showed no significant difference in mortality compared to medical management.",
}

OFFERED_OPTIONS = {
    "A1": (
        "Loss of acetylcholine-producing neurons",
        "Loss of dopamine-producing neurons",
        "Loss of GABA-producing neurons",
        "Loss of Norepinephrine-producing neurons",
        "None of the above",
    ),
    "A2": ("Diabetes", "Prior Stroke", "Male Sex", "Age", "Hypertension"),
    "A3": (
        "Visual Hallucinations",
        "REM Behavior Disorder",
        "Fluctuations in mental status",
        "None of the above",
        "All of the above",
    ),
    "A4": ("Fluoxetine", "Donepezil", "Carbidopa-Levodopa", "Amantadine", "Olanzapine"),
    "A5": (
        "Increase in dopamine update in the basal ganglia update on SPECT scan?",
        "MRI with hippocampal and medial temporal lobe atrophy bilaterally",
        "Sleep study consistent with REM behavior disorder",
        "EEG with intermittent sharp waves",
        "CSF α-synuclein levels",
    ),
    "B1": (
        "The procedure is associated with a significantly higher risk of sICH compared to medical management alone.",
        "The procedure is associated with a numerically higher but not statistically significant risk of sICH compared to medical management.",
        "The procedure significantly lowers the risk of sICH by reperfusing the threatened tissue.",
        "The risk of sICH is only increased if the patient is also treated with intravenous thrombolysis.",
        "The procedure significantly reduces the overall risk of death in patients with this size of stroke.",
    ),
    "B2": (
        "Infarct core volume > 30 mL or ASPECTS < 7",
        "Infarct core volume > 50 mL or ASPECTS < 5",
        "Infarct core volume > 70 mL or ASPECTS < 3",
        "Infarct core volume > 100 mL or ASPECTS < 2",
        "Infarct core volume > 150 mL regardless of ASPECTS",
    ),
    "B3": (
        "EVT was associated with a nearly twofold higher probability of achieving independent ambulation (mRS 0–3) at 90 days.",
        "EVT showed no significant difference in independent ambulation rates but significantly reduced 90-day mortality.",
        'EVT was superior only in the "early window," defined as within 6 hours of symptom onset.',
        "EVT significantly increased the rate of functional independence (mRS 0–2) while also significantly increasing mortality.",
        "EVT demonstrated a higher chance for a favorable mRS shift than that seen in prior small-core (HERMES) meta-analyses.",
    ),
    "B4": (
        "EVT significantly increased the need for subsequent DC due to increased reperfusion-related edema.",
        "Successful EVT was shown to remove the need for subsequent DC.",
        "There was no significant difference in the rate of DC between the EVT and MM groups in the analysis.",
        "DC was found to be a superior primary treatment compared to EVT for patients with ASPECTS scores of 3–5.",
        "The necessity for DC is determined primarily by the success of reperfusion rather than the initial core volume.",
    ),
    "B5": (
        "EVT significantly increased mortality due to high rates of symptomatic hemorrhage.",
        "EVT significantly reduced mortality compared to medical management.",
        "EVT showed no significant difference in mortality compared to medical management.",
        "EVT reduced mortality only in patients with an ASPECTS score of 0–2.",
        "EVT reduced mortality only when performed within 3 hours of symptom onset.",
    ),
}

# Allowed values for the non-item text columns that ingest writes, in form order (SAP section 13).
# Source: the blank Phase 3 form printout, Bloomer Phase 3.pdf (2026-06-29). The printout truncates the
# usefulness grid after three columns; "Useful" and "Very useful" complete the 5-level scale.
GROUP_OPTIONS = ("A", "B")
YES_NO = ("Yes", "No")
DISCUSSED_OPTIONS = ("Yes", "No", "Maybe")  # the discussion question alone also offers "Maybe"
USEFULNESS_SCALE = ("Not useful at all", "Slightly useful", "Moderately useful", "Useful", "Very useful")
PERCEIVED_BETTER_OPTIONS = ("Bloomer", "Tradtional MCQ", "Both equally", "Neither / not sure")  # sic
ALLOWED_VALUES = {
    "group": GROUP_OPTIONS,
    "reread_a": YES_NO,
    "reread_b": YES_NO,
    "used_ai": YES_NO,
    "discussed": DISCUSSED_OPTIONS,
    "useful_bloomer": USEFULNESS_SCALE,
    "useful_mcq": USEFULNESS_SCALE,
    "perceived_better": PERCEIVED_BETTER_OPTIONS,
}

# Items scored only for responses dated on or after [study] a4_offered_from and excluded before it (SAP section 5.3),
# with the reason. valid_items() is the only place the rule is applied.
DATE_LIMITED_ITEMS = {
    "A4": "its keyed answer (Olanzapine) was added to the Part 1 and Phase 3 forms on 2026-09-14",
}


def valid_items(paper: str, response_date: date, a4_offered_from: date) -> tuple[str, ...]:
    """The paper's scored items for one response: every item, less date-limited items before the cutoff."""
    return tuple(
        i for i in ITEM_IDS
        if i[0] == paper and (i not in DATE_LIMITED_ITEMS or response_date >= a4_offered_from)
    )


_TRANSLATE = str.maketrans(
    {"\xa0": " ", "–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'"}
)
_ENUM_PREFIX = re.compile(r"^[A-F][.)]\s+")
_OPTION_SUFFIX = re.compile(r"\s*Option \d+$")


def normalize_text(value: object) -> str | None:
    """Collapse whitespace and unify NBSP, dashes and quotes; None for blank or missing."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = " ".join(str(value).translate(_TRANSLATE).split())
    return text or None


def normalize_response(value: object) -> str | None:
    """normalize_text plus removal of Forms export artefacts ("A.<tab>" prefixes, " Option 2" suffixes)."""
    text = normalize_text(value)
    if text is None:
        return None
    text = _OPTION_SUFFIX.sub("", _ENUM_PREFIX.sub("", text)).strip()
    return text or None


def _fold(text: str) -> str:
    return normalize_response(text).casefold()


_OFFERED_FOLDED = {item: {_fold(option) for option in options} for item, options in OFFERED_OPTIONS.items()}


def is_correct(item_id: str, response: object) -> bool:
    """True only when the normalised response matches the keyed answer; blank is False."""
    text = normalize_response(response)
    return text is not None and text.casefold() == _fold(ANSWER_KEY[item_id])


def unrecognized_responses(item_id: str, responses: Iterable[object]) -> list[str]:
    """Sorted unique normalised non-blank responses that are not offered options for this item."""
    texts = {normalize_response(r) for r in responses} - {None}
    return sorted(t for t in texts if t.casefold() not in _OFFERED_FOLDED[item_id])
