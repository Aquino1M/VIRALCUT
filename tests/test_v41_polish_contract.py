from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'polish.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'polish@test.com','password':'abcdef'})
    user = db.fetchone("SELECT * FROM users WHERE email='polish@test.com'")
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload',?,'smart','done',100,'ok',?,?,?)",
        (user['id'], str(source), json.dumps({'aspect_ratio':'9:16'}), now, now),
    )
    db.execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at,updated_at) VALUES('c1','p1','Corte',0,30,8.5,?,?)",
        (now, now),
    )
    return client, user


def test_brand_kit_can_be_edited(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    created = client.post('/api/v1/brand-kits', json={'name':'Canal A','config':{'primary_color':'#111111'}})
    assert created.status_code == 200
    kit_id = created.json()['id']
    updated = client.put(f'/api/v1/brand-kits/{kit_id}', json={'name':'Canal B','config':{'primary_color':'#abcdef','cta_text':'SIGA'}})
    assert updated.status_code == 200
    payload = updated.json()
    assert payload['name'] == 'Canal B'
    assert payload['config']['primary_color'] == '#abcdef'
    assert payload['config']['cta_text'] == 'SIGA'


def test_publish_queue_reports_export_readiness(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    queued = client.post('/api/v1/publish', json={'clip_id': 'c1', 'platform':'youtube'})
    assert queued.status_code == 200
    assert queued.json()['export_ready'] is False

    out = tmp_path / 'final.mp4'
    out.write_bytes(b'mp4')
    db.execute('UPDATE clips SET video_path=? WHERE id=?', (str(out), 'c1'))
    items = client.get('/api/v1/publish').json()['items']
    item = next(x for x in items if x['id'] == queued.json()['id'])
    assert item['export_ready'] is True
    assert item['export_path'] == str(out)


def test_capabilities_advertise_v41_smart_studio(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    import app.services.api_v1 as api_v1
    monkeypatch.setattr(api_v1.hardware, 'load_or_build_profile', lambda: {'cpu_threads':4,'ram_mb':8192,'asr':{}})
    monkeypatch.setattr(api_v1.assets, 'starter_pack_status', lambda: {'ready': True})
    data = client.get('/api/v1/capabilities').json()
    features = data['features']
    for key in ['smart_director','viral_score_v2','studio_templates','named_brand_kits','publish_queue','viralytics','render_cache','waveform_cache','performance_modes','pwa_shell']:
        assert features[key] is True


def test_readme_identifies_v41_and_single_windows_launcher():
    text = Path('README.md').read_text(encoding='utf-8')
    assert '# ViralClip Studio V4.2' in text
    assert 'VIRALCLIP.bat' in text
    assert 'Smart Studio Engine' in text


def test_brand_and_publish_pages_expose_edit_and_export_state():
    brand = Path('app/templates/brand_kit.html').read_text(encoding='utf-8')
    publish = Path('app/templates/publish.html').read_text(encoding='utf-8')
    assert 'brand-kit-edit' in brand
    assert 'Exportação pronta' in publish
    assert 'Aguardando MP4' in publish
