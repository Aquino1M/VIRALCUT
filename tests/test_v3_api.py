import json
from pathlib import Path

from fastapi.testclient import TestClient
from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'api.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'api@test.com','password':'abcdef'})
    user = db.fetchone("SELECT * FROM users WHERE email='api@test.com'")
    now = db.now_iso()
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload','smart',?,?,?)", (user['id'], json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,12,?)", (now,))
    from app.services import editor
    editor.replace_caption_cues('c1', [{'start_time':0,'end_time':1,'text':'mercado financeiro','word_index':0}])
    return client


def test_v1_health_is_versioned(monkeypatch, tmp_path):
    setup_client(monkeypatch, tmp_path)
    r = TestClient(main.app).get('/api/v1/health')
    assert r.status_code == 200
    data = r.json()
    assert data['api_version'] == 1
    assert data['timeline_schema'] == 3
    assert data['local_first'] is True


def test_v1_capabilities_reports_hardware_and_asset_pack(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    monkeypatch.setattr(main.api_v1_service.hardware, 'load_or_build_profile', lambda: {'gpu_vendor':'amd','render':{'encoder':'h264_amf'},'profile':{'name':'balanced'}})
    monkeypatch.setattr(main.api_v1_service.assets, 'starter_pack_status', lambda: {'preset':'lite','limit_bytes':2*1024**3,'size_bytes':123,'counts':{}})
    r = client.get('/api/v1/capabilities')
    assert r.status_code == 200
    assert r.json()['hardware']['gpu_vendor'] == 'amd'
    assert r.json()['assets']['preset'] == 'lite'


def test_v1_timeline_roundtrip(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    r = client.get('/api/v1/clips/c1/timeline')
    assert r.status_code == 200
    data = r.json()
    data['markers'].append({'id':'x','time':1,'type':'note','label':'x'})
    saved = client.put('/api/v1/clips/c1/timeline', json=data)
    assert saved.status_code == 200
    assert saved.json()['markers'][-1]['id'] == 'x'


def test_v1_auto_edit_endpoint_builds_editable_plan(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    monkeypatch.setattr(main.auto_edit_service.assets, 'search_assets', lambda query, kind=None, limit=8, orientation=None: [])
    r = client.post('/api/v1/clips/c1/auto-edit', json={'style':'podcast-viral','intensity':'normal','options':{'broll':False}})
    assert r.status_code == 200
    data = r.json()
    assert data['metadata']['autoEdit']['editable'] is True
    assert data['metadata']['autoEdit']['style'] == 'podcast-viral'
