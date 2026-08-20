from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'command.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'command@test.com','password':'abcdef'})
    user = db.fetchone("SELECT * FROM users WHERE email='command@test.com'")
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    rendered = tmp_path / 'render.mp4'; rendered.write_bytes(b'render')
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload',?,'smart','done',100,'ok',?,?,?)",
        (user['id'], str(source), json.dumps({'aspect_ratio':'9:16'}), now, now),
    )
    db.execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,score,hook,reason,video_path,created_at,updated_at,analysis_json) VALUES('c1','p1','Corte muito forte',0,40,9.3,'Você não vai acreditar','Trecho polêmico que gera comentários',?,?,?, '{}')",
        (str(rendered), now, now),
    )
    db.execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,score,hook,reason,created_at,updated_at,analysis_json) VALUES('c2','p1','Segundo corte',45,75,8.1,'Olha isso','Curiosidade e emoção',?,?, '{}')",
        (now, now),
    )
    return client, user


def test_project_command_center_backfills_viral_score_and_exposes_workflow(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    page = client.get('/projects/p1')
    assert page.status_code == 200
    assert 'ViralScore' in page.text
    assert 'Auto Director' in page.text
    assert 'id="bulkSmartBar"' in page.text
    assert 'Renderizando' in page.text
    assert 'Agendados' in page.text
    assert 'Publicados' in page.text
    saved = db.fetchone("SELECT analysis_json FROM clips WHERE id='c1'")
    analysis = json.loads(saved['analysis_json'])
    assert 0 <= analysis['score'] <= 100
    assert set(analysis['breakdown']) == {'hook','curiosity','emotion','controversy','clarity','shareability','comments','retention'}


def test_project_filter_can_show_scheduled_items(monkeypatch, tmp_path):
    client, user = setup_client(monkeypatch, tmp_path)
    now = db.now_iso()
    db.execute(
        "INSERT INTO publish_queue(id,user_id,clip_id,platform,status,scheduled_at,caption,created_at,updated_at) VALUES('q1',?,'c2','tiktok','scheduled','2026-08-21T18:00:00','',?,?)",
        (user['id'], now, now),
    )
    page = client.get('/projects/p1?filter=scheduled')
    assert page.status_code == 200
    assert 'Segundo corte' in page.text
    assert 'Corte muito forte' not in page.text
    assert 'scheduled' in page.text.lower()


def test_command_endpoint_applies_template_brand_kit_and_director(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    template = client.post('/api/v1/templates', json={'name':'T','config':{'caption_preset_id':'mrbeast','layout_preset_id':'split'}}).json()
    kit = client.post('/api/v1/brand-kits', json={'name':'K','config':{'primary_color':'#ff00aa','cta_text':'SIGA'}}).json()
    monkeypatch.setattr(main.auto_edit_service, 'build_auto_edit_plan', lambda clip_id, **kwargs: {'clip_id':clip_id,'metadata':{'autoEdit':{'directorScenes':2}}})
    result = client.post('/api/v1/projects/p1/command', json={
        'clip_ids':['c1'], 'template_id':template['id'], 'brand_kit_id':kit['id'], 'auto_director':True,
    })
    assert result.status_code == 200
    body = result.json()
    assert body['selected'] == 1
    assert body['template_updated'] == 1
    assert body['brand_kit_updated'] == 1
    assert body['director_updated'] == 1


def test_performance_profile_stays_automatic_and_controls_editor_proxy(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    saved = client.post('/api/v1/performance-mode', json={'mode':'basic'})
    assert saved.status_code == 200
    assert saved.json()['mode'] == 'auto'
    page = client.get('/hardware')
    assert page.status_code == 200
    assert 'Modo de desempenho' not in page.text
    assert 'id="performanceMode"' not in page.text

    captured = {}
    proxy_file = tmp_path / 'proxy.mp4'; proxy_file.write_bytes(b'proxy')
    def fake_proxy(*args, **kwargs):
        captured['target_height'] = kwargs.get('target_height')
        return proxy_file
    monkeypatch.setattr(main.proxy_media_service, 'ensure_editor_proxy', fake_proxy)
    r = client.get('/clips/c1/editor-proxy')
    assert r.status_code == 200
    assert captured['target_height'] in {360, 480, 720}
