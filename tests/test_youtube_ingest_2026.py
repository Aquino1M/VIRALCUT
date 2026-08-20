from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.services import ingest


class FakeDownloadError(Exception):
    pass


def install_fake_ytdlp(monkeypatch, outcomes, captured):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            captured.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            outtmpl = self.opts["outtmpl"]
            path = Path(outtmpl.replace("%(ext)s", "mp4"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-video")
            return {"requested_downloads": [{"filepath": str(path)}]}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYoutubeDL
    fake_utils = types.ModuleType("yt_dlp.utils")
    fake_utils.DownloadError = FakeDownloadError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", fake_utils)


def test_youtube_download_enables_modern_js_support(monkeypatch, tmp_path):
    captured = []
    install_fake_ytdlp(monkeypatch, [object()], captured)
    monkeypatch.setattr(ingest.shutil, "which", lambda name: f"C:/fake/{name}.exe" if name == "deno" else None)

    result = ingest.ingest_url("https://www.youtube.com/watch?v=test", tmp_path)

    assert result.exists()
    assert "deno" in captured[0]["js_runtimes"]
    assert captured[0]["js_runtimes"]["deno"]["path"].endswith("deno.exe")
    assert "ejs:github" in captured[0]["remote_components"]


def test_youtube_403_retries_with_po_token_provider(monkeypatch, tmp_path):
    captured = []
    install_fake_ytdlp(monkeypatch, [FakeDownloadError("HTTP Error 403: Forbidden"), object()], captured)
    monkeypatch.setattr(ingest.shutil, "which", lambda name: f"C:/fake/{name}.exe" if name == "deno" else None)
    monkeypatch.setattr(ingest, "_detect_chromium_browser", lambda: Path("C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"))

    result = ingest.ingest_url("https://www.youtube.com/watch?v=test", tmp_path)

    assert result.exists()
    assert len(captured) == 2
    assert captured[1]["extractor_args"]["youtube"]["player_client"] == ["mweb"]
    assert captured[1]["extractor_args"]["youtubepot-wpc"]["browser_path"] == ["C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"]


def test_explicit_brave_cookie_fallback_is_only_used_after_403(monkeypatch, tmp_path):
    captured = []
    install_fake_ytdlp(
        monkeypatch,
        [
            FakeDownloadError("HTTP Error 403: Forbidden"),
            FakeDownloadError("HTTP Error 403: Forbidden"),
            object(),
        ],
        captured,
    )
    monkeypatch.setattr(ingest.shutil, "which", lambda name: f"C:/fake/{name}.exe" if name == "deno" else None)
    monkeypatch.setattr(ingest, "_detect_chromium_browser", lambda: None)

    result = ingest.ingest_url("https://www.youtube.com/watch?v=test", tmp_path, cookie_browser="brave")

    assert result.exists()
    assert "cookiesfrombrowser" not in captured[0]
    assert "cookiesfrombrowser" not in captured[1]
    assert captured[2]["cookiesfrombrowser"] == ("brave", None, None, None)
