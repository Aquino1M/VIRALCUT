from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def test_project_workspace_contains_player_filters_bulk_and_download(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "workspace.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "w@test.com", "password": "abcdef"})
    user = db.fetchone("SELECT * FROM users WHERE email='w@test.com'")
    now = db.now_iso()
    dummy = tmp_path / "clip.mp4"; dummy.write_bytes(b"not-real")
    db.execute("INSERT INTO projects(id,user_id,title,source_type,source_value,mode,status,progress,message,settings_json,created_at,updated_at,duration,channel_label) VALUES('p1',?,'Projeto','youtube','https://youtube.com/watch?v=x','smart','done',100,'Projeto concluído','{}',?,?,226,'Canal Demo')", (user["id"], now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,reason,video_path,created_at,render_status) VALUES('c1','p1','Polêmica',10,63,9.8,'Motivo viral',?,?,'rendered')", (str(dummy), now))

    r = client.get("/projects/p1?sort=score&page_size=24")
    assert r.status_code == 200
    html = r.text
    assert '<video' in html
    assert '53s' in html
    assert 'Baixar' in html
    assert 'Por Score' in html
    assert 'Editar selecionados' in html
    assert '<dialog' in html
    assert 'Formato real' in html
    assert '/projects/p1/download-all' in html
