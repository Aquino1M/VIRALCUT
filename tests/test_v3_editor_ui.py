from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_editor_exposes_cta_asset_library_and_multitrack_timeline():
    html = (ROOT / 'app/templates/editor.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/editor.js').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/style.css').read_text(encoding='utf-8')

    for token in [
        'id="saveEditorBtn"',
        'data-tab="cta"',
        'id="ctaX"',
        'id="ctaY"',
        'id="ctaFont"',
        'id="headlineFont"',
        'value="{{clip.title}}"',
        'data-tab="library"',
        'id="assetSearch"',
        'id="assetImportForm"',
        'id="multiTrackTimeline"',
    ]:
        assert token in html

    assert 'data-tab="auto-edit"' not in html
    assert 'Edite com comandos' not in html
    assert 'prompt-edit' not in html
    assert 'syncCtaControls' in js
    assert "replaceOverlay(o=>o.type==='cta'" in js
    assert 'autoVideoTitle:true' in js
    assert 'fontFamily:`"${o.fontFamily' in js
    assert "const start=e=>{if(dragging||e.button!==0" in js
    assert "document.addEventListener('mousemove',move)" in js
    assert '/api/v1/clips/${boot.clipId}/timeline' in js
    assert '/api/v1/assets?' in js
    assert '/api/v1/assets/import' in js
    assert 'renderV3Timeline' in js
    assert '.v3-track' in css
    assert '.save-editor-btn' in css
    assert ':not(.save-editor-btn)' in css


def test_editor_library_can_insert_assets_at_playhead():
    js = (ROOT / 'app/static/editor.js').read_text(encoding='utf-8')
    assert 'insertAssetAtPlayhead' in js
    assert 'saveV3Timeline' in js
    assert 'assetId' in js
