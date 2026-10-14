-- Albion Craft Planner: kullanıcılar, bulut kayıt, duyurular
-- Supabase > SQL Editor'e yapıştırıp Run de.

-- Kullanıcı profilleri (Discord ile ilk girişte otomatik oluşur)
create table if not exists public.profiles (
  id uuid primary key references auth.users on delete cascade,
  name text,
  avatar text,
  is_admin boolean not null default false,
  banned boolean not null default false,
  created_at timestamptz not null default now(),
  last_seen timestamptz
);
alter table public.profiles enable row level security;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select is_admin from public.profiles where id = auth.uid()), false)
$$;

create or replace function public.is_banned() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select banned from public.profiles where id = auth.uid()), false)
$$;

drop policy if exists "profil okuma" on public.profiles;
create policy "profil okuma" on public.profiles
  for select using (id = auth.uid() or public.is_admin());

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, name, avatar) values (
    new.id,
    coalesce(new.raw_user_meta_data->'custom_claims'->>'global_name',
             new.raw_user_meta_data->>'full_name',
             new.raw_user_meta_data->>'name',
             new.email),
    new.raw_user_meta_data->>'avatar_url')
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Kullanıcının bulut verisi (profiller, plan, ayarlar)
create table if not exists public.user_data (
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  key text not null,
  value text not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, key)
);
alter table public.user_data enable row level security;

drop policy if exists "kendi verisi" on public.user_data;
create policy "kendi verisi" on public.user_data
  for all
  using (user_id = auth.uid() and not public.is_banned())
  with check (user_id = auth.uid() and not public.is_banned() and length(value) < 1000000);

-- Duyurular (herkes aktif olanları görür, sadece admin yazar)
create table if not exists public.announcements (
  id bigint generated always as identity primary key,
  text text not null check (length(text) <= 500),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.announcements enable row level security;

drop policy if exists "duyuru okuma" on public.announcements;
create policy "duyuru okuma" on public.announcements
  for select using (active or public.is_admin());

drop policy if exists "duyuru yönetim" on public.announcements;
create policy "duyuru yönetim" on public.announcements
  for all using (public.is_admin()) with check (public.is_admin());

-- Son görülme
create or replace function public.touch() returns void
language sql security definer set search_path = public as $$
  update public.profiles set last_seen = now() where id = auth.uid()
$$;

-- Admin: kullanıcı listesi
create or replace function public.admin_users()
returns table (id uuid, name text, avatar text, banned boolean, is_admin boolean,
               created_at timestamptz, last_seen timestamptz, keys int, bytes int)
language sql stable security definer set search_path = public as $$
  select p.id, p.name, p.avatar, p.banned, p.is_admin, p.created_at, p.last_seen,
         count(d.key)::int, coalesce(sum(length(d.value)), 0)::int
  from public.profiles p
  left join public.user_data d on d.user_id = p.id
  where public.is_admin()
  group by p.id
  order by p.created_at desc
$$;

-- Admin: engelle / engeli kaldır
create or replace function public.admin_set_banned(uid uuid, b boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Yetki yok'; end if;
  if uid = auth.uid() then raise exception 'Kendini engelleyemezsin'; end if;
  update public.profiles set banned = b where id = uid;
end $$;

-- KENDİNİ ADMİN YAP: siteye Discord ile ilk kez giriş yaptıktan sonra
-- aşağıdaki satırın başındaki "--" işaretini silip sadece onu çalıştır.
-- update public.profiles set is_admin = true where id = (select id from public.profiles order by created_at limit 1);
