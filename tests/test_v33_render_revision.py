from __future__ import annotations
import json
from pathlib import Path
from app import db


def _seed(monkeypatch,tmp_path: Path):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'r.db'); db.init_db(); now=db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'x@y.z','x',?)",(now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p',1,'P','upload','smart','{}',?,?)",(now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at,updated_at) VALUES('c','p','C',0,5,?,?)",(now,now))


def test_render_record_can_freeze_editor_snapshot(monkeypatch,tmp_path):
    _seed(monkeypatch,tmp_path)
    from app.services import render_queue
    snap={'editor':{'revision':7,'caption_config':{'fontSize':90}},'timeline':{'tracks':[]},'cues':[{'text':'A'}]}
    rid=render_queue.create_render_record('c','final','abc',7,snap)
    row=render_queue.get_render_record(rid)
    assert row['editor_revision']==7
    assert json.loads(row['snapshot_json'])['editor']['caption_config']['fontSize']==90
