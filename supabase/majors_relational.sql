begin;

create table if not exists public.major_definitions (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (length(code) between 3 and 30),
  name text not null check (length(name) between 2 and 300),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.admission_methods (
  id uuid primary key default gen_random_uuid(),
  label text not null unique check (length(label) between 1 and 500)
);
create table if not exists public.subject_groups (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (length(code) between 2 and 20)
);
create table if not exists public.admission_programs (
  id uuid primary key default gen_random_uuid(),
  major_id uuid not null references public.major_definitions(id),
  admission_code text not null check(length(admission_code) between 2 and 30),
  program_name text not null check(length(program_name) between 2 and 500),
  admission_year integer not null check(admission_year between 2000 and 2100),
  campus text not null check(campus in ('hanoi','hcm')),
  quota integer check(quota between 0 and 100000),
  notes text not null default '',
  source_url text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(admission_year,campus,admission_code)
);
create index if not exists admission_programs_filter_idx
  on public.admission_programs(admission_year,campus,is_active,admission_code);
create index if not exists admission_programs_major_idx on public.admission_programs(major_id);
create table if not exists public.program_methods (
  program_id uuid not null references public.admission_programs(id) on delete cascade,
  method_id uuid not null references public.admission_methods(id),
  position integer not null check (position >= 0),
  primary key (program_id, method_id),
  unique (program_id, position)
);
create table if not exists public.program_subject_groups (
  program_id uuid not null references public.admission_programs(id) on delete cascade,
  group_id uuid not null references public.subject_groups(id),
  position integer not null check (position >= 0),
  primary key (program_id, group_id),
  unique (program_id, position)
);
create index if not exists program_methods_method_idx on public.program_methods(method_id);
create index if not exists program_subject_groups_group_idx on public.program_subject_groups(group_id);

-- Copy the existing catalogue; retain public.majors unchanged as a reversible legacy snapshot.
insert into public.major_definitions(code,name)
select major_code,min(name) from public.majors group by major_code
on conflict(code) do nothing;
insert into public.admission_methods(label)
select distinct unnest(methods) from public.majors
on conflict(label) do nothing;
insert into public.subject_groups(code)
select distinct unnest(subject_groups) from public.majors
on conflict(code) do nothing;
insert into public.admission_programs
  (id,major_id,admission_code,program_name,admission_year,campus,quota,notes,
   source_url,is_active,created_at,updated_at)
select old.id,d.id,old.admission_code,old.program_name,old.admission_year,old.campus,
       old.quota,old.notes,old.source_url,old.is_active,old.created_at,old.updated_at
from public.majors old join public.major_definitions d on d.code=old.major_code
on conflict(id) do nothing;
insert into public.program_methods(program_id,method_id,position)
select old.id,m.id,src.ordinality::integer-1
from public.majors old
cross join lateral unnest(old.methods) with ordinality as src(label,ordinality)
join public.admission_methods m on m.label=src.label
on conflict do nothing;
insert into public.program_subject_groups(program_id,group_id,position)
select old.id,g.id,src.ordinality::integer-1
from public.majors old
cross join lateral unnest(old.subject_groups) with ordinality as src(code,ordinality)
join public.subject_groups g on g.code=src.code
on conflict do nothing;

create or replace view public.major_catalogue with (security_invoker = true) as
select p.id,p.admission_code,d.code as major_code,d.name,p.program_name,
  p.admission_year,p.campus,p.quota,p.notes,p.source_url,p.is_active,
  p.created_at,p.updated_at,
  (p.admission_code || ' ' || d.code || ' ' || d.name || ' ' || p.program_name) as search_text,
  coalesce((select array_agg(m.label order by pm.position)
    from public.program_methods pm join public.admission_methods m on m.id=pm.method_id
    where pm.program_id=p.id), '{}'::text[]) as methods,
  coalesce((select array_agg(g.code order by pg.position)
    from public.program_subject_groups pg join public.subject_groups g on g.id=pg.group_id
    where pg.program_id=p.id), '{}'::text[]) as subject_groups
from public.admission_programs p join public.major_definitions d on d.id=p.major_id;

create or replace function public.save_major(p_data jsonb, p_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp
as $$
declare
  v_definition_id uuid;
  v_program_id uuid;
  v_existing_code text;
  v_label text;
  v_method_id uuid;
  v_group_id uuid;
  v_position integer;
  v_result jsonb;
begin
  if p_id is not null then
    select d.code into v_existing_code
    from public.admission_programs p join public.major_definitions d on d.id=p.major_id
    where p.id=p_id for update of p;
    if not found then return null; end if;
  end if;

  insert into public.major_definitions(code,name)
  values (p_data->>'major_code', p_data->>'name')
  on conflict(code) do update
  set name=excluded.name, updated_at=now()
  returning id into v_definition_id;

  if p_id is null then
    insert into public.admission_programs(major_id,admission_code,program_name,admission_year,campus,quota,notes,source_url,is_active)
    values (v_definition_id,p_data->>'admission_code',p_data->>'program_name',
      (p_data->>'admission_year')::integer,p_data->>'campus',
      (p_data->>'quota')::integer,coalesce(p_data->>'notes',''),p_data->>'source_url',
      coalesce((p_data->>'is_active')::boolean,true))
    returning id into v_program_id;
  else
    update public.admission_programs set major_id=v_definition_id,admission_code=p_data->>'admission_code',
      program_name=p_data->>'program_name',admission_year=(p_data->>'admission_year')::integer,
      campus=p_data->>'campus',quota=(p_data->>'quota')::integer,
      notes=coalesce(p_data->>'notes',''),source_url=p_data->>'source_url',
      is_active=coalesce((p_data->>'is_active')::boolean,true),updated_at=now()
    where id=p_id returning id into v_program_id;
    delete from public.program_methods where program_id=v_program_id;
    delete from public.program_subject_groups where program_id=v_program_id;
  end if;

  v_position:=0;
  for v_label in select value from jsonb_array_elements_text(coalesce(p_data->'methods','[]'::jsonb)) loop
    insert into public.admission_methods(label) values(v_label)
      on conflict(label) do update set label=excluded.label
      returning id into v_method_id;
    insert into public.program_methods(program_id,method_id,position)
      values(v_program_id,v_method_id,v_position);
    v_position:=v_position+1;
  end loop;

  v_position:=0;
  for v_label in select value from jsonb_array_elements_text(coalesce(p_data->'subject_groups','[]'::jsonb)) loop
    insert into public.subject_groups(code) values(v_label)
      on conflict(code) do update set code=excluded.code
      returning id into v_group_id;
    insert into public.program_subject_groups(program_id,group_id,position)
      values(v_program_id,v_group_id,v_position);
    v_position:=v_position+1;
  end loop;

  if p_id is not null and v_existing_code is distinct from p_data->>'major_code' then
    delete from public.major_definitions d where d.code=v_existing_code
      and not exists(select 1 from public.admission_programs p where p.major_id=d.id);
  end if;
  select to_jsonb(c) into v_result from public.major_catalogue c where c.id=v_program_id;
  return v_result;
end $$;

create or replace function public.delete_major(p_id uuid)
returns boolean language plpgsql security invoker set search_path = public, pg_temp
as $$
declare v_definition_id uuid;
begin
  delete from public.admission_programs where id=p_id returning major_id into v_definition_id;
  if not found then return false; end if;
  delete from public.major_definitions d where d.id=v_definition_id
    and not exists(select 1 from public.admission_programs p where p.major_id=d.id);
  return true;
end $$;

create or replace function public.import_majors(p_rows jsonb)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp
as $$
declare v_row jsonb; v_inserted integer:=0; v_skipped integer:=0;
begin
  for v_row in select value from jsonb_array_elements(p_rows) loop
    if exists(select 1 from public.admission_programs where admission_year=(v_row->>'admission_year')::integer
      and campus=v_row->>'campus' and admission_code=v_row->>'admission_code') then
      v_skipped:=v_skipped+1;
    else
      perform public.save_major(v_row,null);
      v_inserted:=v_inserted+1;
    end if;
  end loop;
  return jsonb_build_object('inserted',v_inserted,'skipped',v_skipped,
                            'total',v_inserted+v_skipped);
end $$;

alter table public.admission_programs enable row level security;
alter table public.major_definitions enable row level security;
alter table public.admission_methods enable row level security;
alter table public.subject_groups enable row level security;
alter table public.program_methods enable row level security;
alter table public.program_subject_groups enable row level security;
revoke all on public.admission_programs,public.major_definitions,public.admission_methods,
  public.subject_groups,public.program_methods,public.program_subject_groups from anon,authenticated;
revoke all on public.major_catalogue from anon,authenticated;
grant all on public.admission_programs,public.major_definitions,public.admission_methods,public.subject_groups,
  public.program_methods,public.program_subject_groups to service_role;
grant select on public.major_catalogue to service_role;
revoke execute on function public.save_major(jsonb,uuid),
  public.delete_major(uuid),public.import_majors(jsonb) from public,anon,authenticated;
grant execute on function public.save_major(jsonb,uuid),
  public.delete_major(uuid),public.import_majors(jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
