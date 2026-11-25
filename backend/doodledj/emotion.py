"""Sketch -> emotion model.

Maps the visual and motion features of a drawing onto the valence/arousal plane
(Russell's circumplex model of affect), then onto a mood.

* Color: Valdez & Mehrabian (1994) found pleasure ~ 0.69*brightness + 0.22*saturation
  and arousal ~ -0.31*brightness + 0.60*saturation; warm hues read as more arousing,
  yellows/greens as more pleasant, saturated reds and dark palettes as less pleasant.
* Motion: fast, jagged, dense strokes read as energetic/tense; slow, smooth, sparse
  strokes as calm.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field

MOODS: dict[str, dict] = {
    "euphoric": {
        "emoji": "🤩",
        "description": "Bright, fast and bursting with energy",
        "queries": ["dance party hits", "upbeat edm", "feel good pop"],
        "genres": ["Dance", "Pop", "Electro"],
    },
    "happy": {
        "emoji": "😊",
        "description": "Warm, light and optimistic",
        "queries": ["happy pop", "sunny indie", "good vibes"],
        "genres": ["Pop", "Indie", "Funk"],
    },
    "calm": {
        "emoji": "😌",
        "description": "Soft, slow and peaceful",
        "queries": ["chill acoustic", "lofi beats", "peaceful piano"],
        "genres": ["Acoustic", "Lo-fi", "Ambient"],
    },
    "dreamy": {
        "emoji": "🌙",
        "description": "Hazy, floating and introspective",
        "queries": ["dream pop", "ambient chill", "shoegaze"],
        "genres": ["Dream pop", "Ambient", "Electronic"],
    },
    "melancholic": {
        "emoji": "🌧️",
        "description": "Dark, slow and reflective",
        "queries": ["sad songs", "melancholy piano", "rainy day indie"],
        "genres": ["Indie folk", "Piano", "Singer-songwriter"],
    },
    "tense": {
        "emoji": "😬",
        "description": "Dark, jagged and restless",
        "queries": ["dark electronic", "intense soundtrack", "industrial"],
        "genres": ["Electronic", "Soundtrack", "Alternative"],
    },
    "angry": {
        "emoji": "😤",
        "description": "Hot, chaotic and aggressive",
        "queries": ["hard rock", "heavy metal", "aggressive rap"],
        "genres": ["Rock", "Metal", "Hip-hop"],
    },
}


@dataclass
class SketchFeatures:
    """Features the frontend extracts from the canvas."""

    colors: list[tuple[str, float]] = field(default_factory=list)  # (hex, share of ink)
    stroke_count: int = 0
    avg_speed: float = 0.0  # px per ms
    jaggedness: float = 0.0  # 0 smooth .. 1 zig-zag
    coverage: float = 0.0  # 0..1 of canvas inked
    avg_width: float = 4.0  # brush size px
    duration_ms: float = 0.0

    @staticmethod
    def from_json(data: dict) -> "SketchFeatures":
        def num(key, lo, hi, default=0.0):
            v = data.get(key, default)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or math.isnan(v):
                raise ValueError(f"'{key}' must be a number")
            return float(min(max(v, lo), hi))

        colors = []
        raw = data.get("colors", [])
        if not isinstance(raw, list) or len(raw) > 32:
            raise ValueError("'colors' must be a list of at most 32 items")
        for c in raw:
            if not isinstance(c, dict):
                raise ValueError("each color must be an object {hex, weight}")
            hx = str(c.get("hex", ""))
            if not (len(hx) == 7 and hx[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in hx[1:])):
                raise ValueError(f"invalid color hex {hx!r}")
            w = c.get("weight", 0)
            if not isinstance(w, (int, float)) or w < 0:
                raise ValueError("color weight must be a non-negative number")
            colors.append((hx.lower(), float(w)))
        return SketchFeatures(
            colors=colors,
            stroke_count=int(num("strokeCount", 0, 10_000)),
            avg_speed=num("avgSpeed", 0, 20),
            jaggedness=num("jaggedness", 0, 1),
            coverage=num("coverage", 0, 1),
            avg_width=num("avgWidth", 1, 100, 4),
            duration_ms=num("durationMs", 0, 3_600_000),
        )

    def cache_key(self) -> tuple:
        """Coarse fingerprint so near-identical sketches share cached results."""
        top = tuple(sorted(((h, round(w, 1)) for h, w in self.colors), key=lambda x: -x[1])[:3])
        return (
            top,
            min(self.stroke_count // 5, 10),
            round(self.avg_speed, 1),
            round(self.jaggedness, 1),
            round(self.coverage, 2),
        )


@dataclass
class EmotionResult:
    mood: str
    valence: float  # -1..1
    arousal: float  # -1..1
    confidence: float  # 0..1
    signals: dict

    def to_dict(self) -> dict:
        m = MOODS[self.mood]
        return {
            "label": self.mood,
            "emoji": m["emoji"],
            "description": m["description"],
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
        }


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def color_affect(colors: list[tuple[str, float]]) -> tuple[float, float, dict]:
    """Weighted valence/arousal contribution of the palette, each in -1..1."""
    total = sum(w for _, w in colors)
    if total <= 0:
        return 0.0, 0.0, {"brightness": None, "saturation": None, "warmth": None}
    v = a = bright = sat = warm = 0.0
    for hx, w in colors:
        r, g, b = (int(hx[i : i + 2], 16) / 255 for i in (1, 3, 5))
        h, light, s = colorsys.rgb_to_hls(r, g, b)
        brightness = max(r, g, b)
        share = w / total
        # Valdez & Mehrabian coefficients, re-centred so mid grey is ~neutral
        pleasure = 0.69 * brightness + 0.22 * s - 0.5
        arousal = -0.31 * brightness + 0.60 * s
        deg = h * 360
        # warmth: +1 at red/orange, -1 at blue/cyan
        warmth = math.cos(math.radians(deg - 30)) * s
        # yellow/green hues read as pleasant; saturated reds read as hostile/alarming
        if 40 <= deg <= 160 and s > 0.25:
            pleasure += 0.15
        elif (deg < 20 or deg > 335) and s > 0.4:
            pleasure -= 0.3
        v += share * pleasure
        a += share * (arousal + 0.35 * warmth - 0.1)
        bright += share * brightness
        sat += share * s
        warm += share * warmth
    signals = {"brightness": round(bright, 3), "saturation": round(sat, 3), "warmth": round(warm, 3)}
    return _clamp(v * 1.6), _clamp(a * 1.4), signals


def motion_affect(f: SketchFeatures) -> tuple[float, float]:
    speed = _clamp(math.tanh(f.avg_speed / 1.2) * 2 - 1)  # ~0.6 px/ms is "neutral"
    density = _clamp(math.tanh(f.stroke_count / 25) * 2 - 1)
    coverage = _clamp(f.coverage * 4 - 1)
    jag = f.jaggedness * 2 - 1
    arousal = 0.45 * speed + 0.25 * jag + 0.15 * density + 0.15 * coverage
    valence = -0.35 * jag + 0.1 * (1 - abs(speed))
    return _clamp(valence), _clamp(arousal)


def classify(valence: float, arousal: float, warmth: float | None) -> str:
    if abs(valence) < 0.15 and abs(arousal) < 0.15:
        return "dreamy"
    if valence >= 0:
        if arousal >= 0.45:
            return "euphoric"
        if arousal >= 0.0:
            return "happy"
        return "calm" if valence > 0.25 or arousal < -0.3 else "dreamy"
    if arousal >= 0.3:
        return "angry" if (warmth or 0) > 0.15 else "tense"
    if arousal >= 0.0:
        return "tense"
    return "melancholic"


def analyze(f: SketchFeatures) -> EmotionResult:
    cv, ca, csig = color_affect(f.colors)
    mv, ma = motion_affect(f)
    has_color = bool(f.colors)
    # colour carries most of the valence signal; motion most of the arousal
    valence = _clamp((0.6 * cv + 0.4 * mv) if has_color else mv)
    arousal = _clamp((0.45 * ca + 0.55 * ma) if has_color else ma)
    mood = classify(valence, arousal, csig.get("warmth"))
    # confidence grows with distance from the origin and with how much was drawn
    amount = min(1.0, f.stroke_count / 8)
    confidence = _clamp(math.hypot(valence, arousal) / 1.0, 0, 1) * (0.4 + 0.6 * amount)
    signals = {
        **csig,
        "speed": round(f.avg_speed, 3),
        "jaggedness": round(f.jaggedness, 3),
        "strokes": f.stroke_count,
        "coverage": round(f.coverage, 3),
        "colorValence": round(cv, 3),
        "colorArousal": round(ca, 3),
        "motionValence": round(mv, 3),
        "motionArousal": round(ma, 3),
    }
    return EmotionResult(mood, valence, arousal, confidence, signals)
