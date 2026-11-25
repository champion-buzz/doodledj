import pytest

from doodledj.emotion import SketchFeatures, analyze, classify
from doodledj.llm import parse_llm_json


def feats(**kw):
    base = dict(colors=[], stroke_count=12, avg_speed=0.6, jaggedness=0.3, coverage=0.15, duration_ms=8000)
    base.update(kw)
    return SketchFeatures(**base)


def test_bright_fast_warm_sketch_is_upbeat():
    r = analyze(feats(colors=[("#ffd400", 0.6), ("#ff7a00", 0.4)], avg_speed=2.2, jaggedness=0.4, stroke_count=40))
    assert r.valence > 0 and r.arousal > 0.3
    assert r.mood in {"euphoric", "happy"}


def test_slow_smooth_pastel_sketch_is_calm():
    r = analyze(feats(colors=[("#a8d8ea", 0.7), ("#cdeac0", 0.3)], avg_speed=0.15, jaggedness=0.05, stroke_count=6, coverage=0.05))
    assert r.arousal < 0
    assert r.mood in {"calm", "dreamy"}


def test_dark_slow_sketch_is_melancholic():
    r = analyze(feats(colors=[("#1b1f3b", 0.8), ("#3a3f5c", 0.2)], avg_speed=0.2, jaggedness=0.1, stroke_count=10))
    assert r.valence < 0 and r.arousal < 0
    assert r.mood == "melancholic"


def test_red_jagged_frantic_sketch_is_angry():
    r = analyze(feats(colors=[("#d00000", 0.8), ("#111111", 0.2)], avg_speed=3.0, jaggedness=0.95, stroke_count=60, coverage=0.4))
    assert r.mood == "angry"


def test_dark_blue_jagged_sketch_is_tense_not_angry():
    r = analyze(feats(colors=[("#0b1d51", 1.0)], avg_speed=2.5, jaggedness=0.9, stroke_count=50, coverage=0.3))
    assert r.mood == "tense"


def test_classify_center_is_dreamy():
    assert classify(0.05, -0.05, 0) == "dreamy"


def test_from_json_validates():
    f = SketchFeatures.from_json({"colors": [{"hex": "#FF0000", "weight": 1}], "strokeCount": 3, "avgSpeed": 99})
    assert f.colors == [("#ff0000", 1.0)] and f.avg_speed == 20  # clamped
    with pytest.raises(ValueError):
        SketchFeatures.from_json({"colors": [{"hex": "red", "weight": 1}]})
    with pytest.raises(ValueError):
        SketchFeatures.from_json({"avgSpeed": "fast"})
    with pytest.raises(ValueError):
        SketchFeatures.from_json({"colors": [{"hex": "#000000", "weight": 1}] * 33})


def test_parse_llm_json_accepts_wrapped_json_and_rejects_garbage():
    ok = parse_llm_json('Sure! {"mood": "Calm", "vibe": "sunday morning tea", "queries": ["lofi", "acoustic chill"]}')
    assert ok == {"mood": "calm", "vibe": "sunday morning tea", "queries": ["lofi", "acoustic chill"]}
    assert parse_llm_json('{"mood": "confused", "queries": ["x"]}') is None
    assert parse_llm_json('{"mood": "calm", "queries": []}') is None
    assert parse_llm_json("no json here") is None
