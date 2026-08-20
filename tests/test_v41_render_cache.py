from __future__ import annotations

import json
from pathlib import Path

from app import db


def setup_clip(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'cache.db')
    db.init_db()
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'u@test.com','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload',?,'smart',?, ?,?)", (str(source), json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,10,?)", (now,))
    from app.services import editor, timeline, preview
    state = editor.get_or_create_edit_state('c1')
    tl = timeline.get_or_create_timeline('c1')
    state_hash = preview.settings_hash({'editor':state,'timeline':tl})
    return state, tl, state_hash


def test_final_render_reuses_same_revision_and_hash(monkeypatch, tmp_path):
    state, _tl, state_hash = setup_clip(monkeypatch, tmp_path)
    from app.services import render_queue
    now = db.now_iso()
    cached = tmp_path / 'cached.mp4'; cached.write_bytes(b'video')
    db.execute("INSERT INTO clip_renders(id,clip_id,kind,status,progress,settings_hash,editor_revision,video_path,created_at,updated_at) VALUES('r-cache','c1','final','done',100,?,?,?, ?,?)", (state_hash, state['revision'], str(cached), now, now))
    class Bomb:
        def submit(self, *args, **kwargs):
            raise AssertionError('executor should not run for cached final')
    monkeypatch.setattr(render_queue, '_executor', Bomb())
    rid = render_queue.enqueue_clip_render('c1', 'final', editor_revision=state['revision'])
    assert rid == 'r-cache'
    assert db.fetchone("SELECT COUNT(*) n FROM clip_renders WHERE clip_id='c1' AND kind='final'")['n'] == 1


def test_missing_cached_file_is_not_reused(monkeypatch, tmp_path):
    state, _tl, state_hash = setup_clip(monkeypatch, tmp_path)
    from app.services import render_queue
    now = db.now_iso()
    missing = tmp_path / 'missing.mp4'
    db.execute("INSERT INTO clip_renders(id,clip_id,kind,status,progress,settings_hash,editor_revision,video_path,created_at,updated_at) VALUES('r-old','c1','final','done',100,?,?,?, ?,?)", (state_hash, state['revision'], str(missing), now, now))
    calls=[]
    class Fake:
        def submit(self, *args, **kwargs): calls.append(args)
    monkeypatch.setattr(render_queue, '_executor', Fake())
    rid = render_queue.enqueue_clip_render('c1', 'final', editor_revision=state['revision'])
    assert rid != 'r-old'
    assert calls
