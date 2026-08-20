from __future__ import annotations

from pathlib import Path

from app import db


def test_render_record_lifecycle(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'queue.db')
    db.init_db()
    from app.services import render_queue
    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'a@b.c','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart','{}',?,?)", (now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,10,?)", (now,))
    rid = render_queue.create_render_record('c1', 'preview', 'hash1')
    row = render_queue.get_render_record(rid)
    assert row['status'] == 'queued'
    render_queue.update_render_record(rid, status='rendering', progress=40)
    row = render_queue.get_render_record(rid)
    assert row['progress'] == 40
    render_queue.update_render_record(rid, status='done', progress=100, encoder='h264_amf', resolution='540x960')
    row = render_queue.get_render_record(rid)
    assert row['status'] == 'done'
    assert row['encoder'] == 'h264_amf'
