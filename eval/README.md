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

### Run `gemini-budget1000` (2026-10-29)

Record: [`results/a8286e9e-88e1-4579-baf1-1649783269a1.json`](results/a8286e9e-88e1-4579-baf1-1649783269a1.json),
config hash `ca9d874f6d7e13e8`. The run completed with 0 failed queries.

| Setting | Value |
|---|---|
| Embeddings | `gemini-embedding-001`, 1536 dimensions |
| Router and answer model | `gemini-3.1-flash-lite`, reasoning effort low |
| Judge | `gemini-3.8-flash` |
| Context budget | 1,000 tokens for every mode |
| Vector top-k | 8 |
| Run | one at a time, seed 0 |

53 questions: 47 answerable, 6 unanswerable. Retrieval metrics are scored on
the 47 answerable questions.

| Metric | vector | structure | hybrid |
|---|---|---|---|
| Hit@1 | 0.74 | 0.64 | **0.81** |
| Hit@3 | 0.85 | 0.83 | **0.98** |
| Recall@5 | 0.91 | **0.99** | 0.98 |
| MRR | 0.81 | 0.76 | **0.89** |
| nDCG@5 | 0.83 | 0.82 | **0.91** |
| Answer correctness (judged) | 0.93 | 0.98 | **0.99** |
| Abstention accuracy (all 53) | 0.94 | **1.00** | **1.00** |
| Faithfulness / citation support | 1.00 | 1.00 | 1.00 |
| Invalid router ids per query | – | 0.04 | 0 |
| End-to-end latency p50 / p95 | **1.8 / 2.1 s** | 3.3 / 4.7 s | 3.6 / 4.8 s |
| Cost per query (excl. judge) | **$0.00056** | $0.00156 | $0.00187 |

Recall@3 by question type:

| Type | vector | structure | hybrid |
|---|---|---|---|
| semantic (26) | 0.88 | 0.85 | 1.00 |
| heading_context (14) | 0.71 | 0.71 | 0.93 |
| exact_id, answerable (8) | 0.62 | 0.62 | 1.00 |
| multi_section (6) | 0.67 | 0.83 | 0.83 |

What the run shows:

- **Hybrid** retrieved best overall. It had the right section in its top 3 for
  46 of 47 answerable questions. It costs about 3.4× vector and roughly doubles latency.
- **Vector** is cheapest and fastest. It was the only mode to miss answers,
  on 3 service-bulletin questions (t02, t04, t10). Those sections share identical
  sub-headings, so the bulletin number appears only in the parent heading;
  vector retrieved the wrong bulletin's text and abstained. It never made a
  claim up: every claim it made was supported.
- **Structure** finds the right sections (best Recall@5) but ranks them
  worse (lowest Hit@1 and MRR). It returns a selected section's whole subtree in
  document order, so for "the repair in TSB-2026-014" the "Applies To" chunk
  comes before "Repair". Ordering chunks inside a selected subtree by relevance
  is the obvious next experiment.
- Answer quality barely separates the modes here: the answer model coped with
  imperfect ranking whenever the right text was anywhere in the 1,000 tokens.

Limits: this is one run, so there is no variance estimate, and the per-type
counts are small (6–26). The corpus is synthetic and built to stress section
disambiguation, and correctness is graded by an LLM. Treat it as a working
comparison, not a general verdict on the three methods.

### Run `baseline-budget1000` (2026-10-29), invalid

OpenRouter returned HTTP 402 (out of credits) on most queries. The run is
recorded as failed and its numbers are not reported.
