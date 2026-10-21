// /api/sweep: Vercel Cron her gün çalıştırır. Discord'dan çıkmış ya da rolü düşmüş kişilerin hesabını ve verisini siler.
// Botta "Server Members Intent" açık olmalı (üye listesini okumak için).
import { SB, svcHeaders, allowedRoles, discordIdOf, deleteUser, json } from "./_guild.js";

const DAPI = "https://discord.com/api/v10";

async function guildMembers(gid) {
  const out = new Map();
  let after = "0";
  for (;;) {
    const r = await fetch(`${DAPI}/guilds/${gid}/members?limit=1000&after=${after}`, { headers: { Authorization: `Bot ${process.env.DISCORD_BOT_TOKEN.trim()}` } });
    if (!r.ok) throw new Error(`Discord üye listesi okunamadı (${r.status}); botta Server Members Intent açık mı?`);
    const page = await r.json();
    page.forEach(m => out.set(m.user.id, m.roles || []));
    if (page.length < 1000) return out;
    after = page[page.length - 1].user.id;
  }
}

async function allUsers() {
  const out = [];
  for (let p = 1; ; p++) {
    const r = await fetch(`${SB}/auth/v1/admin/users?page=${p}&per_page=500`, { headers: svcHeaders() });
    if (!r.ok) throw new Error(`Supabase kullanıcıları okunamadı (${r.status})`);
    const j = await r.json(), list = j.users || j;
    out.push(...list);
    if (list.length < 500) return out;
  }
}

export async function GET(req) {
  const secret = (process.env.CRON_SECRET || "").trim();
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) return json({ error: "izin yok" }, 401);
  try {
    const R = await allowedRoles(), members = await guildMembers(R.gid);
    // Güvenlik: liste boş ya da şüpheli derecede kısaysa (Discord hatası) kimseyi silme
    if (members.size < 2) throw new Error("üye listesi boş geldi, silme yapılmadı");
    const ar = await fetch(`${SB}/rest/v1/profiles?is_admin=eq.true&select=id`, { headers: svcHeaders() });
    const admins = new Set((ar.ok ? await ar.json() : []).map(x => x.id));
    const removed = [];
    for (const u of await allUsers()) {
      if (admins.has(u.id)) continue;
      const did = discordIdOf(u);
      if (!did) continue;
      const roles = members.get(did);
      if (roles && roles.some(id => R.ids.has(id))) continue;
      await deleteUser(u.id);
      removed.push({ name: u.user_metadata?.full_name || u.user_metadata?.name || did, why: roles ? "rolü yok" : "sunucuda değil" });
    }
    return json({ ok: true, members: members.size, removed });
  } catch (e) {
    return json({ ok: false, error: String(e.message || e) }, 500);
  }
}
