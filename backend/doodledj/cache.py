"""Small thread-safe LRU cache with per-entry TTL."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class TTLCache:
    def __init__(self, maxsize: int = 1024, ttl: float = 3600.0, clock: Callable[[], float] = time.monotonic):
        self.maxsize = maxsize
        self.ttl = ttl
        self.clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None or item[0] < self.clock():
                if item is not None:
                    del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = (self.clock() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {"size": len(self._data), "hits": self.hits, "misses": self.misses,
                    "hitRate": round(self.hits / total, 3) if total else 0.0}
