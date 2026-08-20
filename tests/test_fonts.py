from __future__ import annotations

import json
from pathlib import Path

from app.services import fonts


def test_font_registry_contains_creator_fonts():
    names = {f["family"] for f in fonts.list_fonts()}
    assert {"Bangers", "Anton", "Montserrat", "Bebas Neue", "Oswald", "Roboto Condensed", "Archivo Black", "League Spartan", "Permanent Marker"} <= names


def test_resolve_font_prefers_local_download(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path)
    path = tmp_path / "Bangers-Regular.ttf"
    path.write_bytes(b"font")
    resolved = fonts.resolve_font("Bangers")
    assert resolved["family"] == "Bangers"
    assert resolved["path"] == str(path)
    assert resolved["source"] == "local"


def test_resolve_unknown_font_falls_back(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path)
    monkeypatch.setattr(fonts, "_windows_font_candidates", lambda family: [])
    resolved = fonts.resolve_font("Made Up Font")
    assert resolved["family"] in {"Arial", "DejaVu Sans"}
    assert resolved["fallback"] is True


def test_write_metadata_is_idempotent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path)
    first = fonts.write_font_metadata()
    second = fonts.write_font_metadata()
    assert first == second
    data = json.loads((tmp_path / "fonts.json").read_text(encoding="utf-8"))
    assert any(f["family"] == "Bangers" for f in data["fonts"])
