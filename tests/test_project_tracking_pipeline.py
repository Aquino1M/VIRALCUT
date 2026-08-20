from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main
from app.services import jobs


def test_project_processing_tracks_only_selected_clip_window(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tracking.db")
    db.init_db()
    now = db.now_iso()
    db.execute("INSERT INTO users(email,password_hash,created_at) VALUES('u@test.com','x',?)", (now,))
    user = db.fetchone("SELECT id FROM users WHERE email='u@test.com'")
    source = tmp_path / "source.mp4"; source.write_bytes(b"fake")
    settings = {"manual_ranges": "0-5", "layout_preset_id": "single", "captions": True}
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'P','upload',?,'manual','queued',0,'Na fila',?,?,?)",
        (user["id"], str(source), json.dumps(settings), now, now),
    )
    monkeypatch.setattr(jobs, "TEMP_DIR", tmp_path / "temp")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(jobs, "THUMB_DIR", tmp_path / "thumb")
    monkeypatch.setattr(jobs, "ingest_upload", lambda path, work: source)
    monkeypatch.setattr(jobs, "probe_video", lambda path: {"duration": 10.0, "width": 1920, "height": 1080, "codec": "h264"})
    monkeypatch.setattr(jobs, "generate_thumbnail", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip thumb")))
    monkeypatch.setattr(jobs.asr_cache, "CACHE_ROOT", tmp_path / "asr-cache")
    monkeypatch.setattr(jobs, "transcribe_segments", lambda *a, **k: {"language": "pt", "duration": 10.0, "segments": [{"start": 0, "end": 5, "text": "fala", "words": []}]})
    monkeypatch.setattr(jobs, "transcribe_words", lambda _src, start, end, **k: {"language": "pt", "duration": end-start, "segments": [{"start": start, "end": end, "text": "fala", "words": [{"start": start, "end": end, "word": "fala"}]}]})
    monkeypatch.setattr(jobs, "save_transcript", lambda data, path: Path(path).write_text(json.dumps(data), encoding="utf-8"))
    calls = {"tracking": 0, "fps": None}

    def fake_tracking(video, start, end, *, out_path=None, fps=4.0, analysis_width=640, progress_callback=None, **kwargs):
        calls["tracking"] += 1
        calls["fps"] = fps
        data = {"version":3,"backend":"haar","analyzed_frames":4,"total_samples":4,"frames_with_faces":3,"tracks":[{"id":"face_1","samples":[{"t":max(0.0,start),"box":[.2,.1,.2,.3],"center":[.3,.25],"confidence":.9,"activity":.1}]}],"fallback_reason":None,"source_start":start,"source_end":end}
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(data), encoding="utf-8")
        if progress_callback:
            progress_callback(1.0, "haar")
        return data

    monkeypatch.setattr(jobs.face_tracking, "analyze_window", fake_tracking)
    monkeypatch.setattr(jobs.hardware, "load_or_build_profile", lambda: {"gpu_vendor":"cpu","profile":{"name":"eco","label":"ECO"},"render":{"encoder":"libx264"},"transcription":{"backend":"cpu","model":"base"},"analysis":{"tracking_fps":1.0,"width":480}})

    def fake_clean(source, out_path, *args, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True); Path(out_path).write_bytes(b"clean")
        return {"encoder":"libx264"}
    def fake_final(source, out_path, *args, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True); Path(out_path).write_bytes(b"final")
        return {"encoder":"libx264"}
    monkeypatch.setattr(jobs, "render_clean_clip", fake_clean)
    monkeypatch.setattr(jobs, "render_edited_clip", fake_final)

    jobs.process_project("p1")
    assert calls["tracking"] == 1
    assert calls["fps"] <= 2.0
    project = db.fetchone("SELECT tracking_path,tracking_summary_json,status FROM projects WHERE id='p1'")
    assert project["status"] == "done"
    assert Path(project["tracking_path"]).exists()
    summary = json.loads(project["tracking_summary_json"])
    assert summary["track_count"] == 1
    assert summary["coverage_percent"] == 75.0


def test_tracking_api_returns_project_summary(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email":"api@test.com","password":"abcdef"})
    user = db.fetchone("SELECT id FROM users WHERE email='api@test.com'")
    now = db.now_iso()
    summary = {"backend":"yunet","track_count":2,"coverage_percent":88.5,"dominant_tracks":["face_1","face_2"],"fallback_reason":None,"model_available":True,"analyzed_frames":100}
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,tracking_summary_json,created_at,updated_at) VALUES('p2',?,'P','upload','smart','{}',?,?,?)", (user["id"], json.dumps(summary), now, now))
    r = client.get('/api/projects/p2/tracking')
    assert r.status_code == 200
    assert r.json()["track_count"] == 2
    assert r.json()["backend"] == "yunet"


def test_special_layouts_seed_editable_title_overlay():
    base = jobs._initial_edit_state({"layout_preset_id":"choquei-movimento","captions":True})
    state = jobs._state_for_candidate(base, {"title":"PRESIDENTE NÃO VIVE DE PALAVRÕES"})
    bars = [o for o in state["overlays"] if o.get("autoLayoutTitle")]
    assert len(bars) == 1
    assert bars[0]["text"] == "PRESIDENTE NÃO VIVE DE PALAVRÕES"
    assert bars[0]["type"] == "text"
