from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def test_editor_page_exposes_visual_presets_layouts_timeline_and_export(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "editor@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='editor@test.com'")
    now = db.now_iso()
    dummy = tmp_path / "clip.mp4"; dummy.write_bytes(b"fake")
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload','smart',?,?,?)", (user["id"], json.dumps({"caption_preset_id":"green-fresh","layout_preset_id":"auto"}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,video_path,created_at) VALUES('c1','p1','Teste',0,30,?,?)", (str(dummy), now))
    r = client.get('/clips/c1/edit')
    assert r.status_code == 200
    html = r.text
    for text in ('Estilos de legenda', 'Layouts de vídeo', 'Posição vertical', 'Brand Kit', 'Baixar MP4', 'multiTrackTimeline'):
        assert text in html
    assert 'captionTimeline' not in html
    assert '/static/editor.js' in html
    assert 'Renderizar preview' not in html
    assert 'Render final' not in html


def test_editor_exposes_advanced_caption_layout_and_layer_controls(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "advanced.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "advanced@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='advanced@test.com'")
    now = db.now_iso(); dummy=tmp_path/'clip.mp4'; dummy.write_bytes(b'fake')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p2',?,'Demo','upload','smart','{}',?,?)", (user['id'],now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,video_path,created_at) VALUES('c2','p2','Teste',0,30,?,?)",(str(dummy),now))
    html=client.get('/clips/c2/edit').text
    for control_id in ('maxWidth','shadowColor','shadowDepth','backgroundColor','backgroundOpacity','backgroundRadius','minWordDurationMs','animationDuration','scaleAmount','popScalePeak','popFontSizeBoost','popDurationMs','fadeInMs','fadeOutMs','resetLayout','resetOverlays'):
        assert f'id="{control_id}"' in html
    js=client.get('/static/editor.js').text
    assert 'layoutControls' in js
    assert 'dragOverlay' in js
