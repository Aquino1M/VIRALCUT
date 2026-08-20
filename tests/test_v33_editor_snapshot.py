from __future__ import annotations
import json
from pathlib import Path
from app import db


def seed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'v33.db'); db.init_db(); now=db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'a@b.c','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p',1,'P','upload','smart','{}',?,?)", (now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at,updated_at) VALUES('c','p','C',0,10,?,?)", (now,now))


def test_editor_snapshot_increments_revision_and_persists_all(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    from app.services import editor, timeline
    tl=timeline.get_or_create_timeline('c')
    saved=editor.save_editor_snapshot('c', {'aspect_ratio':'1:1','layout_preset_id':'split','overlays':[{'id':'cta1','type':'cta','text':'x'}]}, [{'start_time':0,'end_time':1,'text':'oi'}], tl)
    assert saved['revision'] == 2
    assert saved['state']['aspect_ratio'] == '1:1'
    assert editor.list_caption_cues('c')[0]['text'] == 'oi'
    assert timeline.get_or_create_timeline('c')['composition']['aspectRatio'] == '1:1'


def test_v33_db_has_revision_columns(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    with db.connect() as c:
        edits={r['name'] for r in c.execute('PRAGMA table_info(clip_edits)')}
        renders={r['name'] for r in c.execute('PRAGMA table_info(clip_renders)')}
    assert {'revision','aspect_ratio'} <= edits
    assert 'editor_revision' in renders
