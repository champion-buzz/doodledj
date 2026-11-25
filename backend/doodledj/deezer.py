"""Deezer public search API client (no API key needed) with caching and parallel queries."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

from .cache import TTLCache

log = logging.getLogger(__name__)


class DeezerClient:
    def __init__(self, base_url: str = "https://api.deezer.com", timeout: float = 4.0,
                 cache: TTLCache | None = None, max_workers: int = 8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache = cache or TTLCache(maxsize=2048, ttl=3600)
        self.session = requests.Session()
        # keep-alive connection pool shared by all request threads
        self.session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=32))
        self.session.mount("http://", HTTPAdapter(pool_connections=4, pool_maxsize=32))
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="deezer")

    def search(self, query: str, limit: int = 25) -> list[dict]:
        key = (query.lower(), limit)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            r = self.session.get(f"{self.base_url}/search", params={"q": query, "limit": limit},
                                 timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            tracks = [self._slim(t) for t in payload.get("data", []) if t.get("readable", True)]
        except Exception as e:
            log.warning("Deezer search failed for %r: %s", query, e)
            return []  # don't cache failures
        self.cache.set(key, tracks)
        return tracks

    def playlist(self, queries: list[str], size: int = 12) -> list[dict]:
        """Runs queries in parallel and interleaves results, deduping tracks and spreading artists."""
        results = list(self.pool.map(self.search, queries))
        out: list[dict] = []
        seen_ids: set[int] = set()
        artist_count: dict[str, int] = {}
        for rank in range(max((len(r) for r in results), default=0)):
            for tracks in results:
                if rank >= len(tracks) or len(out) >= size:
                    continue
                t = tracks[rank]
                if t["id"] in seen_ids or artist_count.get(t["artist"], 0) >= 2:
                    continue
                seen_ids.add(t["id"])
                artist_count[t["artist"]] = artist_count.get(t["artist"], 0) + 1
                out.append(t)
        return out

    @staticmethod
    def _slim(t: dict) -> dict:
        album = t.get("album") or {}
        artist = t.get("artist") or {}
        return {
            "id": t.get("id"),
            "title": t.get("title_short") or t.get("title"),
            "artist": artist.get("name", "Unknown"),
            "album": album.get("title"),
            "cover": album.get("cover_medium"),
            "preview": t.get("preview"),
            "link": t.get("link"),
            "duration": t.get("duration"),
        }
