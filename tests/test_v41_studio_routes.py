from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'routes.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email':'route@test.com','password':'abcdef'})
    user = db.fetchone("SELECT * FROM users WHERE email='route@test.com'")
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload',?,'smart','done',100,'ok',?,?,?)", (user['id'], str(source), json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,video_path,created_at) VALUES('c1','p1','Corte viral',0,40,9.2,?,?)", (str(tmp_path/'render.mp4'), now))
    return client, user


def test_templates_page_manages_saved_templates(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    page = client.get('/templates')
    assert page.status_code == 200
    assert 'Meus Templates' in page.text
    assert 'id="createStudioTemplate"' in page.text
    created = client.post('/api/v1/templates', json={'name':'Podcast Viral','config':{'caption_preset_id':'mrbeast','layout_preset_id':'split'}})
    assert created.status_code == 200
    tid = created.json()['id']
    applied = client.post(f'/api/v1/templates/{tid}/apply', json={'clip_ids':['c1']})
    assert applied.status_code == 200
    assert applied.json()['updated'] == 1


def test_brand_kit_page_can_create_named_kit_and_apply(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    page = client.get('/brand-kit')
    assert page.status_code == 200
    assert 'Kits de Marca' in page.text
    created = client.post('/api/v1/brand-kits', json={'name':'Canal Principal','config':{'font_family':'Anton','primary_color':'#ff00aa','cta_text':'SIGA'}})
    assert created.status_code == 200
    kid = created.json()['id']
    applied = client.post(f'/api/v1/brand-kits/{kid}/apply', json={'clip_ids':['c1']})
    assert applied.status_code == 200
    assert applied.json()['updated'] == 1


def test_publish_page_and_queue_endpoint_are_local_workflow(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    page = client.get('/publish')
    assert page.status_code == 200
    assert 'Fila de Publicação' in page.text
    assert 'não publica sozinho' in page.text.lower()
    r = client.post('/api/v1/publish', json={'clip_id':'c1','platform':'tiktok','scheduled_at':'2026-08-21T18:00:00','caption':'Teste'})
    assert r.status_code == 200
    assert r.json()['status'] == 'scheduled'
    listing = client.get('/api/v1/publish')
    assert listing.status_code == 200
    assert listing.json()['items'][0]['clip_id'] == 'c1'


def test_analytics_page_exposes_local_viralytics(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    r = client.get('/analytics')
    assert r.status_code == 200
    assert 'Viralytics' in r.text
    assert 'Renderizados' in r.text
    assert 'ViralScore médio' in r.text


def test_youtube_browser_choice_is_available_for_new_and_failed_projects(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    new_page = client.get('/projects/new')
    assert new_page.status_code == 200
    assert 'name="youtube_cookies"' in new_page.text
    assert 'value="brave"' not in new_page.text
    assert 'value="chrome"' not in new_page.text

    db.execute("UPDATE projects SET status='error', message='HTTP 403' WHERE id='p1'")
    project_page = client.get('/projects/p1')
    assert project_page.status_code == 200
    assert 'value="Automático" readonly' in project_page.text
    saved = client.post('/projects/p1/defaults', json={'youtube_cookies': 'brave'})
    assert saved.status_code == 200
    assert 'youtube_cookies' not in json.loads(db.fetchone("SELECT settings_json FROM projects WHERE id='p1'")['settings_json'])


def test_admin_monitor_reports_cloud_cpu_status(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    monkeypatch.setattr(main.cloud_client_service, 'configured', lambda: True)
    monkeypatch.setattr(main.cloud_client_service, 'health', lambda **_: {
        'ok': True, 'status': 'online', 'free_cpu_only': True,
        'queue': {'active': 1, 'queued': 2}, 'capabilities': {'cpu_count': 4, 'ram_mb': 15786},
    })

    monitor = client.get('/admin/monitor')

    assert monitor.status_code == 200
    assert monitor.json()['cloud'] == {
        'configured': True, 'online': True, 'status': 'online', 'remote_active': 1,
        'remote_queued': 2, 'app_active': 0, 'cpu_count': 4, 'ram_mb': 15786, 'free_cpu_only': True,
    }
    assert 'adminCloudStatus' in client.get('/admin').text


def test_sidebar_hides_technical_and_unused_workflow_links():
    html = Path('app/templates/base.html').read_text(encoding='utf-8')
    assert 'href="/publish"' not in html
    assert 'href="/analytics"' not in html
    assert 'href="/hardware"' not in html
    assert 'href="/compute"' not in html
    assert 'href="/admin"' in html
