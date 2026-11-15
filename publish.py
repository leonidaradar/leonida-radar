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
import csv, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")
KEY = "".join(os.environ.get("BUFFER_API_KEY", "").split())
BASE = os.environ.get("MEDIA_BASE_URL", "").rstrip("/") + "/"
STATE_FILE = Path(os.environ.get("STATE_FILE", str(ROOT / "published.json")))
OUT = Path(os.environ.get("OUT_DIR", str(ROOT / "out")))
CONTENT = Path(os.environ.get("CONTENT_FILE", str(ROOT / "content.csv")))
SERVICES = ["instagram", "tiktok", "youtube"]

DEFAULTS = {"max_per_run": 2, "queue_limit": 10, "youtube_category_id": "20",
            "ai_generated": False, "media_wait_seconds": 600, "mode": "addToQueue"}


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


def media_ready(url, wait_s):
    """Buffer videoyu yayın anında kendisi indirir: adres herkese açık, doğrudan ve video olarak sunulmalı."""
    end = time.time() + wait_s
    last = "bilinmiyor"
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=30) as r:
                ctype = r.headers.get("Content-Type", "")
                r.read(1024)
                if r.status == 200 and ctype.startswith("video/"):
                    return True
                last = f"HTTP {r.status}, Content-Type {ctype}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last = str(e.reason)
        if time.time() >= end:
            raise Fatal(f"Video adresi hazır değil ({url}): {last}")
        time.sleep(min(10, max(1, end - time.time())))


CREATE = """mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def build_input(svc, channel_id, text, title, url, cfg):
    inp = {"text": text, "channelId": channel_id, "schedulingType": "automatic", "mode": cfg["mode"],
           "assets": [{"video": {"url": url}}]}
    if svc == "instagram":
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


def main():
    dry = "--dry-run" in sys.argv
    cfg = load_cfg()
    rows = list(csv.DictReader(open(CONTENT, encoding="utf-8-sig")))
    caps = {}
    for c in csv.DictReader(open(OUT / "captions.csv", encoding="utf-8-sig")):
        caps[(c["id"], c["platform"])] = c
    state = load_state()
    if dry:
        print("KURU ÇALIŞMA: ağ kullanılmıyor.")
        channels, org = {s: f"<{s}-kanal>" for s in SERVICES}, "<org>"
    else:
        if not KEY:
            raise Fatal("BUFFER_API_KEY tanımlı değil.")
        if not BASE.startswith("http"):
            raise Fatal("MEDIA_BASE_URL tanımlı değil (videoların herkese açık adresi).")
        org = get_org()
        channels = get_channels(org)
    full = set()
    done_rows = 0
    for row in rows:
        rid = row["id"]
        todo = [s for s in channels if s not in state.get(rid, {}) and s not in full]
        if not todo:
            continue
        if done_rows >= cfg["max_per_run"]:
            break
        if not (OUT / f"{rid}.mp4").exists():
            raise Fatal(f"out/{rid}.mp4 yok; önce factory.py çalışmalı.")
        url = f"{BASE}{rid}.mp4"
        print(f"[{rid}] {row['series']}: {row['headline']}")
        if not dry:
            media_ready(url, cfg["media_wait_seconds"])
        for svc in todo:
            cap = caps.get((rid, svc))
            if not cap:
                print(f"  {svc}: açıklama bulunamadı, atlandı")
                continue
            if not dry:
                n = queue_count(org, channels[svc])
                if n is not None and n >= cfg["queue_limit"]:
                    print(f"  {svc}: kuyruk dolu ({n}/{cfg['queue_limit']}), atlandı")
                    full.add(svc)
                    continue
            inp = build_input(svc, channels[svc], cap["caption"], cap["title"] or row["headline"], url, cfg)
            if dry:
                print(f"  {svc}: gönderilecek -> {json.dumps(inp, ensure_ascii=False)[:160]}...")
                continue
            res = gql(CREATE, {"input": inp})["createPost"]
            if res.get("post"):
                state.setdefault(rid, {})[svc] = {"post_id": res["post"]["id"], "due": res["post"].get("dueAt")}
                save_state(state)
                print(f"  {svc}: kuyruğa eklendi ({res['post']['id']}, zaman {res['post'].get('dueAt')})")
            else:
                msg = str(res.get("message", "bilinmeyen hata"))
                print(f"  {svc}: REDDEDİLDİ: {msg}")
                if "limit" in msg.lower() or "queue" in msg.lower():
                    full.add(svc)
        if dry or all(s in state.get(rid, {}) for s in channels):
            done_rows += 1
    left = [r["id"] for r in rows if any(s not in state.get(r["id"], {}) for s in channels)]
    print(f"\nBu çalışmada tamamlanan video: {done_rows}. Bekleyen: {len(left)}")
    if full:
        print(f"Dolu kuyruklar: {', '.join(sorted(full))}. Buffer'da yer açılınca sonraki çalışma devam eder.")


if __name__ == "__main__":
    try:
        main()
    except Fatal as e:
        print(f"HATA: {e}")
        sys.exit(1)
