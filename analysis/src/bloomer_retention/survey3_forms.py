"""Survey 3 ("Bloomer Survey part 2") form definition: allowlisted columns and offered options (SAP Part B, B2).

Options are in form order, copied from Forms/Bloomer Survey part 2.pdf, including the form's own spellings
("No opinon"). "Neurology fellow" was added to the role question after the 2026-04-06 snapshot.
"""
from __future__ import annotations

ColumnSpec = dict[str, tuple[str, str]]

SURVEY3_SPEC: ColumnSpec = {
    "start_time": ("exact", "Start time"),
    "completion_time": ("exact", "Completion time"),
    "age": ("exact", "Age"),
    "gender": ("exact", "Gender"),
    "region": ("exact", "Geographical area"),
    "role": ("exact", "Which best describes you?"),
    "years": ("prefix", "Years in practice"),
    "subspecialty": ("prefix", "Subspecialty focus"),
    "setting": ("exact", "Primary Practice setting"),
    "ai_use": ("prefix", "Prior use of AI"),
    "cme_hours": ("prefix", "How many hours per week do you typically spend on continuing medical education"),
    "cme_format": ("prefix", "What format do you most commonly use for continuing medical education"),
    "bloomer_paper": ("exact", "Which paper did you complete in Bloomer?"),
    "prior_knowledge": ("prefix", "For the paper you read what would you rate your prior knowledge"),
    "q1_time": ("exact", "Time took to attempt"),
    "q1_attempts": ("exact", "Number of attempts"),
    "q2_time": ("exact", "Time took to attempt2"),
    "q2_attempts": ("exact", "Number of attempts2"),
    "q3_time": ("exact", "Time took to attempt to"),
    "q3_attempts": ("exact", "Number of attempts3"),
    "best_comprehension": ("prefix", "Which was best for checking your comprehension"),
    "quiz_difficulty": ("prefix", "How difficult was the traditional 5-question quiz"),
    "bloomer_difficulty": ("prefix", "How difficult was the new Bloomer AI tool"),
    "preference": ("prefix", "For CME competency with articles, would you rather prove competency with"),
}
SURVEY3_CONTACT_EMAIL = ("prefix", "Email to get invite to the last phase")

QUESTIONS = ("q1", "q2", "q3")  # Q1 key idea, Q2 clinical case, Q3 limitation (manuscript Methods)
QUESTION_LABELS = {"q1": "Q1 key idea", "q2": "Q2 clinical case", "q3": "Q3 limitation or methodological issue"}

OPTIONS: dict[str, tuple[str, ...]] = {
    "gender": ("Man", "Woman", "Non-binary", "Prefer not to say"),
    "region": ("Northeast", "West", "South", "Midwest"),
    "role": ("ABPN-certified neurologist", "Neurology resident", "Neurology fellow", "Other"),
    "subspecialty": ("Epilepsy", "Stroke", "Headache", "Movement", "MS/Neuroimmunology", "Neuromuscular",
                     "Clinical Neurophysiology", "Cognitive", "Neurocritical", "Other"),
    "setting": ("Academic", "Community", "Mixed", "VA", "Other"),
    "ai_use": ("Very Often", "Often", "Sometimes", "Never"),
    "cme_hours": ("Less than 1 hour", "1-2 hours", "3-5 hours", "More than 5"),
    "cme_format": ("Reading journal articles", "Watching recorded lectures or webinars",
                   "Attending live conferences or grand rounds", "Listening to medical podcasts",
                   "Interactive learning platforms (e.g., quizzes, case simulations)", "Others"),
    "bloomer_paper": ("Paper A", "Paper B"),
    "best_comprehension": ("The 5-question quiz", "Bloomer", "They were about the same", "Neither were very good",
                           "No opinon"),
    "quiz_difficulty": ("not at all difficult", "not very difficult", "neutral", "a little difficult",
                        "very difficult", "no opinon"),
    "bloomer_difficulty": ("not at all difficult", "not very difficult", "neutral", "a little difficult",
                           "very difficult"),
    "preference": ("A 5-question quiz", "Bloomer-AI", "Unsure", "No opinon"),
}
# Columns whose form offers a free-text "Other": unrecognised answers are recoded to this option, never written.
OTHER_OPTION = {"role": "Other", "subspecialty": "Other", "setting": "Other", "cme_format": "Others"}

DIFFICULTY_SCORE = {"not at all difficult": 1, "not very difficult": 2, "neutral": 3, "a little difficult": 4,
                    "very difficult": 5}  # "no opinon" is missing

# Bloomer on Paper A means the MCQ was on Paper B, i.e. group B (manuscript Methods, Study Design).
GROUP_BY_BLOOMER_PAPER = {"Paper A": "B", "Paper B": "A"}

SURVEY3_COLUMNS = [
    "pid", "start_date", "completion_date", "age", "gender", "region", "role", "years", "subspecialty", "setting",
    "ai_use", "cme_hours", "cme_format", "bloomer_paper", "prior_knowledge",
    *[f"{q}_{field}" for q in QUESTIONS for field in ("minutes", "time_status", "attempts", "attempts_status")],
    "best_comprehension", "quiz_difficulty", "bloomer_difficulty", "preference",
]
