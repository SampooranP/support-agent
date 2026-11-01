-- Ingestion helpers for doc_chunks.

-- Replace all chunks of one document in a single transaction, so a failed re-ingest
-- never leaves a mix of old and new chunks. Rows are inserted fresh, so created_at
-- shows when the content was last ingested.
-- p_chunks: [{"doc_title", "section", "chunk_index", "content", "embedding": [floats]}, ...]
create or replace function public.replace_doc_chunks(p_source text, p_chunks jsonb)
returns int
language plpgsql
set search_path = public, extensions
as $$
declare
  inserted int;
begin
  delete from public.doc_chunks where source = p_source;

  insert into public.doc_chunks (source, doc_title, section, chunk_index, content, embedding)
  select p_source,
         c ->> 'doc_title',
         c ->> 'section',
         (c ->> 'chunk_index')::int,
         c ->> 'content',
         (c ->> 'embedding')::vector
  from jsonb_array_elements(p_chunks) as c;

  get diagnostics inserted = row_count;
  return inserted;
end;
$$;

-- The distinct documents in the table, in one request (instead of paging through every chunk).
create or replace function public.doc_chunk_sources()
returns table (source text)
language sql
stable
set search_path = public
as $$
  select distinct c.source from public.doc_chunks c order by c.source;
$$;

revoke execute on function public.replace_doc_chunks(text, jsonb) from public, anon, authenticated;
revoke execute on function public.doc_chunk_sources() from public, anon, authenticated;
grant execute on function public.replace_doc_chunks(text, jsonb) to service_role;
grant execute on function public.doc_chunk_sources() to service_role;
