from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import db


def _use_temp_db(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_v2_migration_creates_editor_tables(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"clip_edits", "caption_cues", "user_presets", "clip_renders", "project_assets", "brand_assets"} <= names


def test_editor_state_roundtrip_and_defaults(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    from app.services import editor

    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'a@b.c','x',?)", (now,))
    db.execute(
        "INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart',?,?,?)",
        (json.dumps({"caption_preset_id": "green-fresh", "layout_preset_id": "auto"}), now, now),
    )
    db.execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,10,?)",
        (now,),
    )

    state = editor.get_or_create_edit_state("c1")
    assert state["caption_preset_id"] == "green-fresh"
    assert state["layout_preset_id"] == "auto"
    assert state["tracks"]["captions"]["visible"] is True

    saved = editor.save_edit_state(
        "c1",
        {
            **state,
            "caption_preset_id": "rainbow-fun",
            "caption_config": {"fontSize": 82, "positionY": 1250},
        },
    )
    assert saved["caption_preset_id"] == "rainbow-fun"
    assert saved["caption_config"]["fontSize"] == 82

    loaded = editor.get_or_create_edit_state("c1")
    assert loaded["caption_config"]["positionY"] == 1250


def test_caption_cues_can_be_replaced(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    from app.services import editor

    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'a@b.c','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart','{}',?,?)", (now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,10,?)", (now,))

    cues = editor.replace_caption_cues("c1", [
        {"start_time": 0.0, "end_time": 0.8, "text": "Olá", "word_index": 0},
        {"start_time": 0.8, "end_time": 1.5, "text": "mundo", "word_index": 1},
    ])
    assert [c["text"] for c in cues] == ["Olá", "mundo"]
    assert editor.list_caption_cues("c1")[1]["start_time"] == pytest.approx(0.8)
