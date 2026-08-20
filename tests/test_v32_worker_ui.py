import json
from pathlib import Path

from fastapi.testclient import TestClient
from app import db, main
from app.services import job_store


def _client(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'ui.db')
    db.init_db()
    client=TestClient(main.app)
    client.post('/register',data={'email':'ui@test.com','password':'abcdef'})
    user=db.fetchone("SELECT * FROM users WHERE email='ui@test.com'")
    now=db.now_iso()
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload','manual','processing',20,'Transcrevendo','{}',?,?)",(user['id'],now,now))
    jid=job_store.create_job('project','p1')
    job_store.start_stage(jid,'transcribe',total=100,backend='cuda',message='Transcrevendo')
    job_store.update_stage(jid,current=40,speed=2.0,message='Transcrevendo')
    return client,jid


def test_project_status_api_includes_worker_snapshot(monkeypatch,tmp_path):
    client,jid=_client(monkeypatch,tmp_path)
    r=client.get('/api/projects/p1')
    assert r.status_code==200
    worker=r.json()['worker']
    assert worker['id']==jid
    assert worker['stage']=='transcribe'
    assert worker['eta_seconds'] >= 29


def test_project_template_has_worker_controls_and_detailed_progress():
    text=Path('app/templates/project.html').read_text(encoding='utf-8')
    for token in ('workerStatus','workerStage','workerEta','workerBackend','workerHeartbeat','workerPause','workerResume','workerCancel'):
        assert token in text
    assert '/api/v1/jobs/' in text


def test_shell_probes_webgpu_with_fallback():
    text=Path('app/static/shell.js').read_text(encoding='utf-8')
    assert 'navigator.gpu' in text
    assert 'webgl' in text.lower()
    assert 'canvas2d' in text.lower()


def test_hardware_page_uses_verified_profile(monkeypatch,tmp_path):
    client,_=_client(monkeypatch,tmp_path)
    profile={'gpu_name':'RTX 3060','gpu_vendor':'nvidia','ram_mb':32768,'cpu_threads':16,'profile':{'label':'TURBO'},'transcription':{'backend':'cuda'},'render':{'encoder':'h264_nvenc','verified':True},'analysis':{'tracking_fps':2.5,'width':720},'os':'Windows'}
    monkeypatch.setattr(main.hardware_service,'load_or_build_profile',lambda:profile)
    r=client.get('/hardware')
    assert r.status_code==200
    assert 'RTX 3060' in r.text
    assert 'h264_nvenc' in r.text
    assert 'cuda' in r.text
    assert '720' in r.text


def test_hardware_page_has_revalidate_action_and_browser_acceleration_status():
    text=Path('app/templates/hardware.html').read_text(encoding='utf-8')
    assert 'Reavaliar hardware' in text
    assert '/api/v1/hardware/revalidate' in text
    assert 'browserAccelerationStatus' in text
