from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def _seed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "clean.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "clean@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='clean@test.com'")
    now = db.now_iso()
    source = tmp_path / "source.mp4"; source.write_bytes(b"source")
    final = tmp_path / "final.mp4"; final.write_bytes(b"burned-final")
    clean = tmp_path / "clean.mp4"; clean.write_bytes(b"clean-proxy")
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_path,mode,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload',?,'smart',?,?,?)",
        (user["id"], str(source), json.dumps({"layout_preset_id": "single"}), now, now),
    )
    db.execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,video_path,clean_path,created_at) VALUES('c1','p1','Clip',0,10,?,?,?)",
        (str(final), str(clean), now),
    )
    return client, clean, final, source


def test_editor_uses_clean_media_endpoint(monkeypatch, tmp_path: Path):
    client, *_ = _seed(monkeypatch, tmp_path)
    html = client.get("/clips/c1/edit").text
    assert 'src="/clips/c1/editor-proxy?v=42-robust"' in html
    assert 'src="/clips/c1/video"' not in html


def test_clean_video_endpoint_prefers_clean_path(monkeypatch, tmp_path: Path):
    client, clean, final, _ = _seed(monkeypatch, tmp_path)
    response = client.get("/clips/c1/clean-video")
    assert response.status_code == 200
    assert response.content == clean.read_bytes()
    assert response.content != final.read_bytes()


def test_clean_video_legacy_clip_lazily_generates_clean_media(monkeypatch, tmp_path: Path):
    client, clean, _, source = _seed(monkeypatch, tmp_path)
    clean.unlink()
    db.execute("UPDATE clips SET clean_path=NULL WHERE id='c1'")
    generated = tmp_path / "legacy-clean.mp4"

    def fake_render(source_path, out_path, start, end, edit_state, **kwargs):
        assert Path(source_path) == source
        assert edit_state["tracks"]["captions"]["visible"] is False
        assert edit_state["overlays"] == []
        generated.write_bytes(b"legacy-clean")
        Path(out_path).write_bytes(generated.read_bytes())
        return {"path": str(out_path), "encoder": "libx264", "resolution": "1080x1920"}

    monkeypatch.setattr(main, "render_edited_clip", fake_render)
    response = client.get("/clips/c1/clean-video")
    assert response.status_code == 200
    assert response.content == b"legacy-clean"
    row = db.fetchone("SELECT clean_path FROM clips WHERE id='c1'")
    assert row["clean_path"] and Path(row["clean_path"]).exists()


def test_editor_js_hides_live_overlays_when_showing_burned_preview():
    js = Path("app/static/editor.js").read_text(encoding="utf-8")
    assert "setRenderedPreviewMode" in js
    assert "caption.style.visibility" in js
