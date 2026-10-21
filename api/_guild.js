// Kal Vas Flam guild erişimi: Discord botu ile üyelik ve rol kontrolü, Supabase servis anahtarı ile hesap silme.
// Vercel ortam değişkenleri:
//   DISCORD_BOT_TOKEN           botun token'ı (Discord Developer Portal > Bot)
//   DISCORD_GUILD_ID            sunucu ID'si
//   DISCORD_MIN_ROLE            siteye girmek için gereken rolün adı (varsayılan "Üye"); sadece bu rolü olanlar girer
//   SUPABASE_SERVICE_ROLE_KEY   Supabase > Project Settings > API Keys > secret (ya da service_role)
//   CRON_SECRET                 günlük temizliği sadece Vercel Cron çalıştırabilsin diye
export const SB = "https://aulscfeqndppxbtypezs.supabase.co";
export const ANON = "sb_publishable_v-eTBIU2R9vng0qCfOOpjA_lQm2m95W";
const DAPI = "https://discord.com/api/v10";
const env = k => (process.env[k] || "").trim();

export function svcHeaders(extra) {
  const k = env("SUPABASE_SERVICE_ROLE_KEY");
  if (!k) throw new Error("SUPABASE_SERVICE_ROLE_KEY ayarlı değil");
  // Eski JWT anahtarları Authorization ister; yeni sb_secret_ anahtarları apikey ile yeter
  return { apikey: k, ...(k.startsWith("eyJ") ? { Authorization: `Bearer ${k}` } : {}), ...extra };
}

async function discord(path) {
  const t = env("DISCORD_BOT_TOKEN");
  if (!t) throw new Error("DISCORD_BOT_TOKEN ayarlı değil");
  for (let i = 0; i < 3; i++) {
    const r = await fetch(DAPI + path, { headers: { Authorization: `Bot ${t}` } });
    if (r.status === 429) {
      const wait = Math.min(5000, 1000 * (+(await r.json().catch(() => ({}))).retry_after || 1));
      await new Promise(s => setTimeout(s, wait));
      continue;
    }
    return r;
  }
  throw new Error("Discord çok fazla istek dedi");
}

const low = s => String(s || "").toLocaleLowerCase("tr").trim();

// İzinli rol: sadece DISCORD_MIN_ROLE adındaki rol (ör. "Üye"). Üst roller tek başına yetmez, bu rol de olmalı.
export async function allowedRoles() {
  const gid = env("DISCORD_GUILD_ID");
  if (!gid) throw new Error("DISCORD_GUILD_ID ayarlı değil");
  const r = await discord(`/guilds/${gid}/roles`);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    const hint = r.status === 401 ? "DISCORD_BOT_TOKEN yanlış"
      : j.code === 10004 ? `sunucu bulunamadı: DISCORD_GUILD_ID (${gid.slice(0, 4)}…, ${gid.length} hane) yanlış ya da bot sunucuda değil`
      : j.code === 50001 ? "bot sunucuda değil" : (j.message || "");
    throw new Error(`Discord rolleri okunamadı (${r.status}${j.code ? "/" + j.code : ""}): ${hint}`);
  }
  const roles = await r.json(), want = low(env("DISCORD_MIN_ROLE") || "Üye");
  const min = roles.find(x => low(x.name) === want);
  if (!min) throw new Error(`Discord'da "${env("DISCORD_MIN_ROLE") || "Üye"}" rolü bulunamadı`);
  return { gid, min: min.name, ids: new Set([min.id]) };
}

// true: girebilir, false: Discord kesin olarak "üye değil / rolü yok" dedi, hata: bilinmiyor (hiçbir şey silinmez)
export async function memberAllowed(discordId, R) {
  const r = await discord(`/guilds/${R.gid}/members/${discordId}`);
  if (r.status === 404) { const j = await r.json().catch(() => ({})); if (j.code === 10007 || j.code === 10013) return { ok: false, why: "sunucuda değil" }; }
  if (!r.ok) throw new Error(`Discord üyeliği okunamadı (${r.status})`);
  const m = await r.json();
  return (m.roles || []).some(id => R.ids.has(id)) ? { ok: true } : { ok: false, why: `Discord'da ${R.min} rolün yok` };
}

export const discordIdOf = u => {
  const i = (u.identities || []).find(x => x.provider === "discord");
  return (i && (i.identity_data?.provider_id || i.identity_data?.sub || i.id)) || u.user_metadata?.provider_id || u.user_metadata?.sub || null;
};

export async function profileOf(uid) {
  const r = await fetch(`${SB}/rest/v1/profiles?id=eq.${uid}&select=is_admin,member`, { headers: svcHeaders() });
  if (!r.ok) throw new Error(`profil okunamadı (${r.status})`);
  return (await r.json())[0] || {};
}

export async function setMember(uid, did, ok) {
  const r = await fetch(`${SB}/rest/v1/profiles?id=eq.${uid}`, {
    method: "PATCH", headers: svcHeaders({ "Content-Type": "application/json", Prefer: "return=minimal" }),
    body: JSON.stringify({ member: ok, discord_id: did, member_checked_at: new Date().toISOString() })
  });
  if (!r.ok) throw new Error(`profil güncellenemedi (${r.status}); veritabanı SQL'i çalıştırıldı mı?`);
}

// Hesabı siler; bütün tablolar auth.users'a "on delete cascade" bağlı olduğu için build, destiny ve bulut kaydı da gider
export async function deleteUser(uid) {
  const r = await fetch(`${SB}/auth/v1/admin/users/${uid}`, { method: "DELETE", headers: svcHeaders() });
  if (!r.ok && r.status !== 404) throw new Error(`hesap silinemedi (${r.status})`);
}

export const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
