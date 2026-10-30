# Bloomer app

`bloomer_app.tsx` is the source code of Bloomer, downloaded from the Google Gemini Canvas app that every study participant used. The live app is at:

https://gemini.google.com/share/5c03cb982010

Opening it needs a Google account.

## How it works

- The learner uploads the article as a PDF and writes three questions in turn: a key idea, a clinical case, and a limitation of the study.
- For each question the app sends one request to the Gemini API with a system instruction, the learner's question, and the PDF (`evaluateWithGemini`). The grading instructions are the `systemPrompt`, `promptText` and `qTypeRules` strings in the file.
- The model returns a Bloom level from 1 to 6, PASS (level 3 or above) or FAIL, feedback, and suggestions. The instructions bar the feedback from naming the article's content, so the learner has to go back to the article.
- A question must pass before the next one unlocks. The app shows points for each Bloom level and a summary at the end.

## Notes

- The file requests the model `gemini-2.5-flash-preview-09-2025`. Gemini Canvas supplied the API key and controlled model routing, so `apiKey` is empty in the file, and the model that actually answered participants could not be confirmed afterwards.
- No temperature, top-p, or random seed was set, so the same question can get a different response.
- The app did not save participants' questions, the model's responses, or the uploaded PDFs.
- To run it outside Gemini Canvas you would need your own Gemini API key in `apiKey` and a React build with Tailwind CSS and `lucide-react`.
