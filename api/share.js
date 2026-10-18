// /b/<id> ve /g/<id>: Discord/sosyal medya botlarına başlık, açıklama ve görsel verir,
// insanları build sayfasına yönlendirir (botlar JavaScript çalıştırmaz, #... kısmını da görmez).
import { getBuild, getGroup, game, itemName } from "./_build.js";

export const config = { runtime: "edge" };

const esc = t => String(t == null ? "" : t).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export default async function handler(req) {
  const u = new URL(req.url), origin = u.origin;
  const b = u.searchParams.get("b"), g = u.searchParams.get("g");
  const kind = b ? "b" : "g", id = b || g || "";
  const target = `${origin}/builds#${kind}=${encodeURIComponent(id)}`;
  let title = "Albion Builds", desc = "KVF build paylaşımı", img = "";
  try {
    const G = await game(origin);
    if (b) {
      const x = await getBuild(b);
      if (x) {
        title = x.title;
        const items = ["w", "o", "h", "a", "s", "c"].map(k => itemName(G, k, (x.gear || {})[k])).filter(Boolean);
        const sw = (x.gear || {}).x && itemName(G, "x", x.gear.x);
        desc = [[x.content, x.role, x.owner_name].filter(Boolean).join(" · "), items.join(", ") + (sw ? ` · Swap: ${sw}` : "")].filter(Boolean).join("\n");
        img = `${origin}/api/og?b=${x.id}`;
      }
    } else if (g) {
      const x = await getGroup(g);
      if (x) {
        title = x.title;
        const n = x.slots.reduce((a, s) => a + s.n, 0);
        desc = [[x.content, `${n} kişi`, x.owner_name].filter(Boolean).join(" · "), x.slots.map(s => `${s.n}× ${s.r || s.title}`).join(", ")].join("\n");
        img = `${origin}/api/og?g=${x.id}`;
      }
    }
  } catch (e) { /* veri gelmezse yine de yönlendir */ }
  const html = `<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>${esc(title)} · Albion Builds</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="KVF Albion">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${esc(`${origin}/${kind}/${id}`)}">
${img ? `<meta property="og:image" content="${esc(img)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="${esc(img)}">` : ""}
<meta name="theme-color" content="#f0883e">
<meta http-equiv="refresh" content="0;url=${esc(target)}">
</head><body style="background:#0b0f14;color:#e6e9ee;font-family:sans-serif">
<script>location.replace(${JSON.stringify(target)})</script>
<a href="${esc(target)}" style="color:#f0883e">${esc(title)}</a>
</body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=60, s-maxage=300" } });
}
