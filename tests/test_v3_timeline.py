import json
from pathlib import Path

from app import db


def seed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v3.db")
    db.init_db()
    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'v3@test','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart',?,?,?)", (json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',10,40,?)", (now,))
    return now


def test_v3_migration_creates_timeline_table(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    with db.connect() as conn:
        names = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'clip_timelines' in names


def test_timeline_created_with_editor_tracks(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    from app.services import editor, timeline
    editor.replace_caption_cues('c1', [
        {'start_time': 0, 'end_time': 1, 'text': 'Brasil', 'word_index': 0},
        {'start_time': 1, 'end_time': 2, 'text': 'cresceu', 'word_index': 1},
    ])
    data = timeline.get_or_create_timeline('c1')
    assert data['schemaVersion'] == 3
    assert data['composition']['width'] == 1080
    assert data['composition']['height'] == 1920
    track_types = {t['type'] for t in data['tracks']}
    assert {'video','captions','broll','sfx','music','effects','text','overlays'} <= track_types
    captions = next(t for t in data['tracks'] if t['type'] == 'captions')
    assert len(captions['items']) == 2
    assert captions['items'][0]['text'] == 'Brasil'


def test_timeline_roundtrip_and_validation(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    from app.services import timeline
    data = timeline.get_or_create_timeline('c1')
    data['markers'].append({'id':'m1','time':2.5,'type':'hook','label':'Hook'})
    saved = timeline.save_timeline('c1', data)
    assert saved['markers'][0]['type'] == 'hook'
    loaded = timeline.get_or_create_timeline('c1')
    assert loaded['markers'][0]['time'] == 2.5
