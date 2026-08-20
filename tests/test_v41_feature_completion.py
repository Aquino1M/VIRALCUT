from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main
from app.services import captions, jobs


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'complete.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'complete@test.com','password':'abcdef'})
    user = db.fetchone("SELECT * FROM users WHERE email='complete@test.com'")
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    render = tmp_path / 'render.mp4'; render.write_bytes(b'render')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload',?,'smart','done',100,'ok',?,?,?)", (user['id'],str(source),json.dumps({'aspect_ratio':'9:16'}),now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,hook,reason,video_path,created_at,updated_at,analysis_json) VALUES('c1','p1','Corte',0,35,9.0,'Olha isso','Polêmica',?,?,?,'{}')", (str(render),now,now))
    return client, user


def test_caption_engine_has_modern_after_effects_variants():
    ids = {p['id'] for p in captions.list_caption_presets()}
    assert {'after-effects-01','after-effects-02','after-effects-03'} <= ids


def test_jobs_candidate_analysis_uses_viral_score_v2():
    result = jobs._candidate_analysis({'title':'Você não vai acreditar','hook':'Olha isso','reason':'Polêmica','score':9.1,'start':0,'end':42})
    assert result['version'] == 2
    assert result['score'] >= 0
    assert 'retention' in result['breakdown']


def test_editor_exposes_saved_studio_templates_and_brand_kits(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    client.post('/api/v1/templates', json={'name':'Meu Template','config':{'caption_preset_id':'after-effects-02'}})
    client.post('/api/v1/brand-kits', json={'name':'Minha Marca','config':{'primary_color':'#ff00aa'}})
    page = client.get('/clips/c1/edit')
    assert page.status_code == 200
    assert 'Studio Templates' in page.text
    assert 'Meu Template' in page.text
    assert 'id="brandKitSelect"' in page.text
    assert 'Minha Marca' in page.text


def test_project_defaults_persist_template_and_brand_kit(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    t = client.post('/api/v1/templates', json={'name':'T','config':{}}).json()
    k = client.post('/api/v1/brand-kits', json={'name':'K','config':{}}).json()
    r = client.post('/projects/p1/defaults', json={'template_id':t['id'],'brand_kit_id':k['id'],'caption_preset_id':'after-effects-02'})
    assert r.status_code == 200
    row = db.fetchone("SELECT template_id,brand_kit_id FROM projects WHERE id='p1'")
    assert row['template_id'] == t['id']
    assert row['brand_kit_id'] == k['id']


def test_videos_page_uses_viral_score_v2(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    page = client.get('/videos')
    assert page.status_code == 200
    assert 'ViralScore' in page.text
    saved = json.loads(db.fetchone("SELECT analysis_json FROM clips WHERE id='c1'")['analysis_json'])
    assert saved['version'] == 2
