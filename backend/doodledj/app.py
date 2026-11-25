"""Flask API for DoodleDJ."""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from .cache import TTLCache
from .deezer import DeezerClient
from .emotion import MOODS, SketchFeatures, analyze
from .llm import LLMClient
from .storage import MemoryStorage, MongoStorage

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def create_app(config: dict | None = None) -> Flask:
    cfg = {
        "DEEZER_URL": os.getenv("DEEZER_URL", "https://api.deezer.com"),
        "LLM_BASE_URL": os.getenv("LLM_BASE_URL", ""),  # e.g. http://localhost:11434/v1 (Ollama)
        "LLM_MODEL": os.getenv("LLM_MODEL", "llama3.2:3b"),
        "LLM_API_KEY": os.getenv("LLM_API_KEY", ""),
        "LLM_TIMEOUT": float(os.getenv("LLM_TIMEOUT", "2.5")),
        "MONGO_URI": os.getenv("MONGO_URI", ""),
        "PLAYLIST_SIZE": int(os.getenv("PLAYLIST_SIZE", "12")),
        "STATIC_DIR": os.getenv("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")),
        **(config or {}),
    }
    app = Flask(__name__, static_folder=None)
    app.config.update(cfg)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*")}})
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    deezer = cfg.get("DEEZER_CLIENT") or DeezerClient(cfg["DEEZER_URL"])
    llm = cfg.get("LLM_CLIENT") or LLMClient(cfg["LLM_BASE_URL"] or None, cfg["LLM_MODEL"],
                                              cfg["LLM_API_KEY"] or None, cfg["LLM_TIMEOUT"])
    storage = cfg.get("STORAGE") or (MongoStorage(cfg["MONGO_URI"]) if cfg["MONGO_URI"] else MemoryStorage())
    mood_cache = TTLCache(maxsize=4096, ttl=600)  # sketch fingerprint -> mood + queries
    background = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg")
    app.extensions["doodledj"] = {"deezer": deezer, "llm": llm, "storage": storage, "mood_cache": mood_cache}

    def error(status: int, message: str):
        return jsonify({"error": message}), status

    @app.post("/api/playlist")
    def playlist():
        t0 = time.perf_counter()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("features"), dict):
            return error(400, "JSON body with a 'features' object is required")
        session_id = body.get("sessionId")
        if session_id is not None and not (isinstance(session_id, str) and SESSION_RE.match(session_id)):
            return error(400, "invalid sessionId")
        try:
            features = SketchFeatures.from_json(body["features"])
        except ValueError as e:
            return error(400, str(e))

        # 1) emotion recognition (+ optional LLM refinement), cached per sketch fingerprint
        key = features.cache_key()
        cached = mood_cache.get(key)
        if cached is None:
            emotion = analyze(features)
            mood = emotion.to_dict()
            queries = list(MOODS[emotion.mood]["queries"])
            mood["source"] = "heuristic"
            refined = llm.refine(emotion)
            if refined:
                mood.update(label=refined["mood"], emoji=MOODS[refined["mood"]]["emoji"],
                            description=refined["vibe"], source="llm")
                queries = refined["queries"]
            cached = (mood, queries)
            mood_cache.set(key, cached)
        mood, queries = cached
        t1 = time.perf_counter()

        # 2) music lookup (parallel Deezer queries, cached per query)
        tracks = deezer.playlist(queries, size=app.config["PLAYLIST_SIZE"])
        t2 = time.perf_counter()

        result = {
            "mood": mood,
            "queries": queries,
            "genres": MOODS[mood["label"]]["genres"],
            "tracks": tracks,
            "timings": {
                "analyzeMs": round((t1 - t0) * 1000, 1),
                "musicMs": round((t2 - t1) * 1000, 1),
                "totalMs": round((t2 - t0) * 1000, 1),
            },
        }
        if session_id:
            doc = {"mood": {k: mood[k] for k in ("label", "emoji", "valence", "arousal", "source")},
                   "trackIds": [t["id"] for t in tracks]}
            background.submit(storage.save, session_id, doc)  # keep DB writes off the hot path
        return jsonify(result)

    @app.get("/api/history/<session_id>")
    def history(session_id: str):
        if not SESSION_RE.match(session_id):
            return error(400, "invalid sessionId")
        return jsonify({"items": storage.history(session_id)})

    @app.get("/api/moods")
    def moods():
        return jsonify({"moods": {k: {"emoji": v["emoji"], "description": v["description"], "genres": v["genres"]}
                                  for k, v in MOODS.items()}})

    @app.get("/api/health")
    def health():
        return jsonify({
            "ok": True,
            "llm": {"enabled": llm.enabled, "model": cfg["LLM_MODEL"] if llm.enabled else None},
            "storage": type(storage).__name__,
            "caches": {"moods": mood_cache.stats(), "deezer": deezer.cache.stats()},
        })

    # Serve the built React app (frontend/dist) in production
    @app.get("/")
    @app.get("/<path:path>")
    def spa(path: str = "index.html"):
        static_dir = os.path.abspath(app.config["STATIC_DIR"])
        if path.startswith("api/"):
            return error(404, "not found")
        if not os.path.isdir(static_dir):
            return error(404, "frontend not built: run `npm run build` in frontend/")
        if path != "index.html" and os.path.isfile(os.path.join(static_dir, path)):
            return send_from_directory(static_dir, path)
        return send_from_directory(static_dir, "index.html")

    @app.errorhandler(413)
    def too_large(_):
        return error(413, "request too large")

    return app
