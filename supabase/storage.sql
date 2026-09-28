begin;
alter table public.documents add column if not exists storage_path text;
alter table public.documents add column if not exists original_filename text;
alter table public.documents add column if not exists original_size bigint;
alter table public.documents drop constraint if exists documents_status_check;
alter table public.documents add constraint documents_status_check check (status in ('processing','ready','failed','inactive','deleting'));
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('admission-documents','admission-documents',false,10485760,array['application/pdf','text/plain','text/markdown'])
on conflict(id) do nothing;
notify pgrst, 'reload schema';
commit;