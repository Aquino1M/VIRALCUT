from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_v33_editor_uses_proxy_and_browser_layout_runtime():
    html=(ROOT/'app/templates/editor.html').read_text(encoding='utf-8')
    js=(ROOT/'app/static/editor.js').read_text(encoding='utf-8')
    assert 'Visualização em baixa qualidade' in html
    assert '/clips/${boot.clipId}/editor-proxy' in js
    assert 'reloadCleanVideoForLayout' not in js
    assert 'projectRatio' in html
    for ratio in ['9:16','1:1','4:5','16:9','Original']:
        assert ratio in html
    assert 'overlay-remove' in js
    assert 'requestAnimationFrame' in js


def test_timeline_is_selectable_and_has_edit_controls():
    html=(ROOT/'app/templates/editor.html').read_text(encoding='utf-8')
    js=(ROOT/'app/static/editor.js').read_text(encoding='utf-8')
    for token in ['timelineSplit','timelineDelete','timelineDuplicate','timelineZoom','timelineInspector']:
        assert token in html
    assert 'selectedTimelineItem' in js
    assert 'v3-track-item selected' in js or "classList.toggle('selected'" in js
