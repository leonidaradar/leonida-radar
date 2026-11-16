#!/usr/bin/env python3
"""Yayın öncesi otomatik kontrol: video teknik şartları + açıklama kuralları. Hata varsa çıkış kodu 1."""
import csv, json, subprocess, sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
errors, ok = [], 0

def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)],
                       capture_output=True, text=True)
    return json.loads(r.stdout)

def err(msg): errors.append(msg); print("  HATA:", msg)

sys.path.insert(0, str(ROOT))
from validate_rows import load_valid
rows, _problems = load_valid(ROOT / "content.csv")   # karantinadaki satırlar zaten üretilmedi; denetlenmez
if not rows: print("Geçerli satır yok."); sys.exit(1)
caps = list(csv.DictReader(open(OUT / "captions.csv", encoding="utf-8-sig")))
headlines = [r["headline"].strip().lower() for r in rows]
if len(set(headlines)) != len(headlines): err("Aynı manşet iki kez var (tekrar içerik).")
if len({r["series"] for r in rows}) < 3: err("En az 3 farklı seri kullanın (kalıp tekrarı riski).")

for r in rows:
    vid = OUT / f"{r['id']}.mp4"; print(f"[{r['id']}] {vid.name}")
    if not vid.exists(): err("video yok"); continue
    if not r["source"].strip(): err("kaynak boş")
    info = probe(vid)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur, size = float(info["format"]["duration"]), int(info["format"]["size"])
    if not v: err("video akışı yok"); continue
    if (v["width"], v["height"]) != (1080, 1920): err(f"çözünürlük {v['width']}x{v['height']} (1080x1920 olmalı)")
    if v["codec_name"] != "h264": err(f"codec {v['codec_name']} (h264 olmalı)")
    if v["pix_fmt"] != "yuv420p": err(f"pix_fmt {v['pix_fmt']}")
    fr = eval(v["r_frame_rate"]);
    if not (29 <= fr <= 31): err(f"fps {fr}")
    if not a or a["codec_name"] != "aac": err("aac ses akışı yok")
    if not (5 <= dur <= 59.5): err(f"süre {dur:.1f} sn (5-59 arası olmalı)")
    if size > 100 * 1024 * 1024: err("dosya 100 MB üstü")
    print(f"  ok  {v['width']}x{v['height']} {v['codec_name']} {fr:.0f}fps {dur:.1f}sn {size/1024:.0f}KB ses:{a['codec_name'] if a else '-'}")

for c in caps:
    tags = re.findall(r"#\w+", c["caption"], flags=re.UNICODE)
    tag = f"{c['id']}/{c['platform']}"
    if c["platform"] == "instagram":
        if len(set(t.lower() for t in tags)) > 5: err(f"{tag}: 5'ten fazla etiket")
        if len(c["caption"]) > 2200: err(f"{tag}: açıklama 2200 üstü")
    if c["platform"] == "tiktok":
        if len(c["caption"]) > 2200: err(f"{tag}: açıklama 2200 üstü")
        if len(set(tags)) > 5: err(f"{tag}: 5'ten fazla etiket")
    if c["platform"] == "youtube":
        if not c["title"] or len(c["title"]) > 100: err(f"{tag}: başlık 1-100 karakter olmalı")
        if len(set(tags)) > 15: err(f"{tag}: 15'ten fazla etiket")
    if "bağlantılı değildir" not in c["caption"] and c["platform"] != "tiktok": err(f"{tag}: bağımsızlık uyarısı yok")
    if "Kaynak:" not in c["caption"] and c["platform"] != "tiktok": err(f"{tag}: kaynak satırı yok")

print("\nSONUÇ:", "BAŞARILI, yayına hazır" if not errors else f"{len(errors)} hata var")
sys.exit(1 if errors else 0)
