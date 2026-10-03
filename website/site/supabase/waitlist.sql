-- klausnote.com waitlist, as applied to the "Klaus" Supabase project (pmdpzroiuhlhwovcqvuz).
-- The site calls join_waitlist() with the publishable key. The table is closed to the
-- public (RLS on, no policies, no grants), so the list can't be read, changed or probed;
-- a repeat signup is silently ignored. Read signups in the dashboard or with:
--   select email, source, created_at from public.waitlist order by created_at;

create extension if not exists citext with schema extensions;

create table public.waitlist (
  id bigint generated always as identity primary key,
  email extensions.citext not null unique
    check (length(email) <= 254 and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  source text check (source is null or length(source) <= 40),
  created_at timestamptz not null default now()
);

alter table public.waitlist enable row level security;
revoke all on public.waitlist from anon, authenticated;

create function public.join_waitlist(email text, source text default null)
returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.waitlist (email, source)
  values (join_waitlist.email, left(join_waitlist.source, 40))
  on conflict on constraint waitlist_email_key do nothing;
$$;

revoke execute on function public.join_waitlist(text, text) from public, authenticated;
grant execute on function public.join_waitlist(text, text) to anon;
