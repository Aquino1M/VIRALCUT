from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_editor_exposes_auto_edit_asset_library_and_multitrack_timeline():
    html = (ROOT / 'app/templates/editor.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/editor.js').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/style.css').read_text(encoding='utf-8')

    for token in [
        'data-tab="auto-edit"',
        'data-tab="library"',
        'id="autoEditRun"',
        'id="assetSearch"',
        'id="assetImportForm"',
        'id="multiTrackTimeline"',
    ]:
        assert token in html

    assert '/api/v1/clips/${boot.clipId}/auto-edit' in js
    assert '/api/v1/clips/${boot.clipId}/timeline' in js
    assert '/api/v1/assets?' in js
    assert '/api/v1/assets/import' in js
    assert 'renderV3Timeline' in js
    assert '.v3-track' in css


def test_editor_library_can_insert_assets_at_playhead():
    js = (ROOT / 'app/static/editor.js').read_text(encoding='utf-8')
    assert 'insertAssetAtPlayhead' in js
    assert 'saveV3Timeline' in js
    assert 'assetId' in js
