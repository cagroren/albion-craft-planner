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

-- GUILD ERİŞİMİ (yeni eklendi): sadece Kal Vas Flam Discord'unda "Üye" rolü olanlar veri okuyup yazabilir.
-- member alanını sadece sunucu (/api/access, servis anahtarı) değiştirir; kullanıcıların profiles'a yazma izni yok.
alter table public.profiles add column if not exists discord_id text;
alter table public.profiles add column if not exists member boolean not null default false;
alter table public.profiles add column if not exists member_checked_at timestamptz;

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select (member or is_admin) and not banned from public.profiles where id = auth.uid()), false)
$$;

drop policy if exists "kendi verisi" on public.user_data;
create policy "kendi verisi" on public.user_data
  for all
  using (user_id = auth.uid() and public.is_member())
  with check (user_id = auth.uid() and public.is_member() and length(value) < 1000000);

drop policy if exists "build okuma" on public.builds;
create policy "build okuma" on public.builds for select using (public.is_member());
drop policy if exists "build ekleme" on public.builds;
create policy "build ekleme" on public.builds for insert with check (owner = auth.uid() and public.is_member());
drop policy if exists "build düzenleme" on public.builds;
create policy "build düzenleme" on public.builds for update using (owner = auth.uid() and public.is_member()) with check (owner = auth.uid());
drop policy if exists "grup okuma" on public.group_builds;
create policy "grup okuma" on public.group_builds for select using (public.is_member());
drop policy if exists "grup ekleme" on public.group_builds;
create policy "grup ekleme" on public.group_builds for insert with check (owner = auth.uid() and public.is_member());
drop policy if exists "grup düzenleme" on public.group_builds;
create policy "grup düzenleme" on public.group_builds for update using (owner = auth.uid() and public.is_member()) with check (owner = auth.uid());

drop policy if exists "destiny okuma" on public.destiny_boards;
create policy "destiny okuma" on public.destiny_boards for select using (owner = auth.uid() and public.is_member());
drop policy if exists "destiny ekleme" on public.destiny_boards;
create policy "destiny ekleme" on public.destiny_boards for insert with check (owner = auth.uid() and public.is_member());
drop policy if exists "destiny güncelleme" on public.destiny_boards;
create policy "destiny güncelleme" on public.destiny_boards for update using (owner = auth.uid() and public.is_member()) with check (owner = auth.uid());
drop policy if exists "plan okuma" on public.destiny_plans;
create policy "plan okuma" on public.destiny_plans for select using (owner = auth.uid() and public.is_member());
drop policy if exists "plan ekleme" on public.destiny_plans;
create policy "plan ekleme" on public.destiny_plans for insert with check (owner = auth.uid() and public.is_member());
drop policy if exists "plan güncelleme" on public.destiny_plans;
create policy "plan güncelleme" on public.destiny_plans for update using (owner = auth.uid() and public.is_member()) with check (owner = auth.uid());

-- CANLI ÜYE KONTROLÜ (yeni eklendi): Supabase her dakika /api/sweep'i çağırır; Discord'dan atılan ya da rolü
-- düşen kişinin hesabı ve verisi en geç 1 dakikada silinir. Çağrı anahtarını veritabanı kendisi üretir.
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

create table if not exists public.app_secrets (name text primary key, value text not null);
alter table public.app_secrets enable row level security;  -- politika yok: sadece servis anahtarı okuyabilir
revoke all on public.app_secrets from anon, authenticated;
insert into public.app_secrets (name, value)
  values ('sweep', encode(extensions.gen_random_bytes(32), 'hex'))
  on conflict (name) do nothing;

select cron.unschedule(jobid) from cron.job where jobname = 'kvf-sweep';
select cron.schedule('kvf-sweep', '* * * * *', $$
  select net.http_get(
    url := 'https://albion-craft-planner-lovat.vercel.app/api/sweep',
    headers := jsonb_build_object('x-sweep-key', (select value from public.app_secrets where name = 'sweep')),
    timeout_milliseconds := 30000)
$$);

-- PANEL (yeni eklendi): silinenler geçmişi, canlı kontrol durumu, kullanım istatistikleri, admin yapma.
-- Silinen hesapların kaydı (hesap silindiği için auth.users'a bağlı değil). Sadece sunucu yazar, adminler okur.
create table if not exists public.removals (
  id bigserial primary key,
  discord_id text,
  name text,
  why text,
  source text not null,          -- 'sweep' (dakikalık), 'access' (girişte), 'manual' (panelden)
  by_admin uuid,
  created_at timestamptz not null default now()
);
alter table public.removals enable row level security;
drop policy if exists "silinenler okuma" on public.removals;
create policy "silinenler okuma" on public.removals for select using (public.is_admin());

-- Dakikalık temizliğin son durumu (sunucu yazar)
create table if not exists public.app_status (key text primary key, data jsonb not null, updated_at timestamptz not null default now());
alter table public.app_status enable row level security;
drop policy if exists "durum okuma" on public.app_status;
create policy "durum okuma" on public.app_status for select using (public.is_admin());

create or replace function public.admin_sweep_status() returns jsonb
language plpgsql stable security definer set search_path = public, cron as $$
begin
  if not public.is_admin() then raise exception 'Yetki yok'; end if;
  return jsonb_build_object(
    'job', (select jsonb_build_object('active', active, 'schedule', schedule) from cron.job where jobname = 'kvf-sweep'),
    'last', (select jsonb_build_object('data', data, 'at', updated_at) from public.app_status where key = 'sweep'));
end $$;

-- Sayfa açılışları: gün, sayfa ve kullanıcı başına sayaç. Doğrudan erişim yok, sadece track() ve admin_stats().
create table if not exists public.page_views (
  day date not null default current_date,
  page text not null,
  user_id uuid not null references auth.users on delete cascade,
  n int not null default 1,
  primary key (day, page, user_id)
);
alter table public.page_views enable row level security;

create or replace function public.track(p text) returns void
language sql security definer set search_path = public as $$
  insert into public.page_views (page, user_id) select left(p, 40), auth.uid() where auth.uid() is not null and public.is_member()
  on conflict (day, page, user_id) do update set n = page_views.n + 1
$$;

create or replace function public.admin_stats(days int default 30) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Yetki yok'; end if;
  return jsonb_build_object(
    'daily', (select coalesce(jsonb_agg(x order by x.day), '[]') from (
        select d::date as day,
               (select count(distinct user_id) from public.page_views v where v.day = d::date) as users,
               (select coalesce(sum(n), 0) from public.page_views v where v.day = d::date) as views,
               (select count(*) from public.profiles p where p.created_at::date = d::date) as signups
        from generate_series(current_date - (days - 1), current_date, interval '1 day') d) x),
    'pages', (select coalesce(jsonb_agg(x order by x.views desc), '[]') from (
        select page, sum(n)::int as views, count(distinct user_id)::int as users
        from public.page_views where day > current_date - days group by page) x));
end $$;

-- Kullanıcı listesi: Discord bilgisi ve kullanım (build, destiny) ile. Dönüş tipi değiştiği için önce silinir.
drop function if exists public.admin_users();
create or replace function public.admin_users()
returns table (id uuid, name text, avatar text, banned boolean, is_admin boolean, created_at timestamptz,
               last_seen timestamptz, keys int, bytes int, discord_id text, member boolean,
               member_checked_at timestamptz, builds int, groups int, boards int, has_plan boolean)
language sql stable security definer set search_path = public as $$
  select p.id, p.name, p.avatar, p.banned, p.is_admin, p.created_at, p.last_seen,
         (select count(*) from public.user_data d where d.user_id = p.id)::int,
         (select coalesce(sum(length(d.value)), 0) from public.user_data d where d.user_id = p.id)::int,
         p.discord_id, p.member, p.member_checked_at,
         (select count(*) from public.builds b where b.owner = p.id)::int,
         (select count(*) from public.group_builds g where g.owner = p.id)::int,
         (select count(*) from public.destiny_boards s where s.owner = p.id)::int,
         exists (select 1 from public.destiny_plans l where l.owner = p.id)
  from public.profiles p
  where public.is_admin()
  order by p.created_at desc
$$;

-- Admin yap / adminliği al (kendini alamazsın)
create or replace function public.admin_set_admin(uid uuid, a boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Yetki yok'; end if;
  if uid = auth.uid() and not a then raise exception 'Kendi adminliğini alamazsın'; end if;
  update public.profiles set is_admin = a where id = uid;
end $$;

-- PANEL 2 (yeni eklendi): resmi guild build'leri, sekme aç/kapat, admin işlem kaydı.
alter table public.builds add column if not exists official boolean not null default false;
alter table public.group_builds add column if not exists official boolean not null default false;

-- Build damgası: "resmi" işaretini sadece admin değiştirir; sadece işaret değişince tarih (sıralama) değişmez
create or replace function public.build_stamp() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    new.owner := old.owner; new.created_at := old.created_at;
    if not public.is_admin() then new.official := old.official; end if;
    if (to_jsonb(new) - 'official' - 'updated_at' - 'owner_name') = (to_jsonb(old) - 'official' - 'updated_at' - 'owner_name') then
      return new;
    end if;
  elsif not public.is_admin() then
    new.official := false;
  end if;
  new.owner_name := (select name from public.profiles where id = new.owner);
  new.updated_at := now();
  return new;
end $$;

-- Site ayarları (herkes okur, sadece admin yazar). tabs_off: kapalı sekmelerin listesi, ör. ["dps"]
create table if not exists public.site_settings (key text primary key, value jsonb not null, updated_at timestamptz not null default now());
alter table public.site_settings enable row level security;
drop policy if exists "ayar okuma" on public.site_settings;
create policy "ayar okuma" on public.site_settings for select using (true);
drop policy if exists "ayar yazma" on public.site_settings;
create policy "ayar yazma" on public.site_settings for all using (public.is_admin()) with check (public.is_admin());

-- Admin işlem kaydı: veritabanı tetikleyicileri yazar, adminler okur
create table if not exists public.admin_log (
  id bigserial primary key,
  admin uuid,
  admin_name text,
  action text not null,
  target text,
  created_at timestamptz not null default now()
);
alter table public.admin_log enable row level security;
drop policy if exists "kayıt okuma" on public.admin_log;
create policy "kayıt okuma" on public.admin_log for select using (public.is_admin());

create or replace function public.admin_log_add(a text, t text) returns void
language sql security definer set search_path = public as $$
  insert into public.admin_log (admin, admin_name, action, target)
  select auth.uid(), (select name from public.profiles where id = auth.uid()), a, left(t, 200)
  where auth.uid() is not null and public.is_admin()
$$;

create or replace function public.log_profiles() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.banned is distinct from old.banned then
    perform public.admin_log_add(case when new.banned then 'Engelledi' else 'Engeli kaldırdı' end, new.name);
  end if;
  if new.is_admin is distinct from old.is_admin then
    perform public.admin_log_add(case when new.is_admin then 'Admin yaptı' else 'Adminliği aldı' end, new.name);
  end if;
  return new;
end $$;
drop trigger if exists profiles_log on public.profiles;
create trigger profiles_log after update on public.profiles for each row execute function public.log_profiles();

create or replace function public.log_builds() returns trigger
language plpgsql security definer set search_path = public as $$
declare k text := case when tg_table_name = 'group_builds' then 'grup build' else 'build' end;
begin
  if tg_op = 'DELETE' then
    if old.owner is distinct from auth.uid() then perform public.admin_log_add(initcap(k) || ' sildi', old.title || ' (' || coalesce(old.owner_name, '?') || ')'); end if;
    return old;
  end if;
  if new.official is distinct from old.official then
    perform public.admin_log_add(case when new.official then 'Resmi ' || k || ' yaptı' else 'Resmi ' || k || ' işaretini kaldırdı' end, new.title || ' (' || coalesce(new.owner_name, '?') || ')');
  end if;
  return new;
end $$;
drop trigger if exists builds_log on public.builds;
create trigger builds_log after update or delete on public.builds for each row execute function public.log_builds();
drop trigger if exists group_builds_log on public.group_builds;
create trigger group_builds_log after update or delete on public.group_builds for each row execute function public.log_builds();

create or replace function public.log_announcements() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then perform public.admin_log_add('Duyuru yayınladı', new.text);
  elsif tg_op = 'DELETE' then perform public.admin_log_add('Duyuru sildi', old.text); return old;
  elsif new.active is distinct from old.active then perform public.admin_log_add(case when new.active then 'Duyuruyu tekrar yayınladı' else 'Duyuruyu yayından kaldırdı' end, new.text);
  end if;
  return new;
end $$;
drop trigger if exists announcements_log on public.announcements;
create trigger announcements_log after insert or update or delete on public.announcements for each row execute function public.log_announcements();

create or replace function public.log_settings() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.admin_log_add('Ayar değiştirdi: ' || new.key, new.value::text);
  return new;
end $$;
drop trigger if exists settings_log on public.site_settings;
create trigger settings_log after insert or update on public.site_settings for each row execute function public.log_settings();

-- Adminler başkasının build'inde sadece "resmi" işaretini değiştirebilsin (diğer alanları panel göndermez; sahibi tetikleyici korur)
drop policy if exists "build admin" on public.builds;
create policy "build admin" on public.builds for update using (public.is_admin()) with check (public.is_admin());
drop policy if exists "grup admin" on public.group_builds;
create policy "grup admin" on public.group_builds for update using (public.is_admin()) with check (public.is_admin());

-- GERİ BİLDİRİM (yeni eklendi): üyeler sağ alttaki balondan gönderir; sadece site sahibi (is_owner) okur, adminler göremez.
alter table public.profiles add column if not exists is_owner boolean not null default false;
update public.profiles set is_owner = true where id = '2cd3a1fe-6dba-4128-8a10-5e5fad5bd4c5';

create or replace function public.is_owner() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select is_owner from public.profiles where id = auth.uid()), false)
$$;

create table if not exists public.feedback (
  id bigserial primary key,
  user_id uuid default auth.uid() references auth.users on delete set null,
  name text,
  page text check (length(page) <= 60),
  title text not null check (length(title) between 1 and 100),
  body text check (length(body) <= 2000),
  done boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.feedback enable row level security;
drop policy if exists "geri bildirim gönderme" on public.feedback;
create policy "geri bildirim gönderme" on public.feedback for insert with check (user_id = auth.uid() and public.is_member());
drop policy if exists "geri bildirim okuma" on public.feedback;
create policy "geri bildirim okuma" on public.feedback for select using (public.is_owner());
drop policy if exists "geri bildirim güncelleme" on public.feedback;
create policy "geri bildirim güncelleme" on public.feedback for update using (public.is_owner()) with check (public.is_owner());
drop policy if exists "geri bildirim silme" on public.feedback;
create policy "geri bildirim silme" on public.feedback for delete using (public.is_owner());

-- Gönderenin adı profilden gelir (elle yazılamaz); kişi başı dakikada en fazla 3 gönderim
create or replace function public.feedback_stamp() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.feedback where user_id = auth.uid() and created_at > now() - interval '1 minute') >= 3 then
    raise exception 'Çok hızlı gönderiyorsun, biraz bekle';
  end if;
  new.name := (select name from public.profiles where id = auth.uid());
  new.done := false;
  new.created_at := now();
  return new;
end $$;
drop trigger if exists feedback_stamp on public.feedback;
create trigger feedback_stamp before insert on public.feedback for each row execute function public.feedback_stamp();

-- DRAGON PORTALLARI (yeni eklendi): üyelerin toplayıcılarının gördüğü Ancient Lands portalları (Portallar sekmesi).
-- closes: paketten okunan kapanış; est: okunamadıysa görülme + açık kalma süresi (tahmin).
-- Yazma sadece report_dragon_portal() ile: aynı yerdeki aynı portal tek satır, süresi dolan yeniden açılınca baştan başlar.
create table if not exists public.dragon_portals (
  id text primary key check (length(id) <= 120),
  zone text not null check (length(zone) <= 40),
  kind text check (length(kind) <= 40),
  x real,
  y real,
  opens_at timestamptz,
  closes_at timestamptz not null,
  exact boolean not null default false,
  gone_at timestamptz not null,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  seen_by uuid references auth.users on delete set null,
  seen_name text,
  raw jsonb
);
alter table public.dragon_portals add column if not exists exact boolean not null default false;
alter table public.dragon_portals enable row level security;
drop policy if exists "portal okuma" on public.dragon_portals;
create policy "portal okuma" on public.dragon_portals for select using (public.is_member());
create index if not exists dragon_portals_gone on public.dragon_portals (gone_at);

create or replace function public.report_dragon_portal(p jsonb) returns void
language plpgsql security definer set search_path = public as $$
declare
  z text := left(p->>'zone', 40);
  k text := left(p->>'kind', 40);
  px real := (p->>'x')::real;
  py real := (p->>'y')::real;
  cl timestamptz := least(coalesce(to_timestamp((p->>'closes')::double precision), to_timestamp((p->>'est')::double precision), now() + interval '10 minutes'), now() + interval '30 minutes');
  op timestamptz := to_timestamp((p->>'opens')::double precision);
  pid text;
begin
  if not public.is_member() or z is null then return; end if;
  pid := z || '|' || coalesce(k, '?') || '|' || coalesce(round(px)::text, '?') || '|' || coalesce(round(py)::text, '?');
  insert into public.dragon_portals as d (id, zone, kind, x, y, opens_at, closes_at, exact, gone_at, seen_by, seen_name, raw)
  values (pid, z, k, px, py, op, cl, (p->>'closes') is not null, cl + interval '5 minutes', auth.uid(),
          (select name from public.profiles where id = auth.uid()), case when length(p->>'raw') < 4000 then p->'raw' end)
  on conflict (id) do update set
    -- Eski portalın süresi dolduysa bu yeni bir portal: ilk görülme ve görenler baştan
    first_seen = case when d.gone_at < now() then now() else d.first_seen end,
    seen_by = case when d.gone_at < now() then excluded.seen_by else d.seen_by end,
    seen_name = case when d.gone_at < now() then excluded.seen_name else d.seen_name end,
    opens_at = coalesce(excluded.opens_at, case when d.gone_at < now() then null else d.opens_at end),
    closes_at = case when (p->>'closes') is not null or d.gone_at < now() then excluded.closes_at else d.closes_at end,
    exact = case when (p->>'closes') is not null then true when d.gone_at < now() then false else d.exact end,
    gone_at = case when (p->>'closes') is not null or d.gone_at < now() then excluded.gone_at else d.gone_at end,
    last_seen = now(),
    raw = coalesce(excluded.raw, d.raw);
  delete from public.dragon_portals where gone_at < now() - interval '1 day';
end $$;
revoke all on function public.report_dragon_portal(jsonb) from public, anon;
grant execute on function public.report_dragon_portal(jsonb) to authenticated;

-- PORTAL ZAMANLARI (yeni eklendi): her portal türü oyunda tek bir global sayaçla açılır; Portallar sekmesi
-- son açılıştan sonrakini tahmin eder. Toplayıcının gördükleri dragon_portals'tan, elle "Şimdi açıldı" buradan gelir.
create table if not exists public.dragon_portal_times (
  kind text primary key check (kind ~ '^DRAGON_AREA_(ORANGE|BLACK)_(SMALL|MEDIUM|LARGE)$'),
  last_at timestamptz not null,
  by_name text
);
alter table public.dragon_portal_times enable row level security;
drop policy if exists "portal zamanı okuma" on public.dragon_portal_times;
create policy "portal zamanı okuma" on public.dragon_portal_times for select using (public.is_member());

create or replace function public.mark_portal_time(k text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_member() or k !~ '^DRAGON_AREA_(ORANGE|BLACK)_(SMALL|MEDIUM|LARGE)$' then return; end if;
  insert into public.dragon_portal_times as t (kind, last_at, by_name)
  values (k, now(), (select name from public.profiles where id = auth.uid()))
  -- Aynı açılışa birkaç kişi basarsa ilk basış geçerli kalır
  on conflict (kind) do update set last_at = excluded.last_at, by_name = excluded.by_name
  where t.last_at < now() - interval '3 minutes';
end $$;
revoke all on function public.mark_portal_time(text) from public, anon;
grant execute on function public.mark_portal_time(text) to authenticated;
