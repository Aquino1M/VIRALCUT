from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "u@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='u@test.com'")
    now = db.now_iso()
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload','smart',?,?,?)",
        (user["id"], json.dumps({"caption_preset_id": "green-fresh", "layout_preset_id": "auto"}), now, now),
    )
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at) VALUES('c1','p1','Corte',10,40,9.8,?)", (now,))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at) VALUES('c2','p1','Corte 2',50,80,8.5,?)", (now,))
    return client


def test_preset_and_layout_apis(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    caps = client.get("/api/caption-presets")
    layouts = client.get("/api/layout-presets")
    fonts = client.get("/api/fonts")
    assert caps.status_code == 200 and any(x["id"] == "green-fresh" for x in caps.json())
    assert layouts.status_code == 200 and any(x["id"] == "split" for x in layouts.json())
    assert fonts.status_code == 200 and any(x["family"] == "Bangers" for x in fonts.json())


def test_editor_state_and_caption_api_roundtrip(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    state = client.get("/clips/c1/editor-state").json()
    assert state["caption_preset_id"] == "green-fresh"
    response = client.put("/clips/c1/editor-state", json={**state, "layout_preset_id": "react", "caption_config": {"fontSize": 88}})
    assert response.status_code == 200
    assert response.json()["layout_preset_id"] == "react"

    cues = [{"start_time": 0, "end_time": 0.7, "text": "Olá", "word_index": 0}]
    assert client.put("/clips/c1/captions", json=cues).status_code == 200
    assert client.get("/clips/c1/captions").json()[0]["text"] == "Olá"


def test_rebuild_captions_recovers_project_transcript(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"segments": [{"start": 10, "end": 11, "words": [{"start": 10, "end": 10.4, "word": "Legenda"}, {"start": 10.4, "end": 11, "word": "pronta"}]}]}), encoding="utf-8")
    db.execute("UPDATE projects SET transcript_path=? WHERE id='p1'", (str(transcript),))

    response = client.post("/clips/c1/captions/rebuild")

    assert response.status_code == 200
    assert response.json()["source"] == "transcrição do projeto"
    assert [cue["text"] for cue in response.json()["cues"]] == ["Legenda", "pronta"]


def test_bulk_apply_updates_multiple_clips(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    response = client.post("/projects/p1/bulk-edit", json={
        "clip_ids": ["c1", "c2"],
        "caption_preset_id": "mrbeast",
        "layout_preset_id": "split",
        "caption_config": {"positionY": 1350},
    })
    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert client.get("/clips/c2/editor-state").json()["caption_preset_id"] == "mrbeast"


def test_user_can_save_custom_preset(monkeypatch, tmp_path):
    client = setup_client(monkeypatch, tmp_path)
    r = client.post("/presets", json={"preset_type": "combined", "name": "Meu Viral", "config": {"caption_preset_id": "green-fresh", "layout_preset_id": "single"}, "favorite": True})
    assert r.status_code == 200
    assert r.json()["name"] == "Meu Viral"
    assert r.json()["favorite"] is True
