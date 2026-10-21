// /b/<id> ve /g/<id> paylaşım linkleri için ortak yardımcılar (Discord önizlemesi).
// Varsa servis anahtarı kullanılır (build okuma sadece guild üyelerine açık), yoksa publishable key.
export const SB = "https://aulscfeqndppxbtypezs.supabase.co";
const KEY = "sb_publishable_v-eTBIU2R9vng0qCfOOpjA_lQm2m95W";
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function rest(path) {
  // Build'ler sadece guild üyelerine açık (RLS); önizleme sunucuda servis anahtarıyla okur
  const sk = (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();
  const headers = sk ? { apikey: sk, ...(sk.startsWith("eyJ") ? { Authorization: `Bearer ${sk}` } : {}) } : { apikey: KEY };
  const r = await fetch(`${SB}/rest/v1/${path}`, { headers });
  if (!r.ok) return null;
  return r.json();
}

// Oyun verisi (eşya adları, tier'lar) sitenin kendi data/builds.json dosyasından gelir
let gameData = null;
export async function game(origin) {
  if (!gameData) {
    const r = await fetch(`${origin}/data/builds.json`);
    gameData = r.ok ? await r.json() : { items: {}, mounts: [], cons: [] };
  }
  return gameData;
}

export async function getBuild(id) {
  if (!UUID.test(id || "")) return null;
  const d = await rest(`builds?id=eq.${id}&select=id,title,content,role,descr,owner_name,gear`);
  return d && d[0] || null;
}

// Grup: kayıtlı build'e bağlı slotların ekipmanı da çekilir
export async function getGroup(id) {
  if (!UUID.test(id || "")) return null;
  const d = await rest(`group_builds?id=eq.${id}&select=id,title,content,descr,owner_name,slots`);
  const g = d && d[0];
  if (!g) return null;
  const ids = [...new Set((g.slots || []).map(s => s.b).filter(b => UUID.test(b || "")))];
  const refs = ids.length ? await rest(`builds?id=in.(${ids.join(",")})&select=id,title,role,gear`) || [] : [];
  g.slots = (g.slots || []).map(s => {
    const x = s.b ? refs.find(r => r.id === s.b) : s.g ? { title: s.t || "Set", role: s.ro || "", gear: s.g } : null;
    return x ? { n: +s.n || 1, r: s.r || "", title: x.title, role: x.role || "", gear: x.gear || {} } : null;
  }).filter(Boolean);
  return g;
}

// builds.html'deki iconId ile aynı: binek/yemek/iksir ID'si doğrudan, diğerleri en yüksek tier
export function iconId(G, sl, v) {
  if (!v || !v.i) return "";
  if (sl === "m" || sl === "f" || sl === "p") return v.i;
  const it = G.items[v.i];
  if (!it) return "";
  const t = it.t.includes(8) ? 8 : Math.max(...it.t);
  return `T${t}_${v.i}`;
}

export function itemName(G, sl, v) {
  if (!v || !v.i) return "";
  if (sl === "m") return ((G.mounts || []).find(x => x[0] === v.i) || [, v.i])[1];
  if (sl === "f" || sl === "p") return ((G.cons || []).find(x => x[0] === v.i) || [, v.i])[1];
  return (G.items[v.i] || {}).n || v.i;
}

export const iconUrl = (id, size) => `https://render.albiononline.com/v1/item/${encodeURIComponent(id)}.png?size=${size || 128}`;
