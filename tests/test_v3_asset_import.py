from pathlib import Path

from app import db, main
from app.services import assets
from fastapi.testclient import TestClient


def setup_assets(monkeypatch, tmp_path: Path):
    root = tmp_path / 'assets'
    monkeypatch.setattr(assets, 'ASSET_DIR', root)
    monkeypatch.setattr(assets, 'ASSET_CATALOG', root / 'catalog.json')
    monkeypatch.setattr(assets, 'ASSET_PACK_MARKER', root / '.lite_complete')
    assets.ensure_asset_dirs()
    return root


def test_user_assets_do_not_consume_starter_pack_two_gb_budget(monkeypatch, tmp_path):
    root = setup_assets(monkeypatch, tmp_path)
    stock = root / 'broll' / 'stock.mp4'; stock.write_bytes(b'x' * 1024)
    own = root / 'user' / 'mine.mp4'; own.write_bytes(b'y' * 4096)
    assets.register_asset('broll', stock, provider='wikimedia')
    assets.register_asset('broll', own, provider='user')
    assert assets.current_size_bytes() < 4096
    assert assets.user_size_bytes() >= 4096


def test_authenticated_user_can_import_and_preview_local_asset(monkeypatch, tmp_path):
    root = setup_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'import.db')
    db.init_db()
    client = TestClient(main.app)
    client.post('/register', data={'email': 'assets@test.com', 'password': 'abcdef'})
    r = client.post(
        '/api/v1/assets/import',
        data={'kind': 'broll', 'tags': 'dinheiro, mercado'},
        files={'file': ('meu_broll.mp4', b'fake-video-bytes', 'video/mp4')},
    )
    assert r.status_code == 200
    item = r.json()
    assert item['provider'] == 'user'
    assert item['kind'] == 'broll'
    assert Path(item['local_path']).exists()
    preview = client.get(f"/api/v1/assets/{item['id']}/file")
    assert preview.status_code == 200
    assert preview.content == b'fake-video-bytes'
