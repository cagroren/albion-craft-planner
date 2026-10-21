// /api/admin: yönetim paneli için Discord bilgisi ve elle hesap silme. Sadece adminler çağırabilir.
//   GET  ?op=discord          site kullanıcılarının Discord adı ve rolleri (discord id -> bilgi)
//   POST ?op=delete {uid}      hesabı ve bütün verisini siler, silinenler geçmişine yazar
import { SB, ANON, svcHeaders, profileOf, guildMembers, guildRoles, deleteUser, logRemovals, discordIdOf, nameOf, json } from "./_guild.js";

async function admin(req) {
  const tok = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!tok) return null;
  const r = await fetch(`${SB}/auth/v1/user`, { headers: { apikey: ANON, Authorization: `Bearer ${tok}` } });
  if (!r.ok) return null;
  const u = await r.json();
  return (await profileOf(u.id)).is_admin ? u : null;
}

export async function GET(req) {
  try {
    if (!(await admin(req))) return json({ error: "yetki yok" }, 403);
    const gid = (process.env.DISCORD_GUILD_ID || "").trim();
    const [roles, members, pr] = await Promise.all([guildRoles(gid), guildMembers(gid),
      fetch(`${SB}/rest/v1/profiles?select=discord_id&discord_id=not.is.null`, { headers: svcHeaders() })]);
    const ids = new Set((pr.ok ? await pr.json() : []).map(p => p.discord_id));
    // Rolleri Discord'daki sırasıyla (üstteki önce) ve renkleriyle verir
    const R = new Map(roles.filter(x => x.id !== gid).map(x => [x.id, x]));
    const out = {};
    for (const id of ids) {
      const m = members.get(id);
      out[id] = m ? {
        name: m.nick || m.user.global_name || m.user.username, user: m.user.username,
        roles: (m.roles || []).map(r => R.get(r)).filter(Boolean).sort((a, b) => b.position - a.position)
          .map(r => ({ name: r.name, color: r.color ? "#" + r.color.toString(16).padStart(6, "0") : null }))
      } : { gone: true };
    }
    return json({ members: out, total: members.size });
  } catch (e) {
    return json({ error: String(e.message || e) }, 502);
  }
}

export async function POST(req) {
  try {
    const me = await admin(req);
    if (!me) return json({ error: "yetki yok" }, 403);
    const op = new URL(req.url, "http://x").searchParams.get("op");
    if (op !== "delete") return json({ error: "bilinmeyen işlem" }, 400);
    const { uid } = await req.json().catch(() => ({}));
    if (!/^[0-9a-f-]{36}$/i.test(uid || "")) return json({ error: "geçersiz kullanıcı" }, 400);
    if (uid === me.id) return json({ error: "kendi hesabını panelden silemezsin" }, 400);
    const ur = await fetch(`${SB}/auth/v1/admin/users/${uid}`, { headers: svcHeaders() });
    const u = ur.ok ? await ur.json() : {};
    await deleteUser(uid);
    await logRemovals([{ discord_id: discordIdOf(u), name: nameOf(u) || uid, why: "panelden silindi", source: "manual", by_admin: me.id }]);
    return json({ ok: true });
  } catch (e) {
    return json({ error: String(e.message || e) }, 502);
  }
}
