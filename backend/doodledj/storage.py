"""Session history storage: MongoDB when MONGO_URI is set, otherwise in memory."""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime, timezone


class MemoryStorage:
    def __init__(self, per_session: int = 50):
        self._data: dict[str, deque] = defaultdict(lambda: deque(maxlen=per_session))
        self._lock = threading.Lock()

    def save(self, session_id: str, doc: dict) -> None:
        with self._lock:
            self._data[session_id].appendleft({**doc, "createdAt": datetime.now(timezone.utc).isoformat()})

    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._data.get(session_id, []))[:limit]

    def mood_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        with self._lock:
            for items in self._data.values():
                for d in items:
                    counts[d["mood"]["label"]] += 1
        return dict(counts)


class MongoStorage:
    def __init__(self, uri: str, db: str = "doodledj"):
        from pymongo import ASCENDING, DESCENDING, MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000, maxPoolSize=50)
        self.col = self.client[db]["sessions"]
        self.col.create_index([("sessionId", ASCENDING), ("createdAt", DESCENDING)])

    def save(self, session_id: str, doc: dict) -> None:
        self.col.insert_one({**doc, "sessionId": session_id, "createdAt": datetime.now(timezone.utc)})

    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self.col.find({"sessionId": session_id}, {"_id": 0, "sessionId": 0}).sort("createdAt", -1).limit(limit)
        return [{**r, "createdAt": r["createdAt"].isoformat()} for r in rows]

    def mood_counts(self) -> dict[str, int]:
        return {r["_id"]: r["n"] for r in self.col.aggregate([{"$group": {"_id": "$mood.label", "n": {"$sum": 1}}}])}
