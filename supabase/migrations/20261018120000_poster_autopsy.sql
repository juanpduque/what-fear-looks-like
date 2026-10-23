-- One row per film for the autopsy. The essay's chart series and the
-- search catalog stay as static files on Netlify; this table replaces the
-- ~70 MB of per-poster JSON the page used to download up front.
--
-- Apply in the Supabase SQL editor, or with the Supabase CLI:
--   supabase db push

create table if not exists public.poster_autopsy (
  id bigint primary key,
  lookup jsonb,
  pose jsonb,
  creature_boxes jsonb,
  weapon_boxes jsonb,
  saliency jsonb,
  title_ink jsonb,
  omdb jsonb,
  medium_cl jsonb,
  key_art jsonb,
  alts jsonb,
  alts_rek jsonb,
  alts_pose jsonb,
  alts_sal jsonb,
  alts_comp jsonb,
  alts_faces jsonb,
  alts_owl jsonb,
  alts_text jsonb,
  alts_clip jsonb
);

alter table public.poster_autopsy enable row level security;

drop policy if exists poster_autopsy_public_read on public.poster_autopsy;
create policy poster_autopsy_public_read
  on public.poster_autopsy
  for select
  to anon, authenticated
  using (true);

grant select on public.poster_autopsy to anon, authenticated;
