from __future__ import annotations

import pytest

from app.services import projects


def test_source_provider_classification():
    assert projects.classify_source_url("https://www.youtube.com/watch?v=x") == "youtube"
    assert projects.classify_source_url("https://youtu.be/x") == "youtube"
    assert projects.classify_source_url("https://www.twitch.tv/channel/videos/1") == "twitch"
    assert projects.classify_source_url("https://kick.com/test") == "kick"
    assert projects.classify_source_url("https://drive.google.com/file/d/abc/view") == "gdrive"
    assert projects.classify_source_url("https://example.com/video.mp4") == "url"


def test_upload_validation_accepts_only_initial_video_formats():
    for name in ("x.mp4", "x.MOV", "x.mkv", "x.avi"):
        assert projects.validate_upload_filename(name) is True
    assert projects.validate_upload_filename("x.exe") is False
    assert projects.validate_upload_filename("x.webm") is False


def test_normalize_project_defaults_has_v2_style_fields():
    settings = projects.normalize_project_settings({
        "prompt": "cortes polêmicos",
        "layout_preset_id": "split",
        "caption_preset_id": "green-fresh",
        "caption_font": "Bangers",
        "aspect_ratio": "9:16",
        "emojis": "on",
        "start_range": -20,
        "end_range": 999,
        "source_duration": 300,
    })
    assert settings["prompt"] == "cortes polêmicos"
    assert settings["layout_preset_id"] == "split"
    assert settings["caption_preset_id"] == "green-fresh"
    assert settings["caption_font"] == "Bangers"
    assert settings["aspect_ratio"] == "9:16"
    assert settings["emojis"] is True
    assert settings["start_range"] == 0
    assert settings["end_range"] == 300


def test_invalid_layout_and_caption_fall_back():
    settings = projects.normalize_project_settings({"layout_preset_id": "wat", "caption_preset_id": "wat"})
    assert settings["layout_preset_id"] == "auto"
    assert settings["caption_preset_id"] == "green-fresh"

def test_remote_provider_detection_for_background_job():
    for value in ("youtube", "twitch", "kick", "gdrive", "url"):
        assert projects.is_remote_source_type(value) is True
    assert projects.is_remote_source_type("upload") is False
