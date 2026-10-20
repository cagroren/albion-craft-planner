"""data/destiny.json üretir: Destiny Board düğümleri, seviye tabloları ve bonuslar.

Kaynak: ao-data/ao-bin-dumps (achievements.xml, localization.xml, characters.xml).
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

lp = {k: num(v) for k, v in re.findall(r'(learningpoint\w+)="([^"]+)"', chars)}

# Oyun düğümlere bu sırayla numara verir (0'dan başlayarak); DPS Meter toplayıcısı board'u bu numaralarla gönderir
order = [el.get("id") for el in ach if el.tag in ("achievement", "templateachievement")]

data = {"src": "ao-bin-dumps", "order": order, "templates": templates, "nodes": nodes,
        "lp": {"secPerPointPremium": lp.get("learningpointsecondsperpointpremium"), "fameFactor": lp.get("learningpointfamefactor")}}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
print(f"{len(nodes)} düğüm, {len(templates)} şablon -> {os.path.relpath(OUT)} ({os.path.getsize(OUT)//1024} KB)", file=sys.stderr)
