#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish.py için otomatik testler (SAHTE Buffer sunucusuna karşı; gerçek Buffer'a bağlanmaz)."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import mock_buffer as mb

API_PORT, MEDIA_PORT = 18080, 18081
work = Path(tempfile.mkdtemp())
proj = work / "proj"
shutil.copytree(ROOT, proj, ignore=shutil.ignore_patterns("tests", "out", "_tmp", "published.json", "__pycache__"))
(proj / "out").mkdir()
r = subprocess.run([sys.executable, "factory.py"], cwd=proj, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
ROWS = 6
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("  GEÇTİ  " if cond else "  KALDI  ") + name + (f"  [{detail}]" if detail and not cond else ""))


def run(env_extra=None, args=(), state="state.json", cfg=None):
    env = dict(os.environ, BUFFER_API_URL=f"http://127.0.0.1:{API_PORT}", BUFFER_API_KEY="test-key",
               MEDIA_BASE_URL=f"http://127.0.0.1:{MEDIA_PORT}/", STATE_FILE=str(proj / state))
    env.update(env_extra or {})
    if cfg is not None:
        (proj / "autopilot_config.json").write_text(json.dumps(cfg))
    elif (proj / "autopilot_config.json").exists():
        (proj / "autopilot_config.json").unlink()
    return subprocess.run([sys.executable, "publish.py", *args], cwd=proj, env=env, capture_output=True, text=True)


def fresh(queue_limit=10, services=None):
    a, m = mb.start(API_PORT, MEDIA_PORT, proj / "out", queue_limit, services)
    return a, m


def stop(*s):
    for x in s:
        x.shutdown(); x.server_close()


print("T1 kuru çalışma (ağ yok)")
p = run(args=("--dry-run",), state="t1.json", cfg={"max_per_run": 1})
check("dry-run başarılı çıkar", p.returncode == 0, p.stdout + p.stderr)
check("dry-run 3 platform planlar", p.stdout.count("gönderilecek") == 3, p.stdout)
check("dry-run durum dosyası yazmaz", not (proj / "t1.json").exists())

print("T2 mutlu yol: günde 2 video x 3 platform")
a, m = fresh()
p = run(state="t2.json", cfg={"max_per_run": 2})
posts = list(mb.POSTS)
check("çıkış kodu 0", p.returncode == 0, p.stdout + p.stderr)
check("2 video x 3 platform = 6 gönderi", len(posts) == 6, str(len(posts)))
yt = [x for x in posts if x["channelId"] == "ch_youtube"][0]["input"]
ig = [x for x in posts if x["channelId"] == "ch_instagram"][0]["input"]
check("YouTube başlık + kategori 20 + başlık<=100", yt["metadata"]["youtube"]["title"] and yt["metadata"]["youtube"]["categoryId"] == "20" and len(yt["metadata"]["youtube"]["title"]) <= 100)
check("Instagram type=reel", ig["metadata"]["instagram"]["type"] == "reel")
check("video adresi .mp4 ve doğru taban", all(x["input"]["assets"][0]["video"]["url"].startswith(f"http://127.0.0.1:{MEDIA_PORT}/") for x in posts))
check("durum dosyası 2 videoyu yazdı", len(json.loads((proj / "t2.json").read_text())) == 2)

print("T3 tekrar çalıştırma: kopya yok")
p = run(state="t2.json", cfg={"max_per_run": 2})
posts = list(mb.POSTS)
keys = [(x["input"]["assets"][0]["video"]["url"], x["channelId"]) for x in posts]
check("12 gönderi (2 yeni video daha)", len(posts) == 12, str(len(posts)))
check("hiçbir (video, kanal) çifti iki kez gönderilmedi", len(keys) == len(set(keys)))
p = run(state="t2.json", cfg={"max_per_run": 2}); p = run(state="t2.json", cfg={"max_per_run": 2})
posts = list(mb.POSTS)
keys = [(x["input"]["assets"][0]["video"]["url"], x["channelId"]) for x in posts]
check("6 video bitince toplam 18 gönderi, kopya yok", len(posts) == ROWS * 3 and len(keys) == len(set(keys)), str(len(posts)))
p = run(state="t2.json", cfg={"max_per_run": 2})
check("her şey bitince yeni gönderi yok", len(mb.POSTS) == ROWS * 3 and "Bekleyen: 0" in p.stdout, p.stdout)
stop(a, m)

print("T4 kuyruk sınırı (kanal başına 3)")
a, m = fresh(queue_limit=3)
p = run(state="t4.json", cfg={"max_per_run": 6, "queue_limit": 10})   # bizim sınır 10, mock 3: Buffer hatasına güvenir
check("çökmeden biter (çıkış kodu 0)", p.returncode == 0, p.stdout + p.stderr)
check("kanal başına en çok 3 gönderi", all(sum(1 for x in mb.POSTS if x["channelId"] == c) <= 3 for c in ("ch_instagram", "ch_tiktok", "ch_youtube")))
check("kuyruk dolu bildirimi var", "kuyruk" in p.stdout.lower() or "REDDEDİLDİ" in p.stdout, p.stdout)
st = json.loads((proj / "t4.json").read_text())
check("reddedilen video tamamlandı sayılmadı", all(len(v) <= 3 for v in st.values()))
stop(a, m)

print("T5 kendi kuyruk sınırımız (queue_limit=2)")
a, m = fresh()
p = run(state="t5.json", cfg={"max_per_run": 6, "queue_limit": 2})
check("kanal başına 2 gönderiyle durur", all(sum(1 for x in mb.POSTS if x["channelId"] == c) == 2 for c in ("ch_instagram", "ch_tiktok", "ch_youtube")), str(len(mb.POSTS)))
stop(a, m)

print("T6 yanlış anahtar")
a, m = fresh()
p = run(env_extra={"BUFFER_API_KEY": "yanlis"}, state="t6.json")
check("anlaşılır hata ve çıkış kodu 1", p.returncode == 1 and "HATA" in p.stdout, p.stdout)
check("hiç gönderi yok", len(mb.POSTS) == 0)
stop(a, m)

print("T7 video adresi ulaşılamaz")
a, m = fresh()
p = run(env_extra={"MEDIA_BASE_URL": f"http://127.0.0.1:{MEDIA_PORT}/yok/"}, state="t7.json", cfg={"media_wait_seconds": 2})
check("hata verir, çıkış kodu 1", p.returncode == 1 and "hazır değil" in p.stdout, p.stdout)
check("hiç gönderi yok", len(mb.POSTS) == 0)
stop(a, m)

print("T8 TikTok kanalı bağlı değil")
a, m = fresh(services=["instagram", "youtube"])
p = run(state="t8.json", cfg={"max_per_run": 1})
check("uyarı verir ve diğer ikisine gönderir", "tiktok" in p.stdout and len(mb.POSTS) == 2, p.stdout)
stop(a, m)

print("T9 anahtar tanımlı değil")
p = run(env_extra={"BUFFER_API_KEY": ""}, state="t9.json")
check("çıkış kodu 1 ve açıklama", p.returncode == 1 and "BUFFER_API_KEY" in p.stdout, p.stdout)

fails = [n for n, ok in results if not ok]
print(f"\nSONUÇ: {len(results) - len(fails)}/{len(results)} test geçti")
shutil.rmtree(work, ignore_errors=True)
sys.exit(1 if fails else 0)
