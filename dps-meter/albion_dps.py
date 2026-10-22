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
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = 10                 # GitHub'daki dps-vN sürümüyle aynı olmalı (güncelleme kontrolü bunu karşılaştırır)
PORT = int(os.environ.get("ALBION_DPS_PORT") or 47700)
COMBAT_GAP_SECONDS = 5       # vuruşlar arası bundan uzun boşluk "savaş süresi"ne sayılmaz
FP = 10000.0                 # oyunun sabit noktalı sayı çarpanı
# credits = Combat Fame Credit (Destiny Board'da 100 olmuş düğümlerden gelen kredi; oyun bunu "ReSpec puanı"
# olarak ayrı bir mesajla bildirir). respecSilver = ReSpec boost açıkken bu krediler için ödenen silver.
GAINS = ("fame", "credits", "silver", "might", "favor", "faction", "respecSilver")
MAX_FIGHTS_IN_MEMORY = 300
MAX_OBJECTS = 5000           # hatırlanan karakter sayısı (en eskiler silinir)
JOIN_KEEP_SECONDS = 15       # bölge değişince bundan daha yeni görülen karakterler tutulur
PHOTON_PORTS = (5055, 5056, 5058)

PANEL_URL = "https://albion-craft-planner-lovat.vercel.app/dps"
# Sadece bu adreslerden açılan sayfalar toplayıcıya bağlanabilir (başka siteler kayıtları okuyamaz/silemez)
ALLOWED_ORIGINS = ("https://albion-craft-planner-lovat.vercel.app",)
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")

# .exe olarak çalışırken kayıtlar exe'nin yanındaki klasörlere yazılır
HERE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SAVE_DIR = os.path.join(HERE, "kayitlar")
CACHE_DIR = os.path.join(HERE, "onbellek")
LIVE_FILE = os.path.join(CACHE_DIR, "aktif-oturum.json")

# ---------------------------------------------------------------------------
# Olay / işlem kodları. Oyun güncellemelerinde değişebilir; program açılışta
# güncel listeyi indirmeyi dener, olmazsa bu değerleri kullanır (15 Ekim 2026).
# ---------------------------------------------------------------------------
EV = {
    "Leave": 1, "HealthUpdate": 6, "HealthUpdates": 7, "NewCharacter": 29,
    "CharacterEquipmentChanged": 90, "PartyJoined": 230, "PartyDisbanded": 231,
    "PartyPlayerJoined": 232, "PartyPlayerLeft": 234,
    "TakeSilver": 62, "UpdateFame": 82, "UpdateCurrency": 85,
    "MightAndFavorReceivedEvent": 496, "InCombatStateUpdate": 277,
    "UpdateReSpecPoints": 84,
}
OP = {"Join": 2, "ClaimPaymentTransaction": 297}

# Destiny Board kayıt modu (1. aşama): oyunun board mesajları henüz çözülmedi; ham hâlleri dosyaya yazılır.
# Oyun board düğümlerine içeride "achievement" der. Adı bu desene uyan olay/işlemler kaydedilir.
DESTINY_NAME = re.compile(r"Achievement|LearningPoints|ReSpec")
DESTINY_EV = {83: "UpdateLearningPoints", 84: "UpdateReSpecPoints", 150: "FullAchievementInfo", 151: "FinishedAchievement",
              152: "AchievementProgressInfo", 153: "FullAchievementProgressInfo", 154: "FullTrackedAchievementInfo",
              155: "FullAutoLearnAchievementInfo"}
DESTINY_OP = {147: "ReSpecAchievement", 311: "TrackAchievements", 312: "SetAchievementsAutoLearn"}

CODES_URL = "https://raw.githubusercontent.com/Triky313/AlbionOnline-StatisticsAnalysis/main/src/StatisticsAnalysisTool/Network/{}.cs"
ITEMS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"
SPELLS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/spells.xml"
MAX_SPELLS_PER_PLAYER = 30


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def jsonable(v, depth=0):
    """Photon değerlerini JSON'a çevirir (bytes -> hex, iç içe listeler/sözlükler korunur)."""
    if depth > 12:
        return repr(v)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return {"hex": bytes(v[:20000]).hex(), "len": len(v)}
    if isinstance(v, dict):
        return {str(k): jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x, depth + 1) for x in v]
    try:
        return [jsonable(x, depth + 1) for x in list(v)]
    except Exception:
        return repr(v)


class DestinyRecorder:
    """Board mesajlarını destiny-kayit/<başlangıç>.jsonl dosyasına satır satır yazar (dosya başına en çok 40 MB)."""
    MAX_BYTES = 40 * 1024 * 1024

    def __init__(self):
        self.dir = os.path.join(HERE, "destiny-kayit")
        self.path = os.path.join(self.dir, time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
        self.size = 0
        self.counts = {}
        self.lock = threading.Lock()

    def write(self, kind, code, name, p):
        with self.lock:
            if self.size > self.MAX_BYTES:
                return
            try:
                os.makedirs(self.dir, exist_ok=True)
                line = json.dumps({"t": round(time.time(), 3), "kind": kind, "code": code, "name": name,
                                   "p": jsonable(p)}, ensure_ascii=False) + "\n"
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                self.size += len(line.encode("utf-8"))
                first = name not in self.counts
                self.counts[name] = self.counts.get(name, 0) + 1
                if first:
                    log(f"Destiny Board verisi kaydedildi: {name} ({os.path.basename(self.path)})")
            except Exception as e:
                log("Destiny kaydı yazılamadı:", e)

    def status(self):
        return {"file": os.path.basename(self.path) if self.counts else None, "counts": dict(self.counts),
                "bytes": self.size}


DESTINY = DestinyRecorder()


def first_int(v):
    """İç içe liste ya da metin içindeki ilk tam sayı (board fame değerleri bu biçimde gelir)."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple)):
        for x in v:
            n = first_int(x)
            if n is not None:
                return n
        return None
    m = re.search(r"-?\d+", str(v))
    return int(m.group()) if m else None


class DestinyBoard:
    """Oyunun gönderdiği Destiny Board'u çözer (2. aşama).
    FullAchievementInfo: 1 = sonuna ulaşmış düğümler, 2 = düğüm numaraları, 3 = seviyeler (bayt). İki listede de olmayan düğüm seviye 0'dır.
    FullAchievementProgressInfo: 1 = numaralar, 2 = seviyeler, 3 = seviye içi ilerleme (0-1), 4 = seviye içi fame × 10000.
    Numara = düğümün achievements.xml'deki sırası (panel data/destiny.json'daki "order" ile adını bulur)."""
    PATH = os.path.join(CACHE_DIR, "destiny-board.json")

    def __init__(self):
        self.data = {}
        try:
            with open(self.PATH, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(self.PATH, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False)
        except Exception as e:
            log("Destiny Board kaydedilemedi:", e)

    def _start(self, char):
        # Başka karaktere geçilince sıfırlanır; ad henüz bilinmiyorsa (giriş cevabından önce) eldeki korunur
        if char and self.data.get("char") and self.data.get("char") != char:
            self.data = {}
        if char:
            self.data["char"] = char
        self.data.setdefault("lv", {})
        self.data.setdefault("prog", {})

    def full_info(self, char, p):
        ids, lv = as_list(p.get(2)), p.get(3)
        if not ids or not isinstance(lv, (bytes, bytearray, list)):
            return
        self._start(char)
        self.data["lv"] = {str(to_int(i)): int(lv[k]) for k, i in enumerate(ids) if k < len(lv) and to_int(i) is not None and int(lv[k]) > 0}
        # 1 = sonuna ulaşmış düğümler (100 ya da elite'te 120); oyun bunların seviyesini ayrıca göndermez
        self.data["max"] = [str(to_int(i)) for i in as_list(p.get(1)) if to_int(i) is not None]
        self.data["ts"] = int(time.time() * 1000)
        self._save()
        log(f"Destiny Board okundu: {len(self.data['lv'])} düğüm ({char or '?'})")

    def progress(self, char, p):
        ids, lv, fr, fame = as_list(p.get(1)), p.get(2), as_list(p.get(3)), as_list(p.get(4))
        if not ids:
            return
        self._start(char)
        prog = {}
        for k, i in enumerate(ids):
            i = to_int(i)
            if i is None:
                continue
            f = first_int(fame[k]) if k < len(fame) else None
            level = int(lv[k]) if isinstance(lv, (bytes, bytearray, list)) and k < len(lv) else None
            prog[str(i)] = [level, round(float(fr[k]), 4) if k < len(fr) else None, round(f / FP) if f is not None else None]
            if level:
                self.data.setdefault("lv", {})[str(i)] = level
        self.data["prog"] = prog
        self.data["ts"] = int(time.time() * 1000)
        self._save()


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
            d = {v: k for k, v in e.items() if DESTINY_NAME.search(k)}
            if d:
                DESTINY_EV.clear()
                DESTINY_EV.update(d)
        if ot:
            o = parse_enum(ot)
            if all(k in o for k in OP):
                OP.update({k: o[k] for k in OP})
            d = {v: k for k, v in o.items() if DESTINY_NAME.search(k)}
            if d:
                DESTINY_OP.clear()
                DESTINY_OP.update(d)
        log("Olay kodları hazır:", ", ".join(f"{k}={v}" for k, v in EV.items()))
    except Exception as e:
        log("Kod listesi okunamadı, yerleşik değerler kullanılıyor:", e)


ITEM_NAMES = {}


SPELLS = []  # oyunun gönderdiği skill numarası -> skill anahtarı (panel adını ve ikonunu bundan bulur)


def load_spells():
    """spells.xml'deki sıra = oyunun HealthUpdate'te gönderdiği skill numarası (colortag hariç,
    kanal skilli olan activespell iki numara alır)."""
    txt = fetch_text(SPELLS_URL, "spells.xml", max_age_h=72)
    if not txt:
        return
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(txt)
        loc = {}
        for el in root:
            u, t = el.get("uniquename"), el.get("namelocatag")
            if u and t and t.startswith("@SPELLS_"):
                loc[u] = t[8:]

        tags = set(loc.values())

        def key(u):
            if not u:
                return ""
            if u in loc:
                return loc[u]
            parts = u.split("_")
            for i in range(len(parts) - 1, 0, -1):  # SKILLSHOT_FIREBALL_FX -> SKILLSHOT_FIREBALL
                k = "_".join(parts[:i])
                if k in loc:
                    return loc[k]
                if k in tags:
                    return k
            return u

        out = []
        for el in root:
            if el.tag == "colortag":
                continue
            k = key(el.get("uniquename"))
            out.append(k)
            if el.tag == "activespell" and el.find("channelingspell") is not None:
                out.append(k)
        SPELLS[:] = out
        log(f"{len(SPELLS)} skill yüklendi (skill dökümü için).")
    except Exception as e:
        log("Skill listesi okunamadı:", e)


def spell_key(idx):
    i = to_int(idx)
    if i is None or i < 0:
        return "AUTO"
    return SPELLS[i] if i < len(SPELLS) and SPELLS[i] else "#%d" % i


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
        self.fame_total = None   # oyunun bildirdiği toplam fame (fark = kazanılan)
        self.credits_total = None  # karakterdeki toplam combat fame credit
        self.respec_boost = None   # ReSpec boost açık mı (bilinmiyorsa None)
        self.silver_tax = 0.0      # son kendi silver'ındaki vergi oranı; parti payına uygulanır
        self.paused = False        # paneldeki 'Duraklat': hasar/heal/kazanç sayılmaz, süre işlemez
        self.board = DestinyBoard()  # Destiny Board seviyeleri (panelin Destiny Board sekmesi /destiny'den okur)
        self.live_dirty = False
        self.packets = 0
        self.events = 0
        self.last_packet = 0
        self.started = time.time()
        self.load_saved()
        self.load_live()

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

    def load_live(self):
        try:
            with open(LIVE_FILE, encoding="utf-8") as fh:
                f = json.load(fh)
            f.setdefault("gains", {})
            for k in GAINS:
                f["gains"].setdefault(k, 0)
            f["gains"].pop("combatFame", None)  # eski sürümün yanlış sayacı
            f.setdefault("active", 0.0)
            f.setdefault("lastHit", None)
            f.setdefault("pausedSecs", 0.0)
            self.fight = f
            self.paused = bool(f.get("pausedAt"))
            log("Yarım kalan oturum geri yüklendi.")
        except Exception:
            pass

    def save_live(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            if self.fight:
                with open(LIVE_FILE, "w", encoding="utf-8") as fh:
                    json.dump(self.fight, fh, ensure_ascii=False)
            elif os.path.exists(LIVE_FILE):
                os.remove(LIVE_FILE)
        except Exception as e:
            log("Aktif oturum kaydedilemedi:", e)

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
        # Önce kalıcı hesap kimliği (GUID): dragon haritası gibi yerlerde isimler gizlenir ("PA")
        if o.get("guid") and o["guid"] in self.party:
            return True
        return o["name"] in self.party_names()

    def name_of(self, oid):
        """Gösterilecek ad: partideyse partideki gerçek adı (isim gizli bölgelerde de doğru çıkar)."""
        o = self.objects[oid]
        if oid == self.local_id and self.local_name:
            return self.local_name
        return self.party.get(o.get("guid")) or o["name"]

    # ---- olaylar ----
    def on_event(self, _code, p):
        code = to_int(p.get(252))
        if code is None:
            return
        self.events += 1
        if code in DESTINY_EV:
            name = DESTINY_EV[code]
            DESTINY.write("event", code, name, p)
            with self.lock:
                if name == "FullAchievementInfo":
                    self.board.full_info(self.local_name, p)
                elif name == "FullAchievementProgressInfo":
                    self.board.progress(self.local_name, p)
        with self.lock:
            if code == EV["HealthUpdate"]:
                self.health(to_int(p.get(0)), p.get(2), p.get(3), to_int(p.get(6)), 3 in p, p.get(7))
            elif code == EV["HealthUpdates"]:
                aff = to_int(p.get(0))
                ch, nh, cs, sp = as_list(p.get(2)), as_list(p.get(3)), as_list(p.get(6)), as_list(p.get(7))
                for i in range(max(len(ch), len(cs))):
                    self.health(aff, ch[i] if i < len(ch) else 0, nh[i] if i < len(nh) else None,
                                to_int(cs[i]) if i < len(cs) else None, i < len(nh), sp[i] if i < len(sp) else None)
            elif code == EV["NewCharacter"]:
                oid = to_int(p.get(0))
                name = p.get(1)
                if oid is not None and isinstance(name, str):
                    w = self.weapon_from(p.get(40))
                    self.objects[oid] = {"name": name, "guid": guid_key(p.get(7)), "t": time.time()}
                    if len(self.objects) > MAX_OBJECTS:
                        for k in list(self.objects)[:len(self.objects) - MAX_OBJECTS]:
                            if k != self.local_id:
                                del self.objects[k]
                    if w:
                        self.weapons[self.name_of(oid)] = w
            elif code == EV["CharacterEquipmentChanged"]:
                oid = to_int(p.get(0))
                o = self.objects.get(oid)
                w = self.weapon_from(p.get(2))
                if o and w:
                    self.weapons[self.name_of(oid)] = w
            elif code == EV["UpdateFame"]:
                if self.is_local(p.get(0)):
                    # Kazanılan fame = oyunun gönderdiği toplam fame'in (1) bir önceki mesaja göre farkı.
                    # (2) zaten premium dahil kazançtır; toplam yoksa ona düşülür.
                    total = to_int(p.get(1))
                    if total is not None and self.fame_total is not None and 0 < total - self.fame_total < 10 ** 13:
                        fame = (total - self.fame_total) / FP
                    else:
                        fame = ((to_int(p.get(2)) or 0) + (to_int(p.get(10)) or 0)) / FP
                    if total is not None:
                        self.fame_total = total
                    if fame > 0:
                        self.gain("fame", fame)
            elif code == EV["UpdateReSpecPoints"]:
                # 0: [.., toplam kredi, ..], 2: kazanılan kredi, 3: ReSpec boost için ödenen silver
                arr = p.get(0)
                if isinstance(arr, (list, tuple)) and len(arr) > 1:
                    self.credits_total = (to_int(arr[1]) or 0) / FP
                    self.gain("credits", (to_int(p.get(2)) or 0) / FP)
                    earned = (to_int(p.get(2)) or 0) / FP
                    paid = (to_int(p.get(3)) or 0) / FP
                    if paid > 0:
                        self.gain("respecSilver", paid)
                    if earned > 0:
                        # Auto-respec durumu sadece buradan anlaşılır: kredi kazanılırken silver kesildiyse açık
                        self.respec_boost = paid > 0
            elif code == EV["TakeSilver"]:
                # 0: alan, 2: mobu kesen, 3: vergi öncesi silver, 4/5/6: şehir vergisi, guild vergisi, ittifak kesintisi
                oid, target, pre = to_int(p.get(0)), to_int(p.get(2)), to_int(p.get(3)) or 0
                if oid is not None and pre > 0:
                    if oid == self.local_id:
                        tax = sum((to_int(p.get(k)) or 0) for k in (4, 5, 6))
                        if target != oid:
                            self.silver_tax = min(1.0, tax / pre)
                        self.gain("silver", max(0, pre - tax) / FP)
                    elif oid != target and self.in_party(oid):
                        # Partide son vuruşu arkadaşın yaptıysa sana düşen pay onun adıyla gelir ve vergisi yazmaz;
                        # senin son silver'ındaki vergi oranı uygulanır (StatisticsAnalysis ile aynı yöntem)
                        self.gain("silver", pre * (1 - self.silver_tax) / FP)
            elif code == EV["MightAndFavorReceivedEvent"]:
                self.gain("might", (to_int(p.get(1)) or 0) / FP)
                self.gain("favor", (to_int(p.get(4)) or 0) / FP)
            elif code == EV["UpdateCurrency"]:
                # Bu mesaj başka para birimleri için de gelir (ör. dragon haritasındaki favor);
                # sadece 6 şehir faction'ı (1-6) faction puanı sayılır.
                if (to_int(p.get(2)) or 0) in (1, 2, 3, 4, 5, 6):
                    self.gain("faction", (to_int(p.get(3)) or 0) / FP)
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
        # Auto-respec durumu eskiden buradan tahmin ediliyordu ama yanlış "açık" gösteriyordu;
        # artık sadece UpdateReSpecPoints olayından (silver kesildi mi) belirleniyor.
        code = to_int(p.get(253))
        if code in DESTINY_OP:
            DESTINY.write("request", code, DESTINY_OP[code], p)

    def on_response(self, _code, p):
        code = to_int(p.get(253))
        if code in DESTINY_OP:
            DESTINY.write("response", code, DESTINY_OP[code], p)
        elif code == OP["Join"]:
            # Giriş cevabı karakterin genel bilgilerini taşır; board'la ilgili alan var mı diye o da kaydedilir
            DESTINY.write("response", code, "Join", p)
        if code == OP["Join"]:
            with self.lock:
                oid = to_int(p.get(0))
                name = p.get(2)
                # Numaralar bölgeye özel (instance'larda baştan başlar), o yüzden eski bölgenin
                # karakterleri silinir. Ama oyun geçişte Join'i birkaç saniye arayla iki kez
                # gönderebiliyor; aradaki "yeni karakter" mesajları kaybolmasın diye son
                # JOIN_KEEP_SECONDS içinde görülenler tutulur.
                now = time.time()
                self.objects = {k: o for k, o in self.objects.items() if now - o.get("t", 0) <= JOIN_KEEP_SECONDS}
                self.last_health = {}
                if oid is not None and isinstance(name, str):
                    if name != self.local_name:
                        self.fame_total = None  # başka karakter: toplam fame farkı geçersiz
                    self.local_id, self.local_name = oid, name
                    self.objects[oid] = {"name": name, "t": time.time()}
                self.zone = str(p.get(8)) if p.get(8) is not None else None
                rs = p.get(43)
                if isinstance(rs, (list, tuple)) and len(rs) > 1:
                    self.credits_total = (to_int(rs[1]) or 0) / FP
                log(f"Bölgeye girildi. Karakter: {self.local_name}")

    def is_local(self, oid):
        oid = to_int(oid)
        return oid is None or self.local_id is None or oid == self.local_id

    def gain(self, key, amount):
        if amount <= 0 or self.paused:
            return
        f = self.ensure_fight(time.time())
        f["gains"][key] = f["gains"].get(key, 0) + amount
        self.live_dirty = True

    def weapon_from(self, eq):
        eq = as_list(eq)
        if not eq:
            return None
        idx = to_int(eq[0])
        if not idx or idx <= 0:
            return None
        return ITEM_NAMES.get(idx)

    def health(self, aff, change, new_health, causer, has_new, spell=None):
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
        if change == 0 or causer is None or self.paused:
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
        if f["lastHit"] is not None:
            f["active"] += min(now - f["lastHit"], COMBAT_GAP_SECONDS)
        f["lastHit"] = now
        self.live_dirty = True
        if causer_in:
            st = self.player(f, self.name_of(causer))
            st["last"] = now
            if st["first"] is None:
                st["first"] = now
            sk = st.setdefault("spells", {}).setdefault(spell_key(spell), [0, 0, 0])  # hasar, heal, vuruş
            sk[2] += 1
            if is_damage:
                amt = round(-change)
                st["damage"] += amt
                sk[0] += amt
                if aff not in self.objects:
                    st["mob"] += amt
            else:
                amt = round(change)
                over = has_new and prev is not None and new_health is not None and abs(float(new_health) - prev) < 0.5
                if over:
                    st["overheal"] += amt
                else:
                    st["heal"] += amt
                    sk[1] += amt
            f["last"] = now
        if is_damage and aff_in:
            st = self.player(f, self.name_of(aff))
            st["taken"] += round(-change)
            f["last"] = now

    def ensure_fight(self, now):
        if not self.fight:
            self.fight = {"start": now, "last": now, "players": {}, "zone": self.zone,
                          "gains": {k: 0 for k in GAINS}, "active": 0.0, "lastHit": None, "pausedSecs": 0.0}
        return self.fight

    def set_paused(self, on):
        """Duraklat/devam: duraklatılan süre oturum süresinden düşülür."""
        now = time.time()
        f = self.fight
        if on and not self.paused:
            if f:
                f["pausedAt"] = now
                f["lastHit"] = None  # devam edince aradaki boşluk savaş süresine eklenmesin
            log("Oturum duraklatıldı.")
        elif not on and self.paused:
            if f and f.get("pausedAt"):
                f["pausedSecs"] = f.get("pausedSecs", 0.0) + now - f.pop("pausedAt")
            log("Oturum devam ediyor.")
        self.paused = bool(on)
        self.live_dirty = True

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
        end = f["last"] if final else max(f["last"], time.time())
        paused = f.get("pausedSecs", 0.0) + (max(0.0, end - f["pausedAt"]) if f.get("pausedAt") else 0.0)
        dur = max(1.0, end - f["start"] - paused)
        act = max(1.0, f.get("active", 0) + (1 if f.get("lastHit") else 0))  # sadece vuruşma süresi
        players = []
        for name, st in f["players"].items():
            if st["damage"] == 0 and st["heal"] == 0 and st["taken"] == 0:
                continue
            players.append({
                "name": name,
                "weapon": st.get("weapon") or self.weapons.get(name),
                "damage": st["damage"], "heal": st["heal"], "overheal": st["overheal"],
                "taken": st["taken"],
                "dps": round(st["damage"] / act, 1), "hps": round(st["heal"] / act, 1),
                "spells": [{"key": k, "damage": v[0], "heal": v[1], "hits": v[2]} for k, v in
                           sorted(st.get("spells", {}).items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
                           if v[0] or v[1]][:MAX_SPELLS_PER_PLAYER],
                "me": name == self.local_name,
            })
        gains = {k: round(f.get("gains", {}).get(k, 0)) for k in GAINS}
        for p in players:
            if p["me"]:
                p["gains"] = gains  # kazançlar sadece toplayıcıyı çalıştıran karakter için bilinir
        players.sort(key=lambda x: (-x["damage"], -x["heal"]))
        start = f["start"]
        return {
            "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(start)) + "-%03d" % int((start % 1) * 1000),
            "start": int(start * 1000), "end": int(end * 1000),
            "duration": round(dur, 1), "combat": round(act, 1), "zone": f.get("zone"),
            "gains": gains,
            "totalDamage": sum(p["damage"] for p in players),
            "totalHeal": sum(p["heal"] for p in players),
            "players": players, "final": final,
        }

    def end_fight(self):
        """Oturumu bitirir, geçmişe kaydeder; sonraki vuruş/kazançta yenisi başlar (paneldeki 'Bitir')."""
        f, self.fight = self.fight, None
        self.paused = False
        self.save_live()
        if not f:
            return None
        f["last"] = time.time()
        s = self.summarize(f, True)
        if s["totalDamage"] == 0 and s["totalHeal"] == 0 and not any(s["gains"].values()):
            return None
        self.fights.append(s)
        self.fights = self.fights[-MAX_FIGHTS_IN_MEMORY:]
        self.save(s)
        top = s["players"][0]["name"] if s["players"] else "-"
        log(f"Oturum bitti: {s['duration']:.0f} sn, toplam hasar {s['totalDamage']:,}, en yüksek: {top}")
        return s

    def tick(self):
        with self.lock:
            if self.live_dirty:
                self.live_dirty = False
                self.save_live()

    def status(self):
        with self.lock:
            return {
                "ok": True, "version": VERSION, "update": APP.update, "dataClient": APP.data_client, "paused": self.paused, "destiny": DESTINY.status(),
                "board": {"char": self.board.data.get("char"), "ts": self.board.data.get("ts"), "n": len(self.board.data.get("lv", {}))},
                "capturing": time.time() - self.last_packet < 10 if self.last_packet else False,
                "packets": self.packets, "events": self.events,
                "character": self.local_name,
                "party": sorted(self.party_names()), "partyKnown": self.party_known,
                "live": self.summarize(self.fight, False) if self.fight else None,
                "fightCount": len(self.fights),
                "respecBoost": self.respec_boost,
                "creditsTotal": round(self.credits_total) if self.credits_total is not None else None,
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

        def origin_ok(self):
            o = self.headers.get("Origin")
            return o is None or o in ALLOWED_ORIGINS or bool(LOCAL_ORIGIN.match(o))

        def cors(self):
            o = self.headers.get("Origin")
            if o and self.origin_ok():
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
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
            if not self.origin_ok():
                return self.send_json({"error": "izin yok"}, 403)
            path = self.path.split("?")[0].rstrip("/")
            if path in ("", "/status"):
                self.send_json(tracker.status())
            elif path == "/fights":
                with tracker.lock:
                    self.send_json(list(reversed(tracker.fights)))
            elif path == "/destiny":
                with tracker.lock:
                    self.send_json(dict(tracker.board.data))
            else:
                self.send_json({"error": "bulunamadı"}, 404)

        def do_POST(self):
            if not self.origin_ok():
                return self.send_json({"error": "izin yok"}, 403)
            if self.path.split("?")[0].rstrip("/") == "/end":
                with tracker.lock:
                    s = tracker.end_fight()
                self.send_json({"ok": True, "saved": s["id"] if s else None})
            elif self.path.split("?")[0].rstrip("/") in ("/pause", "/resume"):
                with tracker.lock:
                    tracker.set_paused(self.path.startswith("/pause"))
                self.send_json({"ok": True, "paused": tracker.paused})
            elif self.path.split("?")[0].rstrip("/") == "/update":
                ok = APP.start_update()
                self.send_json({"ok": ok, "update": APP.update}, 200 if ok else 409)
            else:
                self.send_json({"error": "bulunamadı"}, 404)

        def do_DELETE(self):
            if not self.origin_ok():
                return self.send_json({"error": "izin yok"}, 403)
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


# ---------------------------------------------------------------------------
# Masaüstü kısmı: albiondps:// bağlantısı, tepsi simgesi, Albion Data client, otomatik güncelleme
# ---------------------------------------------------------------------------
REPO_RELEASES = "https://api.github.com/repos/cagroren/albion-craft-planner/releases?per_page=20"
EXE_NAME = "AlbionDPSMeter.exe"
DATA_CLIENT_URL = "https://github.com/ao-data/albiondata-client/releases/latest/download/update-windows-amd64.exe.gz"
DATA_CLIENT_DIR = os.path.join(HERE, "albiondata")
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
FROZEN = getattr(sys, "frozen", False)
# Site albiondps:// ile açtıysa ya da güncellemeden sonra yeniden açıldıysa tarayıcı tekrar açılmaz
FROM_LINK = any(a.lower().startswith("albiondps:") or a == "--updated" for a in sys.argv[1:])


def message(text, title="Albion DPS Meter"):
    log(text)
    if os.name == "nt" and sys.stdin is None:  # pencere yok: Windows mesaj kutusu
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        try:
            input("Kapatmak için Enter'a bas...")
        except EOFError:
            pass


def register_link():
    """albiondps:// adresini bu exe'ye bağlar; site toplayıcı kapalıysa onu bununla açar (yönetici izni gerekmez)."""
    if not (FROZEN and os.name == "nt"):
        return
    try:
        import winreg
        exe = sys.executable
        base = r"Software\Classes\albiondps"
        for sub, name, val in (("", "", "URL:Albion DPS Meter"), ("", "URL Protocol", ""),
                               (r"\DefaultIcon", "", f'"{exe}",0'), (r"\shell\open\command", "", f'"{exe}" "%1"')):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + sub) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    except OSError as e:
        log("albiondps:// kaydedilemedi:", e)


class App:
    def __init__(self):
        self.update = None       # {"version": N, "url": ..., "state": "var" | "iniyor" | "hata", "error": ...}
        self.data_client = None  # "çalışıyor" | "zaten açık" | "indiriliyor" | "hata: ..."
        self.proc = None

    # --- Albion Data Project client (pazar fiyatlarını albion-online-data.com'a gönderir) ---
    def start_data_client(self):
        if os.name != "nt" or os.environ.get("ALBION_NO_DATA_CLIENT"):
            return
        try:
            import subprocess
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq albiondata-client.exe", "/NH"],
                                 capture_output=True, text=True, creationflags=NO_WINDOW).stdout
            if "albiondata-client" in out.lower():
                self.data_client = "zaten açık"
                return
            exe = os.path.join(DATA_CLIENT_DIR, "albiondata-client.exe")
            if not os.path.exists(exe):
                self.data_client = "indiriliyor"
                log("Albion Data client indiriliyor...")
                import gzip
                os.makedirs(DATA_CLIENT_DIR, exist_ok=True)
                req = urllib.request.Request(DATA_CLIENT_URL, headers={"User-Agent": "AlbionDPSMeter"})
                data = gzip.decompress(urllib.request.urlopen(req, timeout=120).read())
                if data[:2] != b"MZ":
                    raise ValueError("indirilen dosya exe değil")
                with open(exe + ".tmp", "wb") as fh:
                    fh.write(data)
                os.replace(exe + ".tmp", exe)
            self.proc = subprocess.Popen([exe, "-minimize"], cwd=DATA_CLIENT_DIR, creationflags=NO_WINDOW,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            self.data_client = "çalışıyor"
            log("Albion Data client başlatıldı.")
        except Exception as e:
            self.data_client = f"hata: {e}"
            log("Albion Data client başlatılamadı:", e)

    def stop_data_client(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    # --- Otomatik güncelleme (GitHub'daki en yeni dps-vN sürümü) ---
    def check_update(self):
        try:
            req = urllib.request.Request(REPO_RELEASES, headers={"User-Agent": "AlbionDPSMeter", "Accept": "application/vnd.github+json"})
            best = None
            for r in json.loads(urllib.request.urlopen(req, timeout=20).read()):
                m = re.fullmatch(r"dps-v(\d+)", r.get("tag_name") or "")
                if not m or r.get("draft") or r.get("prerelease"):
                    continue
                n = int(m.group(1))
                url = next((a["browser_download_url"] for a in r.get("assets", []) if a.get("name") == EXE_NAME), None)
                if url and n > VERSION and (best is None or n > best["version"]):
                    best = {"version": n, "url": url, "state": "var"}
            if best:
                log(f"Yeni sürüm var: dps-v{best['version']} (panelden 'Güncelle'ye bas)")
            self.update = best
        except Exception as e:
            log("Güncelleme kontrol edilemedi:", e)

    def start_update(self):
        u = self.update
        if not u or u.get("state") == "iniyor" or not FROZEN:
            return False
        u["state"] = "iniyor"
        threading.Thread(target=self._do_update, args=(u,), daemon=True).start()
        return True

    def _do_update(self, u):
        try:
            import subprocess
            exe = sys.executable
            new = exe + ".new"
            req = urllib.request.Request(u["url"], headers={"User-Agent": "AlbionDPSMeter"})
            data = urllib.request.urlopen(req, timeout=300).read()
            if data[:2] != b"MZ" or len(data) < 1_000_000:
                raise ValueError("indirilen dosya bozuk")
            with open(new, "wb") as fh:
                fh.write(data)
            # Çalışan exe kendi üstüne yazamaz: küçük bir betik program kapanınca dosyayı değiştirip yeniden açar.
            # Tek dosyalık exe iki işlemdir (açıcı + program), ikisinin de kapanması beklenir.
            wait = "".join(f'tasklist /FI "PID eq {p}" /NH | find "{p}" >nul && (timeout /t 1 /nobreak >nul & goto w)\r\n'
                           for p in {os.getpid(), os.getppid()})
            os.makedirs(CACHE_DIR, exist_ok=True)
            bat = os.path.join(CACHE_DIR, "guncelle.bat")
            with open(bat, "w", encoding="mbcs") as fh:
                fh.write(f'@echo off\r\n:w\r\n{wait}move /y "{new}" "{exe}" >nul\r\nstart "" "{exe}" --updated\r\ndel "%~f0"\r\n')
            log(f"dps-v{u['version']} indirildi, yeniden başlatılıyor...")
            # Yeni exe eski exe'nin geçici klasör ayarlarını devralırsa açılamaz; ortam sıfırlanarak başlatılır
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEI"))}
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen(["cmd", "/c", bat], creationflags=NO_WINDOW, close_fds=True, env=env)
            self.quit()
        except Exception as e:
            u["state"], u["error"] = "hata", str(e)
            log("Güncelleme başarısız:", e)

    def quit(self):
        self.stop_data_client()
        os._exit(0)


APP = App()


def make_tray():
    """Saatin yanındaki simge. pystray yoksa (kaynak koddan çalıştırırken) None döner."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(240, 136, 62, 255))
    for x, top in ((18, 36), (29, 26), (40, 16)):
        d.rectangle((x, top, x + 7, 48), fill=(20, 20, 20, 255))
    menu = pystray.Menu(
        pystray.MenuItem("DPS Meter'ı aç", lambda: webbrowser.open(PANEL_URL), default=True),
        pystray.MenuItem("Kapat", lambda icon: (icon.stop(), APP.quit())))
    return pystray.Icon("AlbionDPSMeter", img, f"Albion DPS Meter v{VERSION}", menu)


def setup_output():
    # Penceresiz (--noconsole) exe'de çıktılar dosyaya yazılır
    if sys.stdout is None or sys.stderr is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        f = open(os.path.join(CACHE_DIR, "toplayici.log"), "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def main():
    setup_output()
    print("=" * 60)
    print(f"  Albion DPS Meter toplayıcısı v{VERSION}")
    print("  Panelde 'DPS Meter' sekmesini aç. Saatin yanındaki simgeden kapatılır.")
    print("=" * 60, flush=True)
    register_link()
    if os.name == "nt" and not os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "Npcap", "wpcap.dll")):
        webbrowser.open("https://npcap.com/#download")
        message("Npcap kurulu değil. Açılan sayfadan indirip varsayılan ayarlarla kur, sonra bu programı tekrar çalıştır.")
        return
    class Server(ThreadingHTTPServer):
        # Windows'ta SO_REUSEADDR aynı portu ikinci kez açtırır; tek kopya çalışsın diye port özel tutulur
        allow_reuse_address = False

        def server_bind(self):
            import socket
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    try:
        srv = Server(("127.0.0.1", PORT), BaseHTTPRequestHandler)
    except OSError:
        if not FROM_LINK:  # site açmaya çalıştıysa sessizce çık, zaten açık
            message(f"DPS Meter zaten açık (saatin yanındaki simge). {PORT} portu kullanımda.")
        return
    update_codes()
    load_items()
    load_spells()
    tracker = Tracker()
    parser = PhotonParser(tracker.on_event, tracker.on_request, tracker.on_response)
    srv.RequestHandlerClass = make_handler(tracker)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"Panel bağlantısı hazır: http://127.0.0.1:{PORT}")
    if FROZEN and not FROM_LINK and not os.environ.get("ALBION_NO_BROWSER"):
        webbrowser.open(PANEL_URL)
    threading.Thread(target=APP.check_update, daemon=True).start()
    threading.Thread(target=APP.start_data_client, daemon=True).start()

    def ticker():
        while True:
            time.sleep(3)
            tracker.tick()
    threading.Thread(target=ticker, daemon=True).start()

    log("Albion'u aç (ya da karakter seçim ekranına dön), oyuna gir.")
    log("İpucu: Partiyi doğru görmesi için toplayıcıyı oyuna girmeden önce başlat.")
    tray = make_tray()
    if tray is None:
        run_capture(tracker, parser)
        APP.stop_data_client()
        message("Toplayıcı durdu.")
        return
    threading.Thread(target=run_capture, args=(tracker, parser), daemon=True).start()
    tray.run()
    APP.quit()


if __name__ == "__main__":
    main()
