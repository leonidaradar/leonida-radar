#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leonida Radar · Otomatik yayıncı
out/*.mp4 + out/captions.csv  ->  Buffer API  ->  Instagram Reels + TikTok + YouTube Shorts

Gerekenler (ortam değişkenleri):
  BUFFER_API_KEY   Buffer > Settings > API'den aldığınız kişisel anahtar (ASLA koda yazmayın)
  MEDIA_BASE_URL   videoların herkese açık adresi, örn. https://KULLANICI.github.io/REPO/
İsteğe bağlı:
  BUFFER_ORG_ID, CHANNEL_INSTAGRAM, CHANNEL_TIKTOK, CHANNEL_YOUTUBE  (birden fazla hesap varsa)
  BUFFER_API_URL (test için), STATE_FILE (varsayılan published.json)
Kullanım:
  python publish.py            # yayına gönder
  python publish.py --dry-run  # ağ kullanmadan ne göndereceğini yazdır
"""
import csv, json, os, re, sys, time, urllib.request, urllib.error
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_rows import load_valid, due_at_utc, parse_publish_at, istanbul_now, format_problems, row_platforms

ROOT = Path(__file__).resolve().parent
API = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")
KEY = "".join(os.environ.get("BUFFER_API_KEY", "").split())  # kopyalamadan gelen boşluk/satır sonlarını temizler
BASE = "".join(os.environ.get("MEDIA_BASE_URL", "").split()).rstrip("/") + "/"
STATE_FILE = Path(os.environ.get("STATE_FILE", str(ROOT / "published.json")))
OUT = Path(os.environ.get("OUT_DIR", str(ROOT / "out")))
CONTENT = Path(os.environ.get("CONTENT_FILE", str(ROOT / "content.csv")))
SERVICES = ["instagram", "tiktok", "youtube"]

DEFAULTS = {"max_per_run": 10, "queue_limit": 10, "youtube_category_id": "20",
            "ai_generated": False, "media_wait_seconds": 600, "mode": "addToQueue",
            "disabled_services": [],
            "instagram_format": "carousel",       # carousel | reel | both
            "thumbnail_offset_ms": 600}           # Instagram/TikTok videosunda kapak karesi   # örn. ["tiktok"]: o platform otomasyondan geçici çıkarılır


class Fatal(Exception):
    pass


def load_cfg():
    cfg = dict(DEFAULTS)
    p = ROOT / "autopilot_config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise Fatal(f"Buffer istek sınırı aşıldı (429). {e.headers.get('Retry-After', '?')} sn sonra tekrar deneyin.")
        if e.code == 401:
            raise Fatal("Buffer anahtarı reddedildi (401). BUFFER_API_KEY doğru mu?")
        raise Fatal(f"Buffer HTTP hatası {e.code}")
    except urllib.error.URLError as e:
        raise Fatal(f"Buffer'a ulaşılamadı: {e.reason}")
    if data.get("errors"):
        msg = "; ".join(str(x.get("message")) for x in data["errors"])
        raise Fatal(f"Buffer hatası: {msg}")
    return data["data"]


def get_org():
    if os.environ.get("BUFFER_ORG_ID"):
        return os.environ["BUFFER_ORG_ID"]
    d = gql("query { account { organizations { id name } } }")
    orgs = d["account"]["organizations"]
    if not orgs:
        raise Fatal("Buffer hesabında organizasyon bulunamadı.")
    if len(orgs) > 1:
        print(f"UYARI: {len(orgs)} organizasyon var; ilki kullanılıyor ({orgs[0]['name']}). Değiştirmek için BUFFER_ORG_ID verin.")
    return orgs[0]["id"]


def get_channels(org):
    d = gql("query($o: OrganizationId!) { channels(input: { organizationId: $o }) { id name service } }", {"o": org})
    found = {}
    for ch in d["channels"]:
        svc = str(ch["service"]).lower()
        if svc in SERVICES:
            found.setdefault(svc, []).append(ch)
    chosen = {}
    for svc in SERVICES:
        override = os.environ.get(f"CHANNEL_{svc.upper()}")
        lst = found.get(svc, [])
        if override:
            chosen[svc] = override
        elif len(lst) == 1:
            chosen[svc] = lst[0]["id"]
        elif len(lst) > 1:
            raise Fatal(f"{svc} için {len(lst)} kanal var; CHANNEL_{svc.upper()} ile birini seçin.")
        else:
            print(f"UYARI: Buffer'da bağlı {svc} kanalı yok; bu platform atlanıyor.")
    if not chosen:
        raise Fatal("Buffer'da Instagram, TikTok ya da YouTube kanalı bağlı değil.")
    return chosen


def queue_count(org, channel_id):
    q = ("query($o: OrganizationId!, $c: [ChannelId!]) { posts(first: 100, input: { organizationId: $o, "
         "filter: { status: [scheduled], channelIds: $c } }) { edges { node { id } } } }")
    try:
        d = gql(q, {"o": org, "c": [channel_id]})
        return len(d["posts"]["edges"])
    except Fatal:
        return None  # sayamazsak Buffer'ın kendi hata mesajına güveniriz


def media_ready(url, wait_s, expect="video/"):
    """Buffer videoyu yayın anında kendisi indirir: adres herkese açık, doğrudan ve video olarak sunulmalı."""
    end = time.time() + wait_s
    last = "bilinmiyor"
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=30) as r:
                ctype = r.headers.get("Content-Type", "")
                r.read(1024)
                if r.status == 200 and ctype.startswith(expect):
                    return True
                last = f"HTTP {r.status}, Content-Type {ctype}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last = str(e.reason)
        if time.time() >= end:
            raise Fatal(f"Medya adresi hazır değil ({url}): {last}")
        time.sleep(min(10, max(1, end - time.time())))


CREATE = """mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def build_input(svc, channel_id, text, title, urls, cfg, due_at=None, kind="video"):
    mode = "customScheduled" if due_at else cfg["mode"]
    if kind == "carousel":
        assets = [{"image": {"url": u}} for u in urls]
    else:
        vid = {"url": urls[0]}
        if svc in ("instagram", "tiktok") and cfg.get("thumbnail_offset_ms") is not None:
            vid["metadata"] = {"thumbnailOffset": int(cfg["thumbnail_offset_ms"])}
        assets = [{"video": vid}]
    inp = {"text": text, "channelId": channel_id, "schedulingType": "automatic", "mode": mode, "assets": assets}
    if due_at:
        inp["dueAt"] = due_at
    if svc == "instagram" and kind == "carousel":
        inp["metadata"] = {"instagram": {"type": "post", "isAiGenerated": bool(cfg["ai_generated"])}}
    elif svc == "instagram":
        inp["metadata"] = {"instagram": {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": bool(cfg["ai_generated"])}}
    elif svc == "tiktok":
        inp["metadata"] = {"tiktok": {"isAiGenerated": bool(cfg["ai_generated"])}}
    elif svc == "youtube":
        inp["metadata"] = {"youtube": {"title": title[:100], "categoryId": str(cfg["youtube_category_id"]),
                                       "madeForKids": False, "isAiGenerated": bool(cfg["ai_generated"])}}
    return inp


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def make_targets(channels, cfg, plats):
    """(durum_anahtarı, kanal_servisi, tür) listesi. Satırın platforms değerine ve instagram_format ayarına göre."""
    fmt = str(cfg.get("instagram_format", "carousel")).lower()
    out = []
    for svc in channels:
        if svc not in plats:
            continue
        if svc == "instagram":
            if fmt in ("reel", "both"):
                out.append(("instagram", "instagram", "video"))
            if fmt in ("carousel", "both"):
                out.append(("instagram" if fmt == "carousel" else "instagram_carousel", "instagram", "carousel"))
        else:
            out.append((svc, svc, "video"))
    return out


def is_done(state, rid, targets):
    st = state.get(rid, {})
    return "_atlandi" in st or all(k in st for k, _, _ in targets)


def card_urls(rid):
    files = sorted(OUT.glob(f"{rid}_c*.png"), key=lambda p: int(re.search(r"_c(\d+)\.png$", p.name).group(1)))
    return [f"{BASE}{p.name}" for p in files]


def main():
    dry = "--dry-run" in sys.argv
    cfg = load_cfg()
    rows, problems = load_valid(CONTENT)
    if problems:
        print("Atlanan/uyarılı satırlar:\n" + format_problems(problems) + "\n")
    caps = {}
    for c in csv.DictReader(open(OUT / "captions.csv", encoding="utf-8-sig")):
        caps[(c["id"], c["platform"])] = c
    state = load_state()
    far = parse_publish_at("2999-01-01 00:00")
    rows = sorted(enumerate(rows), key=lambda x: ((parse_publish_at(x[1].get("publish_at")) or far), x[0]))
    rows = [r for _, r in rows]
    if dry:
        print("KURU ÇALIŞMA: ağ kullanılmıyor.")
        channels, org = {s: f"<{s}-kanal>" for s in SERVICES}, "<org>"
        qcount = {s: 0 for s in channels}
    else:
        if not KEY:
            raise Fatal("BUFFER_API_KEY tanımlı değil.")
        if not BASE.startswith("http"):
            raise Fatal("MEDIA_BASE_URL tanımlı değil (videoların herkese açık adresi).")
        org = get_org()
        channels = get_channels(org)
        qcount = {}
        for svc, ch in channels.items():
            qcount[svc] = queue_count(org, ch)
    disabled = {str(x).lower() for x in cfg.get("disabled_services", [])}
    if disabled:
        print(f"Geçici devre dışı platformlar: {', '.join(sorted(disabled))} (bu satırlar için atlanır, açılınca eski satırlar geriye dönük gönderilmez)")
    channels = {s: c for s, c in channels.items() if s not in disabled}
    if not channels:
        raise Fatal("Tüm platformlar devre dışı ya da bağlı değil.")
    full = set()
    done_rows = 0
    now = istanbul_now()
    for row in rows:
        rid = row["id"]
        targets = make_targets(channels, cfg, row_platforms(row))
        if is_done(state, rid, targets):
            continue
        pub = parse_publish_at(row.get("publish_at"))
        if pub and pub < now + timedelta(minutes=2):
            print(f"[{rid}] publish_at geçmiş ({row['publish_at']}); eski haber yayınlanmıyor, atlandı.")
            if not dry:
                state.setdefault(rid, {})["_atlandi"] = "gecmis zaman"
                save_state(state)
            continue
        todo = [t for t in targets if t[0] not in state.get(rid, {}) and t[1] not in full]
        if not todo:
            continue
        if done_rows >= cfg["max_per_run"]:
            break
        need_video = any(k == "video" for _, _, k in todo)
        need_cards = any(k == "carousel" for _, _, k in todo)
        if need_video and not (OUT / f"{rid}.mp4").exists():
            raise Fatal(f"out/{rid}.mp4 yok; önce factory.py çalışmalı.")
        cards = card_urls(rid) if need_cards else []
        if need_cards and len(cards) < 2:
            raise Fatal(f"out/{rid}_c*.png kartları yok; önce factory.py çalışmalı.")
        vurl = f"{BASE}{rid}.mp4"
        due = due_at_utc(row)
        label = "+".join(sorted({'instagram': 'ig', 'tiktok': 'tt', 'youtube': 'yt'}[s] for _, s, _ in todo))
        print(f"[{rid}] {row['series']} ({label}): {row['headline']}" + (f"  (saat {row['publish_at']})" if due else ""))
        if not dry:
            if need_video:
                media_ready(vurl, cfg["media_wait_seconds"], "video/")
            for u in cards:
                media_ready(u, cfg["media_wait_seconds"], "image/")
        for ds in disabled:
            if not dry:
                state.setdefault(rid, {})[ds] = {"atlandi": "devre disi"}
        for key, svc, kind in todo:
            cap = caps.get((rid, svc))
            if not cap:
                print(f"  {key}: açıklama bulunamadı, atlandı")
                continue
            if not dry and qcount.get(svc) is not None and qcount[svc] >= cfg["queue_limit"]:
                print(f"  {key}: kuyruk dolu ({qcount[svc]}/{cfg['queue_limit']}), atlandı")
                full.add(svc)
                continue
            inp = build_input(svc, channels[svc], cap["caption"], cap["title"] or row["headline"], cards if kind == "carousel" else [vurl], cfg, due, kind)
            if dry:
                print(f"  {key} ({kind}): gönderilecek -> {json.dumps(inp, ensure_ascii=False)[:170]}...")
                continue
            res = gql(CREATE, {"input": inp})["createPost"]
            if res.get("post"):
                state.setdefault(rid, {})[key] = {"post_id": res["post"]["id"], "due": res["post"].get("dueAt")}
                save_state(state)
                if qcount.get(svc) is not None:
                    qcount[svc] += 1
                print(f"  {key} ({kind}): kuyruğa eklendi ({res['post']['id']}, zaman {res['post'].get('dueAt')})")
            else:
                msg = str(res.get("message", "bilinmeyen hata"))
                print(f"  {key}: REDDEDİLDİ: {msg}")
                if "limit" in msg.lower() or "queue" in msg.lower():
                    full.add(svc)
        if dry or all(k in state.get(rid, {}) for k, _, _ in targets):
            done_rows += 1
    left = [r["id"] for r in rows if not is_done(state, r["id"], make_targets(channels, cfg, row_platforms(r)))]
    print(f"\nBu çalışmada tamamlanan satır: {done_rows}. Bekleyen: {len(left)}")
    if full:
        print(f"Dolu kuyruklar: {', '.join(sorted(full))}. Buffer'da yer açılınca sonraki çalışma devam eder.")
    if not dry:
        print("Kuyruk doluluğu: " + ", ".join(f"{s} {qcount[s]}/{cfg['queue_limit']}" for s in channels if qcount.get(s) is not None))


if __name__ == "__main__":
    try:
        main()
    except Fatal as e:
        print(f"HATA: {e}")
        sys.exit(1)
