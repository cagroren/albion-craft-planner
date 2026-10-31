// /api/kills: DPS Meter savaş raporu için resmî Albion API'sinden (gameinfo) partinin kill/death olayları.
// Toplayıcı ölümü göremediyse (uzakta, sahne dışı) sayfa eksikleri buradan tamamlar. Oyunun API'si tarayıcıya
// CORS izni vermediği için istek buradan geçer. Olaylar oyunda birkaç dakika gecikmeyle görünür.
// ?srv=europe|west|east&since=<ms>&until=<ms>&n=Ad ya da n=Ad|OyuncuId (en çok 20 oyuncu)
const HOST = { europe: "gameinfo-ams.albiononline.com", west: "gameinfo.albiononline.com", east: "gameinfo-sgp.albiononline.com" };
const SLOT = { MainHand: "w", OffHand: "o", Head: "h", Armor: "a", Shoes: "s", Bag: "b", Cape: "c", Mount: "m", Potion: "p", Food: "f" };

const json = (o, status = 200) => new Response(JSON.stringify(o), {
  status, headers: { "content-type": "application/json", "cache-control": "public, max-age=0, s-maxage=60" },
});

async function get(url) {
  for (let i = 0; i < 2; i++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(8000), headers: { accept: "application/json" } });
      if (r.ok) return await r.json();
    } catch (e) { /* oyunun API'si sık sık 504 verir; bir kez daha denenir */ }
  }
  return null;
}

const side = x => {
  const eq = {};
  for (const [k, v] of Object.entries(x.Equipment || {})) if (SLOT[k] && v && v.Type) eq[SLOT[k]] = v.Type;
  return { name: x.Name || "", guild: x.GuildName || "", ip: x.AverageItemPower ? Math.round(x.AverageItemPower * 10) / 10 : null, eq };
};

export async function GET(req) {
  const u = new URL(req.url), base = "https://" + (HOST[u.searchParams.get("srv")] || HOST.europe) + "/api/gameinfo";
  const since = +u.searchParams.get("since") || 0, until = +u.searchParams.get("until") || Infinity;
  const ns = u.searchParams.getAll("n").slice(0, 20).map(s => s.split("|")).filter(([n]) => n);
  if (!ns.length) return json({ error: "oyuncu adı yok" }, 400);
  const ids = {}, ev = new Map();
  await Promise.all(ns.map(async ([name, id]) => {
    if (!id) {
      const s = await get(`${base}/search?q=${encodeURIComponent(name)}`);
      const p = s && (s.players || []).find(p => p.Name.toLowerCase() === name.toLowerCase());
      if (!p) return;
      id = p.Id;
    }
    ids[name] = id;
    const [k, d] = await Promise.all([get(`${base}/players/${id}/kills`), get(`${base}/players/${id}/deaths`)]);
    for (const e of [...(k || []), ...(d || [])]) {
      const t = Date.parse(e.TimeStamp);
      if (!(t >= since && t <= until) || ev.has(e.EventId)) continue;
      // g: öldürenin grubundakiler ve katkı verenler; sayfa senin o anda partide olup olmadığını buradan anlar
      const g = [...new Set([...(e.GroupMembers || []), ...(e.Participants || [])].map(x => x.Name).filter(Boolean))];
      ev.set(e.EventId, { id: e.EventId, t, k: side(e.Killer || {}), v: side(e.Victim || {}), g });
    }
  }));
  return json({ ids, kills: [...ev.values()].sort((a, b) => a.t - b.t) });
}
