-- Run once in the Supabase SQL Editor of a new project.
create extension if not exists vector with schema extensions;

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  title text not null, source_url text not null,
  admission_year integer not null, campus text not null check (campus in ('hanoi','hcm')),
  category text not null, checksum text not null unique, raw_text text not null,
  status text not null check (status in ('processing','ready','failed','inactive')),
  chunk_count integer not null default 0, error text,
  created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  chunk_index integer not null, content text not null, embedding extensions.vector(768) not null,
  unique(document_id,chunk_index)
);
create index chunks_embedding_idx on public.document_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index documents_filter_idx on public.documents(admission_year,campus,status);
create table public.chat_sessions (
  id uuid primary key default gen_random_uuid(), token_hash text not null unique,
  created_at timestamptz not null default now()
);
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.chat_sessions(id) on delete cascade,
  role text not null check (role in ('user','assistant')), content text not null, question text,
  sources jsonb not null default '[]', supported boolean, latency_ms integer,
  created_at timestamptz not null default now()
);
create index messages_session_idx on public.messages(session_id,created_at);
create table public.feedback (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null unique references public.messages(id) on delete cascade,
  rating integer not null check (rating in (-1,1)), comment text not null default '',
  created_at timestamptz not null default now()
);
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.chat_sessions enable row level security;
alter table public.messages enable row level security;
alter table public.feedback enable row level security;
-- All data access goes through FastAPI; browser roles have no table privileges.
revoke all on public.documents,public.document_chunks,public.chat_sessions,public.messages,public.feedback from anon,authenticated;
grant all on public.documents,public.document_chunks,public.chat_sessions,public.messages,public.feedback to service_role;

create function public.match_chunks(query_embedding extensions.vector(768), filter_year integer, filter_campus text, min_similarity float default 0.65, match_count integer default 6)
returns table(id uuid, document_id uuid, content text, title text, source_url text, admission_year integer, campus text, similarity float)
language sql stable security invoker set search_path = public, extensions
as $$
  select c.id,c.document_id,c.content,d.title,d.source_url,d.admission_year,d.campus,
    1-(c.embedding <=> query_embedding) as similarity
  from public.document_chunks c join public.documents d on d.id=c.document_id
  where d.status='ready' and d.admission_year=filter_year and d.campus=filter_campus
    and 1-(c.embedding <=> query_embedding) >= min_similarity
  order by c.embedding <=> query_embedding limit least(greatest(match_count,1),20)
$$;
revoke execute on function public.match_chunks(extensions.vector,integer,text,float,integer) from public,anon,authenticated;
grant execute on function public.match_chunks(extensions.vector,integer,text,float,integer) to service_role;
