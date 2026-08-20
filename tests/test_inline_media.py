from __future__ import annotations
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app import db, main


def _client(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'media.db');db.init_db();c=TestClient(main.app);c.post('/register',data={'email':'m@test.com','password':'abcdef'});u=db.fetchone("SELECT * FROM users WHERE email='m@test.com'");now=db.now_iso();v=tmp_path/'v.mp4';v.write_bytes(b'video')
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload',?,'smart','{}',?,?)",(u['id'],str(v),now,now));db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,video_path,created_at) VALUES('c1','p1','C',0,1,?,?)",(str(v),now));return c,v


def test_video_preview_routes_are_inline_and_download_route_is_attachment(monkeypatch,tmp_path):
    c,_=_client(monkeypatch,tmp_path)
    preview=c.get('/clips/c1/video')
    assert preview.status_code==200
    assert 'attachment' not in preview.headers.get('content-disposition','').lower()
    source=c.get('/projects/p1/source-video')
    assert 'attachment' not in source.headers.get('content-disposition','').lower()
    download=c.get('/clips/c1/download')
    assert 'attachment' in download.headers.get('content-disposition','').lower()
