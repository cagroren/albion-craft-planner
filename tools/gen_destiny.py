"""data/destiny.json üretir: Destiny Board düğümleri, seviye tabloları ve bonuslar.

Kaynak: ao-data/ao-bin-dumps (achievements.xml, localization.xml, characters.xml, items.xml).
Oyun güncellenince tekrar çalıştır:  py -3 tools/gen_destiny.py
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "destiny.json")


def get(name):
    print("indiriliyor:", name, file=sys.stderr)
    return urllib.request.urlopen(BASE + name, timeout=120).read().decode("utf-8-sig")


def num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


ach = ET.fromstring(get("achievements.xml"))
loc_xml = get("localization.xml")
chars = get("characters.xml")

# Sadece ihtiyaç duyulan İngilizce metinler
need = set()
for el in ach.iter():
    for a in ("tag", "subcategorylocatag"):
        if el.get(a):
            need.add(el.get(a))
LOC = {}
for m in re.finditer(r'<tu tuid="([^"]+)"[^>]*>\s*<tuv xml:lang="EN-US">\s*<seg>([^<]*)</seg>', loc_xml):
    if m.group(1) in need:
        LOC[m.group(1)] = m.group(2)

templates = {}
for t in ach.findall("template"):
    base, elite = [], []
    bl = t.find("baselevels")
    if bl is not None and bl.text:
        for line in bl.text.strip().splitlines():
            p = line.strip().split(";")
            base.append([num(p[0]) or 0, num(p[1]) or 0])
    el = t.find("elitelevels")
    if el is not None and el.text:
        for line in el.text.strip().splitlines():
            p = line.strip().split(";")
            elite.append([num(p[0]) or 0, num(p[1]) or 0])
    templates[t.get("name")] = {"spec": t.get("learngroup") == "spec", "lv": base, "el": elite}


def bonuses(node):
    out = []
    if node is None:
        return out
    for b in node.findall("bonus"):
        d = b.find("description")
        out.append({k: v for k, v in {
            "type": b.get("type"), "attr": b.get("attribute"), "buff": b.get("bufftype"),
            "b": num(b.get("bonus")), "min": num(b.get("mintier")), "max": num(b.get("maxtier")),
            "d": LOC.get(d.get("tag")) if d is not None else None}.items() if v is not None})
    return out


nodes = {}
for a in ach.findall("templateachievement"):
    nid = a.get("id")
    title = a.find("title")
    parents = [p.get("id") for p in a.findall("parentachievements/achievement")]
    nodes[nid] = {k: v for k, v in {
        "t": LOC.get(title.get("tag")) if title is not None else nid,
        "tpl": a.get("usetemplate"),
        "fm": num(a.get("famemultiplier")) or 1,
        "lm": num(a.get("lpmultiplier")) or 1,
        "rm": num(a.get("respecmodifier")),  # off-hand'lerde 0.2: credit ile respec maliyetini düşürür
        "cat": a.get("category"),
        "ring": num(a.get("ring")),
        "icon": a.get("itemforsprite"),
        "sub": LOC.get(a.get("subcategorylocatag")),
        "rs": a.get("re-spectype"),
        "p": parents or None,
        "bon": bonuses(a.find("baserewards")) or None,
        "ebon": bonuses(a.find("eliterewards")) or None,
    }.items() if v is not None}

# Ana düğümler (Adventurer, Fighter, Crafter...): sadece başlık ve üst düğüm
for a in ach.findall("achievement"):
    nid = a.get("id")
    title = a.find("title")
    parents = [p.get("id") for p in a.findall("parentachievements/achievement")]
    nodes.setdefault(nid, {"t": LOC.get(title.get("tag")) if title is not None else nid, "cat": a.get("category"),
                           "ring": num(a.get("ring")), "main": True, **({"p": parents} if parents else {})})

# Craft düğümleri: düğümün eşyasının (itemforsprite) tarifindeki rafine malzeme adedi ve artifact fame çarpanı.
# Craft fame = adet × malzeme fame'i (tier'a göre) × 2^enchant × çarpan; sayfa bu iki sayıyla "kaç tane craftlarsam" hesabını yapar.
items = ET.fromstring(get("items.xml"))
ITEM = {el.get("uniquename"): el for el in items if el.get("uniquename")}
MAT = re.compile(r"^T\d_(PLANKS|METALBAR|CLOTH|LEATHER|STONEBLOCK)(_LEVEL\d)?$")
for nid, n in nodes.items():
    if n.get("cat") != "crafting" or not str(n.get("tpl", "")).startswith("CRAFT_") or not n.get("icon"):
        continue
    base = re.sub(r"^T\d_", "", n["icon"])
    got = {}
    for t in range(4, 9):
        el = ITEM.get(f"T{t}_{base}")
        cr = el.find("craftingrequirements") if el is not None else None
        if cr is None:
            continue
        got[t] = (sum(int(c.get("count") or 0) for c in cr if MAT.match(c.get("uniquename") or "")),
                  num(el.get("destinyandjournalcraftfamefactor")) or 1)
    vals = set(got.values())
    if len(vals) == 1 and list(vals)[0][0]:
        c, f = vals.pop()
        n["cr"] = {k: v for k, v in {"n": c, "f": f if f != 1 else None, "t0": min(got)}.items() if v is not None}
    else:
        print("craft tarifi yok/farklı:", nid, base, got, file=sys.stderr)

lp = {k: num(v) for k, v in re.findall(r'(learningpoint\w+)="([^"]+)"', chars)}

# Oyun düğümlere bu sırayla numara verir (0'dan başlayarak); DPS Meter toplayıcısı board'u bu numaralarla gönderir
order = [el.get("id") for el in ach if el.tag in ("achievement", "templateachievement")]

data = {"src": "ao-bin-dumps", "order": order, "templates": templates, "nodes": nodes,
        "lp": {"secPerPointPremium": lp.get("learningpointsecondsperpointpremium"), "fameFactor": lp.get("learningpointfamefactor")},
        "premium": num(re.search(r'premiumdestinyboardprogressionfactor="([^"]+)"', chars).group(1)),
        "study": num(re.search(r'<StudyFame factor="([^"]+)"', get("gamedata.xml")).group(1))}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
print(f"{len(nodes)} düğüm, {len(templates)} şablon -> {os.path.relpath(OUT)} ({os.path.getsize(OUT)//1024} KB)", file=sys.stderr)
