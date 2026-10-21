// /api/sweep: Supabase pg_cron her dakika, Vercel Cron yedek olarak her gün çalıştırır. Discord'dan çıkmış ya da
// Üye rolü alınmış kişilerin hesabını ve verisini siler; sonucu panel için app_status ve removals'a yazar.
import { SB, svcHeaders, allowedRoles, discordIdOf, deleteUser, guildMembers, logRemovals, setStatus, nameOf, json } from "./_guild.js";

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

// İki çağıran var: Vercel Cron (günde bir, CRON_SECRET) ve Supabase pg_cron (her dakika, x-sweep-key).
// pg_cron'un anahtarını veritabanı kendisi üretip app_secrets tablosunda tutar; kimse elle girmez.
async function authorized(req) {
  const secret = (process.env.CRON_SECRET || "").trim();
  if (secret && req.headers.get("authorization") === `Bearer ${secret}`) return true;
  const k = req.headers.get("x-sweep-key");
  if (!k || k.length < 32) return false;
  const r = await fetch(`${SB}/rest/v1/app_secrets?name=eq.sweep&select=value`, { headers: svcHeaders() });
  const j = r.ok ? await r.json() : [];
  return !!(j[0] && j[0].value === k);
}

export async function GET(req) {
  if (!(await authorized(req).catch(() => false))) return json({ error: "izin yok" }, 401);
  // ?dry=1: kimseyi silmeden kimlerin silineceğini listeler (kural değişikliğinden önce kontrol için)
  const dry = new URL(req.url, "http://x").searchParams.get("dry") === "1";
  try {
    const R = await allowedRoles(), members = await guildMembers(R.gid);
    // Güvenlik: liste boş ya da şüpheli derecede kısaysa (Discord hatası) kimseyi silme
    if (members.size < 2) throw new Error("üye listesi boş geldi, silme yapılmadı");
    const ar = await fetch(`${SB}/rest/v1/profiles?is_admin=eq.true&select=id`, { headers: svcHeaders() });
    const admins = new Set((ar.ok ? await ar.json() : []).map(x => x.id));
    const users = await allUsers(), removed = [];
    for (const u of users) {
      if (admins.has(u.id)) continue;
      const did = discordIdOf(u);
      if (!did) continue;
      const m = members.get(did);
      if (m && (m.roles || []).some(id => R.ids.has(id))) continue;
      if (!dry) await deleteUser(u.id);
      removed.push({ discord_id: did, name: nameOf(u) || did, why: m ? `${R.min} rolü yok` : "sunucuda değil", source: "sweep" });
    }
    if (!dry) {
      await logRemovals(removed);
      await setStatus("sweep", { ok: true, members: members.size, users: users.length, removed: removed.length });
    }
    return json({ ok: true, dry, members: members.size, removed: removed.map(({ name, why }) => ({ name, why })) });
  } catch (e) {
    if (!dry) await setStatus("sweep", { ok: false, error: String(e.message || e) });
    return json({ ok: false, error: String(e.message || e) }, 500);
  }
}
