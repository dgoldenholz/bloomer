# Data

De-identified data from the Bloomer pilot study. Each file covers one study step. Respondent IDs were assigned at random for this release (the assignment was not kept) and cannot be matched across files; the study's forms were not linked.

The two articles were a narrative review of Lewy body dementia (**article A**) and a systematic review with meta-analysis of mechanical thrombectomy for large ischemic-core stroke (**article B**). Each article had a 5-item quiz (items A1-A5 and B1-B5); the item wording is in eMethods 2 of the paper's supplement, and the answer key is in `analysis/src/bloomer_retention/answer_key.py`.

Answer options are copied exactly from the forms, including their own spelling ("Tradtional MCQ", "No opinon"). An empty cell means no answer.

## `retention_items.csv`: 1-month quiz, one row per respondent and item (22 respondents × 10 items)

| Column | Meaning |
| --- | --- |
| `respondent` | Random ID, `ret01` to `ret22`; the same IDs as in `retention_respondents.csv` |
| `article` | `A` or `B` |
| `item` | `A1`-`A5`, `B1`-`B5` |
| `offered` | 1 if the item was scored for this response. Item A4 was scored only from September 15, 2026, the day after its correct answer was added to the form's options, so for A4 this column also shows whether the response came before or after that date. |
| `answered` | 1 if the respondent chose an answer |
| `correct` | 1 if the answer was correct |

## `retention_respondents.csv`: 1-month quiz, one row per respondent (22)

| Column | Meaning |
| --- | --- |
| `respondent` | Random ID, `ret01` to `ret22` |
| `sequence_group` | `A`: quiz on article A and Bloomer on article B. `B`: quiz on article B and Bloomer on article A. Self-reported on the form. |
| `reread_used_ai_or_discussed` | `Yes` if the respondent reported re-reading either article, using an AI tool on it, or discussing it after Part 1; these respondents are left out in one sensitivity analysis |
| `perceived_better` | Which format helped them retain the material better |
| `useful_bloomer`, `useful_mcq` | Usefulness rating of each format, from "Not useful at all" to "Very useful" |

## `part1_quiz_scores.csv`: Part 1 quiz, one row per form (37)

| Column | Meaning |
| --- | --- |
| `form` | Random ID, `p1f01` to `p1f37`. The Part 1 forms were anonymous. |
| `article` | Article quizzed (`A` or `B`) |
| `pct_correct` | Percentage of scored items answered correctly |
| `prior_knowledge` | Self-rated prior knowledge of the field, 1 to 10 |

## `survey_after_bloomer.csv`: survey at the end of Part 1, one row per respondent (29)

| Column | Meaning |
| --- | --- |
| `respondent` | Random ID, `srv01` to `srv29`; the same IDs as in `comment_themes.csv` |
| `sequence_group` | `A` or `B`, as above |
| `bloomer_article` | Article studied with Bloomer (`Paper A` or `Paper B`) |
| `prior_knowledge` | Self-rated prior knowledge of the Bloomer-studied article's field, 1 to 10 |
| `q1_minutes`, `q2_minutes`, `q3_minutes` | Self-reported minutes for Bloomer question 1 (key idea), 2 (clinical case), 3 (limitation) |
| `q1_attempts`, `q2_attempts`, `q3_attempts` | Self-reported attempts for each question |
| `q*_time_status`, `q*_attempts_status` | How the typed answer was read: `ok`, `blank`, or `unparsed` (text that was not a number) |
| `best_comprehension` | Answer to "Which was best for checking your comprehension for CME:" |
| `quiz_difficulty`, `bloomer_difficulty` | Perceived difficulty of each method, from "not at all difficult" to "very difficult" |
| `preference` | Which method the respondent would rather use to prove CME competency |

## `comment_themes.csv`: themes in the survey's final free-text item, one row per survey respondent (29)

The comments themselves are not shared. Each answer was marked `substantive` (1) or not (blank, "no", or a test entry), and each substantive answer was coded 1/0 for seven themes. One author checked every code against the comment text.

| Column | Theme |
| --- | --- |
| `engagement` | Engaged more deeply with the article |
| `prefers_writing` | Preferred writing questions to a quiz, or felt it tested understanding better |
| `teaching` | Would use it with trainees or in teaching |
| `unclear_expectations` | Expectations unclear; asked for examples or a tutorial |
| `grader_feedback` | Grader too strict, or feedback too vague to act on |
| `effort_time` | More effort or time than a quiz |
| `task_design` | Proposed a change to the task |

## `expected_results.json`

The published values that `PYTHONPATH=src python -m bloomer_retention.public_reproduce --data ../data` (run from `analysis/`) recomputes from the files above.
