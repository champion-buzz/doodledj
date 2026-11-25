"""Optional open-source LLM layer.

Talks to any OpenAI-compatible chat endpoint, so it works with locally hosted open
models through Ollama (http://localhost:11434/v1), vLLM, LM Studio, llama.cpp server,
or Hugging Face TGI. The LLM refines the heuristic mood into a short vibe description
and search keywords. If no endpoint is configured, or the call fails or is slow, the
app falls back to the heuristic result, so the LLM can never break or stall a request.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from .emotion import MOODS, EmotionResult

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are DoodleDJ, a music curator. You receive measurements of a user's sketch "
    "(colors, stroke speed, jaggedness, density) and a first-pass mood estimate on the "
    "valence/arousal plane. Reply with ONLY a JSON object of the form "
    '{"mood": one of %s, "vibe": "<= 12 words describing the vibe", '
    '"queries": [2-4 short music search queries, e.g. genre + mood words]}. '
    "No artist names you are unsure exist. No extra text."
) % json.dumps(sorted(MOODS))


class LLMClient:
    def __init__(self, base_url: str | None, model: str, api_key: str | None = None,
                 timeout: float = 2.5, session: requests.Session | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def refine(self, emotion: EmotionResult) -> dict | None:
        """Returns {"mood", "vibe", "queries"} or None on any failure."""
        if not self.enabled:
            return None
        user = json.dumps({"estimate": emotion.to_dict()})
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = self.session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "temperature": 0.4,
                    "max_tokens": 160,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            return parse_llm_json(text)
        except Exception as e:  # network error, timeout, bad JSON, unexpected shape
            log.warning("LLM refinement skipped: %s", e)
            return None


def parse_llm_json(text: str) -> dict | None:
    """Extracts and validates the JSON object from a model reply."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    mood = str(data.get("mood", "")).lower().strip()
    if mood not in MOODS:
        return None
    queries = [str(q).strip()[:60] for q in data.get("queries", []) if str(q).strip()][:4]
    if not queries:
        return None
    vibe = str(data.get("vibe", "")).strip()[:120] or MOODS[mood]["description"]
    return {"mood": mood, "vibe": vibe, "queries": queries}
