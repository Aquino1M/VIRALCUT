from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui21.db")
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'v21@test.com','password':'abcdef'})
    return client


def test_new_project_uses_visual_layout_radio_cards(monkeypatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)
    html = client.get('/projects/new').text
    assert 'class="project-layout-picker"' in html
    assert 'name="layout_preset_id"' in html
    assert 'type="radio"' in html
    assert 'Choquei + Movimento' in html
    assert 'Podcast Dinâmico' in html
    assert '<select name="layout_preset_id"' not in html


def test_editor_face_tracking_is_read_only_and_always_on(monkeypatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)
    user = db.fetchone("SELECT id FROM users WHERE email='v21@test.com'")
    now = db.now_iso(); src=tmp_path/'s.mp4'; src.write_bytes(b'x'); clean=tmp_path/'c.mp4'; clean.write_bytes(b'c')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,settings_json,tracking_summary_json,created_at,updated_at) VALUES('p1',?,'P','upload',?,'smart','{}','{}',?,?)", (user['id'],str(src),now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,clean_path,video_path,created_at) VALUES('c1','p1','C',0,10,?,?,?)", (str(clean),str(clean),now))
    html = client.get('/clips/c1/edit').text
    assert 'id="faceTrackingStatus"' in html
    assert 'Face tracking ativo' in html
    assert 'id="faceTracking"' not in html
    assert 'value="off"' not in html


def test_editor_js_loads_tracking_summary_and_knows_new_layout_shapes():
    js = Path('app/static/editor.js').read_text(encoding='utf-8')
    assert '/tracking' in js
    assert 'faceTrackingStatus' in js
    for layout_id in ('podcast-dynamic','choquei-movimento','header-news','story-documentary'):
        assert layout_id in js
