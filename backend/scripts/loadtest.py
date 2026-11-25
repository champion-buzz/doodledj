"""Load test: N concurrent simulated users redraw and request playlists.

By default it starts the API with a local stand-in for Deezer that adds realistic
network latency (--deezer-ms), so results are repeatable without hitting the real
API. Point --url at a running server to test that instead.

    python scripts/loadtest.py --users 100 --requests 20 --deezer-ms 120
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from werkzeug.serving import make_server

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PALETTE = ["#ffd400", "#ff7a00", "#d00000", "#1b1f3b", "#a8d8ea", "#cdeac0", "#7b2cbf", "#2a9d8f", "#111111"]


def random_features(rnd: random.Random) -> dict:
    k = rnd.randint(1, 3)
    cols = rnd.sample(PALETTE, k)
    weights = [rnd.random() for _ in cols]
    total = sum(weights)
    return {
        "colors": [{"hex": c, "weight": w / total} for c, w in zip(cols, weights)],
        "strokeCount": rnd.randint(1, 60),
        "avgSpeed": round(rnd.uniform(0.05, 3.0), 2),
        "jaggedness": round(rnd.random(), 2),
        "coverage": round(rnd.uniform(0.01, 0.5), 2),
        "durationMs": rnd.randint(500, 60000),
    }


def start_stack(deezer_ms: int) -> str:
    from flask import Flask, jsonify, request

    from doodledj.app import create_app
    from doodledj.deezer import DeezerClient
    from doodledj.llm import LLMClient
    from doodledj.storage import MemoryStorage

    fake = Flask("fake-deezer")

    @fake.get("/search")
    def search():
        time.sleep(deezer_ms / 1000)
        q = request.args["q"]
        return jsonify({"data": [{"id": hash((q, i)) % 10**9, "title": f"{q} {i}", "artist": {"name": f"a{i % 5}"},
                                  "album": {"title": "x"}, "preview": "", "link": ""} for i in range(25)]})

    dz = make_server("127.0.0.1", 0, fake, threaded=True)
    threading.Thread(target=dz.serve_forever, daemon=True).start()
    app = create_app({"DEEZER_CLIENT": DeezerClient(f"http://127.0.0.1:{dz.server_port}"),
                      "LLM_CLIENT": LLMClient(None, "none"), "STORAGE": MemoryStorage()})
    logging_off(app)
    api = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{api.server_port}"


def logging_off(app):
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("doodledj").setLevel(logging.ERROR)


def user(url: str, n: int, seed: int, out: list, server_ms: list):
    rnd = random.Random(seed)
    s = requests.Session()
    sid = f"loadtest-{seed:06d}"
    for _ in range(n):
        t0 = time.perf_counter()
        r = s.post(f"{url}/api/playlist", json={"features": random_features(rnd), "sessionId": sid}, timeout=10)
        out.append((time.perf_counter() - t0) * 1000)
        if r.ok:
            server_ms.append(r.json()["timings"]["totalMs"])
        time.sleep(rnd.uniform(0.05, 0.2))  # think time between strokes


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--requests", type=int, default=20)
    ap.add_argument("--deezer-ms", type=int, default=120)
    ap.add_argument("--url", default=None)
    a = ap.parse_args()

    url = a.url or start_stack(a.deezer_ms)
    lat: list[float] = []
    server_ms: list[float] = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.users) as pool:
        for i in range(a.users):
            pool.submit(user, url, a.requests, i, lat, server_ms)
    wall = time.perf_counter() - t0
    print(f"{a.users} concurrent users x {a.requests} requests (simulated Deezer latency {a.deezer_ms} ms)")
    print(f"requests: {len(lat)}  throughput: {len(lat) / wall:.0f} req/s")
    print(f"end-to-end latency  p50 {pct(lat, .5):.0f} ms  p95 {pct(lat, .95):.0f} ms  "
          f"p99 {pct(lat, .99):.0f} ms  mean {statistics.mean(lat):.0f} ms")
    print(f"server time         p50 {pct(server_ms, .5):.0f} ms  p95 {pct(server_ms, .95):.0f} ms")
    try:
        h = requests.get(f"{url}/api/health", timeout=5).json()
        print("cache hit rates:", {k: v["hitRate"] for k, v in h["caches"].items()})
    except Exception:
        pass


if __name__ == "__main__":
    main()
