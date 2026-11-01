-- Knowledge-base chunks with Voyage AI embeddings, searchable with pgvector.

create extension if not exists vector with schema extensions;

create table if not exists public.doc_chunks (
  id          bigint generated always as identity primary key,
  source      text not null,                -- path relative to docs/, e.g. 'refund-policy.md'
  doc_title   text not null,                -- the document's H1
  section     text,                         -- heading path, e.g. 'Orders > How do I track my order?'
  chunk_index int  not null,                -- position of the chunk within its document
  content     text not null,
  embedding   extensions.vector(1024) not null,  -- Voyage voyage-3.5 (1024 dimensions)
  created_at  timestamptz not null default now(),
  unique (source, chunk_index)
);

-- Approximate nearest-neighbour index for cosine distance.
create index if not exists doc_chunks_embedding_idx
  on public.doc_chunks using hnsw (embedding extensions.vector_cosine_ops);

-- RLS on with no policies: only the service role (which bypasses RLS) can read or write.
alter table public.doc_chunks enable row level security;

-- Returns the chunks closest to query_embedding, most similar first.
-- similarity = 1 - cosine distance (1.0 is identical).
create or replace function public.match_doc_chunks(
  query_embedding extensions.vector(1024),
  match_count     int   default 5,
  min_similarity  float default 0
)
returns table (
  id          bigint,
  source      text,
  doc_title   text,
  section     text,
  chunk_index int,
  content     text,
  similarity  float
)
language sql
stable
set search_path = public, extensions
as $$
  select
    c.id,
    c.source,
    c.doc_title,
    c.section,
    c.chunk_index,
    c.content,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.doc_chunks c
  where 1 - (c.embedding <=> query_embedding) >= min_similarity
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- Newer Supabase projects don't grant the API roles access to new objects
-- automatically. Only the backend (service role) uses this table.
grant select, insert, update, delete on public.doc_chunks to service_role;
revoke execute on function public.match_doc_chunks(extensions.vector, int, float) from public, anon, authenticated;
grant execute on function public.match_doc_chunks(extensions.vector, int, float) to service_role;
