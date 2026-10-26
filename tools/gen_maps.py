"""data/maps.json üretir: Avalon Roads haritalarının içeriği (Maps sekmesi).

Kaynak: ao-data/ao-bin-dumps
  cluster/world.xml (West), world_europe.xml (Europe), world_asia.xml (East) + *_patch.xml:
    harita adı, tipi, hangi cluster dosyasını kullandığı, portallar (tunnelexit)
  cluster/TNL-*.cluster.xml: haritayı oluşturan şablonlar ve aktif katmanlar
  templates/*/*.template.xml: katmanlardaki kaynak düğümleri, sandıklar, boss'lar, dungeon girişleri
Sunucular farklı cluster dosyası (farklı tier/içerik) kullanabildiği için her sunucu ayrı listelenir.

Oyun güncellenince tekrar çalıştır:  py -3 tools/gen_maps.py
İndirilenler önbelleğe alınır (varsayılan: %TEMP%/ao-bin-cache); --fresh ile yeniden indirir.
"""
import json
import math
import os
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

BASE = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/"
TREE = "https://api.github.com/repos/ao-data/ao-bin-dumps/git/trees/master?recursive=1"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "maps.json")
TERDIR = os.path.join(os.path.dirname(OUT), "maps")  # harita başına zemin ızgarası (sayfa seçilen haritanınkini yükler)
CELL = 5  # ızgara hücresi (oyun birimi)
CACHE = os.path.join(tempfile.gettempdir(), "ao-bin-cache")
FRESH = "--fresh" in sys.argv
SERVERS = {"west": "world", "europe": "world_europe", "east": "world_asia"}

os.makedirs(CACHE, exist_ok=True)


def get(path, fresh=False):
    f = os.path.join(CACHE, path.replace("/", "__"))
    if fresh or FRESH or not os.path.exists(f):
        print("indiriliyor:", path, file=sys.stderr)
        url = path if path.startswith("http") else BASE + path
        data = urllib.request.urlopen(url, timeout=180).read()
        with open(f, "wb") as fh:
            fh.write(data)
    return f


def xml(path, fresh=False):
    return ET.parse(get(path, fresh)).getroot()


# Şablon adı -> dosya yolu (NONE klasörü öncelikli)
TPL = {}
for x in json.load(open(get(TREE, True), encoding="utf-8"))["tree"]:
    p = x["path"]
    if p.startswith("templates/") and p.endswith(".template.xml"):
        n = p.rsplit("/", 1)[1][: -len(".template.xml")]
        if n not in TPL or "/NONE/" in p:
            TPL[n] = p


def world(name):
    """Sunucunun TNL haritaları: id -> {n, f, ty, on, exits}"""
    root = xml("cluster/" + name + ".xml", True)
    maps, exits = {}, {}
    for c in root.iter("cluster"):
        cid = c.get("id") or ""
        if not cid.startswith("TNL-"):
            continue
        if c.get("file"):
            # distribution: oyunun kendi kaynak sayımı (düğüm + kaynak yaratıkları); T1-T3 kayıtları editör artığı
            dist = {}
            for r in c.iter("resource"):
                if int(r.get("tier")) >= 4:
                    dist.setdefault(r.get("name"), {})[int(r.get("tier"))] = int(r.get("count"))
            maps[cid] = {"n": c.get("displayname"), "f": c.get("file"), "ty": c.get("type"), "on": c.get("enabled") == "true", "dist": dist}
        else:
            exits[cid] = [t.get("path").split("/")[0] for t in c.findall("tunnelexit")]
    try:
        patch = open(get("cluster/" + name + "_patch.xml", True), encoding="utf-8-sig").read()
        for m in re.finditer(r"cluster\[@id='(TNL-\d+)'\]\">\s*<attribute name=\"enabled\" newvalue=\"(\w+)\"", patch):
            if m.group(1) in maps:
                maps[m.group(1)]["on"] = m.group(2) == "true"
    except Exception as e:  # yama dosyası olmayabilir
        print("yama yok:", name, e, file=sys.stderr)
    for cid, m in maps.items():
        # TNL-3xx gibi kopyalar başka haritanın dosyasını kullanır; çıkışları o haritanın kaydında
        m["exits"] = exits.get(cid) or exits.get(m["f"].split("_", 1)[0], [])
    return maps


def tier(s):
    m = re.search(r"T(\d)", s)
    return int(m.group(1)) if m else 0


FACTION = {"KPR": "KPR", "HER": "HER", "MOR": "MOR", "UND": "UND", "AVA": "AVA"}


def classify(name):
    """Şablondaki tile adını [tür, alt tür, tier] olarak sınıflandırır; ilgisizse None."""
    m = re.match(r"ROADS_T(\d)_(TREE|ROCK|ORE|FIBER)", name)
    if m:
        return ["r", {"TREE": "WOOD", "ROCK": "ROCK", "ORE": "ORE", "FIBER": "FIBER"}[m.group(2)], int(m.group(1))]
    if re.match(r"SpawnPoint_T\d_MOB_(CRITTER_FOREST_MISTCOUGAR|HIDE_)", name):
        return ["r", "HIDE", tier(name)]
    if "LOOTCHEST" in name:
        lv = "raid" if "ELITE" in name else "group" if "VETERAN" in name else "solo"
        return ["c", lv, tier(name)]
    if "BOSS_ANY" in name:
        lv = "raid" if "ELITE" in name else "group" if "VETERAN" in name else "solo"
        return ["b", lv, tier(name)]
    m = re.match(r"ROADS_FIXED_EXIT_\d+x\d+_([A-Z]+)_T(\d)_ROAD_(SOLO|VETERAN|ELITE)", name)
    if m:
        lv = {"SOLO": "solo", "VETERAN": "group", "ELITE": "raid"}[m.group(3)]
        return ["d", lv + ":" + FACTION.get(m.group(1), m.group(1)), int(m.group(2))]
    return None


def tcat(name):
    """Zemin sınıfı: v boşluk (tıklanamayan dolgu), a Avalon taş zemini, w su, r ana yol; diğerleri çizilmez."""
    u = name.upper()
    if u.startswith("_ROADS_MIST_ROAD_"):
        return "r"
    if "NOCLICK" in u:
        return "v"
    if re.search(r"AVA_GROUND_(A_BRIGHT|STONES|INNERCORNER|STONEPATH)", u):
        return "a"
    if "WATER" in u or "RIVER" in u:
        return "w"
    return None


# tiles.xml: parçaların taban ölçüsü (genişlik, yükseklik, ofset)
DIM = {}
for _, e in ET.iterparse(get("cluster/tiles.xml")):
    if e.tag == "tile":
        n = e.get("name") or ""
        if e.get("width") and tcat(n):
            o = [float(v) for v in (e.get("offset") or "0 0").split()]
            DIM[n] = (float(e.get("width")), float(e.get("height")), o[0], o[1])
    e.clear()


def dim(name):
    if name in DIM:
        return DIM[name]
    m = re.search(r"(\d+)x(\d+)", name)
    w, h = (float(m.group(1)), float(m.group(2))) if m else (10.0, 10.0)
    return (w, h, -w / 2, -h / 2)


_tpl = {}


def template(ref):
    """Şablonun katmanları: layer id -> (noktalar [(sınıf, x, z)], zemin [(tür, x, z, roty, ölçü)]).
    Katmansız parçalar None anahtarında, her zaman açık."""
    if ref not in _tpl:
        layers = {}

        def walk(el, lid):
            for c in el:
                if c.tag == "layer":
                    walk(c, c.get("id"))
                elif c.tag in ("tile", "compoundtile"):  # ana yollar compoundtile
                    n = c.get("name") or ""
                    pts, ter = layers.setdefault(lid, ([], []))
                    p = [float(v) for v in c.get("pos", "0 0 0").split()]
                    k = classify(n)
                    if k and lid is not None:
                        pts.append((k, p[0], p[2]))
                    tc = tcat(n)
                    if tc:
                        ter.append((tc, p[0], p[2], float(c.get("roty", 0)), dim(n)))
                else:
                    walk(c, lid)

        if ref in TPL:
            walk(xml(TPL[ref]), None)
        else:
            print("şablon yok:", ref, file=sys.stderr)
        _tpl[ref] = layers
    return _tpl[ref]


def rotate(x, z, deg):
    # Unity: y ekseni etrafında saat yönünde dönüş (x,z düzleminde)
    a = math.radians(deg)
    return x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)


def layout(file):
    root = xml("cluster/" + file)
    slots, pts, ter, homes = {}, [], [], []
    for ti in root.iter("templateinstance"):
        ref = ti.get("ref")
        px, _, pz = [float(v) for v in ti.get("pos", "0 0 0").split()]
        rot = float(ti.get("rot", 0))
        slots[ti.get("id")] = (round(px), round(pz))
        if re.match(r"S_[A-Z_]*ROADS?_Hideout_\d", ref):
            homes.append([round(px), round(pz)])
        layers = template(ref)
        for lid in [None] + [la.get("id") for la in ti.findall("activelayer")]:
            lp, lt = layers.get(lid, ([], []))
            for k, x, z in lp:
                rx, rz = rotate(x, z, rot)
                pts.append(k + [round(px + rx), round(pz + rz)])
            for tc, x, z, ry, d in lt:
                rx, rz = rotate(x, z, rot)
                ter.append((tc, px + rx, pz + rz, rot + ry, d))
    return slots, pts, homes, ter


def roads(ter):
    """Ana yol: parçalar seyrek dizili; aynı hizadaki (doğu-batı / kuzey-güney) en yakın komşular çizgiyle bağlanır."""
    ns = []
    for tc, x, z, *_ in ter:
        if tc == "r" and all(abs(x - a) > 2 or abs(z - b) > 2 for a, b in ns):
            ns.append((x, z))
    seg = set()
    for i, (x, z) in enumerate(ns):
        for axis in (0, 1):
            best = None
            for j, (a, b) in enumerate(ns):
                d, off = (a - x, b - z) if axis == 0 else (b - z, a - x)
                if 0 < d <= 90 and abs(off) <= 6 and (best is None or d < best[0]):
                    best = (d, j)
            if best:
                seg.add(tuple(sorted((i, best[1]))))
    return [[round(ns[a][0]), round(ns[a][1]), round(ns[b][0]), round(ns[b][1])] for a, b in sorted(seg)]


def raster(ter, bb):
    ter_all = ter
    """Zemini CELL'lik ızgaraya döker: '.' boşluk, 'g' yürünebilir, 'a' Avalon zemini, 'w' su.
    Satırlar kuzeyden (büyük z) başlar; her satır 'harf+sayı' koşularıdır (ör. .12g30a4)."""
    x0, z0, x1, z1 = bb
    W, H = math.ceil((x1 - x0) / CELL), math.ceil((z1 - z0) / CELL)
    g = bytearray(b"g" * (W * H))
    ter = [t for t in ter if t[0] != "r"]
    order = {"v": 0, "a": 1, "w": 2}
    for tc, x, z, ang, (w, h, ox, oy) in sorted(ter, key=lambda t: order[t[0]]):
        ch = {"v": b".", "a": b"a", "w": b"w"}[tc]
        cs = [rotate(cx, cz, ang) for cx, cz in ((ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h))]
        xs, zs = [x + c[0] for c in cs], [z + c[1] for c in cs]
        c0, c1 = max(0, int((min(xs) - x0) / CELL + .5)), min(W, int((max(xs) - x0) / CELL + .5))
        r0, r1 = max(0, int((min(zs) - z0) / CELL + .5)), min(H, int((max(zs) - z0) / CELL + .5))
        if c0 >= c1 or r0 >= r1:
            continue
        straight = abs(ang / 90 - round(ang / 90)) < 1e-3
        for r in range(r0, r1):
            if straight:
                if tc == "w":  # su sadece yürünebilir alanın üstüne
                    for i in range(r * W + c0, r * W + c1):
                        if g[i] != 46:
                            g[i] = 119
                else:
                    g[r * W + c0:r * W + c1] = ch * (c1 - c0)
                continue
            for c in range(c0, c1):  # döndürülmüş parça: hücre merkezi parçanın içinde mi
                lx, lz = rotate(x0 + (c + .5) * CELL - x, z0 + (r + .5) * CELL - z, -ang)
                if ox <= lx <= ox + w and oy <= lz <= oy + h and not (tc == "w" and g[r * W + c] == 46):
                    g[r * W + c] = ch[0]
    rows = []
    for r in range(H - 1, -1, -1):
        row, out, i = g[r * W:(r + 1) * W], [], 0
        while i < W:
            j = i
            while j < W and row[j] == row[i]:
                j += 1
            out.append(chr(row[i]) + str(j - i))
            i = j
        rows.append("".join(out))
    return {"c": CELL, "w": W, "h": H, "r": rows, "rd": roads(ter_all)}


def summary(pts):
    s = {"r": {}, "c": {}, "b": {}, "d": {}}
    for k, sub, t, *_ in pts:
        s[k].setdefault(sub, {})
        s[k][sub][t] = s[k][sub].get(t, 0) + 1
    return {k: v for k, v in s.items() if v}


servers = {s: world(n) for s, n in SERVERS.items()}
files = sorted({m["f"] for w in servers.values() for m in w.values()})
with ThreadPoolExecutor(16) as ex:
    list(ex.map(lambda f: get("cluster/" + f), files))
    refs = {ti.get("ref") for f in files for ti in xml("cluster/" + f).iter("templateinstance")}
    list(ex.map(lambda r: get(TPL[r]) if r in TPL else None, refs))

dists = {}
for w in servers.values():
    for m in w.values():
        dists.setdefault(m["f"], m["dist"])

os.makedirs(TERDIR, exist_ok=True)
L, slotmap = {}, {}
for f in files:
    slots, pts, homes, ter = layout(f)
    root = xml("cluster/" + f)
    mn = [float(v) for v in root.get("minimapBoundsMin", root.get("origin", "0 0")).split()]
    mx = [float(v) for v in root.get("minimapBoundsMax", "0 0").split()]
    if mx == [0.0, 0.0]:
        sz = [float(v) for v in root.get("size").split()]
        mx = [mn[0] + sz[0], mn[1] + sz[1]]
    key = f.replace(".cluster.xml", "")
    sm = summary(pts)
    sm["r"] = dists[f]
    if not sm["r"]:
        del sm["r"]
    bb = [round(v) for v in mn + mx]
    L[key] = {"t": tier(key.split("_", 1)[1]), "bb": bb, "h": len(homes), "s": sm, "p": pts + [["h", "", 0] + h for h in homes]}
    slotmap[key] = slots
    with open(os.path.join(TERDIR, key + ".json"), "w", encoding="utf-8") as fh:
        json.dump(raster(ter, bb), fh, separators=(",", ":"))

out = {"src": "ao-data/ao-bin-dumps (cluster/world*.xml, cluster/TNL-*.cluster.xml, templates)", "L": L, "S": {}}
for s, w in servers.items():
    rows = []
    for cid in sorted(w):
        m = w[cid]
        key = m["f"].replace(".cluster.xml", "")
        portals = [slotmap[key][e] for e in m["exits"] if e in slotmap[key]]
        # son alan: sunucuda kapalıysa 0 (nüfusa göre yolların bir kısmı kapatılıyor)
        rows.append([cid, m["n"], key, m["ty"], portals, 1 if m["on"] else 0])
    out["S"][s] = rows
    print(s, len(rows), "harita,", sum(r[5] for r in rows), "açık", file=sys.stderr)

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
print("yazıldı:", OUT, os.path.getsize(OUT) // 1024, "KB", file=sys.stderr)
