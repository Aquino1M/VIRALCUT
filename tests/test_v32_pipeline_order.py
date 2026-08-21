import json
from pathlib import Path

from app import db
from app.services import jobs


def test_project_pipeline_profiles_and_transcribes_before_window_tracking(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'pipeline.db')
    db.init_db()
    now=db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'x@y.z','x',?)",(now,))
    source=tmp_path/'source.mp4'; source.write_bytes(b'video')
    settings={'num_clips':1,'min_duration':5,'max_duration':20,'tracking_fps':1.5,'captions':False,'auto_edit_enabled':False}
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload',?,'smart','queued',?,?,?)",(str(source),json.dumps(settings),now,now))

    events=[]
    profile={'version':2,'profile':{'name':'balanced','label':'BALANCEADO'},'render':{'encoder':'libx264'},'transcription':{'backend':'cpu','model':'base'},'analysis':{'tracking_fps':1.0,'width':480},'gpu_vendor':'cpu'}
    monkeypatch.setattr(jobs.hardware, 'load_or_build_profile', lambda **kw: events.append('hardware') or profile, raising=False)
    monkeypatch.setattr(jobs, 'ingest_upload', lambda p,w: source)
    monkeypatch.setattr(jobs, 'probe_video', lambda p: {'duration':30.0,'width':1920,'height':1080,'fps':30.0})
    monkeypatch.setattr(jobs.disk_manager, 'ensure_job_space', lambda *a,**k: events.append('disk-preflight') or {'ok':True}, raising=False)
    monkeypatch.setattr(jobs, 'generate_thumbnail', lambda *a,**k: None)
    monkeypatch.setattr(jobs.asr_cache, 'CACHE_ROOT', tmp_path/'asr-cache')
    monkeypatch.setattr(jobs, 'transcribe_segments', lambda *a,**k: events.append('transcribe') or {'language':'pt','duration':30.0,'segments':[{'start':0,'end':30,'text':'teste viral','words':[]}]})
    monkeypatch.setattr(jobs, 'transcribe_words', lambda _src,start,end,**k: events.append('refine') or {'language':'pt','duration':end-start,'segments':[{'start':start,'end':end,'text':'teste viral','words':[{'start':start,'end':end,'word':'teste'}]}]})
    monkeypatch.setattr(jobs, 'save_transcript', lambda data,path: Path(path).write_text('{}'))
    monkeypatch.setattr(jobs, 'find_highlights', lambda *a,**k: events.append('highlights') or [{'start':5.0,'end':15.0,'score':90,'title':'Corte','hook':'','reason':'teste'}])
    monkeypatch.setattr(jobs.face_tracking, 'analyze_video', lambda *a,**k: (_ for _ in ()).throw(AssertionError('full video tracking must not run')))
    monkeypatch.setattr(jobs.face_tracking, 'analyze_window', lambda *a,**k: events.append('tracking-window') or {'backend':'none','tracks':[],'total_samples':1,'analyzed_frames':1,'frames_with_faces':0,'source_start':5.0,'source_end':15.0})
    monkeypatch.setattr(jobs.face_tracking, 'tracking_summary', lambda d: {'backend':d.get('backend','none'),'track_count':0,'coverage_percent':0})
    monkeypatch.setattr(jobs.face_tracking, 'slice_tracks', lambda d,s,e: {'tracks':[],'source_start':s,'duration':e-s})
    monkeypatch.setattr(jobs, 'OUTPUT_DIR', tmp_path/'out')
    monkeypatch.setattr(jobs, 'TEMP_DIR', tmp_path/'temp')
    monkeypatch.setattr(jobs, 'THUMB_DIR', tmp_path/'thumb')
    renders=[]
    def fake_render(*, out_path, **kwargs):
        renders.append(Path(out_path))
        Path(out_path).parent.mkdir(parents=True,exist_ok=True); Path(out_path).write_bytes(b'x'); return {'encoder':'libx264'}
    monkeypatch.setattr(jobs, 'render_clean_clip', fake_render)
    monkeypatch.setattr(jobs, 'render_edited_clip', fake_render)
    monkeypatch.setattr(jobs.editor_service, 'save_edit_state', lambda *a,**k: None)
    monkeypatch.setattr(jobs.editor_service, 'replace_caption_cues', lambda *a,**k: None)
    monkeypatch.setattr(jobs, 'cues_from_transcript', lambda *a,**k: [])

    jobs.process_project('p1')
    p=db.fetchone("SELECT * FROM projects WHERE id='p1'")
    assert p['status']=='done'
    assert events.index('hardware') < events.index('disk-preflight') < events.index('transcribe') < events.index('highlights') < events.index('tracking-window')
    assert 'analyze_video' not in events
    assert len(renders) == 2

    db.execute("UPDATE projects SET status='queued' WHERE id='p1'")
    jobs.process_project('p1')
    assert len(renders) == 2
    assert db.fetchone("SELECT COUNT(*) count FROM clips WHERE project_id='p1'")['count'] == 1
