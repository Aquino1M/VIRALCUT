from pathlib import Path
import json

from app.services import assets


def setup_asset_dir(monkeypatch, tmp_path: Path):
    root = tmp_path / 'assets'
    monkeypatch.setattr(assets, 'ASSET_DIR', root)
    monkeypatch.setattr(assets, 'ASSET_CATALOG', root / 'catalog.json')
    monkeypatch.setattr(assets, 'ASSET_PACK_MARKER', root / '.lite_complete')
    assets.ensure_asset_dirs()
    return root


def test_register_and_semanticish_search(monkeypatch, tmp_path):
    root = setup_asset_dir(monkeypatch, tmp_path)
    money = root / 'broll' / 'money.mp4'; money.write_bytes(b'video')
    nature = root / 'broll' / 'forest.mp4'; nature.write_bytes(b'video')
    assets.register_asset('broll', money, name='Bolsa e dinheiro', tags=['money','economy','market','dollar'])
    assets.register_asset('broll', nature, name='Floresta', tags=['nature','trees','green'])
    results = assets.search_assets('o preço do dólar caiu e a bolsa reagiu', kind='broll')
    assert results
    assert results[0]['name'] == 'Bolsa e dinheiro'
    assert results[0]['score'] > 0


def test_asset_budget_is_hard_capped_at_two_gb(monkeypatch, tmp_path):
    setup_asset_dir(monkeypatch, tmp_path)
    assert assets.LITE_PACK_LIMIT_BYTES == 2 * 1024 * 1024 * 1024
    assert assets.can_add_bytes(assets.LITE_PACK_LIMIT_BYTES - 1, current_bytes=0)
    assert not assets.can_add_bytes(2, current_bytes=assets.LITE_PACK_LIMIT_BYTES - 1)


def test_offline_core_generates_reusable_sfx_and_effect_presets(monkeypatch, tmp_path):
    root = setup_asset_dir(monkeypatch, tmp_path)
    summary = assets.generate_offline_core()
    assert summary['sfx'] >= 4
    assert summary['effects'] >= 6
    assert summary['music'] >= 3
    catalog = assets.load_catalog()
    kinds = {x['kind'] for x in catalog['assets']}
    assert 'sfx' in kinds
    assert 'music' in kinds
    presets = json.loads((root / 'effects' / 'presets.json').read_text(encoding='utf-8'))
    assert any(p['id'] == 'zoom-punch' for p in presets)
    assert any(p['id'] == 'cinematic' for p in presets)


def test_status_reports_target_and_size(monkeypatch, tmp_path):
    root = setup_asset_dir(monkeypatch, tmp_path)
    f = root / 'broll' / 'a.mp4'; f.write_bytes(b'x' * 1024)
    assets.register_asset('broll', f, name='A', tags=['a'])
    status = assets.starter_pack_status()
    assert status['limit_bytes'] == assets.LITE_PACK_LIMIT_BYTES
    assert status['size_bytes'] >= 1024
    assert status['preset'] == 'lite'


def test_generated_virtual_filters_are_searchable(monkeypatch, tmp_path):
    setup_asset_dir(monkeypatch, tmp_path)
    assets.generate_offline_core()
    results = assets.search_assets('cool technology news contrast', kind='filter', limit=3)
    assert results
    assert results[0]['kind'] == 'filter'
    assert results[0]['metadata']['eq']
    assert results[0]['local_path'].startswith('filter://')
