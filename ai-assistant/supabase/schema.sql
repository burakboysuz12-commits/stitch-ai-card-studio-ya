-- =============================================================================
-- Mini Agent - Supabase schema
-- Run this in the Supabase SQL editor (or as a migration).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- conversations
-- -----------------------------------------------------------------------------
create table if not exists public.conversations (
  id          uuid primary key default gen_random_uuid(),
  -- Owner of the conversation. The app issues an anonymous per-browser UUID
  -- (httpOnly cookie). If you adopt Supabase Auth, store auth.uid() here and
  -- add: references auth.users (id) on delete cascade
  user_id     uuid        not null,
  title       text        not null default 'New conversation',
  created_at  timestamptz not null default now()
);

create index if not exists conversations_user_id_created_at_idx
  on public.conversations (user_id, created_at desc);

-- -----------------------------------------------------------------------------
-- messages
-- -----------------------------------------------------------------------------
create table if not exists public.messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid        not null references public.conversations (id) on delete cascade,
  role             text        not null check (role in ('system', 'user', 'assistant', 'tool')),
  content          text        not null default '',
  -- Completed tool invocations (name, input, output / error) as emitted by the
  -- Vercel AI SDK. Used both to re-render tool cards and to rebuild model context.
  tool_calls       jsonb,
  created_at       timestamptz not null default now()
);

create index if not exists messages_conversation_id_created_at_idx
  on public.messages (conversation_id, created_at);

-- -----------------------------------------------------------------------------
-- Row Level Security
-- The Next.js API routes use the service-role key (server only), which bypasses
-- RLS. RLS is still enabled so the tables are NOT reachable with the public
-- anon key. The policies below make the tables safe to use directly from the
-- browser if you later switch to Supabase Auth (user_id = auth.uid()).
-- -----------------------------------------------------------------------------
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;

create policy "conversations_select_own" on public.conversations
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "conversations_insert_own" on public.conversations
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "conversations_update_own" on public.conversations
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "conversations_delete_own" on public.conversations
  for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy "messages_select_own" on public.messages
  for select to authenticated
  using (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = (select auth.uid())
  ));

create policy "messages_insert_own" on public.messages
  for insert to authenticated
  with check (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = (select auth.uid())
  ));

create policy "messages_delete_own" on public.messages
  for delete to authenticated
  using (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = (select auth.uid())
  ));

-- -----------------------------------------------------------------------------
-- Storage bucket for generated PDFs (private; the app hands out signed URLs)
-- -----------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 10485760, array['application/pdf'])
on conflict (id) do nothing;
