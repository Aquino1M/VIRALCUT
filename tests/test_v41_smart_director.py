from __future__ import annotations

import json
from pathlib import Path

from app import db


def setup_clip(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'director.db')
    db.init_db()
    now = db.now_iso()
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'u@test.com','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload',?,'smart',?, ?,?)", (str(source), json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at) VALUES('c1','p1','C',0,12,9.0,?)", (now,))
    from app.services import editor
    editor.replace_caption_cues('c1', [
        {'start_time':0.0,'end_time':1.0,'text':'olha isso agora','word_index':0,'speaker_id':'speaker_1'},
        {'start_time':1.0,'end_time':3.0,'text':'eu nunca contei esse segredo','word_index':1,'speaker_id':'speaker_1','highlight':True},
        {'start_time':3.1,'end_time':5.0,'text':'mas eu discordo totalmente','word_index':2,'speaker_id':'speaker_2'},
        {'start_time':5.0,'end_time':8.0,'text':'isso virou uma grande polêmica','word_index':3,'speaker_id':'speaker_2'},
        {'start_time':8.2,'end_time':11.5,'text':'agora todo mundo vai saber','word_index':4,'speaker_id':'speaker_1'},
    ])


def test_auto_edit_adds_editable_director_layout_decisions(monkeypatch, tmp_path):
    setup_clip(monkeypatch, tmp_path)
    from app.services import auto_edit
    monkeypatch.setattr(auto_edit.assets, 'search_assets', lambda *a, **k: [])
    data = auto_edit.build_auto_edit_plan('c1', style='podcast-viral', intensity='viral', options={'broll':False,'sfx':False,'music':False,'filters':False,'effects':True,'director':True})
    effects = next(t for t in data['tracks'] if t['type'] == 'effects')['items']
    director = [x for x in effects if x.get('type') == 'director-layout']
    assert len(director) >= 2
    assert all(x['generatedBy'] == 'auto-edit' for x in director)
    assert all(x.get('layoutPresetId') in {'single','split','podcast-dynamic','react','center'} for x in director)
    meta = data['metadata']['autoEdit']
    assert meta['directorScenes'] == len(director)
    assert meta['editable'] is True


def test_director_segments_fill_timeline_and_keep_scene_layouts():
    from app.services import timeline_render
    data = {'tracks':[{'type':'effects','hidden':False,'items':[
        {'id':'d1','type':'director-layout','from':2,'duration':3,'layoutPresetId':'split'},
        {'id':'d2','type':'director-layout','from':7,'duration':2,'layoutPresetId':'single'},
    ]}]}
    segments = timeline_render.director_layout_segments(data, 10, default_layout='center')
    assert segments[0] == {'start':0.0,'end':2.0,'layout_preset_id':'center'}
    assert {'start':2.0,'end':5.0,'layout_preset_id':'split'} in segments
    assert segments[-1] == {'start':9.0,'end':10.0,'layout_preset_id':'center'}
    assert sum(round(x['end']-x['start'], 3) for x in segments) == 10.0
