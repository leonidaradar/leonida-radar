#!/usr/bin/env python3
"""
LEONIDA RADAR · Shorts Factory
content.csv  ->  1080x1920 mp4 (her satır bir video)  +  captions.csv  +  avatar.png  +  thumb_*.png
Gereken: Python 3.9+, ffmpeg, Pillow  (pip install pillow)
Kullanım:  python factory.py
"""
import csv, json, subprocess, sys, shutil, os, hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from validate_rows import load_valid, format_problems, row_platforms

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
SAFE_X0, SAFE_X1 = 80, 900          # sağdaki buton şeridi (900-1080) boş kalır
SAFE_Y0, SAFE_Y1 = 300, 1480        # üst menü ve alt açıklama alanı boş kalır
MAX_SECONDS = 59
RENDER_VERSION = "3"   # görünüm/ses mantığı değişince artırılır; önbelleği geçersiz kılar
MUSIC_GAIN = 0.32   # müzik seviyesi (video yaklaşık -16 LUFS civarına oturur)
PING_GAIN = 0.60    # radar sesi seviyesi

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

_CLIPG = {}
def clip_gradients():
    if "g" not in _CLIPG:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for y in range(H):
            a = 0
            if y < 650: a = int(150 * (1 - y / 650))
            if y > 780: a = max(a, int(215 * min(1, (y - 780) / 560)))
            if a: d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        _CLIPG["g"] = im
    return _CLIPG["g"].copy()


# ---------------------------------------------------------------- Instagram carousel (kart) üretimi
CW, CH = 1080, 1350     # Instagram 4:5 gönderi/carousel boyutu

def cover_crop(img, w, h):
    img = img.convert("RGB"); r = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))

def gradient_bg_size(brand, w, h):
    top = brand["rgb"]["bg"]; bot = tuple(int(v * 0.35 + t * 0.65) for v, t in zip(tuple(int(x * 0.55 + y * 0.45) for x, y in zip(top, brand["rgb"]["main"])), top))
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / (h - 1); d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    return im.convert("RGBA")

def card_background(brand, row, tmp):
    """bg bir resimse onu, klipse start saniyesinden bir kareyi arka plan yapar; yoksa marka degradesi."""
    bgname = (row.get("bg") or "").strip()
    if bgname:
        p = ROOT / "backgrounds" / bgname
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return cover_crop(Image.open(p), CW, CH).convert("RGBA"), True
        frame = tmp / f"{row['id']}_bgframe.png"
        run(["ffmpeg", "-y", "-ss", str(row.get("start") or 0), "-i", str(p), "-frames:v", "1", str(frame)])
        return cover_crop(Image.open(frame), CW, CH).convert("RGBA"), True
    return gradient_bg_size(brand, CW, CH), False

def render_card(brand, base_bg, has_photo, kind, text, series, idx, n_slides, slide_no):
    rgb = brand["rgb"]; base = base_bg.copy()
    if has_photo:
        base.alpha_composite(Image.new("RGBA", (CW, CH), (0, 0, 0, 120)))
        g = Image.new("RGBA", (CW, CH), (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
        for y in range(CH):
            a = int(160 * max(0, (y - 500) / (CH - 500))) if y > 500 else 0
            if a: gd.line([(0, y), (CW, y)], fill=(0, 0, 0, a))
        base.alpha_composite(g)
    d = ImageDraw.Draw(base); X0, X1 = 80, CW - 80; max_w = X1 - X0
    base.alpha_composite(make_logo(brand, 84, with_bg=False), (X0, 64))
    d.text((X0 + 100, 80), "@" + brand["handle"], font=font(brand, "bold", 34), fill=rgb["text"])
    cnt = f"{slide_no}/{n_slides}"; fc = font(brand, "bold", 32)
    d.text((X1 - int(d.textlength(cnt, font=fc)), 82), cnt, font=fc, fill=rgb["muted"])
    if kind == "headline":
        f_chip = font(brand, "bold", 34); chip = tr_upper(series); cw = int(d.textlength(chip, font=f_chip)) + 52
        d.rounded_rectangle([X0, 220, X0 + cw, 220 + 68], radius=34, fill=rgb["main"]); d.text((X0 + 26, 220 + 13), chip, font=f_chip, fill=(255, 255, 255))
        f, lines, size = fit_text(d, brand, tr_upper(text), "bold", 132, 70, max_w, 640)
        y = 340
        for ln in lines: d.text((X0, y), ln, font=f, fill=rgb["text"]); y += int(size * 1.16)
        d.rectangle([X0, y + 14, X0 + 220, y + 26], fill=rgb["accent"])
        d.text((X0, CH - 190), "KAYDIR  →", font=font(brand, "bold", 46), fill=rgb["accent"])
    elif kind == "detail":
        d.text((X0, 230), f"{idx:02d}", font=font(brand, "bold", 170), fill=rgb["accent"])
        f, lines, size = fit_text(d, brand, text, "bold", 88, 56, max_w, 600)
        y = 470
        for ln in lines: d.text((X0, y), ln, font=f, fill=rgb["text"]); y += int(size * 1.2)
    else:
        f, lines, size = fit_text(d, brand, text, "bold", 92, 56, max_w, 420)
        y = 260
        for ln in lines: d.text((X0, y), ln, font=f, fill=rgb["text"]); y += int(size * 1.18)
        d.text((X0, y + 40), "@" + brand["handle"], font=font(brand, "bold", 72), fill=rgb["accent"])
        base.alpha_composite(make_logo(brand, 200, with_bg=False), (X0, y + 150))
        fd = font(brand, "regular", 28); dy = CH - 190
        for ln in wrap(brand["disclaimer"], fd, max_w, d): d.text((X0, dy), ln, font=fd, fill=rgb["muted"]); dy += 36
    for i in range(n_slides):                    # alt nokta göstergesi
        cx = CW // 2 - (n_slides - 1) * 22 + i * 44
        d.ellipse([cx - 9, CH - 62, cx + 9, CH - 44], fill=rgb["main"] if i == slide_no - 1 else (255, 255, 255, 70))
    return base.convert("RGB")

def build_cards(brand, row, out_dir, tmp):
    parts = [("headline", row["headline"])] + [("detail", row[k].strip()) for k in ("d1", "d2", "d3") if row.get(k, "").strip()] + [("final", row["final"])]
    bg, photo = card_background(brand, row, tmp)
    n, paths, di = len(parts), [], 0
    for no, (kind, text) in enumerate(parts, start=1):
        if kind == "detail": di += 1
        img = render_card(brand, bg, photo, kind, text, row["series"], di, n, no)
        p = out_dir / f"{row['id']}_c{no}.png"; img.save(p, optimize=False); paths.append(p)
    return paths

def load_cfg():
    p = ROOT / "autopilot_config.json"
    cfg = {"instagram_format": "carousel"}
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


_GRAD = {}
def render_scene(brand, kind, text, series, idx, total, use_video_bg, is_last=False):
    rgb = brand["rgb"]
    if use_video_bg:
        if kind == "final":
            base = Image.new("RGBA", (W, H), (0, 0, 0, 175))       # kapanış sahnesi: koyu zemin, marka net okunur
        else:
            base = clip_gradients()                               # oyun klibi görünür kalır; yazı için üst/alt degrade
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
    max_w = SAFE_X1 - SAFE_X0
    if kind == "headline":
        f, lines, size = fit_text(d, brand, tr_upper(text), "bold", 128, 72, max_w, 640)
    elif kind == "detail":
        f, lines, size = fit_text(d, brand, text, "bold", 88, 56, max_w, 560)
    else:  # final
        f, lines, size = fit_text(d, brand, text, "bold", 92, 56, max_w, 420)
    col = rgb["text"]
    block_h = len(lines) * int(size * 1.18)
    clip_mode = use_video_bg and kind != "final"
    y0 = 680
    if clip_mode:   # klip varken yazı alt üçte bire (güvenli alanın içine) oturur, aksiyon görünür kalır
        y0 = max(760, 1390 - block_h - (70 if kind == "detail" else 0) - (30 if kind == "headline" else 0))
    if kind == "detail":
        d.text((SAFE_X0, y0 - (0 if clip_mode else 20)), f"{idx:02d}", font=font(brand, "bold", 64), fill=rgb["accent"])
        y0 += 70
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

def row_hash(brand, row, bg_path):
    h = hashlib.sha1()
    h.update(RENDER_VERSION.encode()); h.update(f"{MUSIC_GAIN}{PING_GAIN}".encode())
    h.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    h.update((ROOT / "brand.json").read_bytes())
    for p in (ROOT / "assets" / "music.mp3", ROOT / "assets" / "ping.wav", bg_path):
        if p and Path(p).exists():
            h.update(Path(p).read_bytes())
    return h.hexdigest()


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
    rh = row_hash(brand, row, bg_path)
    cache_dir = os.environ.get("MEDIA_CACHE_DIR")
    if cache_dir:
        cmp4, chash = Path(cache_dir) / f"{row['id']}.mp4", Path(cache_dir) / f"{row['id']}.hash"
        if cmp4.exists() and chash.exists() and chash.read_text().strip() == rh:
            shutil.copy(cmp4, out_dir / f"{row['id']}.mp4"); (out_dir / f"{row['id']}.hash").write_text(rh)
            print(f"[{row['id']}] önbellekten alındı")
            return total_dur
    clips, cum, n_detail = [], float(row.get("start") or 0), 0
    for i, (kind, text) in enumerate(parts):
        if kind == "detail": n_detail += 1
        img = render_scene(brand, kind, text, row["series"], n_detail if kind == "detail" else 0, total, bool(bg_path))
        png = tmp / f"{row['id']}_{i}.png"; img.save(png)
        if kind == "headline":
            thumb = Image.new("RGB", (W, H), brand["rgb"]["bg"]); thumb.paste(img, (0, 0), img)
            thumb.save(out_dir / f"thumb_{row['id']}.png")
        dur = scene_duration(kind, text); clip = tmp / f"{row['id']}_{i}.mp4"
        if bg_path and bg_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            src = ["-loop", "1", "-framerate", str(FPS), "-i", str(bg_path)]      # sabit resim arka plan
        elif bg_path:
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
    ping = ROOT / "assets" / "ping.wav"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if music.exists():
        # Ses kimliği: kesintisiz müzik + videonun başında ve final sahnesinin başında 'radar' sesi
        D = total_dur
        final_start = max(0.0, D - scene_duration("final", "") + 0.05)
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        fg = (f"[1:a]atrim=0:{D:.2f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.5,"
              f"afade=t=out:st={max(0.0, D - 1.4):.2f}:d=1.4,volume={MUSIC_GAIN}[m]")
        if ping.exists():
            cmd += ["-i", str(ping)]
            ms = int(final_start * 1000)
            fg += (f";[2:a]volume={PING_GAIN},asplit=2[p1][p2];[p2]adelay={ms}|{ms}[p2d];"
                   f"[m][p1][p2d]amix=inputs=3:normalize=0,alimiter=limit=0.89[a]")
        else:
            fg += ";[m]alimiter=limit=0.89[a]"
        cmd += ["-filter_complex", fg, "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-t", f"{total_dur:.2f}",
            "-movflags", "+faststart", str(out)]
    run(cmd)
    (out_dir / f"{row['id']}.hash").write_text(rh)
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
    rows, problems = load_valid(ROOT / "content.csv")
    (out_dir / "skipped.txt").write_text(format_problems(problems), encoding="utf-8")
    bad = {p[1] for p in problems if p[2] == "ERR"}
    if problems:
        print("\nUYARI/ATLANAN SATIRLAR:\n" + format_problems(problems) + "\n")
    if bad:
        print(f"{len(bad)} satır karantinaya alındı (video üretilmedi); diğer satırlar devam ediyor.")
    if not rows:
        print("Geçerli satır yok."); sys.exit(1)
    caps = []
    cfg = load_cfg(); fmt = str(cfg.get("instagram_format", "carousel")).lower()
    for row in rows:
        plats = row_platforms(row)
        need_video = bool(plats & {"tiktok", "youtube"}) or ("instagram" in plats and fmt in ("reel", "both"))
        need_card = "instagram" in plats and fmt in ("carousel", "both")
        info = []
        if need_video:
            dur = build_video(brand, row, out_dir, tmp); info.append(f"video {dur:.1f} sn")
        if need_card:
            n_cards = len(build_cards(brand, row, out_dir, tmp)); info.append(f"{n_cards} kart")
        caps += captions_for(brand, row)
        print(f"[{row['id']}] {row['series']} ({'+'.join(sorted({'instagram': 'ig', 'tiktok': 'tt', 'youtube': 'yt'}[p] for p in plats))}): " + ", ".join(info))
    with open(out_dir / "captions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "platform", "title", "caption"]); w.writeheader(); w.writerows(caps)
    shutil.rmtree(tmp, ignore_errors=True)
    print("Bitti. Şimdi: python check.py")

if __name__ == "__main__":
    main()
