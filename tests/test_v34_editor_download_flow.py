from __future__ import annotations

from pathlib import Path

from app.services import proxy_media

ROOT = Path(__file__).resolve().parents[1]


def test_editor_proxy_preserves_source_aspect_for_browser_crop(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    out = tmp_path / "proxy.mp4"
    captured: dict[str, object] = {}

    monkeypatch.setattr(proxy_media, "proxy_cache_path", lambda *args, **kwargs: out)
    monkeypatch.setattr(proxy_media, "source_proxy_geometry", lambda _source: (854, 480))

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out.write_bytes(b"proxy-data")
        return Result()

    monkeypatch.setattr(proxy_media.subprocess, "run", fake_run)
    monkeypatch.setattr(proxy_media, "valid_proxy", lambda path: path.exists())

    proxy_media.ensure_editor_proxy("clip-1", source, 0, 10, "9:16")

    cmd = captured["cmd"]
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=854:480" in vf
    assert "scale=270:480" not in vf
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"


def test_editor_has_only_automatic_download_action():
    html = (ROOT / "app/templates/editor.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/editor.js").read_text(encoding="utf-8")

    assert "Renderizar preview" not in html
    assert "Render final" not in html
    assert 'id="downloadFinal"' in html
    assert 'id="downloadFinal" class="btn primary"' in html
    assert 'href="/clips/{{clip.id}}/download"' not in html

    assert "renderAndDownload" in js
    assert "final-render" in js
    assert "triggerDownload" in js
    assert "downloadFinal" in js
