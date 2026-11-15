#!/usr/bin/env python3
"""
LEONIDA RADAR · Shorts Factory
content.csv  ->  1080x1920 mp4 (her satır bir video)  +  captions.csv  +  avatar.png  +  thumb_*.png
Gereken: Python 3.9+, ffmpeg, Pillow  (pip install pillow)
Kullanım:  python factory.py
"""
import csv, json, subprocess, sys, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
SAFE_X0, SAFE_X1 = 80, 900          # sağdaki buton şeridi (900-1080) boş kalır
SAFE_Y0, SAFE_Y1 = 300, 1480        # üst menü ve alt açıklama alanı boş kalır
MAX_SECONDS = 59

def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()

def load_brand():
    b = json.loads((ROOT / "brand.json").read_text(encoding="utf-8"))
    b["rgb"] = {k: hex2rgb(v) for k, v in b["colors"].items()}
    return b

def font(brand, kind, size):
    return ImageFont.truetype(str(ROOT / brand["fonts"][kind]), size)

def wrap(text, fnt, max_w, draw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w: cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def fit_text(draw, brand, text, kind, start, min_size, max_w, max_h, spacing=1.18):
    size = start
    while size >= min_size:
        f = font(brand, kind, size)
        lines = wrap(text, f, max_w, draw)
        too_wide = any(draw.textlength(l, font=f) > max_w for l in lines)
        if not too_wide and len(lines) * size * spacing <= max_h:
            return f, lines, size
        size -= 4
    f = font(brand, kind, min_size)
    return f, wrap(text, f, max_w, draw), min_size

def make_logo(brand, size=512, with_bg=True):
    """Kendi çizdiğimiz sembol: radar halkası + tarama çizgisi + nokta. Üç saniyede elle çizilir."""
    S = size * 4
    im = Image.new("RGBA", (S, S), brand["rgb"]["bg"] + (255,) if with_bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(im); c = S // 2
    main, acc = brand["rgb"]["main"], brand["rgb"]["accent"]
    r = int(S * 0.36)
    d.ellipse([c - r, c - r, c + r, c + r], outline=main, width=int(S * 0.045))
    r2 = int(S * 0.19)
    d.ellipse([c - r2, c - r2, c + r2, c + r2], outline=acc, width=int(S * 0.025))
    d.line([c, c, c + int(r * 0.92), c - int(r * 0.92)], fill=acc, width=int(S * 0.04))
    rd = int(S * 0.045)
    px, py = c + int(r * 0.55), c - int(r * 0.2)
    d.ellipse([px - rd, py - rd, px + rd, py + rd], fill=main)
    return im.resize((size, size), Image.LANCZOS)

def gradient_bg(brand):
    top, bot = brand["rgb"]["bg"], tuple(int(x * 0.55 + y * 0.45) for x, y in zip(brand["rgb"]["bg"], brand["rgb"]["main"]))
    bot = tuple(int(v * 0.35 + t * 0.65) for v, t in zip(bot, top))
    im = Image.new("RGB", (W, H)); px = im.load()
    for y in range(H):
        t = y / (H - 1)
        col = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        for x in range(W): px[x, y] = col
    return im.convert("RGBA")

_GRAD = {}
def render_scene(brand, kind, text, series, idx, total, use_video_bg, is_last=False):
    rgb = brand["rgb"]
    if use_video_bg:
        base = Image.new("RGBA", (W, H), (0, 0, 0, 150))
    else:
        if "g" not in _GRAD: _GRAD["g"] = gradient_bg(brand)
        base = _GRAD["g"].copy()
    d = ImageDraw.Draw(base)
    # üst sol: sembol + isim (güvenli alanın içinde)
    logo = make_logo(brand, 96, with_bg=False)
    base.alpha_composite(logo, (SAFE_X0, SAFE_Y0 - 10))
    d.text((SAFE_X0 + 116, SAFE_Y0 + 8), "@" + brand["handle"], font=font(brand, "bold", 38), fill=rgb["text"])
    # seri etiketi
    f_chip = font(brand, "bold", 36); chip = tr_upper(series)
    cw = int(d.textlength(chip, font=f_chip)) + 56
    d.rounded_rectangle([SAFE_X0, 470, SAFE_X0 + cw, 470 + 72], radius=36, fill=rgb["main"])
    d.text((SAFE_X0 + 28, 470 + 14), chip, font=f_chip, fill=(255, 255, 255))
    # ana metin
    max_w, y0 = SAFE_X1 - SAFE_X0, 680
    if kind == "headline":
        f, lines, size = fit_text(d, brand, tr_upper(text), "bold", 128, 72, max_w, 640)
        col = rgb["text"]
    elif kind == "detail":
        d.text((SAFE_X0, y0 - 20), f"{idx:02d}", font=font(brand, "bold", 64), fill=rgb["accent"])
        y0 += 70
        f, lines, size = fit_text(d, brand, text, "bold", 88, 56, max_w, 560)
        col = rgb["text"]
    else:  # final
        f, lines, size = fit_text(d, brand, text, "bold", 92, 56, max_w, 420)
        col = rgb["text"]
    y = y0
    for ln in lines:
        d.text((SAFE_X0, y), ln, font=f, fill=col); y += int(size * 1.18)
    if kind == "headline":
        d.rectangle([SAFE_X0, y + 18, SAFE_X0 + 220, y + 30], fill=rgb["accent"])
    if kind == "final":
        d.text((SAFE_X0, y + 40), "@" + brand["handle"], font=font(brand, "bold", 70), fill=rgb["accent"])
        big = make_logo(brand, 220, with_bg=False)
        base.alpha_composite(big, (SAFE_X0, y + 150))
        fd = font(brand, "regular", 28)
        dy = 1380
        for ln in wrap(brand["disclaimer"], fd, max_w, d):
            d.text((SAFE_X0, dy), ln, font=fd, fill=rgb["muted"]); dy += 36
    # ilerleme çubuğu (üst güvenli çizgi altı değil, alt güvenli çizginin üstü)
    seg_w = (SAFE_X1 - SAFE_X0 - (total - 1) * 8) // total
    for i in range(total):
        x = SAFE_X0 + i * (seg_w + 8)
        d.rounded_rectangle([x, 1470, x + seg_w, 1480], radius=5, fill=rgb["main"] if i <= idx_global(kind, idx, total) else (255, 255, 255, 60))
    return base

def idx_global(kind, idx, total):
    return 0 if kind == "headline" else (total - 1 if kind == "final" else idx)

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFMPEG HATASI:", " ".join(map(str, cmd)), "\n", r.stderr[-1500:]); sys.exit(1)

def scene_duration(kind, text):
    if kind == "headline": return 2.6
    if kind == "final": return 3.6
    return min(6.0, max(2.8, 0.38 * len(text.split()) + 1.0))

def build_video(brand, row, out_dir, tmp):
    parts = [("headline", row["headline"])]
    details = [row[k].strip() for k in ("d1", "d2", "d3") if row.get(k, "").strip()]
    parts += [("detail", t) for t in details]
    parts += [("final", row["final"])]
    total = len(parts)
    bg_path = (ROOT / "backgrounds" / row["bg"]) if row.get("bg", "").strip() else None
    if bg_path and not bg_path.exists():
        print(f"[{row['id']}] bg dosyası yok: {bg_path}"); sys.exit(1)
    total_dur = sum(scene_duration(k, t) for k, t in parts)
    if total_dur > MAX_SECONDS:
        print(f"[{row['id']}] {total_dur:.0f} sn: çok uzun, metni kısaltın."); sys.exit(1)
    clips, cum, n_detail = [], float(row.get("start") or 0), 0
    for i, (kind, text) in enumerate(parts):
        if kind == "detail": n_detail += 1
        img = render_scene(brand, kind, text, row["series"], n_detail if kind == "detail" else 0, total, bool(bg_path))
        png = tmp / f"{row['id']}_{i}.png"; img.save(png)
        if kind == "headline":
            thumb = Image.new("RGB", (W, H), brand["rgb"]["bg"]); thumb.paste(img, (0, 0), img)
            thumb.save(out_dir / f"thumb_{row['id']}.png")
        dur = scene_duration(kind, text); clip = tmp / f"{row['id']}_{i}.mp4"
        if bg_path:
            src = ["-ss", f"{cum:.2f}", "-i", str(bg_path)]
        else:
            src = ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}"]
        cmd = ["ffmpeg", "-y", *src, "-loop", "1", "-framerate", str(FPS), "-i", str(png),
               "-filter_complex",
               f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
               f"[b][1:v]overlay=format=auto,fade=t=in:st=0:d=0.2,format=yuv420p[v]",
               "-map", "[v]", "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(clip)]
        run(cmd); clips.append(clip); cum += dur
    lst = tmp / f"{row['id']}_list.txt"
    lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    out = out_dir / f"{row['id']}.mp4"
    music = ROOT / "assets" / "music.mp3"
    audio = ["-stream_loop", "-1", "-i", str(music)] if music.exists() else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), *audio,
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)])
    return total_dur

def uniq(seq):
    seen, out = set(), []
    for s in seq:
        if s and s.lower() not in seen: seen.add(s.lower()); out.append(s)
    return out

def captions_for(brand, row):
    name, nw = brand["name"], brand["network_word"]
    details = [row[k].strip() for k in ("d1", "d2", "d3") if row.get(k, "").strip()]
    topic = row.get("topic_tag", "").strip()
    campaign = brand.get("campaign_tag", "").strip()
    fixed = brand["fixed_tags"]
    ig_tags = uniq(fixed + [topic, campaign])[:5]            # Instagram: en fazla 5 etiket
    tt_tags = uniq(fixed + [topic])[:5]
    yt_tags = uniq([fixed[0], fixed[1], topic])[:3]          # YouTube: ilk 3 etiket başlık üstünde görünür
    body = "\n".join("• " + t for t in details)
    src = f"Kaynak: {row['source']}"
    ig = (f"{row['headline']}. {name}\n\n{nw} olarak GTA 6 bilgisini kaynağıyla paylaşıyoruz.\n\n{body}\n\n"
          f"{row['final']}\n\n{src}\n{brand['disclaimer']}\n\n{' '.join(ig_tags)}")
    tt = f"{row['headline']} | {row['final']} {' '.join(tt_tags)}"
    yt_title = f"{row['headline']} | {name}"
    yt = (f"{row['headline']}.\n\n{body}\n\n{row['final']}\n\n{src}\n{brand['disclaimer']}\n\n{' '.join(yt_tags)}")
    return [
        {"id": row["id"], "platform": "instagram", "title": "", "caption": ig},
        {"id": row["id"], "platform": "tiktok", "title": "", "caption": tt},
        {"id": row["id"], "platform": "youtube", "title": yt_title, "caption": yt},
    ]

def main():
    brand = load_brand()
    out_dir = ROOT / "out"; out_dir.mkdir(exist_ok=True)
    tmp = ROOT / "_tmp"; tmp.mkdir(exist_ok=True)
    if not shutil.which("ffmpeg"): print("ffmpeg bulunamadı. Kurun: ffmpeg.org"); sys.exit(1)
    make_logo(brand, 1080).convert("RGB").save(out_dir / "avatar.png")      # üç platformda aynı profil fotoğrafı
    rows = list(csv.DictReader(open(ROOT / "content.csv", encoding="utf-8-sig")))
    caps = []
    for row in rows:
        if not row.get("source", "").strip():
            print(f"[{row['id']}] KAYNAK boş: kaynaksız video üretilmez."); sys.exit(1)
        dur = build_video(brand, row, out_dir, tmp)
        caps += captions_for(brand, row)
        print(f"[{row['id']}] {row['series']}: {dur:.1f} sn  ->  out/{row['id']}.mp4")
    with open(out_dir / "captions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "platform", "title", "caption"]); w.writeheader(); w.writerows(caps)
    shutil.rmtree(tmp, ignore_errors=True)
    print("Bitti. Şimdi: python check.py")

if __name__ == "__main__":
    main()
