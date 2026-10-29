# StructRAG — architecture

A structure-aware RAG platform that runs three retrieval modes over one index
and measures which one works better. Inspired by IBM's STAIR work on routing
through a document's table of contents; it does **not** reproduce STAIR's
fine-tuned router or its published numbers.

## 1. Shape

```
                   ┌───────────── React dashboard (Vite, Tailwind) ─────────────┐
                   │ Documents · Structure · Playground · Benchmarks · Settings │
                   └──────────────┬─────────────────────────────────────────────┘
                                  │ Supabase Auth JWT (publishable key only)
                   ┌──────────────▼─────────────────────────────────────────────┐
                   │ FastAPI (async)                                            │
                   │  api/ ── ingest/ ── retrieval/{vector,structure,hybrid} ── │
                   │          answer.py ── evaluation/ ── llm.py (OpenAI-compat)│
                   │  worker: polls ingest_jobs (FOR UPDATE SKIP LOCKED)        │
                   └──────┬──────────────────────────┬──────────────────────────┘
                          │ psycopg, per-request      │ service role (server only)
                          │ `set local role authenticated` + jwt claims → RLS applies
                   ┌──────▼──────────────────────────▼──────────────────────────┐
                   │ Supabase: Postgres + pgvector (HNSW) · Storage · Auth      │
                   └────────────────────────────────────────────────────────────┘
```

The backend talks to Postgres directly (psycopg 3) rather than through
PostgREST, because vector search, transactions and the job queue need SQL.
Every user-scoped query runs inside a transaction that switches to the
`authenticated` role with the caller's JWT claims, so **RLS is enforced by the
database even for the backend's own queries**. The Supabase SDK is used for
Storage; the service-role key never leaves the server.

## 2. Module responsibilities

| Module | Responsibility |
|---|---|
| `app/config.py` | All settings from env. `RetrievalConfig` is the per-request knob set (top-k, budgets, routing depth, fusion weights). |
| `app/db.py` | Connection pool, `user_tx(user_id)` that applies RLS, `service_tx()` for the worker. |
| `app/llm.py` | One OpenAI-compatible client for chat + embeddings. Retries (incl. OpenRouter's 200-with-error bodies), JSON-schema output with a tolerant fallback, token + USD accounting into `llm_calls`. |
| `app/ingest/parse.py` | PDF (PyMuPDF), DOCX (python-docx), Markdown/text → a flat list of `Block`s (heading / paragraph / table) with page + char anchors. |
| `app/ingest/structure.py` | Blocks → section tree, and token-bounded chunks that never cross a section boundary. Heading source priority (decided in `parse.py`): PDF outline → explicit styles (DOCX Heading N, `#`) → inferred (font size, numbering like `3.2.1`) → single root section. Records `heading_source` and a parse confidence. |
| `app/ingest/pipeline.py` | Parse → tree → chunks → embeddings (reusing unchanged ones) → one transaction that swaps the document's sections/chunks. |
| `app/retrieval/vector.py` | Baseline: embed query, pgvector top-k. Sees only chunk text + embeddings. |
| `app/retrieval/structure.py` | Coarse-to-fine LLM routing over a compact ToC, id validation, evidence from selected sections. |
| `app/retrieval/hybrid.py` | Structure + vector candidates → weighted RRF → optional cross-encoder → dedupe → budgeted context. |
| `app/answer.py` | One grounded answer pipeline for all modes; optional claim-level citation verification. |
| `app/evaluation/` | Section-level retrieval metrics, LLM-judged answer metrics, benchmark runner, reproducibility manifest. |
| `app/qa.py` | Retrieve + answer for one mode; shared by the API and the benchmark runner. |
| `app/api/` | Routers. Typed schemas, one error envelope, JWT auth. |
| `app/cli.py` | `ingest` a folder and run a `benchmark` without the dashboard. |

## 3. Database (see `supabase/migrations/`)

```
documents      id, owner_id, title, filename, mime, sha256, storage_path, status,
               version, parse_method, parse_confidence, page_count, metadata jsonb,
               error, timings jsonb, created_at, indexed_at
sections       id (stable text), document_id, owner_id, parent_id, level, ordinal,
               heading, path text[], page_start/end, char_start/end, content,
               token_count, heading_source
chunks         id (stable text), section_id, document_id, owner_id, ordinal, text,
               page, char_start/end, token_count, content_hash,
               embedding vector(1536), embedding_model
ingest_jobs    id, document_id, owner_id, status, attempts, run_after, error
eval_datasets  id, owner_id, name, version, corpus text[], content_hash
eval_queries   id, dataset_id, qid, question, expected_answer, answerable,
               gold jsonb [{doc, path[]}], evidence text[], tags text[]
benchmark_runs id, owner_id, dataset_id, config jsonb, config_hash, manifest jsonb,
               status, summary jsonb
benchmark_results run_id, query_id, mode, retrieved jsonb, answer jsonb,
               metrics jsonb, latency/tokens/cost
llm_calls      owner_id, purpose, model, mode, input/output tokens, cost_usd,
               latency_ms, ok, run_id, document_id
query_log      owner_id, mode, query, ok, latencies, tokens, cost   (live traffic analytics)
user_settings  owner_id, config jsonb
```

Key decisions:

- **Stable ids.** `sections.id = sec_<hash(document_id, heading path, ordinal among same-path siblings)>`;
  `chunks.id = chk_<hash(section_id, ordinal, content_hash)>`. Re-indexing the
  same file yields the same ids, so reruns are idempotent.
- **Gold labels are sections, written as `{doc, path}`.** The golden set says
  `{"doc": "manual.pdf", "path": ["Engine", "Warranty"]}` and is resolved to
  section ids at run time. Changing the chunker therefore never invalidates the
  labels, and retrieval metrics for all three modes are computed at the same
  (section) granularity — vector results are mapped to sections by best rank.
- **Re-indexing** computes everything in memory first (embeddings reused by
  `content_hash + embedding_model`), then deletes and re-inserts the
  document's sections and chunks in one transaction. MVCC means readers see
  the old tree or the new tree, never a mix.
- **RLS** on every table: `owner_id = (select auth.uid())`. Child tables carry
  `owner_id` so policies never need joins.
- **Indexes**: HNSW `vector_cosine_ops` on `chunks.embedding` (the default
  metric; inner-product and L2 work but scan sequentially), btree on
  `(owner_id, document_id)`, `sections(document_id, parent_id)`.
- Embedding dimension is fixed by the migration (1536). Changing it is a
  migration, and the API refuses to start if `EMBEDDING_DIM` disagrees.

## 4. Retrieval modes

**Vector** — query embedding → `ORDER BY embedding <=> $q LIMIT k`, filtered by
owner (RLS), optional document ids and metadata containment. Returns chunks
with similarity scores.

**Structure** — no embeddings at query time.
1. Document selection: skipped when the candidate set is ≤ `doc_select_max`
   documents; otherwise the LLM picks from a catalog of titles + top headings.
2. ToC routing: the LLM sees headings of the candidate documents down to
   `toc_initial_depth`, with short ids, and returns
   `{selected_section_ids, expand_section_ids, confidence, reason}`.
3. Expansion: children of `expand_section_ids` are shown in the next round, up
   to `routing_depth` rounds.
4. Validation: every returned id must be one that was shown in that prompt.
   Invalid ids are dropped and counted; if nothing valid remains the request
   fails with `routing_failed`, or — only when `structure_fallback=vector` —
   runs the vector baseline and labels every result `provenance=fallback_vector`.
5. Evidence: the selected sections' chunks in document order, plus optional
   parent intro, cut to the context token budget.

`confidence` is stored as a model-reported signal, not a probability.

**Hybrid** — runs both, flattens structure sections into chunk lists, fuses
with weighted Reciprocal Rank Fusion (`w / (k + rank)`), optionally reranks
with a local cross-encoder, drops duplicate text, and fills the same token
budget. Each item keeps `{structure_rank, vector_rank, vector_score, rrf}`.

## 5. Answer generation (shared)

Same model, temperature 0, same prompt and same evidence format for every
mode: `[E3] <doc> › <heading path> (p. 12)` followed by the text inside
nonce-tagged delimiters. The system prompt states evidence is untrusted data.
Output is JSON: `{answer, claims:[{text, evidence_ids}], insufficient_evidence}`.
Evidence ids are validated; citations resolve to document, heading and page.
Optional verification asks a judge model whether each claim's cited text
supports it.

Headings appear in the evidence labels for every mode. The vector baseline's
*retrieval* never sees structure; the answer stage is a controlled variable
shared by all three.

## 6. Evaluation

- Retrieval (section level, at K ∈ {1,3,5,10}): Hit, Recall, Precision, MRR, nDCG.
- Answer: correctness (judge vs expected answer), faithfulness (supported
  claims / claims), citation support accuracy, unsupported-claim rate,
  abstention accuracy (unanswerable → abstain; answerable → answer).
- Performance: retrieval and end-to-end latency (p50/p95), tokens per purpose,
  USD per query, indexing time and storage bytes.
- `None` means not measurable, `0.0` means measured zero. An abstention has
  no claims, so its faithfulness is `None`, not 0. Aggregates report how many
  values they could measure.
- Every run stores a manifest: config + hash, dataset hash, corpus sha256s,
  model ids, git commit, library versions. Mocked LLMs exist only in unit
  tests; the benchmark refuses to run against the fake provider.

## 7. Implementation sequence

1. Foundation: config, DB, migrations, RLS, auth, health, LLM client.
2. Ingestion: parsers, structure tree, chunker, pipeline, job worker, upload API.
3. Vector baseline + API.
4. Structure routing + API.
5. Hybrid fusion + API.
6. Grounded answers + verification.
7. Metrics, judge, benchmark runner, golden set, CLI.
8. Dashboard, Docker, docs.

## 8. Main risks

| Risk | Mitigation |
|---|---|
| PDFs without outlines or consistent fonts give a poor tree. | Layered heading detection with a recorded `heading_source` and confidence; a flat single-section fallback keeps the document usable. |
| Router returns invented ids. | Ids are validated against the shown set; failures are counted and surfaced, never silently replaced. |
| Large collections overflow the routing prompt. | Document pre-selection, depth-limited ToC, token-budgeted ToC rendering. |
| Comparison is unfair (different budgets, different answer prompts). | One answer pipeline, one context budget, same chunks; config snapshot per run. |
| Benchmark on a small hand-built golden set is noisy. | Report n and measured counts per metric; per-question results are kept so differences can be inspected, not just averaged. |
| LLM-judged metrics drift with the judge. | Judge model recorded in the manifest; judge separate from the answer model by default. |
| Provider returns 200 with an error body (OpenRouter). | The client checks the body, not just the status, before treating a call as a success. |
