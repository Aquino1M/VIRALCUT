from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_v33_release_contract():
    assert (ROOT/'VERSION').read_text().strip()=='4.2.0'
    html=(ROOT/'app/templates/editor.html').read_text(encoding='utf-8')
    js=(ROOT/'app/static/editor.js').read_text(encoding='utf-8')
    assert 'PROXY' in html
    assert 'Visualização em baixa qualidade' in html
    assert 'flushEditorSnapshot' in js
    assert 'layoutCanvas' in js
    assert 'editorProxyUrl' in js
    assert 'reloadCleanVideoForLayout' not in js
    assert (ROOT/'docs/V3.3_RELEASE_NOTES.md').exists()
