from __future__ import annotations
from pathlib import Path
from fastapi.testclient import TestClient
from app import db, main
from app.services import fonts


def test_downloaded_font_is_served_to_browser_preview(monkeypatch,tmp_path:Path):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'fonts.db');db.init_db()
    font_dir=tmp_path/'fonts';font_dir.mkdir();(font_dir/'Bangers-Regular.ttf').write_bytes(b'x'*12000)
    monkeypatch.setattr(fonts,'FONT_DIR',font_dir)
    c=TestClient(main.app)
    css=c.get('/font-css')
    assert css.status_code==200
    assert '@font-face' in css.text
    assert 'Bangers' in css.text
    assert '/font-files/Bangers-Regular.ttf' in css.text
    f=c.get('/font-files/Bangers-Regular.ttf')
    assert f.status_code==200
