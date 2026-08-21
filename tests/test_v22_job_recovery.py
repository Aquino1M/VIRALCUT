from pathlib import Path

from app import db
from app.services import jobs, render_queue


def _seed(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'recovery.db')
    db.init_db()
    now=db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'x@y.z','x',?)",(now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart','processing',65,'rendering','{}',?,?)",(now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,10,?)",(now,))
    db.execute("INSERT INTO clip_renders(id,clip_id,kind,status,progress,created_at,updated_at) VALUES('r1','c1','final','rendering',44,?,?)",(now,now))


def test_recovery_requeues_inflight_project_without_partial_clips(monkeypatch,tmp_path):
    _seed(monkeypatch,tmp_path)
    monkeypatch.setattr(jobs, 'OUTPUT_DIR', tmp_path/'outputs')
    monkeypatch.setattr(jobs, 'TEMP_DIR', tmp_path/'temp')
    queued=jobs.recover_interrupted_projects()
    p=db.fetchone("SELECT * FROM projects WHERE id='p1'")
    assert queued == ['p1']
    assert p['status']=='queued'
    assert p['progress']==0
    assert 'retomando' in p['message'].lower()
    assert db.fetchone("SELECT id FROM clips WHERE project_id='p1'") is None


def test_recovery_marks_inflight_render_as_error(monkeypatch,tmp_path):
    _seed(monkeypatch,tmp_path)
    count=render_queue.recover_interrupted_renders()
    r=db.fetchone("SELECT * FROM clip_renders WHERE id='r1'")
    assert count==1
    assert r['status']=='error'
    assert 'interrompido' in r['error_message'].lower()
