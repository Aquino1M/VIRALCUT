from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient
from app import db, main


def setup(monkeypatch,tmp_path:Path):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'polish.db');db.init_db();client=TestClient(main.app)
    client.post('/register',data={'email':'polish@test.com','password':'abcdef'});u=db.fetchone("SELECT * FROM users WHERE email='polish@test.com'");now=db.now_iso()
    video=tmp_path/'c.mp4';video.write_bytes(b'x')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_value,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Projeto','youtube','https://youtube.com/watch?v=x','smart','done',100,'ok',?,?,?)",(u['id'],json.dumps({'caption_preset_id':'green-fresh','layout_preset_id':'auto','caption_font':'Bangers'}),now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,video_path,render_encoder,file_size,render_seconds,created_at) VALUES('c1','p1','Corte',0,30,9.5,?,'h264_amf',12345678,4.2,?)",(str(video),now))
    return client


def test_project_workspace_has_default_style_editor_and_technical_details(monkeypatch,tmp_path):
    client=setup(monkeypatch,tmp_path);r=client.get('/projects/p1');assert r.status_code==200
    assert 'id="projectDefaults"' in r.text
    assert 'id="saveProjectDefaults"' in r.text
    assert 'Informações técnicas' in r.text
    assert 'h264_amf' in r.text
    assert 'Selecionar todos' in r.text
    assert 'Copiar link' in r.text
    assert '/projects/p1/thumb' not in r.text  # no thumbnail configured yet


def test_editor_exposes_saved_presets_and_keyboard_help(monkeypatch,tmp_path):
    client=setup(monkeypatch,tmp_path)
    client.post('/presets',json={'preset_type':'combined','name':'Meu Pack','config':{'caption_preset_id':'green-fresh','layout_preset_id':'single'},'favorite':True})
    r=client.get('/clips/c1/edit');assert r.status_code==200
    assert 'Meus presets' in r.text
    assert 'Meu Pack' in r.text
    assert 'Atalhos' in r.text
    js=client.get('/static/editor.js').text
    assert 'keydown' in js
    assert 'Ctrl' in js or 'ctrlKey' in js
    assert 'pointerdown' in js and 'pointermove' in js


def test_project_thumbnail_uses_authenticated_route(monkeypatch,tmp_path):
    client=setup(monkeypatch,tmp_path)
    thumb=tmp_path/'project.jpg';thumb.write_bytes(b'jpeg')
    db.execute("UPDATE projects SET thumbnail_path=? WHERE id='p1'",(str(thumb),))
    page=client.get('/projects/p1')
    assert '/projects/p1/thumb' in page.text
    image=client.get('/projects/p1/thumb')
    assert image.status_code==200
