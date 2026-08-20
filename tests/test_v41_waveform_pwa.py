from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import db, main
from app.services import waveform


def test_waveform_cache_generates_normalized_samples(monkeypatch, tmp_path):
    source = tmp_path/'source.mp4'; source.write_bytes(b'media')
    cache = tmp_path/'wave.json'
    monkeypatch.setattr(waveform, 'waveform_cache_path', lambda *a, **k: cache)
    pcm = (b'\x00\x00' * 20) + (b'\xff\x7f' * 20) + (b'\x00\x40' * 20)
    monkeypatch.setattr(waveform.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=pcm, stderr=b''))
    out = waveform.ensure_waveform('c1', source, 0, 3, samples=12)
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['version'] == 1
    assert len(data['samples']) == 12
    assert all(0 <= x <= 1 for x in data['samples'])
    assert max(data['samples']) == 1


def setup_client(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'wave-route.db'); db.init_db()
    client=TestClient(main.app); client.post('/register', data={'email':'wave@test.com','password':'abcdef'})
    user=db.fetchone("SELECT * FROM users WHERE email='wave@test.com'"); now=db.now_iso()
    source=tmp_path/'source.mp4'; source.write_bytes(b'media')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload',?,'smart','done',100,'ok','{}',?,?)",(user['id'],str(source),now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at,updated_at) VALUES('c1','p1','C',0,10,8,?,?)",(now,now))
    return client,tmp_path


def test_editor_exposes_cached_waveform_and_pwa_shell(monkeypatch,tmp_path):
    client,tmp=setup_client(monkeypatch,tmp_path)
    wave=tmp/'wave.json'; wave.write_text(json.dumps({'version':1,'duration':10,'samples':[0,.5,1]}),encoding='utf-8')
    monkeypatch.setattr(main.waveform_service,'ensure_waveform',lambda *a,**k:wave)
    route=client.get('/clips/c1/waveform')
    assert route.status_code==200
    assert route.json()['samples'][-1]==1
    editor=client.get('/clips/c1/edit')
    assert 'id="waveformCanvas"' in editor.text
    base=Path('app/templates/base.html').read_text(encoding='utf-8')
    assert 'manifest.webmanifest' in base
    assert 'serviceWorker.register' in base
    assert Path('app/static/manifest.webmanifest').exists()
    assert Path('app/static/sw.js').exists()
