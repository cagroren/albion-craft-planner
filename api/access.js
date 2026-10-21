// /api/access: giriş yapan kişi Kal Vas Flam Discord'unda izinli bir role sahip mi?
// Sayfa her açılışta Supabase oturum token'ıyla çağırır. Kesin "hayır" ise hesap ve bütün verisi silinir.
import { SB, ANON, allowedRoles, memberAllowed, discordIdOf, profileOf, setMember, deleteUser, logRemovals, nameOf, json } from "./_guild.js";

export async function GET(req) {
  const tok = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!tok) return json({ allowed: false, why: "giriş yapılmadı" }, 401);
  const ur = await fetch(`${SB}/auth/v1/user`, { headers: { apikey: ANON, Authorization: `Bearer ${tok}` } });
  if (!ur.ok) {
    // Temizlik hesabı sildiyse token hâlâ geçerli görünür ama kullanıcı yoktur
    if (/does not exist|user_not_found/i.test(await ur.text())) return json({ allowed: false, why: "Discord'da gerekli rolün kalmadığı için hesabın silindi", deleted: true });
    return json({ allowed: false, why: "oturum geçersiz", session: true }, 401);
  }
  const u = await ur.json(), did = discordIdOf(u);
  try {
    // first: üyelik yeni açıldı; sayfa verileri yeni izinle bir kere yeniden yükler
    const p = await profileOf(u.id), first = !p.member;
    if (p.is_admin) { if (first) await setMember(u.id, did, true); return json({ allowed: true, admin: true, first }); }
    if (!did) return json({ allowed: null, error: "Discord hesabı bulunamadı" }, 502);
    const R = await allowedRoles(), m = await memberAllowed(did, R);
    if (m.ok) { await setMember(u.id, did, true); return json({ allowed: true, first }); }
    await deleteUser(u.id);
    await logRemovals([{ discord_id: did, name: nameOf(u) || did, why: m.why, source: "access" }]);
    return json({ allowed: false, why: m.why, deleted: true });
  } catch (e) {
    // Discord ya da ayar hatası: kimse silinmez, sayfa son bilinen duruma göre karar verir
    return json({ allowed: null, error: String(e.message || e) }, 502);
  }
}
