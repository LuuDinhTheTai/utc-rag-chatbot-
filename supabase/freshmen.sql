begin;
create table if not exists public.freshman_guides (
 id uuid primary key default gen_random_uuid(),
 cohort text not null unique check(length(cohort) between 2 and 20),
 admission_year integer not null check(admission_year between 2000 and 2100),
 title text not null,
 storage_path text not null,
 is_published boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create table if not exists public.freshman_items (
 id uuid primary key default gen_random_uuid(),
 guide_id uuid not null references public.freshman_guides(id) on delete cascade,
 code text not null check(length(code) between 1 and 20),
 category text not null check(category in ('document','priority')),
 title text not null check(length(title) between 2 and 500),
 applies_to text not null default '',
 evidence text not null default '',
 source_page integer not null check(source_page between 1 and 100),
 sort_order integer not null default 0,
 is_active boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(guide_id,category,code)
);
create index if not exists freshman_items_order_idx on public.freshman_items(guide_id,category,sort_order);
alter table public.freshman_guides enable row level security;
alter table public.freshman_items enable row level security;
revoke all on public.freshman_guides,public.freshman_items from anon,authenticated;
grant all on public.freshman_guides,public.freshman_items to service_role;
notify pgrst, 'reload schema';
commit;