#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAHTE Buffer sunucusu (gerçek Buffer DEĞİLDİR). Buffer belgelerindeki kuralları taklit eder:
Bearer anahtar, createPost(input), assets[].video.url herkese açık ve video olarak indirilebilir olmalı,
YouTube için title + categoryId, Instagram için type=reel, kanal başına kuyruk sınırı.
Kullanım: python mock_buffer.py API_PORT MEDIA_PORT MEDIA_DIR [QUEUE_LIMIT] [SERVICES]
"""
import json, sys, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from functools import partial

KEY = "test-key"
POSTS = []   # kaydedilen gönderiler


class Media(BaseHTTPRequestHandler):
    root = Path(".")

    def do_GET(self):
        p = self.root / self.path.lstrip("/")
        if p.is_file() and p.suffix == ".mp4":
            data = p.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a): pass


class Api(BaseHTTPRequestHandler):
    queue_limit = 10
    services = ["instagram", "tiktok", "youtube"]

    def _reply(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):  # test yardımcısı: kaydedilen gönderiler
        self._reply(POSTS)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._reply({"errors": [{"message": "Not authorized", "extensions": {"code": "UNAUTHORIZED"}}]})
        q, v = body["query"], body.get("variables", {})
        if "organizations" in q:
            return self._reply({"data": {"account": {"organizations": [{"id": "org1", "name": "Test"}]}}})
        if "channels(" in q:
            ch = [{"id": f"ch_{s}", "name": s.title(), "service": s} for s in self.services]
            return self._reply({"data": {"channels": ch}})
        if "posts(" in q:
            cid = v["c"][0]
            n = sum(1 for p in POSTS if p["channelId"] == cid)
            return self._reply({"data": {"posts": {"edges": [{"node": {"id": str(i)}} for i in range(n)]}}})
        if "createPost" in q:
            inp = v["input"]; err = self._validate(inp)
            if err:
                return self._reply({"data": {"createPost": {"message": err}}})
            POSTS.append({"channelId": inp["channelId"], "input": inp})
            return self._reply({"data": {"createPost": {"post": {"id": f"p{len(POSTS)}", "dueAt": "2026-11-20T12:00:00.000Z"}}}})
        self._reply({"errors": [{"message": "unknown operation"}]})

    def _validate(self, inp):
        if inp.get("schedulingType") != "automatic": return "schedulingType must be automatic"
        if inp.get("mode") not in ("addToQueue", "customScheduled", "shareNow"): return "invalid mode"
        if not inp.get("text"): return "text required"
        svc = inp["channelId"].replace("ch_", "")
        if svc not in self.services: return "Channel not found"
        assets = inp.get("assets") or []
        if len(assets) != 1 or set(assets[0].keys()) != {"video"}: return "each asset must specify exactly one of image, video, document"
        url = assets[0]["video"]["url"]
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                if not r.headers.get("Content-Type", "").startswith("video/"): return "Failed to create post: not a video"
        except Exception as e:
            return f"Failed to create post: Failed to fetch video: {e}"
        md = inp.get("metadata", {})
        if svc == "youtube":
            y = md.get("youtube", {})
            if not y.get("title") or not y.get("categoryId"): return "youtube metadata: title and categoryId required"
            if len(y["title"]) > 100: return "youtube title too long"
        if svc == "instagram":
            i = md.get("instagram", {})
            if i.get("type") != "reel" or not isinstance(i.get("shouldShareToFeed"), bool): return "instagram metadata invalid"
        if sum(1 for p in POSTS if p["channelId"] == inp["channelId"]) >= self.queue_limit:
            return "Queue limit reached"
        return None

    def log_message(self, *a): pass


def start(api_port, media_port, media_dir, queue_limit=10, services=None):
    Media.root = Path(media_dir)
    Api.queue_limit = int(queue_limit)
    Api.services = services or ["instagram", "tiktok", "youtube"]
    POSTS.clear()
    a = ThreadingHTTPServer(("127.0.0.1", api_port), Api)
    m = ThreadingHTTPServer(("127.0.0.1", media_port), Media)
    import threading
    for s in (a, m):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return a, m


if __name__ == "__main__":
    a, m = start(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 10,
                 sys.argv[5].split(",") if len(sys.argv) > 5 else None)
    import time
    while True:
        time.sleep(1)
