# -*- coding: utf-8 -*-
"""
Albion DPS Meter toplayıcısı (sadece okur).

Albion Online açıkken bilgisayarındaki oyun trafiğini DİNLER, partindeki
oyuncuların verdiği hasarı / heal'i hesaplar ve savaşları kaydeder.
Oyuna hiçbir şey göndermez, oyunu değiştirmez.

Panel (DPS Meter sekmesi) verileri http://127.0.0.1:47700 adresinden okur.

Protokol çözümü, açık kaynak AlbionOnline-StatisticsAnalysis (GPL-3.0)
projesinin kaynak kodu incelenerek Python'a uyarlanmıştır.
"""
import json
import os
import re
import struct
import sys
import threading
import time
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 47700
FIGHT_IDLE_SECONDS = 12      # bu kadar saniye parti hasarı/heal'i olmazsa savaş biter
MIN_FIGHT_SECONDS = 2        # bundan kısa savaşlar kaydedilmez
MAX_FIGHTS_IN_MEMORY = 300
PHOTON_PORTS = (5055, 5056, 5058)

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(HERE, "kayitlar")
CACHE_DIR = os.path.join(HERE, "onbellek")

# ---------------------------------------------------------------------------
# Olay / işlem kodları. Oyun güncellemelerinde değişebilir; program açılışta
# güncel listeyi indirmeyi dener, olmazsa bu değerleri kullanır (12 Ekim 2026).
# ---------------------------------------------------------------------------
EV = {
    "Leave": 1, "HealthUpdate": 6, "HealthUpdates": 7, "NewCharacter": 29,
    "CharacterEquipmentChanged": 90, "PartyJoined": 230, "PartyDisbanded": 231,
    "PartyPlayerJoined": 232, "PartyPlayerLeft": 234,
}
OP = {"Join": 2}

CODES_URL = "https://raw.githubusercontent.com/Triky313/AlbionOnline-StatisticsAnalysis/main/src/StatisticsAnalysisTool/Network/{}.cs"
ITEMS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def parse_enum(text):
    body = text[text.index("{") + 1:text.rindex("}")]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    out, v = {}, -1
    for part in body.split(","):
        p = re.sub(r"\[.*?\]", "", part).strip()
        if not p:
            continue
        if "=" in p:
            n, val = [x.strip() for x in p.split("=", 1)]
            v = int(val, 0)
        else:
            n = p
            v += 1
        out[n] = v
    return out


def fetch_text(url, cache_name, max_age_h=12):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_name)
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_h * 3600
    if not fresh:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = r.read().decode("utf-8-sig")
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
            return data
        except Exception as e:
            log("İndirilemedi:", cache_name, "-", e)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return None


def update_codes():
    try:
        et = fetch_text(CODES_URL.format("EventCodes"), "EventCodes.cs")
        ot = fetch_text(CODES_URL.format("OperationCodes"), "OperationCodes.cs")
        if et:
            e = parse_enum(et)
            if all(k in e for k in EV):
                EV.update({k: e[k] for k in EV})
        if ot:
            o = parse_enum(ot)
            if all(k in o for k in OP):
                OP.update({k: o[k] for k in OP})
        log("Olay kodları hazır:", ", ".join(f"{k}={v}" for k, v in EV.items()))
    except Exception as e:
        log("Kod listesi okunamadı, yerleşik değerler kullanılıyor:", e)


ITEM_NAMES = {}


def load_items():
    txt = fetch_text(ITEMS_URL, "items.txt", max_age_h=24)
    if not txt:
        return
    for line in txt.splitlines():
        m = re.match(r"\s*(\d+):\s*(\S+)", line)
        if m:
            ITEM_NAMES[int(m.group(1))] = m.group(2)
    log(f"{len(ITEM_NAMES)} eşya adı yüklendi (silah ikonları için).")


# ---------------------------------------------------------------------------
# Protocol18 çözücü
# ---------------------------------------------------------------------------
class Reader:
    __slots__ = ("b", "p")

    def __init__(self, b):
        self.b = b
        self.p = 0

    def byte(self):
        if self.p >= len(self.b):
            raise EOFError
        v = self.b[self.p]
        self.p += 1
        return v

    def take(self, n):
        if n < 0 or self.p + n > len(self.b):
            raise EOFError
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def cu32(self):
        v, s = 0, 0
        while s != 35:
            c = self.byte()
            v |= (c & 0x7F) << s
            s += 7
            if not c & 0x80:
                break
        return v & 0xFFFFFFFF

    def cu64(self):
        v, s = 0, 0
        while s != 70:
            c = self.byte()
            v |= (c & 0x7F) << s
            s += 7
            if not c & 0x80:
                break
        return v & 0xFFFFFFFFFFFFFFFF


def zz(v):
    return (v >> 1) ^ -(v & 1)


class Custom:
    def __init__(self, code, data):
        self.code, self.data = code, data


def des(r, t=None):
    if t is None:
        t = r.byte()
    if 128 <= t <= 228:
        n = r.cu32()
        return Custom(t - 128, r.take(n))
    if t == 2:
        return r.byte() != 0
    if t == 3:
        return r.byte()
    if t == 4:
        return struct.unpack("<h", r.take(2))[0]
    if t == 5:
        return struct.unpack("<f", r.take(4))[0]
    if t == 6:
        return struct.unpack("<d", r.take(8))[0]
    if t == 7:
        return r.take(r.cu32()).decode("utf-8", "replace")
    if t == 8:
        return None
    if t == 9:
        return zz(r.cu32())
    if t == 10:
        return zz(r.cu64())
    if t in (11, 12):
        v = r.byte()
        return -v if t == 12 else v
    if t in (13, 14):
        v = struct.unpack("<H", r.take(2))[0]
        return -v if t == 14 else v
    if t in (15, 16):
        v = r.byte()
        return -v if t == 16 else v
    if t in (17, 18):
        v = struct.unpack("<H", r.take(2))[0]
        return -v if t == 18 else v
    if t == 19:
        code = r.byte()
        return Custom(code, r.take(r.cu32()))
    if t == 20:
        kt, vt = dict_type(r)
        return dict_elems(r, kt, vt)
    if t == 21:
        n = r.cu32()
        out = {}
        for _ in range(n):
            k = des(r)
            v = des(r)
            if k is not None:
                out[hk(k)] = v
        return out
    if t == 23:
        return [des(r) for _ in range(r.cu32())]
    if t == 24:
        return ("req", r.byte(), params(r))
    if t == 25:
        code = r.byte()
        rc = struct.unpack("<h", r.take(2))[0]
        dm = des(r)
        return ("resp", code, rc, dm, params(r))
    if t == 26:
        return ("ev", r.byte(), params(r))
    if t == 27:
        return False
    if t == 28:
        return True
    if t in (29, 30, 31, 34):
        return 0
    if t in (32, 33):
        return 0.0
    if t == 64:
        n = r.cu32()
        out = [des(r) for _ in range(n)]
        return out
    if t == 66:
        n = r.cu32()
        out = []
        while len(out) < n:
            b = r.byte()
            for i in range(8):
                if len(out) < n:
                    out.append(bool(b & (1 << i)))
        return out
    if t == 67:
        return bytes(r.take(r.cu32()))
    if t == 68:
        n = r.cu32()
        return list(struct.unpack("<%dh" % n, r.take(2 * n)))
    if t == 69:
        n = r.cu32()
        return list(struct.unpack("<%df" % n, r.take(4 * n)))
    if t == 70:
        n = r.cu32()
        return list(struct.unpack("<%dd" % n, r.take(8 * n)))
    if t == 71:
        return [des(r, 7) for _ in range(r.cu32())]
    if t == 73:
        return [zz(r.cu32()) for _ in range(r.cu32())]
    if t == 74:
        return [zz(r.cu64()) for _ in range(r.cu32())]
    if t == 83:
        n = r.cu32()
        code = r.byte()
        return [Custom(code, r.take(r.cu32())) for _ in range(n)]
    if t == 84:
        kt, vt = dict_type(r)
        return [dict_elems(r, kt, vt) for _ in range(r.cu32())]
    if t == 85:
        return [des(r, 21) for _ in range(r.cu32())]
    raise ValueError("bilinmeyen tip %d" % t)


def hk(k):
    if isinstance(k, list):
        return tuple(k)
    return k


def nested_dict_type(r):
    kt = r.byte()
    vt = r.byte()
    if vt == 20:
        nested_dict_type(r)
    elif vt == 64:
        array_type(r)


def array_type(r):
    t = r.byte()
    while t == 64:
        t = r.byte()


def dict_type(r):
    kt = r.byte()
    vt = r.byte()
    if vt == 20:
        nested_dict_type(r)
    elif vt == 64:
        array_type(r)
        vt = 0
    return kt, vt


def dict_elems(r, kt, vt):
    out = {}
    for _ in range(r.cu32()):
        k = des(r) if kt == 0 else des(r, kt)
        v = des(r) if vt == 0 else des(r, vt)
        if k is not None:
            out[hk(k)] = v
    return out


def params(r):
    n = r.byte()
    out = {}
    for _ in range(n):
        k = r.byte()
        t = r.byte()
        out[k] = des(r, t)
    return out


# ---------------------------------------------------------------------------
# Photon paket katmanı
# ---------------------------------------------------------------------------
def crc32_photon(data, zero_off):
    d = bytearray(data)
    d[zero_off:zero_off + 4] = b"\0\0\0\0"
    return zlib.crc32(bytes(d)) ^ 0xFFFFFFFF


class PhotonParser:
    def __init__(self, on_event, on_request, on_response):
        self.on_event, self.on_request, self.on_response = on_event, on_request, on_response
        self.frags = {}
        self.last_cleanup = time.time()
        self.errors = 0

    def receive(self, payload):
        now = time.time()
        if now - self.last_cleanup > 1:
            self.last_cleanup = now
            for k in [k for k, v in self.frags.items() if now - v["t"] > 15]:
                del self.frags[k]
        off = 0
        while off < len(payload):
            n = self.packet_len(payload[off:])
            if not n:
                return
            self.single(payload[off:off + n])
            off += n

    @staticmethod
    def packet_len(p):
        if len(p) < 12:
            return 0
        flags = p[2]
        if flags == 1:
            return len(p)
        off = 12 + (4 if flags == 0xCC else 0)
        if off > len(p):
            return 0
        for _ in range(p[3]):
            if off > len(p) - 12:
                return 0
            cl = struct.unpack(">i", p[off + 4:off + 8])[0]
            if cl < 12 or cl > len(p) - off:
                return 0
            off += cl
        return off

    def single(self, p):
        if len(p) < 12:
            return
        peer = struct.unpack(">h", p[0:2])[0]
        flags = p[2]
        cmd_count = p[3]
        challenge = struct.unpack(">i", p[8:12])[0]
        off = 12
        if flags == 1:
            return  # şifreli paket
        if flags == 0xCC:
            if len(p) < 16:
                return
            crc = struct.unpack(">I", p[12:16])[0]
            if crc != crc32_photon(p, 12):
                return
            off = 16
        for _ in range(cmd_count):
            off = self.command(p, off, peer, challenge)
            if off is None:
                return

    def command(self, s, off, peer, challenge):
        start = off
        if start > len(s) - 12:
            return None
        ctype = s[off]
        channel = s[off + 1]
        clen = struct.unpack(">i", s[off + 4:off + 8])[0]
        off += 12
        if clen < 12 or clen > len(s) - start:
            return None
        end = start + clen
        plen = clen - 12
        try:
            if ctype == 7:  # unreliable
                if plen >= 4:
                    self.reliable(s[off + 4:off + plen])
            elif ctype == 6:  # reliable
                self.reliable(s[off:off + plen])
            elif ctype == 8:  # fragment
                self.fragment(s[off:off + plen], peer, challenge, channel)
        except Exception:
            self.errors += 1
        return end

    def reliable(self, d):
        if len(d) < 2:
            return
        mtype = d[1]
        r = Reader(d[2:])
        if mtype == 2:
            code = r.byte()
            self.on_request(code, params(r))
        elif mtype == 3:
            code = r.byte()
            struct.unpack("<h", r.take(2))
            des(r)
            self.on_response(code, params(r))
        elif mtype == 4:
            code = r.byte()
            self.on_event(code, params(r))

    def fragment(self, d, peer, challenge, channel):
        if len(d) <= 20:
            return
        seq, count, num, total, foff = struct.unpack(">iiiii", d[:20])
        data = d[20:]
        if total <= 0 or total > 16 * 1024 * 1024 or count <= 0 or not (0 <= num < count) \
                or foff < 0 or len(data) > total - foff:
            return
        key = (peer, challenge, channel, seq)
        a = self.frags.get(key)
        if a is None or a["total"] != total or a["count"] != count:
            a = {"total": total, "count": count, "buf": bytearray(total), "got": set(), "t": time.time()}
            self.frags[key] = a
        if num not in a["got"]:
            a["buf"][foff:foff + len(data)] = data
            a["got"].add(num)
        a["t"] = time.time()
        if len(a["got"]) == count:
            del self.frags[key]
            self.reliable(bytes(a["buf"]))


# ---------------------------------------------------------------------------
# Oyun durumu ve savaş takibi
# ---------------------------------------------------------------------------
def to_int(v):
    try:
        return int(v)
    except Exception:
        return None


def guid_key(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, list):
        try:
            return bytes(x & 0xFF for x in v).hex()
        except Exception:
            return None
    return None


def as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, (bytes, bytearray)):
        return list(v)
    return [v]


class Tracker:
    def __init__(self):
        self.lock = threading.RLock()
        self.local_id = None
        self.local_name = None
        self.zone = None
        self.objects = {}        # objectId -> {"name":..., "weapon":...}
        self.party = {}          # guid -> name
        self.party_known = False
        self.last_health = {}    # objectId -> son can değeri
        self.weapons = {}        # oyuncu adı -> silah unique name
        self.fight = None
        self.fights = []
        self.packets = 0
        self.events = 0
        self.last_packet = 0
        self.started = time.time()
        self.load_saved()

    # ---- kayıt ----
    def load_saved(self):
        os.makedirs(SAVE_DIR, exist_ok=True)
        files = sorted(f for f in os.listdir(SAVE_DIR) if f.endswith(".json"))[-MAX_FIGHTS_IN_MEMORY:]
        for f in files:
            try:
                with open(os.path.join(SAVE_DIR, f), encoding="utf-8") as fh:
                    self.fights.append(json.load(fh))
            except Exception:
                pass
        if self.fights:
            log(f"{len(self.fights)} eski savaş kaydı yüklendi.")

    def save(self, fight):
        try:
            with open(os.path.join(SAVE_DIR, fight["id"] + ".json"), "w", encoding="utf-8") as fh:
                json.dump(fight, fh, ensure_ascii=False)
        except Exception as e:
            log("Kaydedilemedi:", e)

    def delete(self, fid):
        with self.lock:
            self.fights = [f for f in self.fights if f["id"] != fid]
        p = os.path.join(SAVE_DIR, os.path.basename(fid) + ".json")
        if os.path.exists(p):
            os.remove(p)

    # ---- parti ----
    def party_names(self):
        names = set(self.party.values())
        if self.local_name:
            names.add(self.local_name)
        return names

    def in_party(self, oid):
        o = self.objects.get(oid)
        if not o:
            return False
        if oid == self.local_id:
            return True
        return o["name"] in self.party_names()

    # ---- olaylar ----
    def on_event(self, _code, p):
        code = to_int(p.get(252))
        if code is None:
            return
        self.events += 1
        with self.lock:
            if code == EV["HealthUpdate"]:
                self.health(to_int(p.get(0)), p.get(2), p.get(3), to_int(p.get(6)), 3 in p)
            elif code == EV["HealthUpdates"]:
                aff = to_int(p.get(0))
                ch, nh, cs = as_list(p.get(2)), as_list(p.get(3)), as_list(p.get(6))
                for i in range(max(len(ch), len(cs))):
                    self.health(aff, ch[i] if i < len(ch) else 0, nh[i] if i < len(nh) else None,
                                to_int(cs[i]) if i < len(cs) else None, i < len(nh))
            elif code == EV["NewCharacter"]:
                oid = to_int(p.get(0))
                name = p.get(1)
                if oid is not None and isinstance(name, str):
                    w = self.weapon_from(p.get(40))
                    self.objects[oid] = {"name": name}
                    if w:
                        self.weapons[name] = w
            elif code == EV["CharacterEquipmentChanged"]:
                oid = to_int(p.get(0))
                o = self.objects.get(oid)
                w = self.weapon_from(p.get(2))
                if o and w:
                    self.weapons[o["name"]] = w
            elif code == EV["Leave"]:
                oid = to_int(p.get(0))
                if oid is not None and oid != self.local_id:
                    self.last_health.pop(oid, None)
            elif code == EV["PartyJoined"]:
                guids, names = p.get(8), as_list(p.get(9))
                gl = []
                if isinstance(guids, (bytes, bytearray)):
                    gl = [bytes(guids[i:i + 16]).hex() for i in range(0, len(guids) - 15, 16)]
                elif isinstance(guids, list):
                    gl = [guid_key(g) for g in guids]
                self.party = {g: str(n) for g, n in zip(gl, names) if g and n}
                self.party_known = True
                log("Partiye katıldın:", ", ".join(sorted(self.party.values())))
            elif code == EV["PartyPlayerJoined"]:
                g, n = guid_key(p.get(1)), p.get(2)
                if g and isinstance(n, str) and n:
                    self.party[g] = n
                    self.party_known = True
                    log("Partiye girdi:", n)
            elif code == EV["PartyPlayerLeft"]:
                g = guid_key(p.get(1))
                n = self.party.pop(g, None)
                if n:
                    log("Partiden çıktı:", n)
                if n and n == self.local_name:
                    self.party = {}
            elif code == EV["PartyDisbanded"]:
                self.party = {}
                self.party_known = True
                log("Parti dağıldı.")

    def on_request(self, _code, p):
        pass

    def on_response(self, _code, p):
        code = to_int(p.get(253))
        if code == OP["Join"]:
            with self.lock:
                self.end_fight()
                oid = to_int(p.get(0))
                name = p.get(2)
                self.objects = {}
                self.last_health = {}
                if oid is not None and isinstance(name, str):
                    self.local_id, self.local_name = oid, name
                    self.objects[oid] = {"name": name}
                self.zone = str(p.get(8)) if p.get(8) is not None else None
                log(f"Bölgeye girildi. Karakter: {self.local_name}")

    def weapon_from(self, eq):
        eq = as_list(eq)
        if not eq:
            return None
        idx = to_int(eq[0])
        if not idx or idx <= 0:
            return None
        return ITEM_NAMES.get(idx)

    def health(self, aff, change, new_health, causer, has_new):
        if aff is None:
            return
        try:
            change = float(change or 0)
        except Exception:
            return
        prev = self.last_health.get(aff)
        if has_new and new_health is not None:
            try:
                self.last_health[aff] = float(new_health)
            except Exception:
                pass
        if change == 0 or causer is None:
            return
        is_damage = change < 0
        if is_damage and aff == causer:
            return
        causer_in = self.in_party(causer)
        aff_in = self.in_party(aff)
        if not causer_in and not (is_damage and aff_in):
            return
        now = time.time()
        f = self.ensure_fight(now)
        if causer_in:
            st = self.player(f, self.objects[causer]["name"])
            st["last"] = now
            if st["first"] is None:
                st["first"] = now
            if is_damage:
                amt = round(-change)
                st["damage"] += amt
                if aff not in self.objects:
                    st["mob"] += amt
            else:
                amt = round(change)
                over = has_new and prev is not None and new_health is not None and abs(float(new_health) - prev) < 0.5
                if over:
                    st["overheal"] += amt
                else:
                    st["heal"] += amt
            f["last"] = now
        if is_damage and aff_in:
            st = self.player(f, self.objects[aff]["name"])
            st["taken"] += round(-change)
            f["last"] = now

    def ensure_fight(self, now):
        if self.fight and now - self.fight["last"] > FIGHT_IDLE_SECONDS:
            self.end_fight()
        if not self.fight:
            self.fight = {"start": now, "last": now, "players": {}, "zone": self.zone}
        return self.fight

    def player(self, f, name):
        st = f["players"].get(name)
        if st is None:
            st = {"damage": 0, "heal": 0, "overheal": 0, "taken": 0, "mob": 0, "first": None, "last": None}
            f["players"][name] = st
        w = self.weapons.get(name)
        if w:
            st["weapon"] = w
        return st

    def summarize(self, f, final):
        dur = max(1.0, f["last"] - f["start"])
        players = []
        for name, st in f["players"].items():
            if st["damage"] == 0 and st["heal"] == 0 and st["taken"] == 0:
                continue
            players.append({
                "name": name,
                "weapon": st.get("weapon") or self.weapons.get(name),
                "damage": st["damage"], "heal": st["heal"], "overheal": st["overheal"],
                "taken": st["taken"],
                "dps": round(st["damage"] / dur, 1), "hps": round(st["heal"] / dur, 1),
                "me": name == self.local_name,
            })
        players.sort(key=lambda x: (-x["damage"], -x["heal"]))
        start = f["start"]
        return {
            "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(start)) + "-%03d" % int((start % 1) * 1000),
            "start": int(start * 1000), "end": int(f["last"] * 1000),
            "duration": round(dur, 1), "zone": f.get("zone"),
            "totalDamage": sum(p["damage"] for p in players),
            "totalHeal": sum(p["heal"] for p in players),
            "players": players, "final": final,
        }

    def end_fight(self):
        f, self.fight = self.fight, None
        if not f:
            return
        s = self.summarize(f, True)
        if s["duration"] < MIN_FIGHT_SECONDS or (s["totalDamage"] == 0 and s["totalHeal"] == 0):
            return
        self.fights.append(s)
        self.fights = self.fights[-MAX_FIGHTS_IN_MEMORY:]
        self.save(s)
        top = s["players"][0]["name"] if s["players"] else "-"
        log(f"Savaş bitti: {s['duration']:.0f} sn, toplam hasar {s['totalDamage']:,}, en yüksek: {top}")

    def tick(self):
        with self.lock:
            if self.fight and time.time() - self.fight["last"] > FIGHT_IDLE_SECONDS:
                self.end_fight()

    def status(self):
        with self.lock:
            return {
                "ok": True, "version": 1,
                "capturing": time.time() - self.last_packet < 10 if self.last_packet else False,
                "packets": self.packets, "events": self.events,
                "character": self.local_name,
                "party": sorted(self.party_names()), "partyKnown": self.party_known,
                "idleSeconds": FIGHT_IDLE_SECONDS,
                "live": self.summarize(self.fight, False) if self.fight else None,
                "fightCount": len(self.fights),
            }


# ---------------------------------------------------------------------------
# IPv4 parça birleştirme + yakalama
# ---------------------------------------------------------------------------
class IpDefrag:
    def __init__(self):
        self.parts = {}

    def add(self, key, off, more, data):
        now = time.time()
        for k in [k for k, v in self.parts.items() if now - v["t"] > 10]:
            del self.parts[k]
        e = self.parts.setdefault(key, {"chunks": {}, "end": None, "t": now})
        e["chunks"][off] = data
        e["t"] = now
        if not more:
            e["end"] = off + len(data)
        if e["end"] is None:
            return None
        pos, buf = 0, bytearray()
        for o in sorted(e["chunks"]):
            if o > pos:
                return None
            c = e["chunks"][o]
            if o + len(c) > pos:
                buf += c[pos - o:]
                pos = o + len(c)
        if pos >= e["end"]:
            del self.parts[key]
            return bytes(buf[:e["end"]])
        return None


def make_packet_handler(tracker, parser):
    from scapy.all import IP, UDP
    defrag = IpDefrag()

    def handle_udp(raw_udp):
        if len(raw_udp) < 8:
            return
        sp, dp = struct.unpack(">HH", raw_udp[:4])
        if sp not in PHOTON_PORTS and dp not in PHOTON_PORTS:
            return
        tracker.packets += 1
        tracker.last_packet = time.time()
        parser.receive(raw_udp[8:])

    def on_pkt(pkt):
        try:
            if IP not in pkt:
                if UDP in pkt:
                    u = pkt[UDP]
                    if u.sport in PHOTON_PORTS or u.dport in PHOTON_PORTS:
                        tracker.packets += 1
                        tracker.last_packet = time.time()
                        parser.receive(bytes(u.payload))
                return
            ip = pkt[IP]
            if ip.proto != 17:
                return
            raw = bytes(ip.payload)
            if ip.len:
                raw = raw[:max(0, ip.len - ip.ihl * 4)]
            more = bool(ip.flags.MF)
            off = ip.frag * 8
            if more or off:
                full = defrag.add((ip.src, ip.dst, ip.id), off, more, raw)
                if full:
                    handle_udp(full)
            else:
                handle_udp(raw)
        except Exception:
            parser.errors += 1

    return on_pkt


def run_capture(tracker, parser):
    try:
        from scapy.all import sniff, conf
    except ImportError:
        log("HATA: scapy yüklü değil. 'DPS Meter Baslat.bat' dosyasıyla başlat.")
        return
    on_pkt = make_packet_handler(tracker, parser)
    flt = "(udp and (port 5055 or port 5056 or port 5058)) or (ip and (ip[6:2] & 0x3fff != 0))"
    iface = os.environ.get("ALBION_IFACE") or None
    log("Ağ dinleniyor:", iface or conf.iface)
    try:
        sniff(filter=flt, prn=on_pkt, store=False, iface=iface)
    except Exception as e:
        log("HATA: Ağ dinlenemedi:", e)
        log("Npcap kurulu mu? https://npcap.com adresinden kurup tekrar dene.")
        log("Kuruluysa bu pencereyi 'Yönetici olarak çalıştır' ile açmayı dene.")


# ---------------------------------------------------------------------------
# Yerel HTTP API (sadece bu bilgisayardan erişilir)
# ---------------------------------------------------------------------------
def make_handler(tracker):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def send_json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_OPTIONS(self):
            self.send_response(204)
            self.cors()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path in ("", "/status"):
                self.send_json(tracker.status())
            elif path == "/fights":
                with tracker.lock:
                    self.send_json(list(reversed(tracker.fights)))
            else:
                self.send_json({"error": "bulunamadı"}, 404)

        def do_DELETE(self):
            path = self.path.split("?")[0]
            m = re.match(r"^/fights/([\w\-]+)$", path)
            if m:
                tracker.delete(m.group(1))
                self.send_json({"ok": True})
            elif path == "/fights":
                with tracker.lock:
                    ids = [f["id"] for f in tracker.fights]
                for i in ids:
                    tracker.delete(i)
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "bulunamadı"}, 404)

    return H


def main():
    print("=" * 60)
    print("  Albion DPS Meter toplayıcısı")
    print("  Panelde 'DPS Meter' sekmesini aç. Bu pencere açık kalsın.")
    print("=" * 60, flush=True)
    update_codes()
    load_items()
    tracker = Tracker()
    parser = PhotonParser(tracker.on_event, tracker.on_request, tracker.on_response)

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(tracker))
    except OSError:
        log(f"HATA: {PORT} portu kullanımda. Toplayıcı zaten açık olabilir.")
        input("Kapatmak için Enter'a bas...")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"Panel bağlantısı hazır: http://127.0.0.1:{PORT}")

    def ticker():
        while True:
            time.sleep(1)
            tracker.tick()
    threading.Thread(target=ticker, daemon=True).start()

    log("Albion'u aç (ya da karakter seçim ekranına dön), oyuna gir.")
    log("İpucu: Partiyi doğru görmesi için toplayıcıyı oyuna girmeden önce başlat.")
    run_capture(tracker, parser)
    input("Kapatmak için Enter'a bas...")


if __name__ == "__main__":
    main()
