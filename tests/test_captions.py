from __future__ import annotations

from pathlib import Path

from app.services import captions


def test_green_fresh_matches_reference_defaults():
    cfg = captions.resolve_caption_config("green-fresh")
    assert cfg["fontFamily"] == "Bangers"
    assert cfg["fontSize"] == 75
    assert cfg["textCase"] == "upper"
    assert cfg["primaryColor"] == "#ffffff"
    assert cfg["secondaryColor"] == "#76FF03"
    assert cfg["strokeWidth"] == 10
    assert cfg["wordsPerPage"] == 3
    assert cfg["pageDurationMs"] == 900
    assert cfg["animationType"] == "scaling-words"
    assert cfg["popScalePeak"] == 1.1


def test_caption_config_overrides_are_sanitized():
    cfg = captions.resolve_caption_config("green-fresh", {"fontSize": 500, "wordsPerPage": 0, "positionY": 3000, "strokeWidth": -3})
    assert cfg["fontSize"] == 180
    assert cfg["wordsPerPage"] == 1
    assert cfg["positionY"] == 1920
    assert cfg["strokeWidth"] == 0


def test_hex_to_ass_uses_bgr_order():
    assert captions.hex_to_ass("#76FF03") == "&H03FF76&"
    assert captions.hex_to_ass("#ffffff") == "&HFFFFFF&"


def test_ass_generation_preserves_portuguese_and_highlights_active_words(tmp_path: Path):
    cues = [
        {"start_time": 0.0, "end_time": 0.45, "text": "você", "word_index": 0},
        {"start_time": 0.45, "end_time": 0.9, "text": "não", "word_index": 1},
        {"start_time": 0.9, "end_time": 1.3, "text": "sabia", "word_index": 2},
        {"start_time": 1.3, "end_time": 1.8, "text": "disso?", "word_index": 3},
    ]
    out = tmp_path / "captions.ass"
    captions.build_ass(cues, captions.resolve_caption_config("green-fresh"), out)
    text = out.read_text(encoding="utf-8")
    assert "VOCÊ" in text
    assert "NÃO" in text
    assert "Dialogue:" in text
    assert "&H03FF76&" in text
    assert "\\pos(540," in text


def test_preset_registry_has_creator_and_accessibility_styles():
    ids = {p["id"] for p in captions.list_caption_presets()}
    assert {"green-fresh", "rainbow-fun", "cariani", "mrbeast", "podcast-bold", "minimal-clean", "karaoke", "word-pop", "classic", "neon", "breaking-news", "clean-box"} <= ids
