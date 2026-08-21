from pathlib import Path

from app.services import preview, proxy_media


ROOT = Path(__file__).resolve().parents[1]


def test_proxy_discards_bad_cache_and_recovers_on_cpu_fallback(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    out = tmp_path / "proxy.mp4"
    out.write_bytes(b"corrupt" * 1024)
    calls = []

    monkeypatch.setattr(proxy_media, "proxy_cache_path", lambda *args, **kwargs: out)
    monkeypatch.setattr(proxy_media, "source_proxy_geometry", lambda *args: (854, 480))
    monkeypatch.setattr(proxy_media, "valid_proxy", lambda path: path.exists() and path.read_bytes().startswith(b"valid"))

    def run(cmd, timeout=180):
        calls.append(cmd)
        if len(calls) == 2:
            out.write_bytes(b"valid" + b"x" * 8192)
            return 0, ""
        return 1, "timestamp error"

    monkeypatch.setattr(proxy_media, "_run_attempt", run)
    assert proxy_media.ensure_editor_proxy("c1", source, 0, 8, "9:16") == out
    assert len(calls) == 2
    assert all("libx264" in cmd for cmd in calls)


def test_editor_hotfix_keeps_canvas_safe_and_organizes_caption_layout_tabs():
    html = (ROOT / "app/templates/editor.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/style.css").read_text(encoding="utf-8")
    js = (ROOT / "app/static/editor.js").read_text(encoding="utf-8")
    assert 'preload="auto"' in html
    assert 'style="display:none"' in html
    assert 'id="stylePickerTabs"' in html
    assert 'data-picker-tab="captions"' in html
    assert 'data-picker-tab="layouts"' in html
    assert ".style-picker-panel{display:none}" in css
    assert "&retry=1" in js
    assert "saveAndPrimeProjectPreview" in js
    assert "rebuildCaptions" in html
    assert "captions/rebuild" in js


def test_project_preview_has_a_separate_full_clip_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(preview, "PREVIEW_DIR", tmp_path)
    state = {"editor": {"revision": 2}, "timeline": {"tracks": []}}
    assert preview.project_preview_path("c1", state) != preview.preview_path("c1", state)


def test_editor_proxy_prefers_cloud_cpu_and_validates_download(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"; source.write_bytes(b"source")
    out = tmp_path / "proxy.mp4"
    monkeypatch.setattr(proxy_media, "proxy_cache_path", lambda *args, **kwargs: out)
    monkeypatch.setattr(proxy_media.cloud_client, "configured", lambda: True)
    monkeypatch.setattr(proxy_media.cloud_client, "health", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(proxy_media.cloud_client, "submit_task", lambda *args, **kwargs: "job-1")
    monkeypatch.setattr(proxy_media.cloud_client, "wait_job", lambda job_id: {"state": "done"})
    monkeypatch.setattr(proxy_media.cloud_client, "download_result_file", lambda job_id, target: Path(target).write_bytes(b"cloud-proxy") or Path(target))
    monkeypatch.setattr(proxy_media, "valid_proxy", lambda path: path.exists() and path.read_bytes() == b"cloud-proxy")
    assert proxy_media.ensure_editor_proxy("c1", source, 0, 8) == out
