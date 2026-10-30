# Bloomer

Bloomer is a browser app that coaches clinicians to write questions about a research article. After reading an article, the learner writes three questions (a key idea, a clinical case, and a limitation of the study). A large language model rates each question on Bloom's taxonomy and gives feedback, without giving away the answers, until the question reaches at least level 3 (Apply).

This repository holds the app, the de-identified study data, and the analysis code for the pilot study:

> Gorenshtein A, Hovaguimian A, Casassa C, Goldenholz DM. *Education Research: From Answering to Asking: AI-Coached Question Writing for Neurology CME, A Pilot Study.* Submitted; citation to follow.

In the study, US neurologists and neurology trainees studied one article with a 5-item multiple-choice quiz and a second article with Bloomer, then took a quiz on both articles 1 month later.

## Where things are

| Folder | What it holds |
| --- | --- |
| [`app/`](app/) | The Bloomer source code, downloaded from the Google Gemini Canvas app that participants used, and a link to the live app ([`app/README.md`](app/README.md)) |
| [`data/`](data/) | The de-identified study data, with a description of every column ([`data/README.md`](data/README.md)) |
| [`analysis/`](analysis/) | The Python analysis code (`src/bloomer_retention/`) that produced every number in the paper |
| [`figures/`](figures/) | `make_figures.py`, which drew the paper's figures from the analysis results |

## Rerun the main results from the shared data

With Python 3 (checked with 3.12) and pandas, NumPy, SciPy, statsmodels and matplotlib installed:

```bash
cd analysis
PYTHONPATH=src python -m bloomer_retention.public_reproduce --data ../data
```

The script reruns the 1-month quiz comparison (Bloomer-studied minus quiz-studied article, the primary estimate and five sensitivity analyses), the Part 1 quiz means, and the survey results (preference, comprehension check, difficulty, time, attempts, and comment themes) with the same functions the study used. It prints each value next to the published one from `data/expected_results.json` and exits with an error if any differ.

## What is not shared

The data were collected with Microsoft Forms. The raw exports contain names, email addresses, and other details that could identify participants, so they are not in this repository. The shared files leave out age, gender, region, role, years in practice, subspecialty, practice setting, CME habits, AI use, dates and times, all free-text answers, and any link between forms. Respondent IDs were assigned at random for this release, the assignment was not kept, and IDs do not match across files.

The full pipeline in `analysis/` starts from those raw exports, and `figures/make_figures.py` reads results that are not shared, so neither runs from this repository alone; the code is here so it can be read. The participant characteristics table cannot be rerun from the shared data.

## License

MIT; see [`LICENSE`](LICENSE).
