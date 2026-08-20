import json
from pathlib import Path

from fastapi.testclient import TestClient
from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'worker.db')
    db.init_db()
    client=TestClient(main.app)
    client.post('/register',data={'email':'worker@test.com','password':'abcdef'})
    user=db.fetchone("SELECT * FROM users WHERE email='worker@test.com'")
    now=db.now_iso()
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,status,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload','manual','queued','{}',?,?)",(user['id'],now,now))
    return client


def test_worker_health_declares_heavy_processing_role(monkeypatch,tmp_path):
    setup_client(monkeypatch,tmp_path)
    data=TestClient(main.app).get('/api/v1/health').json()
    assert data['worker_protocol']==1
    assert data['heavy_processing']=='local-worker'
    assert data['browser_acceleration']=='webgpu-optional'


def test_worker_job_create_read_pause_resume_cancel(monkeypatch,tmp_path):
    client=setup_client(monkeypatch,tmp_path)
    monkeypatch.setattr(main.project_jobs.executor,'submit',lambda *a,**k: None)
    created=client.post('/api/v1/jobs',json={'kind':'project','target_id':'p1'})
    assert created.status_code==200
    job=created.json(); jid=job['id']
    assert job['target_id']=='p1'
    assert client.get(f'/api/v1/jobs/{jid}').status_code==200
    assert client.post(f'/api/v1/jobs/{jid}/pause').json()['control_state']=='paused'
    assert client.post(f'/api/v1/jobs/{jid}/resume').json()['control_state']=='running'
    assert client.post(f'/api/v1/jobs/{jid}/cancel').json()['status']=='cancelled'
    events=client.get(f'/api/v1/jobs/{jid}/events')
    assert events.status_code==200
    assert 'stages' in events.json()


def test_pairing_issues_revocable_bearer_token(monkeypatch,tmp_path):
    setup_client(monkeypatch,tmp_path)
    from app.services import worker_pairing
    monkeypatch.setattr(worker_pairing,'PAIR_STATE_PATH',tmp_path/'pair.json')
    code=worker_pairing.current_pair_code(force_new=True)
    r=TestClient(main.app).post('/api/v1/pair',json={'code':code,'device_name':'Vercel Browser'})
    assert r.status_code==200
    token=r.json()['token']
    assert token and token not in (tmp_path/'pair.json').read_text()
    assert worker_pairing.validate_token(token)


def test_paired_browser_can_read_capabilities_and_revalidate_hardware(monkeypatch,tmp_path):
    setup_client(monkeypatch,tmp_path)
    from app.services import worker_pairing
    monkeypatch.setattr(worker_pairing,'PAIR_STATE_PATH',tmp_path/'pair2.json')
    code=worker_pairing.current_pair_code(force_new=True)
    pair=TestClient(main.app).post('/api/v1/pair',json={'code':code,'device_name':'Vercel UI'})
    token=pair.json()['token']
    profile={
        'version':2,'gpu_vendor':'amd','gpu_name':'Test GPU','vram_mb':8192,'ram_mb':16384,'cpu_threads':8,
        'profile':{'label':'BALANCEADO'},'render':{'encoder':'h264_amf','verified':True},
        'transcription':{'backend':'directml','model':'small','cpu_threads':4},
        'analysis':{'tracking_fps':1.8,'width':640},
    }
    calls=[]
    monkeypatch.setattr(main.hardware_service,'load_or_build_profile',lambda force=False: calls.append(force) or profile)
    headers={'Authorization':f'Bearer {token}'}
    caps=TestClient(main.app).get('/api/v1/capabilities',headers=headers)
    assert caps.status_code==200
    assert caps.json()['hardware']['gpu_vendor']=='amd'
    refresh=TestClient(main.app).post('/api/v1/hardware/revalidate',headers=headers)
    assert refresh.status_code==200
    assert refresh.json()['render']['encoder']=='h264_amf'
    assert True in calls
