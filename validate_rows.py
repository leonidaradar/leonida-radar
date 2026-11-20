#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
content.csv satırlarını doğrular ve yer tutucuları açar. factory.py, check.py ve publish.py bunu kullanır.
Hatalı satır TÜM sistemi durdurmaz: karantinaya alınır, nedeni out/skipped.txt dosyasına yazılır.

Sütunlar: id,series,headline,d1,d2,d3,final,topic_tag,source,bg,start,publish_at,platforms
platforms (isteğe bağlı): hangi platformlara gideceği. Boş ya da all = üçü. Örn. ig, tt, yt ya da birleşik: ig+yt
Yer tutucular (metinlerde kullanılabilir):
  {KALAN_GUN}   -> çıkışa kalan gün sayısı (yayın tarihine göre), örn. 4
  {KALAN_YAZI}  -> "4 gün kaldı" / "yarın çıkıyor" / "bugün çıkıyor"   (çıkıştan sonra satır hata verir)
Kullanım: python validate_rows.py [content.csv]
"""
import csv, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIELDS = ["id", "series", "headline", "d1", "d2", "d3", "final", "topic_tag", "source", "bg", "start", "publish_at", "platforms"]
PLATFORM_MAP = {"ig": "instagram", "tt": "tiktok", "yt": "youtube"}
REQUIRED = ["id", "series", "headline", "d1", "final", "topic_tag", "source"]
TEXT_FIELDS = ["headline", "d1", "d2", "d3", "final"]
MAX_LEN = {"series": 20, "headline": 60, "d1": 90, "d2": 90, "d3": 90, "final": 70}
MAX_HEADLINE_WORDS = 9
# Rockstar kuralı: sızdırılmış/erken içerik, spoiler, hile/korsan yok
BANNED = ["sızıntı", "sızdırıl", "leak", "torrent", "crack", "korsan", "hile kodu"]
WARN_WORDS = ["spoiler", "hile"]   # kural açıklayan meşru satırlar olabilir: engellemez, uyarır
TR = timezone(timedelta(hours=3))   # Türkiye UTC+3 (yaz saati uygulaması yok)


def istanbul_now():
    return datetime.now(timezone.utc).astimezone(TR)


def launch_date():
    try:
        b = json.loads((ROOT / "brand.json").read_text(encoding="utf-8"))
        return datetime.strptime(b.get("launch_date", "2026-11-19"), "%Y-%m-%d").date()
    except Exception:
        return datetime(2026, 11, 19).date()


def parse_publish_at(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TR)
        except ValueError:
            pass
    raise ValueError(f"publish_at biçimi hatalı: '{s}' (doğrusu: 2026-11-18 21:00)")


def due_at_utc(row):
    dt = parse_publish_at(row.get("publish_at"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00.000Z") if dt else None


def expand(row, now=None):
    """Yer tutucuları açar. Çıkış tarihi geçmişse ValueError."""
    now = now or istanbul_now()
    pub = parse_publish_at(row.get("publish_at"))
    ref = (pub or now).date()
    days = (launch_date() - ref).days
    out = dict(row)
    for k in TEXT_FIELDS:
        v = out.get(k, "") or ""
        if "{KALAN" in v:
            if days < 0:
                raise ValueError("çıkış tarihi geçti; {KALAN_GUN}/{KALAN_YAZI} kullanan satır eskidi")
            yazi = "bugün çıkıyor" if days == 0 else ("yarın çıkıyor" if days == 1 else f"{days} gün kaldı")
            v = v.replace("{KALAN_YAZI}", yazi).replace("{KALAN_GUN}", str(days))
        out[k] = v
    return out



def row_platforms(row):
    """platforms sütunu -> {'instagram','tiktok','youtube'} kümesi. Boş/all = üçü. Geçersiz belirteçte ValueError."""
    raw = (row.get("platforms") or "").strip().lower()
    if raw in ("", "all"):
        return set(PLATFORM_MAP.values())
    out = set()
    for tok in re.split(r"[+|;\s]+", raw):
        if not tok:
            continue
        if tok == "all":
            return set(PLATFORM_MAP.values())
        if tok not in PLATFORM_MAP:
            raise ValueError(f"platforms değeri hatalı: '{tok}' (ig, tt, yt ya da all; birleştirmek için + kullan)")
        out.add(PLATFORM_MAP[tok])
    return out


def read_raw(path):
    """Ham satırlar: (satır_no, liste). Başlık sütun sayısını döndürür."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [(i, r) for i, r in enumerate(rd, start=2) if any(c.strip() for c in r)]
    return header, rows


def check_row(row, root=ROOT):
    errs, warns = [], []
    for k in REQUIRED:
        if not (row.get(k) or "").strip():
            errs.append(f"'{k}' boş")
    if (row.get("id") or "") and not re.fullmatch(r"\d{1,6}", row["id"].strip()):
        errs.append("id sadece rakam olmalı (örn. 012)")
    for k, mx in MAX_LEN.items():
        if len((row.get(k) or "")) > mx:
            errs.append(f"'{k}' {mx} karakteri aşıyor ({len(row[k])})")
    if len((row.get("headline") or "").split()) > MAX_HEADLINE_WORDS:
        errs.append(f"manşet {MAX_HEADLINE_WORDS} kelimeyi aşıyor")
    tag = (row.get("topic_tag") or "").strip()
    if tag and (not tag.startswith("#") or " " in tag):
        errs.append("topic_tag '#' ile başlamalı, boşluk içermemeli")
    low = " ".join((row.get(k) or "") for k in TEXT_FIELDS + ["topic_tag"]).lower()
    for w in BANNED:
        if w in low:
            errs.append(f"yasak ifade: '{w}' (sızıntı, spoiler, hile ve korsan içerik yayınlanmaz)")
            break
    for w in WARN_WORDS:
        if w in low:
            warns.append(f"'{w}' geçiyor: içerik spoiler/hile içermemeli, kontrol edin")
            break
    src = (row.get("source") or "").strip()
    if src and not re.search(r"https?://", src):
        warns.append("kaynakta bağlantı (https://...) yok; doğrulanabilir bağlantı önerilir")
    st = (row.get("start") or "").strip()
    if st and not re.fullmatch(r"\d+(\.\d+)?", st):
        errs.append("start sayı olmalı (saniye)")
    bg = (row.get("bg") or "").strip()
    if bg and not (Path(root) / "backgrounds" / bg).exists():
        errs.append(f"bg dosyası yok: backgrounds/{bg}")
    try:
        row_platforms(row)
    except ValueError as e:
        errs.append(str(e))
    try:
        pub = parse_publish_at(row.get("publish_at"))
        if pub and pub < istanbul_now():
            warns.append("publish_at geçmişte")
    except ValueError as e:
        errs.append(str(e))
    if not errs:
        try:
            expand(row)
        except ValueError as e:
            errs.append(str(e))
    return errs, warns


def load_valid(path, root=ROOT):
    """(geçerli_satırlar_açılmış, sorunlar). sorunlar: [(satır_no, id, 'ERR'|'WARN', mesaj)]"""
    header, raw_rows = read_raw(path)
    problems, valid, seen = [], [], set()
    for lineno, raw in raw_rows:
        rid = raw[0].strip() if raw else "?"
        if len(raw) > len(header):
            problems.append((lineno, rid, "ERR", f"fazla sütun ({len(raw)} > {len(header)}): metinde virgül var; virgülü kaldırın"))
            continue
        if len(raw) < 9:
            problems.append((lineno, rid, "ERR", f"eksik sütun ({len(raw)}); en az 9 sütun gerekir (source'a kadar)"))
            continue
        row = dict(zip(header, raw + [""] * (len(header) - len(raw))))
        row = {k: (v or "").strip() for k, v in row.items()}
        if rid in seen:
            problems.append((lineno, rid, "ERR", "aynı id ikinci kez kullanılmış"))
            continue
        seen.add(rid)
        errs, warns = check_row(row, root)
        for w in warns:
            problems.append((lineno, rid, "WARN", w))
        if errs:
            for e in errs:
                problems.append((lineno, rid, "ERR", e))
            continue
        row = expand(row)
        valid.append(row)
    return valid, problems


def format_problems(problems):
    return "\n".join(f"satır {ln} (id {rid}) {kind}: {msg}" for ln, rid, kind, msg in problems)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "content.csv")
    valid, probs = load_valid(path)
    print(format_problems(probs) or "Sorun yok.")
    errs = sum(1 for p in probs if p[2] == "ERR")
    print(f"\nGeçerli satır: {len(valid)} | Hatalı (karantina): {len({(p[0]) for p in probs if p[2]=='ERR'})}")
    sys.exit(1 if errs else 0)
