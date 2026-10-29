-- StructRAG core schema: documents, section tree, chunks, jobs, evaluation, usage.
-- Every table carries owner_id and is protected by RLS: owner_id = auth.uid().

create extension if not exists vector with schema extensions;

create type public.document_status as enum ('pending', 'processing', 'ready', 'failed');
create type public.job_status as enum ('queued', 'running', 'done', 'failed');
create type public.heading_source as enum ('outline', 'explicit', 'inferred', 'none');

-- ---------------------------------------------------------------- documents
create table public.documents (
    id               uuid primary key default gen_random_uuid(),
    owner_id         uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title            text not null,
    filename         text not null,
    mime             text not null,
    sha256           text not null,
    size_bytes       bigint not null,
    storage_path     text not null,
    status           public.document_status not null default 'pending',
    version          int not null default 0,           -- bumped by every successful index
    parse_method     text,
    parse_confidence real check (parse_confidence between 0 and 1),
    page_count       int,
    metadata         jsonb not null default '{}',
    error            text,
    timings          jsonb not null default '{}',      -- parse/embed/store ms of the last index
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    indexed_at       timestamptz,
    unique (owner_id, sha256)
);
create index documents_owner_idx on public.documents (owner_id, created_at desc);
create index documents_metadata_idx on public.documents using gin (metadata);

-- ---------------------------------------------------------------- sections
-- id is stable across re-indexing: sec_<hash(document_id, heading path, sibling ordinal)>.
create table public.sections (
    id             text primary key,
    document_id    uuid not null references public.documents (id) on delete cascade,
    owner_id       uuid not null references auth.users (id) on delete cascade,
    parent_id      text references public.sections (id) on delete cascade deferrable initially deferred,
    level          int not null check (level >= 0),    -- 0 = synthetic document root
    ordinal        int not null,                        -- reading order within the document
    heading        text not null,
    path           text[] not null,
    page_start     int,
    page_end       int,
    char_start     int not null,
    char_end       int not null,
    content        text not null default '',          -- this section's own text, children excluded
    token_count    int not null default 0,
    heading_source public.heading_source not null
);
create index sections_doc_idx on public.sections (document_id, ordinal);
create index sections_parent_idx on public.sections (parent_id);
create index sections_owner_idx on public.sections (owner_id);

-- ---------------------------------------------------------------- chunks
create table public.chunks (
    id              text primary key,
    section_id      text not null references public.sections (id) on delete cascade deferrable initially deferred,
    document_id     uuid not null references public.documents (id) on delete cascade,
    owner_id        uuid not null references auth.users (id) on delete cascade,
    ordinal         int not null,                       -- order within the section
    text            text not null,
    page            int,
    char_start      int not null,
    char_end        int not null,
    token_count     int not null,
    content_hash    text not null,
    embedding       extensions.vector(1536),
    embedding_model text
);
create index chunks_section_idx on public.chunks (section_id, ordinal);
create index chunks_owner_doc_idx on public.chunks (owner_id, document_id);
create index chunks_hash_idx on public.chunks (owner_id, content_hash, embedding_model);
create index chunks_embedding_hnsw on public.chunks
    using hnsw (embedding extensions.vector_cosine_ops);

-- ---------------------------------------------------------------- ingest jobs
create table public.ingest_jobs (
    id          bigint generated always as identity primary key,
    document_id uuid not null references public.documents (id) on delete cascade,
    owner_id    uuid not null references auth.users (id) on delete cascade,
    status      public.job_status not null default 'queued',
    attempts    int not null default 0,
    run_after   timestamptz not null default now(),
    error       text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index ingest_jobs_queue_idx on public.ingest_jobs (run_after) where status = 'queued';
create index ingest_jobs_doc_idx on public.ingest_jobs (document_id);

-- ---------------------------------------------------------------- evaluation
create table public.eval_datasets (
    id           uuid primary key default gen_random_uuid(),
    owner_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    name         text not null,
    version      text not null,
    description  text,
    corpus       text[] not null,                      -- filenames the benchmark retrieves over
    content_hash text not null,
    created_at   timestamptz not null default now(),
    unique (owner_id, name, version)
);

create table public.eval_queries (
    id              uuid primary key default gen_random_uuid(),
    dataset_id      uuid not null references public.eval_datasets (id) on delete cascade,
    owner_id        uuid not null references auth.users (id) on delete cascade,
    qid             text not null,
    question        text not null,
    expected_answer text,
    answerable      boolean not null default true,
    gold            jsonb not null default '[]',        -- [{"doc": filename, "path": [heading, ...]}]
    evidence        text[] not null default '{}',
    tags            text[] not null default '{}',
    unique (dataset_id, qid),
    check (answerable or gold = '[]'::jsonb)
);

create table public.benchmark_runs (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
    dataset_id  uuid not null references public.eval_datasets (id) on delete cascade,
    label       text,
    modes       text[] not null,
    config      jsonb not null,
    config_hash text not null,
    manifest    jsonb not null default '{}',
    status      public.job_status not null default 'queued',
    error       text,
    summary     jsonb,
    created_at  timestamptz not null default now(),
    finished_at timestamptz
);
create index benchmark_runs_owner_idx on public.benchmark_runs (owner_id, created_at desc);

create table public.benchmark_results (
    id                   bigint generated always as identity primary key,
    run_id               uuid not null references public.benchmark_runs (id) on delete cascade,
    owner_id             uuid not null references auth.users (id) on delete cascade,
    query_id             uuid not null references public.eval_queries (id) on delete cascade,
    mode                 text not null,
    retrieved            jsonb not null,
    answer               jsonb,
    metrics              jsonb not null,
    retrieval_latency_ms real,
    total_latency_ms     real,
    input_tokens         int,
    output_tokens        int,
    cost_usd             double precision,
    error                text,
    unique (run_id, query_id, mode)
);

-- ---------------------------------------------------------------- usage + settings
create table public.llm_calls (
    id            bigint generated always as identity primary key,
    owner_id      uuid not null references auth.users (id) on delete cascade,
    purpose       text not null,      -- embed_index, embed_query, route, answer, verify, judge, rerank
    model         text not null,
    mode          text,               -- vector / structure / hybrid when tied to a query
    input_tokens  int not null default 0,
    output_tokens int not null default 0,
    cost_usd      double precision,   -- null = provider did not report and model has no known price
    latency_ms    real not null,
    ok            boolean not null default true,
    document_id   uuid references public.documents (id) on delete set null,
    run_id        uuid references public.benchmark_runs (id) on delete set null,
    created_at    timestamptz not null default now()
);
create index llm_calls_owner_idx on public.llm_calls (owner_id, created_at desc);

-- One row per playground/API question per mode: what the analytics page charts.
create table public.query_log (
    id                   bigint generated always as identity primary key,
    owner_id             uuid not null references auth.users (id) on delete cascade,
    mode                 text not null,
    query                text not null,
    ok                   boolean not null,
    error                text,
    retrieval_latency_ms real,
    total_latency_ms     real,
    input_tokens         int,
    output_tokens        int,
    cost_usd             double precision,
    created_at           timestamptz not null default now()
);
create index query_log_owner_idx on public.query_log (owner_id, created_at desc);

create table public.user_settings (
    owner_id   uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    config     jsonb not null default '{}',
    updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- RLS
-- The browser never touches these tables: it only uses Supabase Auth and calls the API.
-- The API runs user-scoped queries as `structrag_api` with the caller's JWT claims set,
-- so RLS decides what each request can see even inside our own backend.
create role structrag_api nologin noinherit;
grant structrag_api to postgres;
grant usage on schema public, extensions to structrag_api;
grant usage on schema auth to structrag_api;
grant execute on function auth.uid() to structrag_api;
grant select, insert, update, delete on all tables in schema public to structrag_api;
grant usage on all sequences in schema public to structrag_api;
revoke all on all tables in schema public from anon, authenticated;

do $$
declare t text;
begin
    foreach t in array array['documents', 'sections', 'chunks', 'ingest_jobs', 'eval_datasets',
                             'eval_queries', 'benchmark_runs', 'benchmark_results', 'llm_calls',
                             'query_log', 'user_settings']
    loop
        execute format('alter table public.%I enable row level security', t);
        execute format($p$create policy owner_all on public.%I for all to structrag_api
                          using (owner_id = (select auth.uid()))
                          with check (owner_id = (select auth.uid()))$p$, t);
    end loop;
end $$;

-- ---------------------------------------------------------------- storage
-- Private bucket; only the API (service role) reads and writes it.
insert into storage.buckets (id, name, public, file_size_limit)
values ('documents', 'documents', false, 52428800)
on conflict (id) do nothing;
