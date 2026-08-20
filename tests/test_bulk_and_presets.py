from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def setup_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "bulk.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "v2@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='v2@test.com'")
    now = db.now_iso()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_value,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p1',?,'Demo','upload','source.mp4',?,'smart','done',100,'ok',?,?,?)",
        (user["id"], str(source), json.dumps({"caption_preset_id": "green-fresh", "layout_preset_id": "auto"}), now, now),
    )
    for idx in range(1, 4):
        db.execute(
            "INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at) VALUES(?,?,?,?,?,?,?)",
            (f"c{idx}", "p1", f"Corte {idx}", idx * 10, idx * 10 + 20, 9 - idx / 10, now),
        )
    return client, user


def test_project_defaults_can_be_updated_and_new_clip_inherits_them(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    r = client.post(
        "/projects/p1/defaults",
        json={
            "caption_preset_id": "mrbeast",
            "layout_preset_id": "split",
            "caption_font": "Anton",
            "emojis": False,
            "cta_enabled": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["caption_preset_id"] == "mrbeast"
    assert r.json()["layout_preset_id"] == "split"

    state = client.get("/clips/c3/editor-state").json()
    assert state["caption_preset_id"] == "mrbeast"
    assert state["layout_preset_id"] == "split"


def test_user_preset_can_be_favorited_and_duplicated(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    saved = client.post(
        "/presets",
        json={"preset_type": "combined", "name": "Original", "config": {"caption_preset_id": "green-fresh"}},
    ).json()
    preset_id = saved["id"]

    fav = client.post(f"/presets/{preset_id}/favorite", json={"favorite": True})
    assert fav.status_code == 200
    assert fav.json()["favorite"] is True

    dup = client.post(f"/presets/{preset_id}/duplicate")
    assert dup.status_code == 200
    assert dup.json()["id"] != preset_id
    assert dup.json()["name"].startswith("Original")
    assert dup.json()["config"] == saved["config"]


def test_bulk_editor_exposes_explicit_preview_and_final_render_actions(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    r = client.get("/projects/p1/bulk-editor?ids=c1,c2")
    assert r.status_code == 200
    assert 'id="renderBulkPreview"' in r.text
    assert 'id="renderBulkFinal"' in r.text
    assert 'id="bulkRenderProgress"' in r.text
    assert 'id="saveBulkPreset"' in r.text
    assert 'id="bulkSavedPreset"' in r.text


def test_imported_video_is_available_as_manual_clip_source(monkeypatch, tmp_path):
    client, _ = setup_client(monkeypatch, tmp_path)
    imported = tmp_path / "extra.mp4"
    imported.write_bytes(b"extra")
    now = db.now_iso()
    db.execute(
        "INSERT INTO project_assets(id,project_id,kind,provider,source_value,local_path,metadata_json,created_at) VALUES('a1','p1','source','upload','extra.mp4',?,'{}',?)",
        (str(imported), now),
    )
    r = client.get("/projects/p1/new-clip?asset_id=a1")
    assert r.status_code == 200
    assert "extra.mp4" in r.text
    assert 'name="asset_id"' in r.text
