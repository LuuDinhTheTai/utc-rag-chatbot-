-- Add the admissions catalogue to an existing project; safe to re-run.
create table if not exists public.majors (
  id uuid primary key default gen_random_uuid(),
  admission_code text not null check (length(admission_code) between 2 and 30),
  major_code text not null,
  name text not null check (length(name) between 2 and 300),
  program_name text not null check (length(program_name) between 2 and 500),
  admission_year integer not null check (admission_year between 2000 and 2100),
  campus text not null check (campus in ('hanoi','hcm')),
  quota integer check (quota between 0 and 100000),
  methods text[] not null default '{}',
  subject_groups text[] not null default '{}',
  notes text not null default '',
  source_url text not null,
  is_active boolean not null default true,
  search_text text generated always as (admission_code || ' ' || major_code || ' ' || name || ' ' || program_name) stored,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(admission_year,campus,admission_code)
);
create index if not exists majors_catalogue_idx on public.majors(admission_year,campus,is_active,admission_code);
alter table public.majors enable row level security;
-- API checks admin privileges; browser clients cannot mutate tables directly.
revoke all on public.majors from anon,authenticated;
grant all on public.majors to service_role;
notify pgrst, 'reload schema';
