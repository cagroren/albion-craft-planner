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

-- Günlük bonuslar (herkes okur, sadece admin girer). Yeni eklendi: bu bölümü SQL Editor'de çalıştırman yeterli.
create table if not exists public.daily_bonus (
  id bigint generated always as identity primary key,
  server text not null default 'europe' check (server in ('europe','west','east')),
  day date not null default current_date,
  name text not null check (length(name) between 1 and 60),
  pct int not null default 10 check (pct between 1 and 100),
  kind text not null default 'other' check (kind in ('potion','food','other')),
  created_at timestamptz not null default now()
);
alter table public.daily_bonus enable row level security;

drop policy if exists "bonus okuma" on public.daily_bonus;
create policy "bonus okuma" on public.daily_bonus for select using (true);

drop policy if exists "bonus yönetim" on public.daily_bonus;
create policy "bonus yönetim" on public.daily_bonus
  for all using (public.is_admin()) with check (public.is_admin());

-- BUILDS (yeni eklendi): bu bölümü SQL Editor'de çalıştırman yeterli.
-- Herkes okur (paylaşım linki giriş yapmadan da açılır), giriş yapan herkes ekler,
-- sadece sahibi düzenler, sahibi ya da admin siler.
create table if not exists public.builds (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null default auth.uid() references auth.users on delete cascade,
  owner_name text,
  title text not null check (length(title) between 1 and 80),
  content text not null default 'ZvZ' check (length(content) <= 40),
  role text check (length(role) <= 40),
  descr text check (length(descr) <= 3000),
  gear jsonb not null default '{}'::jsonb check (pg_column_size(gear) < 8000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.group_builds (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null default auth.uid() references auth.users on delete cascade,
  owner_name text,
  title text not null check (length(title) between 1 and 80),
  content text not null default 'ZvZ' check (length(content) <= 40),
  descr text check (length(descr) <= 3000),
  slots jsonb not null default '[]'::jsonb check (pg_column_size(slots) < 16000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Yazar adı profilden gelir, sahibi değiştirilemez
create or replace function public.build_stamp() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'UPDATE' then new.owner := old.owner; new.created_at := old.created_at; end if;
  new.owner_name := (select name from public.profiles where id = new.owner);
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists builds_stamp on public.builds;
create trigger builds_stamp before insert or update on public.builds for each row execute function public.build_stamp();
drop trigger if exists group_builds_stamp on public.group_builds;
create trigger group_builds_stamp before insert or update on public.group_builds for each row execute function public.build_stamp();

alter table public.builds enable row level security;
alter table public.group_builds enable row level security;

drop policy if exists "build okuma" on public.builds;
create policy "build okuma" on public.builds for select using (true);
drop policy if exists "build ekleme" on public.builds;
create policy "build ekleme" on public.builds for insert with check (owner = auth.uid() and not public.is_banned());
drop policy if exists "build düzenleme" on public.builds;
create policy "build düzenleme" on public.builds for update using (owner = auth.uid() and not public.is_banned()) with check (owner = auth.uid());
drop policy if exists "build silme" on public.builds;
create policy "build silme" on public.builds for delete using (owner = auth.uid() or public.is_admin());

drop policy if exists "grup okuma" on public.group_builds;
create policy "grup okuma" on public.group_builds for select using (true);
drop policy if exists "grup ekleme" on public.group_builds;
create policy "grup ekleme" on public.group_builds for insert with check (owner = auth.uid() and not public.is_banned());
drop policy if exists "grup düzenleme" on public.group_builds;
create policy "grup düzenleme" on public.group_builds for update using (owner = auth.uid() and not public.is_banned()) with check (owner = auth.uid());
drop policy if exists "grup silme" on public.group_builds;
create policy "grup silme" on public.group_builds for delete using (owner = auth.uid() or public.is_admin());

-- DESTINY BOARD (yeni eklendi): DPS Meter toplayıcısının okuduğu board, karakter başına.
-- Herkes sadece kendi satırlarını görür ve yazar.
create table if not exists public.destiny_boards (
  owner uuid not null default auth.uid() references auth.users on delete cascade,
  char text not null check (length(char) between 1 and 40),
  data jsonb not null default '{}'::jsonb check (pg_column_size(data) < 60000),
  updated_at timestamptz not null default now(),
  primary key (owner, char)
);
alter table public.destiny_boards enable row level security;
drop policy if exists "destiny okuma" on public.destiny_boards;
create policy "destiny okuma" on public.destiny_boards for select using (owner = auth.uid());
drop policy if exists "destiny ekleme" on public.destiny_boards;
create policy "destiny ekleme" on public.destiny_boards for insert with check (owner = auth.uid());
drop policy if exists "destiny güncelleme" on public.destiny_boards;
create policy "destiny güncelleme" on public.destiny_boards for update using (owner = auth.uid()) with check (owner = auth.uid());
drop policy if exists "destiny silme" on public.destiny_boards;
create policy "destiny silme" on public.destiny_boards for delete using (owner = auth.uid());

-- DESTINY PLAN (yeni eklendi): Destiny Board sekmesindeki plan (hedef seviyeler), hesap başına tek satır.
create table if not exists public.destiny_plans (
  owner uuid primary key default auth.uid() references auth.users on delete cascade,
  data jsonb not null default '{}'::jsonb check (pg_column_size(data) < 30000),
  updated_at timestamptz not null default now()
);
alter table public.destiny_plans enable row level security;
drop policy if exists "plan okuma" on public.destiny_plans;
create policy "plan okuma" on public.destiny_plans for select using (owner = auth.uid());
drop policy if exists "plan ekleme" on public.destiny_plans;
create policy "plan ekleme" on public.destiny_plans for insert with check (owner = auth.uid());
drop policy if exists "plan güncelleme" on public.destiny_plans;
create policy "plan güncelleme" on public.destiny_plans for update using (owner = auth.uid()) with check (owner = auth.uid());
drop policy if exists "plan silme" on public.destiny_plans;
create policy "plan silme" on public.destiny_plans for delete using (owner = auth.uid());
