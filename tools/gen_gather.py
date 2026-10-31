"""data/gather.json üretir: Toplama sekmesinin oyun verisi.

Kaynak: ao-data/ao-bin-dumps (harvestables.xml, items.xml, spells.xml, rareresourcedistribution.xml).
Oyun güncellenince tekrar çalıştır:  py -3 tools/gen_gather.py
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "gather.json")
RES = ["ORE", "WOOD", "FIBER", "HIDE", "ROCK"]


def get(name):
    print("indiriliyor:", name, file=sys.stderr)
    return urllib.request.urlopen(BASE + name, timeout=300).read().decode("utf-8-sig")


def num(v):
    f = float(v)
    return int(f) if f.is_integer() else f


# Düğümler: tier başına toplama süresi, şarj sayısı, şarj başına adet; alet tier farkı süre çarpanı
harv = ET.fromstring(get("harvestables.xml"))
res = {}
for h in harv.iter("Harvestable"):
    if h.get("name") not in RES:
        continue
    tool = {m.get("tierdifference"): num(m.get("timefactor")) for m in h.iter("Modifier")}
    tiers = {}
    for t in h.findall("Tier"):
        tier = int(t.get("tier"))
        if tier < 4:
            continue
        ch = [c for c in t.findall("Charge") if c.get("yield")][0]
        lo, hi = (ch.get("level").split("-") + [None])[:2]
        tiers[tier] = {"ht": num(t.get("harvesttimeseconds")), "ch": int(hi or lo), "y": num(ch.get("yield"))}
    res[h.get("name")] = {"tool": tool, "t": tiers}

# Toplayıcı zırh/kask/bot pasifleri (30 sn'de bir yığın, en fazla maxcharges)
spells = get("spells.xml")
gear = {"armor": {}, "head": {}, "shoes": {}}
PFX = {"armor": "PASSIVE_YIELD_", "head": "PASSIVE_HEAD_YIELD_", "shoes": "PASSIVE_SHOES_YIELD_"}
stack = None
for slot, pfx in PFX.items():
    for r in RES:
        for tier in range(4, 9):
            m = re.search(r'<activespell uniquename="%s%s_EFFECT_T%d".*?</activespell>' % (pfx, r, tier), spells, re.S)
            v = float(re.search(r'bufftype="gatheringyield"[^>]*value="([\d.]+)"', m.group(0)).group(1))
            stack = int(re.search(r'maxcharges="(\d+)"', m.group(0)).group(1))
            old = gear[slot].get(tier)
            assert old is None or old == v, (slot, r, tier)  # bütün kaynaklarda aynı
            gear[slot][tier] = v
        pm = re.search(r'<passivespell uniquename="%s%s_T8".*?interval="([\d.]+)"' % (pfx, r), spells, re.S)
        interval = num(pm.group(1))


def spell_buffs(name):
    m = re.search(r'<activespell uniquename="%s".*?</activespell>' % name, spells, re.S)
    out = {}
    for b in re.finditer(r'<buffovertime([^>]*)/>', m.group(0)):
        a = dict(re.findall(r'(\w+)="([^"]*)"', b.group(1)))
        if a.get("type") in ("gatheringyield", "gatheringspeed"):
            out[a["type"][9]] = num(a["value"])  # y / s
            out["t"] = num(a["time"])
    return out


# İksir ve yemek: eşya (+büyü seviyesi) -> tüketilen büyü
items = get("items.xml")
cons = {}
for m in re.finditer(r'<consumableitem uniquename="(T\d_(?:POTION_GATHER|MEAL_PIE))"(.*?)</consumableitem>', items, re.S):
    uid, body = m.group(1), m.group(2)
    lv = {0: re.search(r'consumespell="([^"]+)"', body).group(1)}
    for e in re.finditer(r'<enchantment enchantmentlevel="(\d)"[^>]*consumespell="([^"]+)"', body):
        lv[int(e.group(1))] = e.group(2)
    cons[uid] = {k: spell_buffs(v) for k, v in lv.items()}

# Lonca bölgesi buff'ı
m = re.search(r'<activespell uniquename="GUILD_TERRITORY_BUFF".*?</activespell>', spells, re.S)
territory = num(re.search(r'type="gatheringyield" value="([\d.]+)"', m.group(0)).group(1))

# Toplama etkinlikleri (festivities.xml GATHERING kategorisi, 2-3 gün): kaynak türüne yield buff'ı
event = {}
for r in RES:
    m = re.search(r'<activespell uniquename="DYNAMIC_EVENT_%s".*?</activespell>' % r, spells, re.S)
    v = re.search(r'bufftype="gatheringyield"[^>]*resourcetype="%s"[^>]*value="([\d.]+)"' % r, m.group(0))
    event[r] = num(v.group(1))

# Bölgeye göre büyülü düğüm olasılıkları (ağırlıklar: .0 .1 .2 .3)
rare = {}
for d in ET.fromstring(get("rareresourcedistribution.xml")).iter("RareResourceDistribution"):
    t = {}
    for tier in d.findall("Tier"):
        w = [0, 0, 0, 0]
        for rs in tier.findall("RareState"):
            w[int(rs.get("state"))] = int(rs.get("weight"))
        t[tier.get("value") or "d"] = w
    rare[d.get("name")] = t

out = {"src": "ao-data/ao-bin-dumps (harvestables, items, spells, rareresourcedistribution)",
       "res": res, "gear": gear, "stack": stack, "interval": interval,
       "cons": cons, "territory": territory, "event": event, "premium": 0.5, "rare": rare}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print("yazıldı:", OUT, os.path.getsize(OUT), "bayt", file=sys.stderr)
