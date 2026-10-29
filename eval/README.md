# Evaluation

## The corpus is synthetic, on purpose

`build_corpus.py` generates four fictional documents about an EV maker and its
dealers, one per supported parser path:

| File | Parser path | Sections |
|---|---|---|
| `voltra-e5-owners-manual.pdf` | PDF bookmarks | 33 |
| `export-shipping-guide.pdf` | PDF, headings inferred from fonts and numbering | 30 |
| `dealer-operations-handbook.docx` | DOCX heading styles | 22 |
| `voltra-service-bulletins.md` | Markdown | 49 |

It is built to stress section disambiguation: repeated sub-headings ("Warranty"
under two chapters, "Deposits" under Sales and Export, eight bulletins with
identical Symptom/Cause/Repair children), and facts that only mean something
with their heading ("Coverage: 8 years or 160,000 km"). That is the case
structure-aware retrieval claims to fix, so results here show how the modes
behave on documents like this. They say nothing about every corpus. To test
your own documents, write a dataset in the same format against them.

`dataset.json` holds 53 questions with gold sections written as
`{doc, path}`, resolved to section ids at run time, so changing the chunker
never invalidates labels. Tags: `semantic` (26), `heading_context` (14),
`exact_id` (10), `multi_section` (6), `unanswerable` (6), `cross_document` (1).
The generator parses every document with the platform's own parser and refuses
to write the dataset if any gold path doesn't exist.

```bash
cd backend && .venv/Scripts/python ../eval/build_corpus.py
```

## Running a benchmark

```bash
cd backend
.venv/Scripts/python -m app.cli ingest ../eval/corpus --email you@example.com
.venv/Scripts/python -m app.cli benchmark ../eval/dataset.json --email you@example.com \
    --label baseline --config '{"context_token_budget": 1000}'
```

The 1,000-token budget is deliberate: the whole corpus is only ~8k tokens, so
the default 3,000 would let every mode hold a large share of it and hide
differences. The same budget applies to every mode.

Each run stores a manifest (config and its hash, dataset hash, corpus file
hashes and parse methods, models, git commit, package versions) and every
per-question result, and writes `eval/results/<run id>.json`. Modes run
one question at a time, in a seeded random order per question.

The runner refuses a fake LLM, and it aborts on HTTP 401/402/403 from the
provider instead of recording failed questions as results. A run where some
questions failed for other reasons is marked incomplete in the CLI and the
dashboard.

## Metrics

Retrieval is scored at section level for all modes (vector chunks map to
their sections): Hit, Recall, Precision and nDCG at K ∈ {1, 3, 5, 10}, and MRR.
A retrieved section counts if it is a gold section or lies inside one. Answers
are judged by a separate model: correctness against the expected answer,
faithfulness (claims supported by any retrieved text), citation support
(claims supported by the text they cite), unsupported-claim rate, and
abstention accuracy. `None` means not measurable and is never averaged as 0:
unanswerable questions have no retrieval scores, and an abstention has no
faithfulness score.

## Results

No valid run yet. The first attempt (2026-10-29) hit OpenRouter HTTP 402
(out of credits) on most questions. It is recorded as failed and its numbers
are not reported.
