// /api/og?b=<id> ya da ?g=<id>: Discord önizlemesi için 1200x630 build görseli
import { ImageResponse } from "@vercel/og";
import { getBuild, getGroup, game, iconId, itemName, iconUrl } from "./_build.js";

// Node ortamında çalışır: edge'de @vercel/og yazı tipini yükleyemeyip boş görsel döndürüyordu

const C = { bg: "#0b0f14", card: "#11161d", card2: "#151b23", line: "#323c49", ink: "#e6e9ee", mut: "#8b95a3", acc: "#f0883e", accT: "#ffd6b3", acc2: "#7a3e16" };
// Satori JSX yerine düz nesne kabul eder
const h = (type, style, children, extra) => ({ type, props: { style: { display: "flex", ...style }, ...extra, children } });
const img = (src, size) => ({ type: "img", props: { src, width: size, height: size, style: { width: size, height: size } } });

function slotBox(G, gear, sl, size, label) {
  const v = gear[sl], id = iconId(G, sl, v);
  const sw = sl === "w" && gear.x ? iconId(G, "x", gear.x) : "";
  return h("div", { flexDirection: "column", alignItems: "center", gap: 6 }, [
    h("div", { position: "relative", width: size, height: size, borderRadius: 16, background: C.card2, border: `2px solid ${id ? C.line : C.card2}`, alignItems: "center", justifyContent: "center" }, [
      id ? img(iconUrl(id, 128), size - 8) : h("div", {}, ""),
      sw ? h("div", { position: "absolute", right: -10, bottom: -10, width: 54, height: 54, borderRadius: 12, background: C.card, border: `2px solid ${C.acc}`, alignItems: "center", justifyContent: "center" }, [img(iconUrl(sw, 64), 48)]) : h("div", {}, ""),
    ]),
    h("div", { fontSize: 18, color: C.mut, maxWidth: size + 20, justifyContent: "center", textAlign: "center" }, label),
  ]);
}

function header(title, chips, author) {
  return h("div", { flexDirection: "column", gap: 14 }, [
    h("div", { fontSize: 54, fontWeight: 800, color: C.ink, lineHeight: 1.1, maxWidth: 1100 }, title.length > 48 ? title.slice(0, 46) + "…" : title),
    h("div", { gap: 10, alignItems: "center" }, [
      ...chips.filter(Boolean).map(c => h("div", { fontSize: 22, color: C.accT, background: "rgba(240,136,62,.14)", border: `2px solid ${C.acc2}`, borderRadius: 30, padding: "4px 16px" }, c)),
      author ? h("div", { fontSize: 22, color: C.mut, marginLeft: 6 }, author) : h("div", {}, ""),
    ]),
  ]);
}

const frame = children => h("div", { width: 1200, height: 630, background: C.bg, flexDirection: "column", padding: "48px 56px", justifyContent: "space-between", fontFamily: "sans-serif" }, [
  ...children,
  h("div", { justifyContent: "space-between", alignItems: "center", fontSize: 20, color: C.mut }, [h("div", {}, "KVF Albion · Builds"), h("div", { color: C.acc }, "albion-craft-planner")]),
]);

function buildImage(G, x) {
  const g = x.gear || {};
  const main = ["w", "o", "h", "a", "s", "c"].filter(k => g[k]);
  const extra = ["b", "m", "f", "p"].filter(k => g[k]);
  const names = { w: "Silah", o: "Yan el", h: "Kafa", a: "Zırh", s: "Ayakkabı", c: "Pelerin", b: "Çanta", m: "Binek", f: "Yemek", p: "İksir" };
  const label = k => { const n = itemName(G, k, g[k]); return n.length > 18 ? n.slice(0, 17) + "…" : n || names[k]; };
  return frame([
    header(x.title, [x.content, x.role], x.owner_name ? "· " + x.owner_name : ""),
    // 6 ana parça (130px) + sağda çanta/binek/yemek/iksir için 2x2 küçük ızgara: 1200px'e sığar
    h("div", { gap: 18, alignItems: "center" }, [
      ...main.map(k => slotBox(G, g, k, 130, label(k))),
      extra.length ? h("div", { flexWrap: "wrap", width: 180, gap: 10, marginLeft: 12, paddingLeft: 20, borderLeft: `2px solid ${C.line}` }, extra.map(k => h("div", { width: 68, height: 68, borderRadius: 12, background: C.card2, border: `2px solid ${C.line}`, alignItems: "center", justifyContent: "center" }, [img(iconUrl(iconId(G, k, g[k]), 64), 60)]))) : h("div", {}, ""),
    ]),
  ]);
}

function groupImage(G, x) {
  const n = x.slots.reduce((a, s) => a + s.n, 0);
  const list = x.slots.slice(0, 12);
  return frame([
    header(x.title, [x.content, `${n} kişi`], x.owner_name ? "· " + x.owner_name : ""),
    h("div", { flexWrap: "wrap", gap: 16, maxWidth: 1090 }, list.map(s => {
      const w = iconId(G, "w", s.gear.w);
      const t = s.r || s.title;
      return h("div", { alignItems: "center", gap: 10, width: 252, background: C.card2, border: `2px solid ${C.line}`, borderRadius: 14, padding: "8px 12px" }, [
        w ? img(iconUrl(w, 64), 60) : h("div", { width: 60, height: 60 }, ""),
        h("div", { flexDirection: "column", flex: 1 }, [
          h("div", { fontSize: 20, color: C.ink, fontWeight: 700 }, t.length > 14 ? t.slice(0, 13) + "…" : t),
          h("div", { fontSize: 16, color: C.mut }, s.role || " "),
        ]),
        h("div", { fontSize: 26, fontWeight: 800, color: C.accT }, "×" + s.n),
      ]);
    }).concat(x.slots.length > 12 ? [h("div", { fontSize: 22, color: C.mut, alignItems: "center" }, `+${x.slots.length - 12} set daha`)] : [])),
  ]);
}

export async function GET(req) {
  const u = new URL(req.url);
  const b = u.searchParams.get("b"), g = u.searchParams.get("g");
  const G = await game(u.origin);
  let el = null;
  if (b) { const x = await getBuild(b); if (x) el = buildImage(G, x); }
  else if (g) { const x = await getGroup(g); if (x) el = groupImage(G, x); }
  if (!el) el = frame([header("Albion Builds", ["Build bulunamadı"], ""), h("div", {}, "")]);
  return new ImageResponse(el, { width: 1200, height: 630, headers: { "cache-control": "public, max-age=300, s-maxage=600" } });
}
