import threading
import time

import pytest
from werkzeug.serving import make_server
from flask import Flask, jsonify, request

from doodledj.app import create_app
from doodledj.deezer import DeezerClient
from doodledj.llm import LLMClient
from doodledj.storage import MemoryStorage


def fake_deezer_app(calls):
    """Mimics GET https://api.deezer.com/search."""
    app = Flask("fake-deezer")

    @app.get("/search")
    def search():
        q = request.args["q"]
        calls.append(q)
        data = [{
            "id": abs(hash((q, i))) % 10**9,
            "title": f"{q} song {i}",
            "readable": True,
            "preview": f"https://cdn.example/{i}.mp3",
            "link": "https://www.deezer.com/track/1",
            "duration": 180,
            "artist": {"name": f"{q} artist {i % 4}"},
            "album": {"title": "Album", "cover_medium": "https://cdn.example/c.jpg"},
        } for i in range(10)]
        return jsonify({"data": data, "total": 10})

    return app


@pytest.fixture(scope="module")
def deezer_server():
    calls = []
    srv = make_server("127.0.0.1", 0, fake_deezer_app(calls), threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", calls
    srv.shutdown()


@pytest.fixture
def client(deezer_server):
    url, calls = deezer_server
    calls.clear()
    storage = MemoryStorage()
    app = create_app({"DEEZER_CLIENT": DeezerClient(url), "LLM_CLIENT": LLMClient(None, "none"), "STORAGE": storage})
    app.testing = True
    return app.test_client(), calls, storage


HAPPY = {"colors": [{"hex": "#ffd400", "weight": 0.7}, {"hex": "#ff8c00", "weight": 0.3}],
         "strokeCount": 30, "avgSpeed": 2.0, "jaggedness": 0.35, "coverage": 0.2, "durationMs": 9000}


def test_playlist_end_to_end(client):
    c, calls, storage = client
    r = c.post("/api/playlist", json={"features": HAPPY, "sessionId": "session-abc123"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["mood"]["label"] in {"euphoric", "happy"}
    assert body["mood"]["source"] == "heuristic"
    assert len(body["tracks"]) == 12
    assert len({t["id"] for t in body["tracks"]}) == 12  # no duplicates
    artists = [t["artist"] for t in body["tracks"]]
    assert max(artists.count(a) for a in artists) <= 2  # artist diversity
    assert len(calls) == 3  # one Deezer call per query, run in parallel

    time.sleep(0.1)  # history is written in the background
    h = c.get("/api/history/session-abc123").get_json()
    assert h["items"][0]["mood"]["label"] == body["mood"]["label"]


def test_repeat_sketch_is_served_from_cache(client):
    c, calls, _ = client
    c.post("/api/playlist", json={"features": HAPPY})
    n = len(calls)
    r = c.post("/api/playlist", json={"features": HAPPY})
    assert len(calls) == n  # no new upstream calls
    assert r.get_json()["timings"]["totalMs"] < 50


def test_validation_errors(client):
    c, _, _ = client
    assert c.post("/api/playlist", json={}).status_code == 400
    assert c.post("/api/playlist", data="nope", content_type="text/plain").status_code == 400
    assert c.post("/api/playlist", json={"features": {"colors": [{"hex": "blue"}]}}).status_code == 400
    assert c.post("/api/playlist", json={"features": HAPPY, "sessionId": "../../etc"}).status_code == 400
    assert c.get("/api/history/bad id").status_code in (400, 404)


def test_llm_refinement_is_used_when_available(deezer_server):
    url, _ = deezer_server

    class FakeLLM:
        enabled = True

        def refine(self, emotion):
            return {"mood": "dreamy", "vibe": "neon haze at 2am", "queries": ["synthwave", "dream pop"]}

    app = create_app({"DEEZER_CLIENT": DeezerClient(url), "LLM_CLIENT": FakeLLM(), "STORAGE": MemoryStorage()})
    body = app.test_client().post("/api/playlist", json={"features": HAPPY}).get_json()
    assert body["mood"]["source"] == "llm"
    assert body["mood"]["label"] == "dreamy"
    assert body["mood"]["description"] == "neon haze at 2am"
    assert body["queries"] == ["synthwave", "dream pop"]


def test_llm_failure_falls_back_to_heuristic(deezer_server):
    url, _ = deezer_server
    llm = LLMClient("http://127.0.0.1:9", "model", timeout=0.3)  # nothing listens on port 9
    app = create_app({"DEEZER_CLIENT": DeezerClient(url), "LLM_CLIENT": llm, "STORAGE": MemoryStorage()})
    body = app.test_client().post("/api/playlist", json={"features": HAPPY}).get_json()
    assert body["mood"]["source"] == "heuristic"
    assert body["tracks"]


def test_deezer_outage_returns_empty_playlist_not_500():
    app = create_app({"DEEZER_CLIENT": DeezerClient("http://127.0.0.1:9", timeout=0.3),
                      "LLM_CLIENT": LLMClient(None, "x"), "STORAGE": MemoryStorage()})
    r = app.test_client().post("/api/playlist", json={"features": HAPPY})
    assert r.status_code == 200 and r.get_json()["tracks"] == []


def test_health(client):
    c, _, _ = client
    h = c.get("/api/health").get_json()
    assert h["ok"] and h["llm"]["enabled"] is False
